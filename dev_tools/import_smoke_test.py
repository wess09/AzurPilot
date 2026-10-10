"""CI 导入冒烟测试。

遍历 module/ 与 deploy/ 下的全部 Python 模块，在独立子进程中逐个导入，
检测损坏模块（语法错误、缺失依赖、运行时导入异常等），并守护 WebUI/MCP
进程与 OCR 的进程隔离不被破坏。

设计原则：
- **子进程隔离**：每个模块在独立子进程中导入，避免 import 副作用
  （如 fake_pil_module 对 sys.modules['PIL'] 的全局污染）影响其他模块。
- **超时保护**：单模块导入超过阈值按失败处理，防止挂起拖垮 CI。
- **已知失败白名单 KNOWN_FAILURES**：记录真实存在且已定位根因的失败，
  会输出但不会导致 CI 失败；白名单外的任何失败都会使检查失败（拦截回归）。
  白名单中已能正常导入的条目视为过期（stale），同样使检查失败，
  保证白名单始终准确反映代码现状。
- **平台适配**：按当前平台跳过平台专属模块（如 Windows-only 的 winreg）。
- **扫描范围**：module/ + deploy/（运行时代码）。campaign/ 为重量级活动
  数据模块（1400+ 文件，导入耗时数分钟），默认不纳入常规扫描。

用法：
    uv run python -m dev_tools.import_smoke_test [--include-campaign]
"""

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
DEFAULT_TIMEOUT = 30  # 单模块导入超时（秒）
DEFAULT_WORKERS = 8

# 扫描范围：module/ 与 deploy/ 为运行时代码；campaign/ 需显式开启。
SCAN_DIRS = ("module", "deploy")
CAMPAIGN_DIR = "campaign"

# 平台专属模块：当前平台不适用时跳过（不入白名单，避免误报）。
# 以下模块依赖 Windows 注册表（winreg）等，仅在 Windows 上可用。
_WINDOWS_ONLY_MODULES = {
    "module.device.platform.emulator_windows",
    "module.device.platform.platform_windows",
    "deploy.adb",
    "deploy.emulator",
    "deploy.install.emulator_windows",
    "deploy.installer",
}
PLATFORM_SKIP = {
    "win32": set(),
    "linux": _WINDOWS_ONLY_MODULES,
    "darwin": _WINDOWS_ONLY_MODULES,
}

# 已知失败白名单：真实存在且已定位根因的失败。
# 结构：{module: 失败原因}。原因需可追溯到具体缺陷。
#
# 注：曾将 module.os_simulator.simulator 列为已知失败（本地环境 numba 缺
# _version），但该现象源于本地 .venv 损坏；在全新 `uv sync` 环境（CI）下
# numba==0.66.0 可正常导入，故已从白名单移除，避免"过期白名单"误报。
KNOWN_FAILURES = {
    # 以下三个依赖生成器均已弃用，模块故意 raise 提示改用 pyproject.toml + uv.lock。
    "deploy.headless.requirements_generator": "headless requirements 已弃用，模块故意 raise",
    "deploy.AidLux.requirements_generator": "AidLux requirements 已弃用，模块故意 raise",
    "deploy.docker.requirements_generator": "Docker requirements 已弃用，模块故意 raise",
}


def discover_modules(include_campaign: bool) -> list[str]:
    """遍历扫描目录，生成点分模块名列表。

    Args:
        include_campaign (bool): 是否包含 campaign 战役目录下的模块。

    Returns:
        list[str]: 发现的 Python 模块点分路径列表。
    """
    roots = list(SCAN_DIRS)
    if include_campaign:
        roots.append(CAMPAIGN_DIR)

    modules = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            parts = path.relative_to(REPO_ROOT).with_suffix("").parts
            # 跳过 __pycache__ 与 __init__/__main__ 等双下划线模块。
            if "__pycache__" in parts:
                continue
            if any(part.startswith("__") for part in parts):
                continue
            modules.append(".".join(parts))
    return modules


def platform_skip(module: str) -> bool:
    """当前平台不适用的模块直接跳过（不报告失败）。

    Args:
        module (str): 待检查的模块名。

    Returns:
        bool: 是否应在当前平台上跳过。
    """
    return module in PLATFORM_SKIP.get(sys.platform, set())


