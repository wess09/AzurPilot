#!/usr/bin/env python3
"""AzurPilot 终端交互界面 (TUI) 启动入口。

使用方法:
    uv run python tui.py [实例名]
    例如:
    uv run python tui.py alas
"""

import argparse
import os
import sys

# 确保在 Windows 终端下正确配置 UTF-8 编码与 ANSI 色彩支持
if sys.platform == "win32":
    os.system("")  # 激活 Windows 终端 VT100 逃逸序列
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main() -> None:
    """TUI 主入口函数。"""
    parser = argparse.ArgumentParser(
        prog="tui.py",
        description="AzurPilot 现代化全功能终端交互系统 (Textual TUI)",
    )
    parser.add_argument(
        "instance",
        nargs="?",
        default=None,
        help="启动时默认选中的配置实例名称（如 alas、alas2 等）",
    )
    args = parser.parse_args()

    # 标记当前运行于 TUI 终端全屏环境，移除全局控制台日志处理器避免污染终端
    os.environ["AZURPILOT_TUI"] = "1"
    try:
        from module.logger import console_hdlr, logger
        logger.removeHandler(console_hdlr)
    except Exception:
        pass

    from module.persistence.database import initialize
    initialize()

    # 延迟导入以加快帮助输出响应
    from module.tui.app import AzurPilotTUI

    app = AzurPilotTUI(default_instance=args.instance)
    try:
        app.run()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
