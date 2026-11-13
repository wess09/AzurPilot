"""AzurPilot TUI 桥接后端与界面挂载单元测试。"""

import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from textual.widgets import Input

from tests.test_api import fixture

from module.runtime.setting import State
from module.runtime.updater import updater
from module.tui.app import AzurPilotTUI
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


class TestLauncherTuiArgs(unittest.TestCase):
    """启动器 ``--tui`` 参数解析。"""

    def test_tui_request(self) -> None:
        """未指定时不进入 TUI；指定时可选带实例名。"""
        from gui import tui_request

        self.assertEqual((False, None), tui_request([]))
        self.assertEqual((False, None), tui_request(['-r']))
        self.assertEqual((False, None), tui_request(['--host', '0.0.0.0']))
        self.assertEqual((True, None), tui_request(['--tui']))
        self.assertEqual((True, 'alas'), tui_request(['--tui', 'alas']))
        self.assertEqual((True, 'alas'), tui_request(['--tui=alas']))
        self.assertEqual((True, None), tui_request(['--tui', '--reload']))

    def test_run_tui_delegates_to_app(self) -> None:
        """run_tui 将实例名传给 Textual 应用并返回退出码。"""
        from gui import run_tui

        with (
            patch('gui.configure_tui_console'),
            patch('module.logger.logger.removeHandler'),
            patch('module.tui.app.AzurPilotTUI') as app_cls,
        ):
            self.assertEqual(0, run_tui('alas'))

        app_cls.assert_called_once_with(default_instance='alas')
        app_cls.return_value.run.assert_called_once_with()

    def test_run_tui_returns_failure_on_crash(self) -> None:
        """界面异常退出时返回非零退出码。"""
        from gui import run_tui

        with (
            patch('gui.configure_tui_console'),
            patch('module.logger.logger.removeHandler'),
            patch('module.tui.app.AzurPilotTUI') as app_cls,
        ):
            app_cls.return_value.run.side_effect = RuntimeError('boom')
            self.assertEqual(1, run_tui())

        app_cls.assert_called_once_with(default_instance=None)


class IsolatedTUIFixture:
    """实例、进程登记和 Manager 都由测试独占，不读取用户运行状态。"""

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = fixture(directory.name)
        patches = [
            patch('module.runtime.worker_registry.WORKER_REGISTRY_FILE', self.root / 'cache/workers.json'),
            patch.multiple(State, manager=None, process_registry=None, _init=False,
                           _clearup=False, _restart_requested=False),
            patch.object(updater, 'event', None),
        ]
        for context in patches:
            context.start()
            self.addCleanup(context.stop)
        self.addCleanup(self.close_manager)

    @staticmethod
    def close_manager():
        if State.manager is not None:
            State.manager.shutdown()