def import_in_subprocess(module: str, timeout: int) -> tuple[bool, str]:
    """在独立子进程中导入模块，返回导入状态与错误摘要。

    Args:
        module (str): 模块名称。
        timeout (int): 导入超时时限（秒）。

    Returns:
        tuple[bool, str]: (是否导入成功, 错误信息摘要)。
    """
    code = f"import {module}"
    env = {**os.environ, "AZURPILOT_NTP_DISABLE": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            [str(PYTHON), "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return False, f"导入超时（>{timeout}s）"
    if proc.returncode == 0:
        return True, ""
    # 提取最靠后的异常摘要，便于定位根因。
    lines = [line.strip() for line in proc.stderr.splitlines() if line.strip()]
    summary = lines[-1] if lines else "未知错误"
    return False, summary[:200]


def run_scan(include_campaign: bool, timeout: int, workers: int) -> dict:
    """多进程并发执行模块导入扫描。

    Args:
        include_campaign (bool): 是否扫描 campaign 目录。
        timeout (int): 单模块导入超时秒数。
        workers (int): 并发进程池大小。

    Returns:
        dict: 模块名映射到 (成功标志, 错误或跳过说明) 的字典。
    """
    modules = discover_modules(include_campaign)
    results = {}

    def check(module: str):
        if platform_skip(module):
            return module, (True, "平台跳过")
        ok, error = import_in_subprocess(module, timeout)
        return module, (ok, error)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for module, (ok, error) in pool.map(check, modules):
            results[module] = (ok, error)
    return results


def summarize(results: dict) -> tuple[list, list, list, list]:
    """把扫描结果分类汇总。

    Args:
        results (dict): 扫描结果字典。

    Returns:
        tuple[list, list, list, list]: 分别为通过、已知失败、意外失败与过期白名单列表。
    """
    passed = []
    known = []
    unexpected = []
    stale = []
    for module, (ok, error) in sorted(results.items()):
        if ok:
            if module in KNOWN_FAILURES:
                stale.append((module, error, KNOWN_FAILURES[module]))
            else:
                passed.append(module)
        else:
            if module in KNOWN_FAILURES:
                known.append((module, error, KNOWN_FAILURES[module]))
            else:
                unexpected.append((module, error))
    return passed, known, unexpected, stale


def main() -> int:
    """运行导入冒烟测试并输出检测报告。

    Returns:
        int: 全部通过返回 0，存在意外失败或过期白名单返回 1。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-campaign", action="store_true", help="额外扫描 campaign/（耗时较长）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单模块导入超时（秒）")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并行子进程数")
    parser.add_argument("--summary-file", type=str, default=None,
                        help="将扫描汇总写入 JSON 文件（供 CI 报告使用），即使失败也会写入")
    args = parser.parse_args()

    # 模拟真实运行环境：应用启动时会创建 ./log/ 目录。
    # 全新 checkout 无该目录时，部分模块（如 module.azur_stats.image.* 的
    # 导入链）初始化日志文件会抛 FileNotFoundError，导致误报意外失败。
    (REPO_ROOT / "log").mkdir(parents=True, exist_ok=True)

    start = time.time()
    print(f"[import-smoke] 扫描 module/ + deploy/" + (" + campaign/" if args.include_campaign else "")
          + f"，超时 {args.timeout}s，并行 {args.workers}")
    results = run_scan(args.include_campaign, args.timeout, args.workers)
    passed, known, unexpected, stale = summarize(results)
    elapsed = time.time() - start

    print(f"[import-smoke] 共 {len(results)} 个模块，通过 {len(passed)}，"
          f"已知失败 {len(known)}，意外失败 {len(unexpected)}，过期白名单 {len(stale)}，耗时 {elapsed:.1f}s")

    if known:
        print("\n=== 已知失败（已定位根因，不阻断）===")
        for module, error, reason in known:
            print(f"  - {module}\n      {error}\n      原因: {reason}")

    if stale:
        print("\n=== 过期白名单（模块已能正常导入，请从 KNOWN_FAILURES 移除）===")
        for module, _, reason in stale:
            print(f"  - {module}  // {reason}")

    if unexpected:
        print("\n=== 意外失败（需处理，否则 CI 失败）===")
        for module, error in unexpected:
            print(f"  - {module}\n      {error}")

    # 结论：意外失败或过期白名单都会使检查失败。
    ok = not unexpected and not stale
    if ok:
        print("\n[import-smoke] 通过 ✅")
    else:
        print("\n[import-smoke] 失败 ❌")

    # 无论通过与否都写汇总文件，供 CI 报告引用真实数据（不伪造结果）。
    if args.summary_file:
        summary = {
            "total": len(results),
            "passed": len(passed),
            "known": len(known),
            "unexpected": len(unexpected),
            "stale": len(stale),
            "ok": ok,
            "elapsed": round(elapsed, 1),
            "known_failures": {module: reason for module, _, reason in known},
            "unexpected_failures": {module: error for module, error in unexpected},
        }
        import json
        with open(args.summary_file, "w", encoding="utf-8") as fp:
            json.dump(summary, fp, ensure_ascii=False, indent=2)
        print(f"[import-smoke] 汇总已写入 {args.summary_file}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
