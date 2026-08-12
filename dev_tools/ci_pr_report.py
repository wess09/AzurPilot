"""CI 完成后在 PR 上发布检查报告。

在统一 CI 工作流（.github/workflows/ci.yml）的所有检查 job 完成后运行，
将本次运行的结果以一条评论发布/更新到对应 PR，避免每次 push 都新增评论。

（测试提交：用于验证 workflow_run 触发的 ci-report 自动评论功能。）

数据来源（均为 GitHub API 真实数据，不伪造结果）：
- 运行信息：由环境变量注入（GITHUB_RUN_ID / GITHUB_REPOSITORY / GITHUB_EVENT_PATH）
- 各 job 结论与耗时：GET /repos/{repo}/actions/runs/{run_id}/jobs
- 导入冒烟测试汇总：读取 --summary-file 指向的 JSON（由 import_smoke_test.py 产出）

评论更新机制（参考 noneflow 的 resuable_comment_issue 模式）：
- 评论体包含固定标记 <!-- ci-report -->；
- 若 PR 上已有带该标记的评论则更新（PATCH），否则新建（POST）。

权限说明：
- 仅 PR 事件（pull_request）下运行；push 事件直接跳过。
- 需要 workflow 配置 pull-requests: write。来自 fork 的 PR 在 pull_request
  事件下 GITHUB_TOKEN 为只读，发布评论会返回 403——脚本捕获后记录并跳过，
  不会导致 CI 失败。

用法：
    python dev_tools/ci_pr_report.py [--summary-file import-smoke-summary.json]

环境变量：
    GITHUB_TOKEN        GitHub token（CI 自动注入）
    GITHUB_REPOSITORY   owner/repo
    GITHUB_RUN_ID       本次 Actions run id
    GITHUB_EVENT_PATH   Actions 事件负载 JSON 文件路径
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# 用于定位/更新同一条评论的标记。
REPORT_MARKER = "<!-- ci-report -->"

_STATUS_ICON = {
    "success": "✅",
    "failure": "❌",
    "cancelled": "⛔",
    "skipped": "⏭️",
    "neutral": "➖",
}


def api(url: str, token: str, method: str = "GET", payload=None):
    """调用 GitHub REST API。"""
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=30) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def get_pr_number(event_path: str, token: str = "", repo: str = "", run_id: str = "") -> int | None:
    """从事件负载读取 PR 号；非 PR 事件返回 None。

    支持两类事件：
    - pull_request：直接读取 event.pull_request.number；
    - workflow_run（由 CI 完成后触发）：通过 API 查询
      GET /repos/{repo}/actions/runs/{run_id}/pull_requests 获取关联 PR，
      事件负载中的 workflow_run.pull_requests 作为回退。
    """
    try:
        with open(event_path, encoding="utf-8") as fp:
            event = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None

    # workflow_run 事件：优先查 API（该字段在事件负载中可能为空）。
    if "workflow_run" in event:
        if token and repo and run_id:
            try:
                data = api(
                    f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/pull_requests",
                    token,
                )
                prs = data if isinstance(data, list) else (data or {}).get("pull_requests") or []
                if prs:
                    return prs[0].get("number")
            except (urllib.error.URLError, urllib.error.HTTPError):
                pass
        wfr_prs = event.get("workflow_run", {}).get("pull_requests") or []
        if wfr_prs:
            return wfr_prs[0].get("number")
        return None

    # pull_request 事件。
    return event.get("pull_request", {}).get("number")


def get_jobs(repo: str, run_id: str, token: str) -> list[dict]:
    """获取本次运行的全部 job 及其结论/耗时。"""
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"
    data = api(url, token)
    jobs = []
    for job in data.get("jobs", []):
        started = job.get("started_at")
        completed = job.get("completed_at")
        duration = None
        if started and completed:
            try:
                t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                duration = max(0, int((t1 - t0).total_seconds()))
            except ValueError:
                duration = None
        jobs.append(
            {
                "name": job.get("name", job.get("id")),
                "conclusion": job.get("conclusion") or "unknown",
                "duration": duration,
            }
        )
    return jobs


def load_smoke_summary(path: str) -> dict | None:
    """读取导入冒烟测试汇总 JSON；文件不存在时返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def build_report(repo: str, run_id: str, commit: str, jobs: list[dict],
                 smoke: dict | None) -> str:
    """构造 Markdown 报告。"""
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    lines = [
        "## CI 检查报告",
        REPORT_MARKER,
        "",
        f"- 运行：[{run_id}]({run_url})",
        f"- 提交：`{commit[:12]}`" if commit else "",
        "",
        "### 检查结果",
        "",
        "| 检查 | 结果 | 耗时 |",
        "|------|------|------|",
    ]
    for job in jobs:
        icon = _STATUS_ICON.get(job["conclusion"], "➖")
        name = job["name"]
        dur = format_duration(job["duration"])
        lines.append(f"| {name} | {icon} {job['conclusion']} | {dur} |")

    if smoke is not None:
        ok_icon = "✅" if smoke.get("ok") else "❌"
        lines += [
            "",
            "### 导入冒烟测试",
            "",
            f"- 结果：{ok_icon}",
            f"- 扫描模块：{smoke.get('total', '-')}（通过 {smoke.get('passed', '-')}"
            f"，已知失败 {smoke.get('known', '-')}"
            f"，意外失败 {smoke.get('unexpected', '-')}"
            f"，过期白名单 {smoke.get('stale', '-')}）",
        ]
        unexpected = smoke.get("unexpected_failures") or {}
        if unexpected:
            lines += ["", "**意外失败：**"]
            for mod, err in list(unexpected.items())[:10]:
                lines.append(f"- `{mod}`：{err}")

    lines.append("")
    return "\n".join(lines)


