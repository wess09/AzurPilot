"""AzurPilot TUI 主应用程序。"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer

from module.tui.backend import TUIBackend
from module.tui.widgets import ConfigModal, HeaderBar, LogView, ResourceBar, Sidebar, TaskModal, TaskTable


class AzurPilotTUI(App[None]):
    """AzurPilot 终端用户交互应用。"""

    CSS_PATH = "theme.tcss"
    TITLE = "AzurPilot TUI"
    SUB_TITLE = "碧蓝航线自动化终端管理系统"

    BINDINGS = [
        Binding("space", "toggle_scheduler", "启动/停止", priority=True),
        Binding("c", "open_config", "配置功能"),
        Binding("e", "edit_selected_task", "编辑选中任务"),
        Binding("t", "run_task", "单任务执行"),
        Binding("r", "refresh_data", "刷新"),
        Binding("l", "clear_log", "清屏"),
        Binding("p", "toggle_scroll", "滚屏开/关"),
        Binding("1", "switch_idx(1)", "实例1", show=False),
        Binding("2", "switch_idx(2)", "实例2", show=False),
        Binding("3", "switch_idx(3)", "实例3", show=False),
        Binding("4", "switch_idx(4)", "实例4", show=False),
        Binding("5", "switch_idx(5)", "实例5", show=False),
        Binding("6", "switch_idx(6)", "实例6", show=False),
        Binding("7", "switch_idx(7)", "实例7", show=False),
        Binding("8", "switch_idx(8)", "实例8", show=False),
        Binding("9", "switch_idx(9)", "实例9", show=False),
        Binding("q", "quit", "退出", priority=True),
    ]

    def __init__(
        self,
        default_instance: Optional[str] = None,
        root: Optional[Path] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.backend = TUIBackend(root=root, default_instance=default_instance)
        self.cached_instances: List[Dict[str, Any]] = []
        self.log_cursor: int = 0
        self.is_busy: bool = False

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")
        with Horizontal(id="main-layout"):
            yield Sidebar(id="sidebar")
            with Vertical(id="content-pane"):
                yield TaskTable(id="task-table")
                yield ResourceBar(id="resource-bar")
                yield LogView(id="log-view")
        yield Footer()

    def on_mount(self) -> None:
        """应用初始化挂载，启动后台定时器。"""
        self.refresh_all_data()

        # 启动后台异步定时轮询
        self.set_interval(1.0, self.tick_overview)
        self.set_interval(0.35, self.tick_logs)
        self.set_interval(1.0, self.tick_clock)

    def tick_clock(self) -> None:
        """更新状态栏时钟。"""
        header = self.screen_stack[0].query_one(HeaderBar)
        header.tick_clock()

    def refresh_all_data(self) -> None:
        """全量刷新实例列表、当前总览与时间表。"""
        try:
            self.cached_instances = self.backend.list_instances()
            current = self.backend.current_instance

            # 更新侧边栏
            sidebar = self.query_one(Sidebar)
            sidebar.update_instances(self.cached_instances, current)

            # 获取当前实例总览
            overview = self.backend.get_overview(current)
            status = overview.get("status", "stopped")
            emulator = overview.get("emulator", {})
            current_task = None
            for inst in self.cached_instances:
                if inst["name"] == current:
                    current_task = inst.get("currentTask")
                    break

            # 更新顶部栏与侧边栏按钮
            header = self.query_one(HeaderBar)
            header.update_info(current, status, emulator, current_task)
            sidebar.update_button_states(is_running=(status == "running"))

            # 更新任务时间表与资源
            task_table = self.query_one(TaskTable)
            task_table.update_tasks(overview.get("tasks", []))

            resource_bar = self.query_one(ResourceBar)
            resource_bar.update_resources(overview.get("resources", []))
        except Exception as e:
            self.notify(f"刷新数据失败: {e}", severity="error")

    def tick_overview(self) -> None:
        """定时轻量更新实例状态与任务列表。"""
        if self.is_busy:
            return
        self.refresh_all_data()

    def tick_logs(self) -> None:
        """高频轮询增量日志。"""
        current = self.backend.current_instance
        try:
            new_cursor, entries = self.backend.get_logs(current, after=self.log_cursor)
            if entries:
                log_view = self.query_one(LogView)
                log_view.write_entries(entries, new_cursor)
                self.log_cursor = new_cursor
        except Exception:
            pass

    def on_sidebar_instance_selected(self, event: Sidebar.InstanceSelected) -> None:
        """用户切换实例。"""
        target = event.instance_name
        if target != self.backend.current_instance:
            self.switch_to_instance(target)

    def switch_to_instance(self, instance_name: str) -> None:
        """切换当前活动实例并重置面板。"""
        if self.backend.switch_instance(instance_name):
            self.log_cursor = 0
            log_view = self.query_one(LogView)
            log_view.clear_log()
            self.notify(f"已切换到实例: [{instance_name}]")
            self.refresh_all_data()

    def action_switch_idx(self, idx: int) -> None:
        """按 1-9 快捷键快速切换对应索引的实例。"""
        if self.cached_instances and 1 <= idx <= len(self.cached_instances):
            target = self.cached_instances[idx - 1]["name"]
            self.switch_to_instance(target)

    def action_toggle_scheduler(self) -> None:
        """空格快捷键：启停主调度器。"""
        current = self.backend.current_instance
        overview = self.backend.get_overview(current)
        status = overview.get("status", "stopped")

        if status == "running":
            self.stop_current_instance()
        else:
            self.start_current_scheduler()

    def start_current_scheduler(self) -> None:
        """启动当前实例调度器。"""
        current = self.backend.current_instance
        self.is_busy = True
        try:
            success, msg = self.backend.start_scheduler(current)
            self.notify(msg, severity="information" if success else "error")
            self.refresh_all_data()
        finally:
            self.is_busy = False

    def stop_current_instance(self) -> None:
        """停止当前实例。"""
        current = self.backend.current_instance
        self.is_busy = True
        try:
            success, msg = self.backend.stop_instance(current)
            self.notify(msg, severity="warning" if success else "error")
            self.refresh_all_data()
        finally:
            self.is_busy = False

    def action_run_task(self) -> None:
        """T 快捷键：打开单任务触发模态窗。"""
        tasks = self.backend.get_available_tasks()
        if not tasks:
            self.notify("当前无可用单任务功能", severity="warning")
            return

        def handle_selected_task(task_code: Optional[str]) -> None:
            if task_code:
                self.run_single_task(task_code)

        self.push_screen(TaskModal(tasks), handle_selected_task)

    def run_single_task(self, task_code: str) -> None:
        """执行单任务。"""
        current = self.backend.current_instance
        self.is_busy = True
        try:
            success, msg = self.backend.start_task(task_code, instance=current)
            self.notify(msg, severity="information" if success else "error")
            self.refresh_all_data()
        finally:
            self.is_busy = False

    def action_refresh_data(self) -> None:
        """R 快捷键：手动强制刷新。"""
        self.refresh_all_data()
        self.notify("数据已手动刷新")

    def action_clear_log(self) -> None:
        """L 快捷键：清空日志窗。"""
        log_view = self.query_one(LogView)
        log_view.clear_log()
        self.notify("日志视窗已清空")

    def action_toggle_scroll(self) -> None:
        """P 快捷键：切换日志自动滚屏。"""
        log_view = self.query_one(LogView)
        log_view.toggle_scroll()

    def action_open_config(self, task: Optional[str] = None) -> None:
        """C 快捷键：打开功能配置中心。"""
        current = self.backend.current_instance

        def on_config_closed(saved: bool) -> None:
            if saved:
                self.refresh_all_data()

        self.push_screen(ConfigModal(self.backend, initial_task=task, instance=current), on_config_closed)

    def action_edit_selected_task(self) -> None:
        """E 快捷键：编辑当前表格选中的任务。"""
        task_table = self.query_one(TaskTable)
        selected_task = task_table.get_selected_task()
        self.action_open_config(task=selected_task)

    def on_task_table_task_toggle_requested(self, event: TaskTable.TaskToggleRequested) -> None:
        """表格回车：一键切换任务启用/禁用状态。"""
        task = event.task_name
        success, msg, _ = self.backend.toggle_task_enable(task)
        self.notify(msg, severity="information" if success else "error")
        if success:
            self.refresh_all_data()

    def on_task_table_task_edit_requested(self, event: TaskTable.TaskEditRequested) -> None:
        """表格请求编辑：打开该任务的配置窗。"""
        self.action_open_config(task=event.task_name)

    def on_sidebar_action_triggered(self, event: Sidebar.ActionTriggered) -> None:
        """处理来自侧边栏按钮的点击事件。"""
        action = event.action
        if action == "start":
            self.start_current_scheduler()
        elif action == "stop":
            self.stop_current_instance()
        elif action == "config":
            self.action_open_config()
        elif action == "task":
            self.action_run_task()
        elif action == "refresh":
            self.action_refresh_data()
