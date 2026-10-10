"""AzurPilot TUI 桥接后端与界面挂载单元测试。"""

import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from textual.widgets import Input

from tests.test_api import fixture

from module.runtime.setting import State
from module.runtime.updater import updater
from module.tui.app import AzurPilotTUI
from module.tui.backend import TUIBackend
from module.tui.widgets import ConfigModal, HeaderBar, LogView, ResourceBar, Sidebar, TaskTable


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

    def test_get_logs(self) -> None:
        """测试日志拉取契约。"""
        cursor, entries = self.backend.get_logs(after=0)
        self.assertIsInstance(cursor, int)
        self.assertIsInstance(entries, list)


class TestTUIApp(IsolatedTUIFixture, unittest.IsolatedAsyncioTestCase):
    """测试 Textual TUI 应用生命周期与组件挂载。"""

    def setUp(self):
        super().setUp()
        factory = patch('module.tui.app.TUIBackend', side_effect=lambda *args, **kwargs: TUIBackend(root=self.root))
        factory.start()
        self.addCleanup(factory.stop)

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
                # 用真实元数据挂载心情输入，隔离其他参数的空值／多行文本归一化。
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
