"""TUI 单任务选择执行模态弹窗组件。"""

from typing import List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList
from textual.widgets.option_list import Option


class TaskModal(ModalScreen[Optional[str]]):
    """独立单任务选择运行模态窗口。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消", priority=True),
        Binding("down", "focus_options", "选择", show=False),
    ]

    DEFAULT_CSS = """
    TaskModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #modal-dialog {
        width: 90%;
        max-width: 70;
        height: 90%;
        max-height: 26;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #modal-title {
        text-style: bold;
        color: $accent;
        text-align: center;
        margin-bottom: 1;
    }
    #modal-desc {
        color: $text-muted;
        margin-bottom: 1;
        text-align: center;
    }
    #task-filter {
        margin-bottom: 1;
    }
    #filter-status {
        color: $text-muted;
        height: 1;
    }
    #task-option-list {
        height: 1fr;
        min-height: 3;
        border: solid $primary-darken-3;
        background: $surface-darken-1;
        margin-bottom: 1;
    }
    #modal-button-box {
        height: 3;
        align: center middle;
    }
    .modal-btn {
        margin: 0 1;
        min-width: 14;
    }
    """

    def __init__(self, tasks: List[Tuple[str, str]]) -> None:
        super().__init__()
        self.tasks = tasks
        self.filtered_tasks = list(tasks)
        self.selected_task: Optional[str] = tasks[0][0] if tasks else None

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label("🎯 选择要单独执行的任务功能", id="modal-title")
            yield Label("输入关键词过滤，回车立即执行；Esc 取消", id="modal-desc")
            yield Input(placeholder="过滤任务名称或代码…", id="task-filter")
            yield Label("", id="filter-status")
            yield OptionList(id="task-option-list")
            with Horizontal(id="modal-button-box"):
                yield Button(Text("▶ 立即执行"), id="btn-confirm", variant="success", classes="modal-btn")
                yield Button(Text("✕ 取消 [Esc]"), id="btn-cancel", variant="default", classes="modal-btn")

    def on_mount(self) -> None:
        """初始化选项列表并聚焦过滤框。"""
        self._rebuild_options()
        self.query_one("#task-filter", Input).focus()

    def _option_label(self, task_code: str, title: str) -> str:
        return f"{title} ({task_code})" if title != task_code else task_code

    def _rebuild_options(self) -> None:
        """按当前过滤关键字重建选项列表。"""
        option_list = self.query_one("#task-option-list", OptionList)
        option_list.clear_options()
        option_list.add_options([
            Option(prompt=self._option_label(code, title), id=code)
            for code, title in self.filtered_tasks
        ])
        if self.filtered_tasks:
            option_list.highlighted = 0
            self.selected_task = self.filtered_tasks[0][0]
        else:
            self.selected_task = None

        try:
            status = (
                f"共 {len(self.filtered_tasks)} 项候选"
                if self.filtered_tasks
                else "没有匹配的任务，请修改关键词"
            )
            self.query_one("#filter-status", Label).update(status)
        except Exception:
            pass

    def _apply_filter(self, keyword: str) -> None:
        keyword = keyword.strip().lower()
        if not keyword:
            self.filtered_tasks = list(self.tasks)
        else:
            self.filtered_tasks = [
                (code, title)
                for code, title in self.tasks
                if keyword in code.lower() or keyword in title.lower()
            ]
        self._rebuild_options()

    def on_input_changed(self, event: Input.Changed) -> None:
        """过滤框内容变化时刷新候选任务。"""
        if event.input.id == "task-filter":
            self._apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """过滤框回车：执行当前高亮任务；没有匹配项时保持窗口打开。"""
        if event.input.id == "task-filter" and self.selected_task:
            self.dismiss(self.selected_task)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """高亮选项变动。"""
        if event.option_id:
            self.selected_task = str(event.option_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """回车直接确认执行。"""
        if event.option_id:
            self.dismiss(str(event.option_id))

    def action_focus_options(self) -> None:
        """从过滤框切到候选列表。"""
        self.query_one("#task-option-list", OptionList).focus()

    def action_cancel(self) -> None:
        """按 Esc 取消退出。"""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击。"""
        if event.button.id == "btn-confirm" and self.selected_task:
            self.dismiss(self.selected_task)
        elif event.button.id == "btn-cancel":
            self.dismiss(None)
