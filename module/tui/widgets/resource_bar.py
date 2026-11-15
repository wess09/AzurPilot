"""TUI 资源看板面板组件。"""

from typing import Any, Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label


def format_value(value: Any) -> str:
    """把资源数值格式化成便于阅读的文本。"""
    if isinstance(value, bool) or value is None:
        return "-"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.1f}" if not value.is_integer() else f"{int(value):,}"
    return str(value)


class ResourceBar(Widget):
    """游戏与大世界资源状态条。"""

    DEFAULT_CSS = """
    ResourceBar {
        height: 3;
        background: $surface-darken-1;
        border: solid $primary-darken-3;
        padding: 0 1;
    }
    #resource-container {
        width: 100%;
        height: 100%;
        align: left middle;
    }
    #res-summary {
        width: 100%;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="resource-container"):
            yield Label("📊 资源看板: 暂无数据", id="res-summary")

    def update_resources(self, resources: List[Dict[str, Any]]) -> None:
        """更新资源统计数据，忽略没有数值的条目。"""
        try:
            summary_label = self.query_one("#res-summary", Label)
        except Exception:
            return

        items = [res for res in resources if res.get("value") is not None]
        if not items:
            summary_label.update(Text("📊 资源看板: 暂无统计数据", style="dim"))
            return

        res_text = Text()
        res_text.append("📊 资源: ", style="bold cyan")
        for idx, res in enumerate(items):
            label = res.get("label") or res.get("name", "")
            value = format_value(res.get("value"))
            limit = res.get("limit")
            if limit is not None:
                value += f"/{format_value(limit)}"

            res_text.append(f"{label}: ", style="dim")
            res_text.append(value, style="bold cyan")
            if idx < len(items) - 1:
                res_text.append("  │  ", style="dim")

        summary_label.update(res_text)