class TestTUIBackend(IsolatedTUIFixture, unittest.TestCase):
    """测试 TUIBackend 数据桥接与业务逻辑。"""

    def setUp(self) -> None:
        super().setUp()
        self.backend = TUIBackend(root=self.root)

    def test_state_manager_initialized(self) -> None:
        """测试全局多进程管理器正常就绪，避免子进程启动出现 NoneType Queue。"""
        self.assertIsNotNone(State.manager)

    def test_list_instances(self) -> None:
        """测试实例列表获取。"""
        instances = self.backend.list_instances()
        self.assertIsInstance(instances, list)
        self.assertGreater(len(instances), 0)
        first = instances[0]
        self.assertIn("name", first)
        self.assertIn("status", first)
        self.assertIn("serial", first)
        self.assertIn("server", first)

    def test_switch_instance(self) -> None:
        """测试实例切换。"""
        instances = self.backend.list_instances()
        target_name = instances[0]["name"]
        self.assertTrue(self.backend.switch_instance(target_name))
        self.assertEqual(self.backend.current_instance, target_name)

        # 切换不存在的实例应返回 False
        self.assertFalse(self.backend.switch_instance("non_existent_instance_9999"))

    def test_get_overview(self) -> None:
        """测试总览信息获取与任务翻译补充。"""
        overview = self.backend.get_overview()
        self.assertIsInstance(overview, dict)
        self.assertIn("status", overview)
        self.assertIn("tasks", overview)
        self.assertIn("resources", overview)
        self.assertIn("emulator", overview)

        # 校验任务列表结构
        for task in overview.get("tasks", []):
            self.assertIn("name", task)
            self.assertIn("title", task)

    def test_get_available_tasks(self) -> None:
        """测试可独立执行的任务列表。"""
        tasks = self.backend.get_available_tasks()
        self.assertIsInstance(tasks, list)
        self.assertGreater(len(tasks), 0)
        for code, title in tasks:
            self.assertIsInstance(code, str)
            self.assertIsInstance(title, str)

    def test_get_all_configurable_tasks(self) -> None:
        """测试所有可配置任务列表获取。"""
        tasks = self.backend.get_all_configurable_tasks()
        self.assertIsInstance(tasks, list)
        self.assertGreater(len(tasks), 10)
        task_codes = [t[0] for t in tasks]
        self.assertIn("Commission", task_codes)
        self.assertIn("Research", task_codes)

    def test_get_task_config_schema(self) -> None:
        """测试任务参数元数据解析与字段组装。"""
        groups = self.backend.get_task_config_schema("Commission")
        self.assertIsInstance(groups, list)
        self.assertGreater(len(groups), 0)
        first_group = groups[0]
        self.assertIn("group_name", first_group)
        self.assertIn("group_title", first_group)
        self.assertIn("items", first_group)
        first_item = first_group["items"][0]
        self.assertIn("path", first_item)
        self.assertIn("title", first_item)
        self.assertIn("type", first_item)
        self.assertIn("mode", first_item)
        self.assertIn("valuetype", first_item)

    def test_get_logs(self) -> None:
        """测试日志拉取契约。"""
        cursor, entries = self.backend.get_logs(after=0)
        self.assertIsInstance(cursor, int)
        self.assertIsInstance(entries, list)
        delta_cursor, delta_entries, reset = self.backend.get_logs_delta(after=0)
        self.assertEqual(cursor, delta_cursor)
        self.assertEqual(entries, delta_entries)
        self.assertIsInstance(reset, bool)

    def test_list_statuses_contract(self) -> None:
        """轻量状态轮询不读配置，且覆盖全部实例。"""
        statuses = self.backend.list_statuses()
        self.assertEqual([item["name"] for item in statuses], self.backend.config_service.names())
        for item in statuses:
            self.assertIn(item["status"], ("running", "stopped", "error", "updating"))
            self.assertIn("currentTask", item)

    def test_overview_lists_disabled_tasks_and_can_reenable(self) -> None:
        """禁用任务仍需出现在总览中，否则界面无法再次启用。"""
        success, _, enabled = self.backend.toggle_task_enable("Commission")
        self.assertTrue(success, "关闭任务计划失败")
        self.assertFalse(enabled)

        overview = self.backend.get_overview()
        entry = next(item for item in overview["tasks"] if item["name"] == "Commission")
        self.assertFalse(entry["enabled"])
        self.assertEqual("disabled", entry["state"])

        success, _, enabled = self.backend.toggle_task_enable("Commission")
        self.assertTrue(success, "重新启用任务计划失败")
        self.assertTrue(enabled)

        overview = self.backend.get_overview()
        entry = next(item for item in overview["tasks"] if item["name"] == "Commission")
        self.assertTrue(entry["enabled"])
        self.assertNotEqual("disabled", entry["state"])

    def test_toggle_unsupported_task(self) -> None:
        """没有 Scheduler.Enable 的任务不应被误写配置。"""
        success, message, enabled = self.backend.toggle_task_enable("Storage")
        self.assertFalse(success)
        self.assertFalse(enabled)
        self.assertIn("不支持", message)


