"""Starlette 应用工厂模块。

构建包含静态 React 前端页面托管、同源 WebSocket 接口、MCP 挂载与 Android 控制路由的 Starlette 应用。
"""

import argparse
import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from module.api import launcher_api
from module.api.background_service import LIBRARY_DIR, gallery_add_bytes, proxy_fetch
from module.api.config_service import ConfigService, ROOT
from module.api.router import Router
from module.api.runtime_service import RuntimeService
from module.api.socket import Gateway
from module.api.static import FrontendFiles, ItemTemplateFiles
from module.logger import logger
from module.runtime.password_utils import ensure_password_for_host, is_demo_mode
from module.runtime.setting import State


def create_app(*, root: Path = ROOT, password=None, manage_runtime=True, mount_mcp=True):
    """创建并配置完整的 WebUI Starlette 应用。

    测试环境下可以关闭真实进程生命周期并使用临时配置目录。

    Args:
        root (Path, optional): 项目根路径。默认为 ROOT。
        password (str, optional): 访问密码。为 None 时从命令行或部署设置读取。默认为 None。
        manage_runtime (bool, optional): 是否管理调度器和 RPC 生命周期。默认为 True。
        mount_mcp (bool, optional): 是否挂载 /mcp 端点。默认为 True。

    Returns:
        Starlette: 已配置好的 ASGI 应用对象。
    """
    configs = ConfigService(root)
    runtime = RuntimeService(configs)
    mcp_app = None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-k', '--key')
    parser.add_argument('--run', nargs='+')
    args, _ = parser.parse_known_args()
    if password is None:
        key = args.key or State.deploy_config.Password
        host = State.webui_host or State.deploy_config.WebuiHost
        password = ensure_password_for_host(key, host, demo=is_demo_mode())
        if password and password != key:
            State.deploy_config.Password = password
    gateway = Gateway(Router(configs, runtime), password)
    launcher_api.configure_trust(password)

    @asynccontextmanager
    async def lifespan(application):
        """管理应用的启动与关闭生命周期。"""
        try:
            if manage_runtime:
                from module.persistence.database import initialize
                await asyncio.to_thread(initialize, configs.directory)
            if ((root / 'cache' / 'stock-exchange').exists()
                    or (root / 'config' / 'stock-exchange' / 'bindings.json').is_file()):
                gateway.router.stock_exchange.start()
            if manage_runtime:
                from module.api.lifecycle import startup
                from module.runtime.deploy_settings import parse_run_config
                from module.runtime.startup_memory import consume_update_restart, startup_runs
                runs = args.run or parse_run_config(State.deploy_config.Run)
                if not args.run:
                    # 只在决定启动清单这一支消费更新标记。
                    update_restart = consume_update_restart()
                    runs = startup_runs(runs, update_restart=update_restart)
                await asyncio.to_thread(startup, runs)
                if State.deploy_config.DiscordRichPresence:
                    try:
                        from module.runtime.discord_presence import init_discord_rpc
                        init_discord_rpc()
                    except Exception:
                        logger.exception('Discord RPC 启动失败，继续运行 WebUI')
            yield
        finally:
            try:
                # 先禁止 MCP 新操作并等待在途操作结束，再回收共享运行时。
                if mcp_app is not None:
                    await mcp_app.state.tools.close()
            finally:
                try:
                    await asyncio.to_thread(gateway.router.close)
                finally:
                    if manage_runtime:
                        try:
                            from module.runtime.discord_presence import async_close_discord_rpc
                            await async_close_discord_rpc()
                        except Exception:
                            logger.exception('Discord RPC 清理失败，继续回收共享运行时')
                        finally:
                            from module.api.lifecycle import clearup
                            await asyncio.to_thread(clearup)

    dist = root / 'frontend/dist'

    async def index(request):
        """返回前端入口 index.html，未构建时提示 503。"""
        if (dist / 'index.html').is_file():
            return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-cache'})
        return PlainTextResponse('前端尚未构建，请在 frontend 目录运行 npm ci 和 npm run build。', status_code=503)

    async def health(request):
        """健康检查接口，返回协议版本及正常状态。"""
        return JSONResponse({'status': 'ok', 'protocolVersion': 1})

    async def meowfficer_score_report(request):
        """指挥喵评分报告（自包含 HTML），供浏览器直接打开查看。"""
        path = root / 'log' / 'meowfficer_score.html'
        if not path.is_file():
            return PlainTextResponse('评分报告尚未生成，请先运行「指挥喵评分」任务。', status_code=404)
        return FileResponse(path, media_type='text/html', headers={'Cache-Control': 'no-cache'})

    from module.api.android import routes as android_routes

    def background_authorized(request, *, allow_query=False):
        """背景 HTTP 能力令牌只通过已授权的 WebSocket 下发，不复用访问密码。"""
        supplied = request.headers.get('x-azurpilot-background-token', '')
        if not supplied and allow_query:
            supplied = request.query_params.get('token', '')
        return bool(supplied) and secrets.compare_digest(
            supplied.encode('utf-8'), gateway.router.background_token.encode('ascii'))

    async def background_upload(request):
        """接收浏览器上传的本地背景图，存进 cache/background/library（本地图片的唯一落点）。"""
        if not background_authorized(request):
            return JSONResponse({'error': '请先登录'}, status_code=401)
        async with request.form() as form:
            upload = form.get('file')
            if upload is None or not hasattr(upload, 'read'):
                return JSONResponse({'error': '没有收到文件。'}, status_code=400)
            data = await upload.read()
            try:
                entry = gallery_add_bytes(data, getattr(upload, 'filename', '') or '', getattr(upload, 'content_type', '') or '')
            except Exception as error:
                return JSONResponse({'error': str(error)}, status_code=400)
            return JSONResponse({'entry': entry})

    async def background_media(request):
        """同源代理一张网图：解析出的直链由这里回给浏览器，避免防盗链或跨域让显示的图与直链分叉。"""
        if not background_authorized(request, allow_query=True):
            return JSONResponse({'error': '请先登录'}, status_code=401)
        target = request.query_params.get('url', '')
        if not target:
            return JSONResponse({'error': '缺少 url 参数。'}, status_code=400)
        try:
            # 代抓走线程池：同步 requests 会占住事件循环，一次下载最长 20 秒。
            data, content_type = await asyncio.to_thread(proxy_fetch, target)
        except Exception as error:
            return JSONResponse({'error': str(error)}, status_code=400)
        return Response(data, media_type=content_type, headers={'Cache-Control': 'no-cache'})

    routes = [Route('/healthz', health),
              Route('/api/v1/background/media', background_media),
              Route('/reports/meowfficer_score', meowfficer_score_report),
              WebSocketRoute('/api/v1/ws', gateway.endpoint)]
    routes.extend(android_routes(configs, runtime))
    routes.extend(launcher_api.routes())
    # 背景图库：图片直接由 StaticFiles 提供（与 research-items 等模板图同一套做法），
    # 上传走下面那个 POST；目录不存在时先建出来，免得挂载失败。
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    routes.append(Route('/api/v1/background/gallery', background_upload, methods=['POST']))
    routes.append(Mount('/background-library', StaticFiles(directory=LIBRARY_DIR)))
    if (dist / 'assets').is_dir():
        routes.append(Mount('/assets', StaticFiles(directory=dist / 'assets')))
    # 科研掉落的物品图标直接用仓库里的模板图，不走前端构建，
    # 这样补了新模板立刻生效，不用重新 npm build。
    research_items = root / 'assets' / 'stats' / 'research_items'
    research_templates = [research_items, root / 'assets' / 'stats_basic']
    if any(directory.is_dir() for directory in research_templates):
        routes.append(Mount('/research-items', ItemTemplateFiles(research_templates)))
    # 自律结算与领奖弹窗的模板并不互相包含（如通用装备研发图纸只在弹窗库里）。
    # 优先使用结算图标，缺失时按同名模板回退。
    opsi_items = root / 'assets' / 'stats' / 'opsi_reward_items'
    opsi_templates = [opsi_items, root / 'assets' / 'stats' / 'opsi_items']
    if any(directory.is_dir() for directory in opsi_templates):
        routes.append(Mount('/opsi-items', ItemTemplateFiles(opsi_templates)))
    storage_items = root / 'assets' / 'stats'
    if storage_items.is_dir():
        routes.append(Mount('/storage-items', StaticFiles(directory=storage_items)))
    if mount_mcp:
        from mcp_server_sse import configure_auth
        from mcp_server_sse import create_app as create_mcp_app
        configure_auth(password, public_bind=bool(password))
        mcp_app = create_mcp_app(configs, runtime, manage_runtime=False)
        routes.append(Mount('/mcp', mcp_app))
    if (dist / 'index.html').is_file():
        routes.append(Mount('/', FrontendFiles(directory=dist)))
    else:
        routes.append(Route('/{path:path}', index))
    application = Starlette(routes=routes, lifespan=lifespan)
    application.state.gateway = gateway
    return application
