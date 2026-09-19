"""验证 MCP 挂载与 WebUI 共用服务且正确收尾，不连接真实设备。"""
import asyncio
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from module.api.app import create_app
from module.runtime.setting import State
from tests.test_api import fixture


def mounted_mcp(application):
    return next(route.app for route in application.routes if route.path == '/mcp')


class ApiMcpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_tool_keeps_health_endpoint_responsive(self):
        """工具等待外部操作时，同一事件循环仍能完成健康检查。"""
        import mcp_server_sse as mcp

        started, release = threading.Event(), threading.Event()

        def slow_list(arguments):
            started.set()
            release.wait(3)
            return ['testpilot']

        async def request_tool(scope, receive, send):
            result = await mcp.call_tool('list_instances', {})
            await JSONResponse(json.loads(result[0].text))(scope, receive, send)

        with tempfile.TemporaryDirectory() as directory:
            app = create_app(root=fixture(directory), password='', manage_runtime=False)
            tools = mounted_mcp(app).state.tools
            async with app.router.lifespan_context(app):
                with patch.object(tools, 'tool_list_instances', side_effect=slow_list), \
                        patch.object(mcp, '_run_sse', side_effect=request_tool):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                        request = asyncio.create_task(client.get('/mcp/sse'))
                        try:
                            self.assertTrue(await asyncio.to_thread(started.wait, 2))
                            self.assertFalse(request.done(), '阻塞工具不应占住事件循环直到自身完成')
                            response = await asyncio.wait_for(client.get('/healthz'), 1)
                            self.assertEqual(200, response.status_code)
                        finally:
                            release.set()
                            await request

    async def test_requests_keep_their_application_config(self):
        """交错请求两个应用时，工具不能误读最后创建应用的配置目录。"""
        import mcp_server_sse as mcp

        async def read_instances(scope, receive, send):
            await asyncio.sleep(0)
            content = await mcp.call_tool('list_instances', {})
            await JSONResponse(json.loads(content[0].text))(scope, receive, send)

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            roots = [fixture(first), fixture(second)]
            for root, name in zip(roots, ['alpha', 'beta']):
                (root / 'config/testpilot.json').rename(root / f'config/{name}.json')
            apps = [create_app(root=root, password='', manage_runtime=False) for root in roots]
            async with apps[0].router.lifespan_context(apps[0]), apps[1].router.lifespan_context(apps[1]):
                with patch.object(mcp, '_run_sse', side_effect=read_instances):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[0]), base_url='http://first') as client_a, \
                            httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[1]), base_url='http://second') as client_b:
                        responses = await asyncio.gather(client_a.get('/mcp/sse'), client_b.get('/mcp/sse'))
            self.assertEqual([['alpha'], ['beta']], [response.json() for response in responses])

    async def test_mount_reuses_webui_service_objects(self):
        import mcp_server_sse as mcp

        with tempfile.TemporaryDirectory() as directory, patch.object(mcp, 'create_app', wraps=mcp.create_app) as factory:
            app = create_app(root=fixture(directory), password='', manage_runtime=False)
            router = app.state.gateway.router
            factory.assert_called_once_with(router.configs, router.runtime, manage_runtime=False)
            async with app.router.lifespan_context(app):
                pass


class ApiMcpCleanupTests(unittest.TestCase):
    def test_mcp_drains_before_shared_runtime_cleanup(self):
        """关闭共享 Manager 前先等待 MCP 操作结束，避免在途启动留下孤儿进程。"""
        events = []
        settings = SimpleNamespace(Run='', DiscordRichPresence=False)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(State, '_deploy_config_', settings, create=True), \
                patch('module.api.lifecycle.startup', side_effect=lambda runs: events.append('startup')), \
                patch('module.api.lifecycle.clearup', side_effect=lambda: events.append('runtime_cleanup')), \
                patch('module.runtime.discord_presence.async_close_discord_rpc',
                      new=AsyncMock(side_effect=lambda: events.append('discord_cleanup'))):
            app = create_app(root=fixture(directory), password='')
            with patch.object(mounted_mcp(app).state.tools, 'close', new=AsyncMock(side_effect=lambda: events.append('mcp_cleanup'))):
                with TestClient(app) as client:
                    self.assertEqual(200, client.get('/healthz').status_code)
            self.assertEqual(['startup', 'mcp_cleanup', 'discord_cleanup', 'runtime_cleanup'], events)

    def test_runtime_cleanup_still_runs_when_mcp_cleanup_fails(self):
        settings = SimpleNamespace(Run='', DiscordRichPresence=False)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(State, '_deploy_config_', settings, create=True), \
                patch('module.api.lifecycle.startup'), \
                patch('module.api.lifecycle.clearup') as cleanup:
            app = create_app(root=fixture(directory), password='')
            with patch.object(mounted_mcp(app).state.tools, 'close', new=AsyncMock(side_effect=RuntimeError('模拟 MCP 收尾失败'))):
                with self.assertRaisesRegex(RuntimeError, '模拟 MCP 收尾失败'), TestClient(app):
                    pass
            cleanup.assert_called_once_with()
