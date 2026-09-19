"""独立 MCP 初始化、挂载复用及失败回收，不创建真实 Manager。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from module.mcp.lifecycle import cleanup, lifespan
from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State


class McpLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_initializes_event_and_drains_before_cleanup(self):
        events = []
        manager = Mock()
        updater = SimpleNamespace(event=None)
        app = SimpleNamespace(state=SimpleNamespace(tools=SimpleNamespace(
            close=AsyncMock(side_effect=lambda: events.append('drain')))))

        def initialize():
            events.append('init')
            State.manager = manager

        with patch.object(State, 'manager', None), patch.object(State, 'init', side_effect=initialize), \
                patch.dict(sys.modules, {'module.runtime.updater': SimpleNamespace(updater=updater)}), \
                patch('module.mcp.lifecycle.cleanup', side_effect=lambda: events.append('cleanup')):
            async with lifespan(app):
                self.assertIs(updater.event, manager.Event.return_value)
                events.append('request')
        self.assertEqual(['init', 'request', 'drain', 'cleanup'], events)

    async def test_existing_runtime_is_neither_initialized_nor_cleaned(self):
        app = SimpleNamespace(state=SimpleNamespace(tools=SimpleNamespace(close=AsyncMock())))
        with patch.object(State, 'manager', Mock()), patch.object(State, 'init') as initialize, \
                patch('module.mcp.lifecycle.cleanup') as clear:
            async with lifespan(app):
                pass
        initialize.assert_not_called()
        clear.assert_not_called()

    async def test_partial_initialization_is_cleaned(self):
        app = SimpleNamespace(state=SimpleNamespace(tools=SimpleNamespace(close=AsyncMock())))

        def initialize():
            State.manager = Mock()
            raise RuntimeError('模拟初始化失败')

        with patch.object(State, 'manager', None), patch.object(State, 'init', side_effect=initialize), \
                patch('module.mcp.lifecycle.cleanup') as clear:
            with self.assertRaisesRegex(RuntimeError, '模拟初始化失败'):
                async with lifespan(app):
                    self.fail('初始化失败不应进入请求阶段')
        clear.assert_called_once_with()

    async def test_unconfirmed_worker_stop_preserves_shared_state(self):
        worker = Mock()
        worker.stop.return_value = False
        with patch.object(ProcessManager, 'running_instances', return_value=[worker]), \
                patch.object(State, 'clearup') as clear:
            with self.assertRaisesRegex(RuntimeError, '尚未完全停止'):
                cleanup()
        clear.assert_not_called()

    async def test_cleanup_runs_even_when_tool_close_fails(self):
        app = SimpleNamespace(state=SimpleNamespace(tools=SimpleNamespace(
            close=AsyncMock(side_effect=RuntimeError('模拟工具收尾失败')))))

        def initialize():
            State.manager = Mock()

        with patch.object(State, 'manager', None), patch.object(State, 'init', side_effect=initialize), \
                patch.dict(sys.modules, {'module.runtime.updater': SimpleNamespace(updater=SimpleNamespace(event=None))}), \
                patch('module.mcp.lifecycle.cleanup') as clear:
            with self.assertRaisesRegex(RuntimeError, '模拟工具收尾失败'):
                async with lifespan(app):
                    pass
        clear.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