def find_self_comment(comments: list[dict]) -> int | None:
    """查找带标记的评论（通常是由本机器人发布的）。"""
    for comment in comments:
        body = comment.get("body") or ""
        if REPORT_MARKER in body:
            return comment.get("id")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-file", default=None,
                        help="导入冒烟测试汇总 JSON 路径（可缺省）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印报告内容，不实际发布/更新评论")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    commit = os.environ.get("GITHUB_SHA", "")

    if not all([token, repo, run_id, event_path]):
        print("[ci-report] 缺少必要环境变量，跳过")
        return 0

    pr_number = get_pr_number(event_path, token=token, repo=repo, run_id=run_id)
    if pr_number is None:
        print("[ci-report] 非 PR 事件，跳过")
        return 0

    try:
        jobs = get_jobs(repo, run_id, token)
        smoke = load_smoke_summary(args.summary_file)
        report = build_report(repo, run_id, commit, jobs, smoke)
    except urllib.error.HTTPError as exc:
        # fork PR 在 pull_request 事件下 GITHUB_TOKEN 为只读，读取也可能受限；
        # 捕获后记录并跳过，不使 CI 失败。
        print(f"[ci-report] 获取运行信息失败（HTTP {exc.code}），跳过")
        return 0
    except urllib.error.URLError as exc:
        # 网络波动/代理问题不应导致 CI 失败。
        print(f"[ci-report] 获取运行信息失败（网络错误），跳过：{exc.reason}")
        return 0

    if args.dry_run:
        print(report)
        return 0

    # 查找已有评论并更新，避免刷屏。
    comments_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    try:
        comments = api(comments_url, token)
        existing_id = find_self_comment(comments or [])
        if existing_id is not None:
            api(f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}",
                token, method="PATCH", payload={"body": report})
            print(f"[ci-report] 已更新评论 #{existing_id}")
        else:
            api(comments_url, token, method="POST", payload={"body": report})
            print(f"[ci-report] 已发布新评论到 PR #{pr_number}")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            print(f"[ci-report] 无法发布评论（HTTP {exc.code}），"
                  f"常见于 fork PR 的只读 token，跳过")
            return 0
        print(f"[ci-report] 发布评论失败（HTTP {exc.code}）")
        return 0
    except urllib.error.URLError as exc:
        print(f"[ci-report] 发布评论失败（网络错误）：{exc.reason}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ci-report] 发布评论异常：{exc}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
