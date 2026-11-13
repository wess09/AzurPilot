"""TUI 侧边栏组件。

包含实例列表选择与核心生命周期操作按钮。实例列表只在名称或运行状态变化时
重建，避免每秒刷新打断用户的方向键浏览。
"""

from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option

# 状态 → (符号, 颜色)，使用通用符号，避免旧终端无法渲染 emoji。
STATUS_STYLE = {
    "running": ("●", "bold green"),
    "error": ("●", "bold red"),
    "updating": ("◐", "bold yellow"),
    "stopped": ("○", "dim white"),
}

ACTION_BUTTON_IDS = ("btn-config", "btn-task", "btn-refresh")


class Sidebar(ScrollableContainer):
    """侧边栏面板。"""

    DEFAULT_CSS = """
    Sidebar {
        width: 28;
        dock: left;
        background: $panel;
        border-right: solid $primary-darken-2;
        padding: 0 1;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }
    #instances-title {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 0;
    }
    #instance-list {
        height: auto;
        max-height: 8;
        min-height: 3;
        background: $surface;
        border: solid $primary-darken-3;
        margin-bottom: 1;
    }
    #actions-title {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 0;
    }
    .action-btn {
        width: 100%;
        margin-bottom: 0;
    }
    #hint-label {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
        text-wrap: wrap;
        height: auto;
    }
    """

    class InstanceSelected(Message):
        """实例切换事件。"""

        def __init__(self, instance_name: str) -> None:
            super().__init__()
            self.instance_name = instance_name

    class ActionTriggered(Message):
        """控制操作事件。"""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.instance_names: List[str] = []
        self.current_selected: str = ""
        self._signature: Optional[tuple] = None

    def compose(self) -> ComposeResult:
        yield Label("📁 配置实例 (1-9)", id="instances-title")
        yield OptionList(id="instance-list")
        yield Label("⚡ 快捷操作", id="actions-title")
        # Text 不会被当作 Rich markup 解析，方括号提示才能原样显示。
        yield Button(Text("▶ 启动调度器"), id="btn-start", variant="success", classes="action-btn")
        yield Button(Text("⏹ 停止运行"), id="btn-stop", variant="error", classes="action-btn")
        yield Button(Text("⚙ 功能配置 [C]"), id="btn-config", variant="primary", classes="action-btn")
        yield Button(Text("🎯 单任务执行 [T]"), id="btn-task", variant="default", classes="action-btn")
        yield Button(Text("🔄 刷新状态 [R]"), id="btn-refresh", variant="default", classes="action-btn")
        yield Label(
            "Space 启停  C 配置\nE 编辑  ? 帮助\nEnter 开关任务  R 刷新",
            id="hint-label",
            markup=False,
        )

    @staticmethod
    def _option_label(index: int, instance: Dict[str, Any]) -> Text:
        """构造带状态色点的实例选项。"""
        status = instance.get("status", "stopped")
        symbol, style = STATUS_STYLE.get(status, STATUS_STYLE["stopped"])
        name = str(instance.get("name", ""))
        label = Text()
        label.append(f"{index + 1}. ")
        label.append(f"{symbol} ", style=style)
        label.append(name)
        if status == "running":
            task = instance.get("currentTask")
            if task:
                label.append(f"  {task}", style="dim")
        return label

    def update_instances(self, instances: List[Dict[str, Any]], current: str) -> None:
        """更新实例列表，仅在内容变化时重建选项。"""
        signature = tuple((inst.get("name"), inst.get("status"), inst.get("currentTask")) for inst in instances)
        option_list = self.query_one("#instance-list", OptionList)
        current_changed = current != self.current_selected
        self.current_selected = current

        if signature == self._signature and not current_changed:
            return

        highlighted_id = self._highlighted_id(option_list)
        previous_names = self.instance_names
        self.instance_names = [str(inst.get("name", "")) for inst in instances]

        if self.instance_names != previous_names:
            option_list.clear_options()
            option_list.add_options([
                Option(prompt=self._option_label(index, inst), id=self.instance_names[index])
                for index, inst in enumerate(instances)
            ])
        elif signature != self._signature:
            # 实例集合不变时原地更新 prompt，保留用户当前高亮位置。
            for index, inst in enumerate(instances):
                option_list.replace_option_prompt_at_index(index, self._option_label(index, inst))

        self._signature = signature

        if not self.instance_names:
            return
        # 通过数字键或外部切换实例时，把高亮同步到当前实例。
        if current_changed:
            preferred = current if current in self.instance_names else self.instance_names[0]
        elif highlighted_id in self.instance_names:
            preferred = highlighted_id
        else:
            preferred = self.instance_names[0]

        index = self.instance_names.index(preferred)
        if option_list.highlighted != index:
            option_list.highlighted = index

    @staticmethod
    def _highlighted_id(option_list: OptionList) -> Optional[str]:
        """读取当前高亮选项 ID，读取失败时返回 None。"""
        try:
            index = option_list.highlighted
            if index is not None and 0 <= index < option_list.option_count:
                option = option_list.get_option_at_index(index)
                return str(option.id) if option.id is not None else None
        except Exception:
            pass
        return None

    def update_button_states(self, is_running: bool, busy: bool = False) -> None:
        """根据运行状态与忙碌态更新按钮可用性。"""
        try:
            start_btn = self.query_one("#btn-start", Button)
            stop_btn = self.query_one("#btn-stop", Button)
            start_btn.disabled = busy or is_running
            stop_btn.disabled = busy or not is_running
            for button_id in ACTION_BUTTON_IDS:
                self.query_one(f"#{button_id}", Button).disabled = busy
        except Exception:
            # 界面尚未挂载完成时忽略。
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """实例列表选项被选中时触发。"""
        if event.option_id and str(event.option_id) != self.current_selected:
            self.current_selected = str(event.option_id)
            self.post_message(self.InstanceSelected(self.current_selected))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击事件处理。"""
        btn_id = event.button.id
        if btn_id == "btn-start":
            self.post_message(self.ActionTriggered("start"))
        elif btn_id == "btn-stop":
            self.post_message(self.ActionTriggered("stop"))
        elif btn_id == "btn-config":
            self.post_message(self.ActionTriggered("config"))
        elif btn_id == "btn-task":
            self.post_message(self.ActionTriggered("task"))
        elif btn_id == "btn-refresh":
            self.post_message(self.ActionTriggered("refresh"))
