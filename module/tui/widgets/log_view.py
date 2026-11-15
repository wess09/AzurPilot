"""TUI 实时日志滚屏面板组件。"""

from typing import Any, Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Label, RichLog

# 单行显示上限，避免超长日志把终端渲染拖慢。
MAX_LINE_LENGTH = 4000
# 内存中保留的行数。
MAX_LOG_LINES = 2000

LEVEL_STYLE = {
    "ERROR": ("bold white on red", "bold red"),
    "CRITICAL": ("bold white on red", "bold red"),
    "WARNING": ("black on yellow", "yellow"),
    "WARN": ("black on yellow", "yellow"),
    "DEBUG": ("dim cyan", "dim cyan"),
    "INFO": ("green", "bright_white"),
}


class LogView(Widget):
    """实时日志滚屏视图。"""

    DEFAULT_CSS = """
    LogView {
        height: 1fr;
        min-height: 6;
        background: $surface-darken-2;
        border: solid $primary-darken-2;
        padding: 0 1;
    }
    #log-header-bar {
        height: 3;
        align: left middle;
        border-bottom: solid $primary-darken-3;
        margin-bottom: 0;
    }
    #log-title {
        text-style: bold;
        color: $accent;
        margin-right: 2;
        text-wrap: nowrap;
    }
    #log-cursor-info {
        color: $text-muted;
        margin-right: 2;
        text-wrap: nowrap;
    }
    .log-ctrl-btn {
        margin-left: 1;
    }
    #rich-log-container {
        height: 1fr;
        background: #0d1117;
        color: #c9d1d9;
        overflow: hidden;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.auto_scroll_enabled: bool = True
        self.latest_cursor: int = 0
        self.line_count: int = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="log-header-bar"):
                yield Label("📜 日志流", id="log-title")
                yield Label("游标 0", id="log-cursor-info")
                yield Button(Text("滚屏: 开 [P]"), id="btn-toggle-scroll", variant="default", classes="log-ctrl-btn")
                yield Button(Text("清屏 [L]"), id="btn-clear-log", variant="default", classes="log-ctrl-btn")
            yield RichLog(id="rich-log-container", highlight=False, markup=False, wrap=True, max_lines=MAX_LOG_LINES)

    @staticmethod
    def _format_entry(entry: Dict[str, Any]) -> Text:
        """把日志条目渲染成带级别着色的单行文本。"""
        level = str(entry.get("level", "INFO")).upper()
        try:
            sequence = int(entry.get("id") or entry.get("sequence") or 0)
        except (TypeError, ValueError):
            sequence = 0
        raw_text = str(entry.get("text") or entry.get("message") or "").rstrip()
        if len(raw_text) > MAX_LINE_LENGTH:
            raw_text = raw_text[:MAX_LINE_LENGTH] + " …"

        number_style, text_style = LEVEL_STYLE.get(level, LEVEL_STYLE["INFO"])
        line = Text()
        line.append(f"[{sequence:04d}] ", style="dim")
        line.append(f"{level:<8} ", style=number_style)
        line.append(f"│ {raw_text}", style=text_style)
        return line

    def write_entries(self, entries: List[Dict[str, Any]], cursor: int) -> None:
        """追加多条日志条目。"""
        if not entries:
            self.update_cursor(cursor)
            return

        rich_log = self.query_one("#rich-log-container", RichLog)
        for entry in entries:
            rich_log.write(self._format_entry(entry))
            self.line_count += 1

        self.update_cursor(cursor)

    def update_cursor(self, cursor: int) -> None:
        """更新序列号展示。"""
        self.latest_cursor = cursor
        try:
            self.query_one("#log-cursor-info", Label).update(f"游标 {cursor}")
        except Exception:
            pass

    def reset_cursor(self) -> None:
        """实例切换后重置游标展示。"""
        self.line_count = 0
        self.update_cursor(0)

    def clear_log(self) -> None:
        """清空日志记录。"""
        rich_log = self.query_one("#rich-log-container", RichLog)
        rich_log.clear()
        self.line_count = 0

    def toggle_scroll(self) -> bool:
        """切换自动滚动，返回切换后的状态。"""
        self.auto_scroll_enabled = not self.auto_scroll_enabled
        btn = self.query_one("#btn-toggle-scroll", Button)
        btn.label = Text(f"滚屏: {'开' if self.auto_scroll_enabled else '关'} [P]")
        rich_log = self.query_one("#rich-log-container", RichLog)
        rich_log.auto_scroll = self.auto_scroll_enabled
        return self.auto_scroll_enabled

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """工具栏按钮点击。"""
        if event.button.id == "btn-clear-log":
            self.clear_log()
        elif event.button.id == "btn-toggle-scroll":
            self.toggle_scroll()
