"""Discord 使用内存替身验证，不读取本机 IPC 或连接网络。"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from module.runtime import discord_presence as discord


class DiscordPresenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNone(discord.RPC)
        self.logs = patch.object(discord, 'logger')
        self.logger = self.logs.start()
        self.addCleanup(self.logs.stop)

    async def asyncTearDown(self):
        await discord.async_close_discord_rpc()

    def rpc(self, writer=None):
        return SimpleNamespace(client_id='test', sock_writer=writer,
                               connect=AsyncMock(), update=AsyncMock(), send_data=Mock())

    def start(self, rpc):
        with patch.object(discord, 'AioPresence', return_value=rpc) as factory:
            task = discord.init_discord_rpc()
        factory.assert_called_once_with('929437173764223057', loop=asyncio.get_running_loop())
        return task

    async def test_close_before_connection_task_starts(self):
        rpc = self.rpc()
        task = self.start(rpc)
        # 同一轮调度中请求关闭，连接即使已完成也不能访问空 writer。
        await discord.async_close_discord_rpc()
        self.assertTrue(task.done())
        rpc.send_data.assert_not_called()
        self.assertIsNone(discord.RPC)

    async def test_close_cancels_and_awaits_pending_handshake(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def connect():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        rpc = self.rpc()
        rpc.connect.side_effect = connect
        task = self.start(rpc)
        await started.wait()
        await discord.async_close_discord_rpc()
        self.assertTrue(cancelled.is_set())
        self.assertTrue(task.cancelled())
        rpc.update.assert_not_awaited()
        rpc.send_data.assert_not_called()
        self.assertIsNone(discord.RPC)

    async def test_connection_failure_is_logged_and_consumed(self):
        rpc = self.rpc()
        rpc.connect.side_effect = OSError('模拟连接失败')
        await self.start(rpc)
        rpc.update.assert_not_awaited()
        self.logger.exception.assert_called_once()
        await discord.async_close_discord_rpc()
        rpc.send_data.assert_not_called()

    async def test_update_failure_closes_open_writer(self):
        writer = SimpleNamespace(close=Mock(), wait_closed=AsyncMock())
        rpc = self.rpc(writer)
        rpc.update.side_effect = OSError('模拟更新失败')
        await self.start(rpc)
        self.logger.exception.assert_called_once()
        await discord.async_close_discord_rpc()
        writer.close.assert_called_once_with()
        writer.wait_closed.assert_awaited_once_with()

    async def test_constructor_failure_is_optional(self):
        with patch.object(discord, 'AioPresence', side_effect=OSError('未安装 Discord')):
            self.assertIsNone(discord.init_discord_rpc())
        self.logger.exception.assert_called_once()
        self.assertIsNone(discord.RPC)

    async def test_repeated_init_reuses_connection_task(self):
        rpc = self.rpc()
        task = self.start(rpc)
        with patch.object(discord, 'AioPresence') as factory:
            self.assertIs(task, discord.init_discord_rpc())
        factory.assert_not_called()
        await task

    async def test_connected_writer_closes_once_on_owner_loop(self):
        loop = asyncio.get_running_loop()
        events = []
        release = asyncio.Event()

        def record(event):
            self.assertIs(loop, asyncio.get_running_loop())
            events.append(event)

        async def wait_closed():
            record('wait_closed')
            await release.wait()
            record('closed')

        writer = SimpleNamespace(close=Mock(side_effect=lambda: record('close')),
                                 wait_closed=AsyncMock(side_effect=wait_closed))
        rpc = self.rpc(writer)
        rpc.send_data.side_effect = lambda *args: record('send_data')
        task = self.start(rpc)
        await task
        # 同步兼容入口从工作线程发起，实际 writer 操作仍在所属循环执行。
        pending = await asyncio.to_thread(discord.close_discord_rpc)
        local_close = discord.close_discord_rpc()
        release.set()
        await asyncio.gather(asyncio.wrap_future(pending), discord.async_close_discord_rpc(),
                             local_close)
        await discord.async_close_discord_rpc()
        self.assertIsNone(discord.close_discord_rpc())
        self.assertEqual(['send_data', 'close', 'wait_closed', 'closed'], events)
        rpc.send_data.assert_called_once_with(2, {'v': 1, 'client_id': 'test'})

    async def test_handshake_with_writer_is_closed_after_cancellation(self):
        started = asyncio.Event()
        writer = SimpleNamespace(close=Mock(), wait_closed=AsyncMock())
        rpc = self.rpc()

        async def connect():
            rpc.sock_writer = writer
            started.set()
            await asyncio.Event().wait()

        rpc.connect.side_effect = connect
        task = self.start(rpc)
        await started.wait()
        await discord.async_close_discord_rpc()
        self.assertTrue(task.cancelled())
        writer.close.assert_called_once_with()
        writer.wait_closed.assert_awaited_once_with()

    async def test_send_failure_still_closes_writer_and_allows_restart(self):
        writer = SimpleNamespace(close=Mock(), wait_closed=AsyncMock())
        rpc = self.rpc(writer)
        rpc.send_data.side_effect = BrokenPipeError('模拟断开')
        await self.start(rpc)
        await discord.async_close_discord_rpc()
        writer.close.assert_called_once_with()
        writer.wait_closed.assert_awaited_once_with()
        self.logger.exception.assert_called_once()
        replacement = self.rpc()
        await self.start(replacement)
        self.assertIs(replacement, discord.RPC)

    async def test_windows_transport_does_not_require_wait_closed(self):
        transport = SimpleNamespace(close=Mock())
        await self.start(self.rpc(transport))
        await discord.async_close_discord_rpc()
        transport.close.assert_called_once_with()

    async def test_unresponsive_writer_does_not_block_shutdown(self):
        writer = SimpleNamespace(close=Mock(), wait_closed=AsyncMock(side_effect=asyncio.Event().wait))
        await self.start(self.rpc(writer))
        with patch.object(discord, '_CLOSE_TIMEOUT', 0.01):
            await asyncio.wait_for(discord.async_close_discord_rpc(), timeout=1)
        writer.close.assert_called_once_with()
        self.logger.exception.assert_called_once()
        self.assertIsNone(discord.RPC)

    async def test_shutdown_takes_over_cleanup_of_failed_update(self):
        waiting, closed = asyncio.Event(), asyncio.Event()

        async def wait_closed():
            if not waiting.is_set():
                waiting.set()
                await asyncio.Event().wait()
            closed.set()

        writer = SimpleNamespace(close=Mock(), wait_closed=AsyncMock(side_effect=wait_closed))
        rpc = self.rpc(writer)
        rpc.update.side_effect = OSError('模拟更新失败')
        task = self.start(rpc)
        await waiting.wait()
        await discord.async_close_discord_rpc()
        self.assertTrue(task.cancelled())
        self.assertTrue(closed.is_set())
        self.assertIsNone(discord.RPC)
