"""AzurPilot TUI 主应用程序。

界面由四个区域组成：顶部状态栏、左侧实例与操作栏、中间任务计划表、底部实时日志。
所有会阻塞的后端调用都放到线程里执行，主线程只负责渲染，避免启停实例或统计库
查询时终端卡住；定时器按「状态 1s / 总览 5s / 日志 0.35s」分频，兼顾实时性与开销。
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, Select, TextArea

from module.tui.backend import TUIBackend
from module.tui.widgets import (
    ConfigModal,
    HeaderBar,
    HelpScreen,
    LogView,
    ResourceBar,
    Sidebar,
    TaskModal,
    TaskTable,
)

STATUS_INTERVAL = 1.0
OVERVIEW_INTERVAL = 5.0
LOG_INTERVAL = 0.35

# 应用级快捷键动作名，用于在模态界面或文本输入时屏蔽。
APP_ACTIONS = (
    "toggle_scheduler",
    "open_config",
    "edit_selected_task",
    "run_task",
    "refresh_data",
    "clear_log",
    "toggle_scroll",
    "switch_idx",
    "show_help",
    "quit",
)


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
        Binding("question_mark", "show_help", "帮助", key_display="?"),
        Binding("f1", "show_help", "帮助", show=False),
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
        self.startup_warning: Optional[str] = None
        if default_instance and default_instance != self.backend.current_instance:
            self.startup_warning = (
                f"实例 [{default_instance}] 不存在，已回退到 [{self.backend.current_instance}]"
            )
        if not self.backend.config_service.names():
            self.startup_warning = "未找到任何实例配置，请先在 WebUI 中创建实例"
        self.cached_instances: List[Dict[str, Any]] = []
        self.log_cursor: int = 0
        self.is_busy: bool = False
        self._last_status: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_emulator: Dict[str, Any] = {}

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

        # 定时器分频：状态最频繁、总览次之，日志保持高刷。
        self.set_interval(STATUS_INTERVAL, self.tick_status)
        self.set_interval(OVERVIEW_INTERVAL, self.tick_overview)
        self.set_interval(LOG_INTERVAL, self.tick_logs)
        self.set_interval(1.0, self.tick_clock)
        self.call_after_refresh(self._focus_task_table)
        if self.startup_warning:
            self.notify(self.startup_warning, severity="warning", timeout=8, markup=False)

    def _focus_task_table(self) -> None:
        """启动后把焦点放到任务表，方向键与回车立即可用。"""
        try:
            self.query_one("#tasks-datatable", DataTable).focus()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 快捷键可用性
    # ------------------------------------------------------------------
    def check_action(self, action: str, parameters: tuple) -> Optional[bool]:
        """在模态界面与文本输入中屏蔽应用级快捷键。

        应用级 `space` / `q` 使用 priority 绑定，会跳过 Textual 对焦点控件
        按键消费的检查；若不在这里拦截，在配置输入框里输入空格会启停调度器。
        """
        try:
            if action in APP_ACTIONS and len(self.screen_stack) > 1:
                return False
            if isinstance(self.focused, (Input, TextArea, Select)):
                return False
        except Exception:
            # 屏幕尚未就绪时没有焦点控件，按默认行为放行。
            return True
        return True

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh_all_data(self) -> None:
        """触发一次完整数据刷新（在后台线程执行）。"""
        self._load_dashboard()

    @work(exclusive=True, group="data", exit_on_error=False)
    async def _load_dashboard(self) -> None:
        """后台读取实例状态、任务计划与资源看板。"""
        instance = self.backend.current_instance
        try:
            payload = await asyncio.to_thread(self.backend.load_dashboard, instance)
        except Exception as e:
            self._report_error(f"刷新数据失败: {e}")
            return
        if instance != self.backend.current_instance:
            # 期间用户切换了实例，丢弃过期结果。
            return
        self._apply_dashboard(payload)

    def _apply_dashboard(self, payload: Dict[str, Any]) -> None:
        """把后台数据渲染到各个面板。"""
        overview = payload.get("overview") or {}
        error = overview.get("error")
        if error:
            self._report_error(f"总览读取失败: {error}")
        else:
            self._clear_error()

        self._last_emulator = overview.get("emulator") or {}
        # 本次已经是最新数据，不再因状态变化重复触发一轮读取。
        self._apply_statuses(payload.get("instances") or [], allow_refresh=False)
        self.query_one(TaskTable).update_tasks(overview.get("tasks") or [])
        self.query_one(ResourceBar).update_resources(overview.get("resources") or [])

    def _apply_statuses(self, statuses: List[Dict[str, Any]], allow_refresh: bool = True) -> None:
        """更新侧边栏、顶部状态栏与按钮可用性。"""
        self.cached_instances = statuses or []
        current = self.backend.current_instance
        entry = next((item for item in statuses if item["name"] == current), None)
        status = entry.get("status", "stopped") if entry else "stopped"
        task_code = entry.get("currentTask") if entry else None
        task_title = self.backend.get_task_title(task_code) if task_code else None

        sidebar = self.query_one(Sidebar)
        sidebar.update_instances(statuses, current)
        sidebar.update_button_states(is_running=(status == "running"), busy=self.is_busy)

        self.query_one(HeaderBar).update_info(
            current,
            status,
            self._last_emulator,
            task_title,
            error=self._last_error,
        )

        if allow_refresh and self._last_status is not None and status != self._last_status:
            # 运行状态变化后，任务计划与资源看板需要重新读取。
            self.refresh_all_data()
        self._last_status = status

    def tick_status(self) -> None:
        """每秒刷新轻量运行状态（不读配置文件）。"""
        try:
            self._apply_statuses(self.backend.list_statuses())
        except Exception:
            pass

    def tick_clock(self) -> None:
        """更新状态栏时钟。"""
        try:
            if not self.screen_stack:
                return
            header = next(iter(self.screen_stack[0].query(HeaderBar)), None)
            if header is not None:
                header.tick_clock()
        except Exception:
            # 定时器可能在界面挂载或卸载的瞬间触发。
            pass

    def tick_overview(self) -> None:
        """每 5 秒刷新任务计划与资源看板。"""
        if self.is_busy:
            return
        self.refresh_all_data()

    def _report_error(self, message: str) -> None:
        """同一个错误只在首次出现时提示，避免每秒刷屏。"""
        if message == self._last_error:
            return
        self._last_error = message
        self.notify(message, severity="error", timeout=8, markup=False)

    def _clear_error(self) -> None:
        self._last_error = None

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def tick_logs(self) -> None:
        """高频轮询增量日志；缓存被裁剪时自动重载。"""
        current = self.backend.current_instance
        try:
            cursor, entries, reset = self.backend.get_logs_delta(current, after=self.log_cursor)
        except Exception:
            return
        if not entries and not reset:
            return
        try:
            log_view = self.query_one(LogView)
        except Exception:
            return
        if reset:
            log_view.clear_log()
        log_view.write_entries(entries, cursor)
        self.log_cursor = cursor

    # ------------------------------------------------------------------
    # 实例切换
    # ------------------------------------------------------------------
    def on_sidebar_instance_selected(self, event: Sidebar.InstanceSelected) -> None:
        """用户切换实例。"""
        target = event.instance_name
        if target != self.backend.current_instance:
            self.switch_to_instance(target)

    def switch_to_instance(self, instance_name: str) -> None:
        """切换当前活动实例并重置面板。"""
        if not self.backend.switch_instance(instance_name):
            self.notify(f"实例 [{instance_name}] 不存在或已被删除", severity="error", markup=False)
            return

        self.log_cursor = 0
        self._last_status = None
        try:
            log_view = self.query_one(LogView)
            log_view.clear_log()
            log_view.reset_cursor()
        except Exception:
            pass
        self.notify(f"已切换到实例: [{instance_name}]", markup=False)
        self.refresh_all_data()

    def action_switch_idx(self, idx: int) -> None:
        """按 1-9 快捷键快速切换对应索引的实例。"""
        if 1 <= idx <= len(self.cached_instances):
            self.switch_to_instance(self.cached_instances[idx - 1]["name"])
        else:
            self.notify(f"没有第 {idx} 个实例", severity="warning", markup=False)

    # ------------------------------------------------------------------
    # 运行控制
    # ------------------------------------------------------------------
    def _current_status(self) -> str:
        current = self.backend.current_instance
        for item in self.cached_instances:
            if item["name"] == current:
                return item.get("status", "stopped")
        return "stopped"

    def _set_busy(self, busy: bool) -> None:
        """切换忙碌态并同步按钮可用性。"""
        self.is_busy = busy
        try:
            self.query_one(Sidebar).update_button_states(
                is_running=(self._current_status() == "running"), busy=busy
            )
        except Exception:
            pass

    def _run_control(self, action: str, task: Optional[str] = None) -> None:
        """统一的操作入口：校验忙碌态后交给后台线程执行。"""
        if self.is_busy:
            self.notify("上一个操作还在进行中，请稍候", severity="warning", timeout=3, markup=False)
            return
        self._set_busy(True)
        self._control(action, self.backend.current_instance, task)

    @work(exclusive=True, group="control", exit_on_error=False)
    async def _control(self, action: str, instance: str, task: Optional[str]) -> None:
        """在线程中执行启动、停止、单任务与任务开关操作。"""
        ok, msg = False, "未知操作"
        try:
            if action == "start":
                ok, msg = await asyncio.to_thread(self.backend.start_scheduler, instance)
            elif action == "stop":
                ok, msg = await asyncio.to_thread(self.backend.stop_instance, instance)
            elif action == "task" and task:
                ok, msg = await asyncio.to_thread(self.backend.start_task, task, instance)
            elif action == "toggle" and task:
                ok, msg, _ = await asyncio.to_thread(self.backend.toggle_task_enable, task, instance)
        except Exception as e:
            ok, msg = False, f"操作异常: {e}"
        finally:
            self._set_busy(False)

        self.notify(msg, severity="information" if ok else "error", timeout=5, markup=False)
        self.refresh_all_data()

    def action_toggle_scheduler(self) -> None:
        """空格快捷键：启停主调度器。"""
        if self.is_busy:
            self.notify("上一个操作还在进行中，请稍候", severity="warning", timeout=3, markup=False)
            return
        if self._current_status() == "running":
            self._run_control("stop")
        else:
            self._run_control("start")

    def start_current_scheduler(self) -> None:
        """启动当前实例调度器。"""
        self._run_control("start")

    def stop_current_instance(self) -> None:
        """停止当前实例。"""
        self._run_control("stop")

    def action_run_task(self) -> None:
        """T 快捷键：打开单任务触发模态窗。"""
        if self.is_busy:
            self.notify("上一个操作还在进行中，请稍候", severity="warning", timeout=3, markup=False)
            return
        tasks = self.backend.get_available_tasks()
        if not tasks:
            self.notify("当前无可用单任务功能", severity="warning")
            return

        def handle_selected_task(task_code: Optional[str]) -> None:
            if task_code:
                self._run_control("task", task_code)

        self.push_screen(TaskModal(tasks), handle_selected_task)

    def run_single_task(self, task_code: str) -> None:
        """执行单任务。"""
        self._run_control("task", task_code)

    def action_refresh_data(self) -> None:
        """R 快捷键：手动强制刷新。"""
        self.refresh_all_data()
        self.notify("正在刷新数据…", timeout=2)

    def action_clear_log(self) -> None:
        """L 快捷键：清空日志窗。"""
        log_view = self.query_one(LogView)
        log_view.clear_log()
        self.notify("日志视窗已清空", timeout=2)

    def action_toggle_scroll(self) -> None:
        """P 快捷键：切换日志自动滚屏。"""
        log_view = self.query_one(LogView)
        enabled = log_view.toggle_scroll()
        self.notify(f"自动滚屏已{'开启' if enabled else '关闭'}", timeout=2)

    def action_show_help(self) -> None:
        """? 快捷键：显示快捷键与使用说明。"""
        self.push_screen(HelpScreen())

    # ------------------------------------------------------------------
    # 配置编辑
    # ------------------------------------------------------------------
    def action_open_config(self, task: Optional[str] = None) -> None:
        """C 快捷键：打开功能配置中心。"""
        if self.is_busy:
            self.notify("上一个操作还在进行中，请稍候", severity="warning", timeout=3, markup=False)
            return
        current = self.backend.current_instance

        def on_config_closed(saved: bool) -> None:
            if saved:
                self.refresh_all_data()

        self.push_screen(ConfigModal(self.backend, initial_task=task, instance=current), on_config_closed)

    def action_edit_selected_task(self) -> None:
        """E 快捷键：编辑当前表格选中的任务。"""
        selected_task = self.query_one(TaskTable).get_selected_task()
        if not selected_task:
            self.notify("请先在任务表中选择一个任务", severity="warning", timeout=3)
            return
        self.action_open_config(task=selected_task)

    def on_task_table_task_toggle_requested(self, event: TaskTable.TaskToggleRequested) -> None:
        """表格回车：一键切换任务启用/禁用状态。"""
        self._run_control("toggle", event.task_name)

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
