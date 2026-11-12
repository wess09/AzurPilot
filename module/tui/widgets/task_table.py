"""TUI 任务时间表面板组件。

表格会同时展示已启用与已禁用的可调度任务：禁用任务以暗色显示，
按回车即可重新启用，避免任务被关掉后在界面上彻底消失。
"""

from typing import Any, Dict, List, Optional

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Label

STATE_COLUMN_WIDTH = 11
# 时间显示到分钟（16 列），再留滚动条与单元格内边距的宽度。
TIME_COLUMN_WIDTH = 21
# 低于该宽度时隐藏「下次执行」列，优先保证任务名称可读。
TIME_COLUMN_MIN_WIDTH = 55

STATE_STYLE = {
    "running": ("● 运行中", "bold green"),
    "pending": ("◆ 待执行", "bold yellow"),
    "waiting": ("○ 等待中", "white"),
    "disabled": ("⏸ 已禁用", "dim"),
}
EMPTY_ROW_KEY = "__empty__"


class TaskTable(Widget):
    """任务计划队列与时间表。"""

    class TaskToggleRequested(Message):
        """用户请求切换任务启用状态事件。"""

        def __init__(self, task_name: str) -> None:
            super().__init__()
            self.task_name = task_name

    class TaskEditRequested(Message):
        """用户请求编辑任务配置事件。"""

        def __init__(self, task_name: str) -> None:
            super().__init__()
            self.task_name = task_name

    DEFAULT_CSS = """
    TaskTable {
        height: 40%;
        min-height: 8;
        max-height: 18;
        background: $surface;
        border: solid $primary-darken-2;
        padding: 0 1;
    }
    #task-table-title {
        text-style: bold;
        color: $accent;
        margin-top: 0;
        margin-bottom: 0;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    #tasks-datatable {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.task_names: List[str] = []
        self._tasks: List[Dict[str, Any]] = []
        self._signature: Optional[tuple] = None
        self._layout: Optional[tuple] = None
        self._restore_name: Optional[str] = None
        self._name_width: int = 16
        self._show_time: bool = True

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                "📋 任务计划表 ─ [Enter] 开关任务  [E] 编辑",
                id="task-table-title",
                markup=False,
            )
            yield DataTable(id="tasks-datatable", cursor_type="row")

    def on_mount(self) -> None:
        """挂载时初始化表头并显示空状态。"""
        self._apply_column_layout(0)

    def on_resize(self, event: events.Resize) -> None:
        """终端尺寸变化时按可用宽度重排各列。"""
        self._apply_column_layout(event.size.width)

    def _apply_column_layout(self, panel_width: int) -> None:
        """根据面板宽度决定列宽，并重建表头。

        Args:
            panel_width: 面板宽度；为 0 表示尚未完成布局，先按最小宽度处理。
        """
        try:
            table = self.query_one("#tasks-datatable", DataTable)
        except Exception:
            return

        width = panel_width or table.size.width
        # 面板自身占 4 列（边框 + 内边距），右侧滚动条再占 2 列。
        available = max(20, width - 6)
        show_time = available >= TIME_COLUMN_MIN_WIDTH
        name_width = max(16, available - STATE_COLUMN_WIDTH - (TIME_COLUMN_WIDTH if show_time else 0))
        layout = (name_width, show_time)
        if layout == self._layout:
            return

        self._layout = layout
        self._name_width = name_width
        self._show_time = show_time
        self._restore_name = self._selected_name()

        table.clear(columns=True)
        table.add_column("状态", width=STATE_COLUMN_WIDTH)
        table.add_column("任务名称", width=name_width)
        if show_time:
            table.add_column("下次执行", width=TIME_COLUMN_WIDTH)

        self._signature = None
        self.update_tasks(self._tasks)

    @staticmethod
    def _fit_text(text: str, width: int) -> str:
        """按显示宽度截断文本并补省略号，避免中文被硬切。"""
        if width <= 0:
            return ""
        if cell_len(text) <= width:
            return text
        fitted = ""
        for char in text:
            if cell_len(fitted + char) > width - 1:
                break
            fitted += char
        return fitted + "…"

    def _display_name(self, title: str, name: str) -> str:
        """在有限宽度内保留任务代码，标题过长时截断标题。"""
        width = self._name_width
        if title == name:
            return self._fit_text(name, width)
        suffix = f" ({name})"
        if cell_len(suffix) >= width:
            return self._fit_text(name, width)
        return self._fit_text(title, width - cell_len(suffix)) + suffix

    def update_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """更新任务计划列表，内容未变化时不做任何操作。"""
        self._tasks = list(tasks)
        signature = tuple(
            (
                task.get("name", ""),
                task.get("state", "waiting"),
                bool(task.get("enabled", True)),
                str(task.get("nextRun", "")),
            )
            for task in tasks
        )
        if signature == self._signature:
            return
        self._signature = signature

        table = self.query_one("#tasks-datatable", DataTable)
        previous_name = self._restore_name or self._selected_name()
        self._restore_name = None

        table.clear()
        self.task_names.clear()

        if not tasks:
            empty_row = [Text("—", style="dim"), Text("暂无可调度的任务", style="dim italic")]
            if self._show_time:
                empty_row.append(Text("—", style="dim"))
            table.add_row(*empty_row, key=EMPTY_ROW_KEY)
            return

        for task in tasks:
            name = str(task.get("name", ""))
            if not name:
                continue
            self.task_names.append(name)
            title = task.get("title") or name
            display_name = self._display_name(str(title), name)
            next_run = str(task.get("nextRun", "") or "")
            enabled = bool(task.get("enabled", True))

            state = task.get("state", "waiting")
            if not enabled:
                state = "disabled"
            elif state not in STATE_STYLE:
                state = "waiting"
            state_text, state_style = STATE_STYLE[state]

            if state == "running":
                name_text = Text(display_name, style="bold green")
            elif state == "pending":
                name_text = Text(display_name, style="yellow")
            elif state == "disabled":
                name_text = Text(display_name, style="dim")
            else:
                name_text = Text(display_name)

            row = [Text(state_text, style=state_style), name_text]
            if self._show_time:
                row.append(Text(next_run.replace("T", " ")[:16] if next_run else "—",
                                style="cyan" if state == "pending" else "dim" if state == "disabled" else ""))
            table.add_row(*row, key=name)

        if not self.task_names:
            return
        if previous_name and previous_name in self.task_names:
            table.move_cursor(row=self.task_names.index(previous_name))
        else:
            table.move_cursor(row=0)

    def _selected_name(self) -> Optional[str]:
        """读取当前光标所在行的任务代码。"""
        try:
            table = self.query_one("#tasks-datatable", DataTable)
            row = table.cursor_row
            if row is not None and 0 <= row < len(self.task_names):
                return self.task_names[row]
        except Exception:
            pass
        return None

    def get_selected_task(self) -> Optional[str]:
        """获取当前光标选中的任务代码。"""
        return self._selected_name()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """用户在某一行回车时，派发启闭该任务的请求。"""
        selected_task = self.get_selected_task()
        if selected_task:
            self.post_message(self.TaskToggleRequested(selected_task))
