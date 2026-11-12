"""TUI 顶部状态栏组件。"""

from datetime import datetime
from typing import Any, Dict, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label

MAX_ERROR_LENGTH = 40


class HeaderBar(Widget):
    """顶部标题与全局状态栏。"""

    DEFAULT_CSS = """
    HeaderBar {
        height: 2;
        dock: top;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 1;
    }
    #header-container {
        width: 100%;
        height: 100%;
        align: left middle;
    }
    #app-title {
        text-style: bold;
        color: $accent;
        margin-right: 2;
        text-wrap: nowrap;
    }
    #instance-badge {
        color: $text;
        background: $panel;
        padding: 0 1;
        margin-right: 2;
        text-wrap: nowrap;
    }
    #status-badge {
        padding: 0 1;
        margin-right: 2;
        text-wrap: nowrap;
    }
    #emulator-info {
        color: $text-muted;
        margin-right: 2;
        width: 1fr;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    #clock-label {
        dock: right;
        color: $text-muted;
        text-wrap: nowrap;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.instance_name = "alas"
        self.status = "stopped"
        self.serial = "auto"
        self.server = "cn"
        self.current_task: Optional[str] = None
        self.error: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="header-container"):
            yield Label("⚓ AzurPilot TUI", id="app-title")
            yield Label("实例: -", id="instance-badge")
            yield Label("○ 已停止", id="status-badge")
            yield Label("模拟器: -", id="emulator-info")
            yield Label(datetime.now().strftime("%H:%M:%S"), id="clock-label")

    def update_info(
        self,
        instance_name: str,
        status: str,
        emulator: Optional[Dict[str, Any]] = None,
        current_task: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """更新状态栏数据。"""
        self.instance_name = instance_name
        self.status = status
        self.current_task = current_task
        self.error = error
        if emulator:
            self.serial = str(emulator.get("Serial", "auto") or "auto")
            self.server = str(emulator.get("ServerName", "cn") or "cn")

        try:
            self.query_one("#instance-badge", Label).update(Text(f"实例: [{self.instance_name}]"))
            self.query_one("#status-badge", Label).update(self._status_text(status, current_task))
            self.query_one("#emulator-info", Label).update(self._emulator_text())
        except Exception:
            # 组件尚未挂载完成时忽略，下一次轮询会补上。
            pass

    def _status_text(self, status: str, current_task: Optional[str]) -> Text:
        if status == "running":
            task_str = f" · {current_task}" if current_task else ""
            return Text(f"● 运行中{task_str}", style="bold green")
        if status == "updating":
            return Text("◐ 更新中", style="bold yellow")
        if status == "error":
            return Text("● 异常", style="bold red")
        return Text("○ 已停止", style="dim white")

    def _emulator_text(self) -> Text:
        if self.error:
            message = self.error
            if len(message) > MAX_ERROR_LENGTH:
                message = message[:MAX_ERROR_LENGTH] + "…"
            return Text(f"⚠ {message}", style="bold red")
        return Text(f"模拟器: {self.serial} ({self.server.upper()})", style="dim")

    def tick_clock(self) -> None:
        """定时更新右侧时钟。"""
        try:
            self.query_one("#clock-label", Label).update(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