class TestTUIApp(IsolatedTUIFixture, unittest.IsolatedAsyncioTestCase):
    """测试 Textual TUI 应用生命周期与组件挂载。"""

    def setUp(self):
        super().setUp()
        factory = patch('module.tui.app.TUIBackend', side_effect=lambda *args, **kwargs: TUIBackend(root=self.root))
        factory.start()
        self.addCleanup(factory.stop)

    async def test_clock_during_mount_and_teardown(self):
        app = AzurPilotTUI()
        app.tick_clock()  # No screen is mounted yet.
        screen = Mock()
        screen.query.return_value = []
        with patch.object(AzurPilotTUI, 'screen_stack', property(lambda self: [screen])):
            app.tick_clock()  # The screen exists but its header has been removed.
            header = Mock()
            screen.query.return_value = [header]
            app.tick_clock()
            header.tick_clock.assert_called_once()

    async def test_app_compose_and_actions(self) -> None:
        """在无头模式下测试 App 挂载与快捷指令。"""
        app = AzurPilotTUI()
        async with app.run_test():
            # 验证各主要组件成功挂载
            header = app.query_one(HeaderBar)
            sidebar = app.query_one(Sidebar)
            task_table = app.query_one(TaskTable)
            res_bar = app.query_one(ResourceBar)
            log_view = app.query_one(LogView)

            self.assertIsNotNone(header)
            self.assertIsNotNone(sidebar)
            self.assertIsNotNone(task_table)
            self.assertIsNotNone(res_bar)
            self.assertIsNotNone(log_view)

            # 模拟触发清屏快捷动作
            app.action_clear_log()
            # 模拟切换滚屏动作
            initial_scroll = log_view.auto_scroll_enabled
            app.action_toggle_scroll()
            self.assertNotEqual(initial_scroll, log_view.auto_scroll_enabled)

            # 模拟手动刷新动作
            app.action_refresh_data()

    async def test_help_screen_toggles(self) -> None:
        """快捷键弹层可打开并关闭，且不会误触发退出。"""
        app = AzurPilotTUI()
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, HelpScreen)

    async def test_task_modal_filter(self) -> None:
        """单任务弹窗支持关键词过滤且 Esc 可关闭。"""
        app = AzurPilotTUI()
        async with app.run_test() as pilot:
            await pilot.press("t")
            await pilot.pause()
            modal = app.screen
            self.assertIsInstance(modal, TaskModal)

            await pilot.press("s", "c", "a", "n")
            await pilot.pause()
            self.assertTrue(modal.filtered_tasks)
            for code, title in modal.filtered_tasks:
                self.assertIn("scan", f"{code}{title}".lower())

            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, TaskModal)

    async def test_config_modal_mount(self) -> None:
        """测试配置弹窗挂载与表单控件初始化，确保内部 Select 不会导致表单清空消失。"""
        backend = TUIBackend(root=self.root)
        modal = ConfigModal(backend=backend, initial_task="Commission")
        app = AzurPilotTUI(root=self.root)
        async with app.run_test() as pilot:
            await app.push_screen(modal)
            await pilot.pause()
            app.tick_clock()
            # 验证当前任务未被冒泡事件覆盖
            self.assertEqual(modal.current_task, "Commission")
            # 验证表单中已加载字段且没有消失
            self.assertGreater(len(modal.active_fields), 0)
            # 验证内部控件成功渲染挂载
            scroll = modal.query_one("#form-scroll")
            self.assertGreater(len(scroll.children), 0)
            # 未编辑时不应产生任何虚假修改（否则 Esc 会误提示未保存）
            self.assertEqual([], modal.collect_changes())

    async def test_emotion_same_value_can_be_explicitly_recalibrated(self) -> None:
        """挂载不校准，重新输入或回车确认同值后保存完整基准。"""
        from textual.app import App

        backend = TUIBackend(root=self.root)
        # 此处验证配置弹窗；不启动主界面的时钟，避免退出时查询已卸载的状态栏。
        app = App()
        now = datetime(2026, 10, 9, microsecond=123456)
        async with app.run_test() as pilot:
            for task, group, arg in (('Main', 'Emotion', 'Fleet1Value'),
                                     ('General', 'PublicEmotion', 'FleetValue')):
                path = f'{task}.{group}.{arg}'
                modal = ConfigModal(backend=backend, initial_task=task)
                # 用真实元数据挂载心情输入，聚焦验证「同值重新校准」语义。
                groups = [{**item, 'items': [field for field in item['items']
                                            if field['arg'] in ('Fleet1Value', 'Fleet2Value', 'FleetValue')]}
                          for item in backend.get_task_config_schema(task) if item['group_name'] == group]
                with patch.object(backend, 'get_task_config_schema', return_value=groups):
                    await app.push_screen(modal)
                    await pilot.pause()
                self.assertEqual([], modal.collect_changes())
                ctrl = modal.query_one(f"#{modal._ctrl_id('input', path)}", Input)
                original = ctrl.value
                if task == 'Main':
                    ctrl.value = '1'
                    await pilot.pause()
                    ctrl.value = original
                    await pilot.pause()
                else:
                    ctrl.focus()
                    await pilot.press('enter')
                self.assertEqual([{'path': path, 'value': int(original)}], modal.collect_changes())
                with patch('module.api.config_service.current_time', return_value=now):
                    modal.action_save_and_exit()
                fields = backend.config_service.read('testpilot')[0][task][group]
                prefix = arg.removesuffix('Value')
                self.assertEqual(now.isoformat(sep=' ', timespec='microseconds'), fields[prefix + 'Record'])
                self.assertEqual(now.isoformat(timespec='microseconds'), fields[prefix + 'RecoveryState']['record'])
                self.assertEqual([[0, 360_000_000, int(original)]], fields[prefix + 'RecoveryState']['segments'])
                await pilot.pause()


if __name__ == "__main__":
    unittest.main()
