"""AzurPilot WebUI 的兼容入口和 ASGI 应用工厂。

提供 WebUI 的主应用类，通过多个 Mixin 组合实现各功能页面：
仪表盘（Dashboard）、开发者菜单、开发者设置、开发者工具、
版本更新、活动工具等。同时提供 ASGI 应用创建和路由注册。

该模块是 WebUI 的顶层入口，被 gui.py 启动时引用。
"""

import os

from hashlib import sha256
from pathlib import Path

from module.webui.app_dashboard import DashboardMixin
from module.webui.app_dependencies import (
    Dict,
    Frame,
    IS_ON_PHONE_CLOUD,
    List,
    PUBLIC_WEBUI_PASSWORD_GENERATE_FAILED_MESSAGE,
    ProcessManager,
    RESTRICTED_DEVICE_IDS,
    RESTRICTED_DEVICE_MESSAGE,
    RichLog,
    State,
    argparse,
    asgi_app,
    get_device_id,
    get_localstorage_values,
    info,
    lang,
    load_webui_styles,
    local,
    logger,
    login,
    popup,
    run_js,
    set_env,
    task_handler,
    time,
    updater,
    webconfig,
)
from module.webui.app_developer_menu import DeveloperMenuMixin
from module.webui.app_developer_settings import DeveloperSettingsMixin
from module.webui.app_developer_tools import DeveloperToolsMixin
from module.webui.app_developer_update import DeveloperUpdateMixin
from module.webui.app_event_tools import EventToolsMixin
from module.webui.app_fleet_management import FleetManagementMixin
from module.webui.app_helpers import (
    DEMO_DEVICE_ID_TEXT,
    WEBUI_AUTO_PASSWORD_FILE,
    build_copyable_device_id,
    build_muted_notice,
    build_recommendation_box,
    build_simple_table,
    build_title_block,
    ensure_public_webui_password,
    generate_webui_password,
    is_demo_mode,
    is_public_webui_host,
    is_webui_password_set,
    read_webapp_template,
    timedelta_to_text,
)
from module.webui.app_home import HomeMixin
from module.webui.app_instances import InstanceMixin
from module.webui.app_lifecycle import clearup, startup
from module.webui.app_manage import app_manage
from module.webui.app_overview import OverviewMixin
from module.webui.app_shell import (
    AppShellMixin,
    normalize_webui_theme,
    pywebio_theme_for,
)
from module.webui.app_stat_action_point import ActionPointStatisticsMixin
from module.webui.app_stat_action_point_toolbar import ActionPointToolbarMixin
from module.webui.app_stat_commission import CommissionIncomeStatisticsMixin
from module.webui.app_stat_opsi import OpsiStatisticsMixin
from module.webui.app_stat_opsi_export import OpsiExportMixin
from module.webui.app_stat_resource import ResourceStatisticsMixin
from module.webui.app_stat_ship import ShipExperienceStatisticsMixin
from module.webui.app_statistics_page import StatisticsPageMixin
from module.webui.app_task_config import TaskConfigMixin
from module.webui.fastapi import INITIAL_LOADING_STYLE_MARKER


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _versioned_static_asset(relative_path: str) -> str:
    """返回带内容哈希的相对静态资源地址。"""
    digest = sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest()[:12]
    return f"static/{relative_path}?v={digest}"


INITIAL_WEBUI_CSS = _versioned_static_asset("assets/gui/css/alas.css")
WEBUI_THEME_STYLE_NAMES = {
    "dark": ("dark-alas",),
    "advanced_material": ("advanced-material-alas",),
    "dark_advanced_material": (
        "advanced-material-alas",
        "dark-advanced-material-overrides-alas",
    ),
}
INITIAL_LOADING_JS = """
(function () {
    var observer = null;
    function hasContent() {
        var root = document.getElementById("pywebio-scope-ROOT");
        var inputs = document.getElementById("input-cards");
        return (root && root.firstElementChild)
            || (inputs && inputs.firstElementChild)
            || document.querySelector(".modal");
    }
    function markReady() {
        if (!hasContent()) return;
        document.documentElement.classList.add("alas-initial-ready");
        if (observer) observer.disconnect();
    }
    observer = new MutationObserver(markReady);
    observer.observe(document.body, {childList: true, subtree: true});
    markReady();
})();
"""


def _initial_style_names(theme: str) -> tuple[str, ...]:
    """返回首屏必须通过 HTML 预加载的样式名称。"""
    return (
        "alas",
        "entry-alas",
        *WEBUI_THEME_STYLE_NAMES.get(theme, ("light-alas",)),
    )


def _initial_loading_css(theme: str) -> str:
    """生成在 PyWebIO 首条可见输出前展示的轻量加载骨架。"""
    if theme in ("dark", "dark_advanced_material"):
        background = "#202225"
        foreground = "#f2f3f5"
        accent = "#8b89d8"
        track = "rgba(139, 137, 216, .22)"
    else:
        background = "#f4f5f7"
        foreground = "#34343d"
        accent = "#4e4c97"
        track = "rgba(78, 76, 151, .22)"
    return f"""
/* {INITIAL_LOADING_STYLE_MARKER} */
html:not(.alas-initial-ready) #pywebio-scope-ROOT:empty {{
    position: fixed;
    inset: 0;
    z-index: 2147483000;
    display: grid;
    place-items: center;
    min-height: 100vh;
    background: {background};
    color: {foreground};
}}
html:not(.alas-initial-ready) #pywebio-scope-ROOT:empty::before {{
    width: 34px;
    height: 34px;
    content: "";
    border: 3px solid {track};
    border-top-color: {accent};
    border-radius: 50%;
    animation: alas-initial-spin .72s linear infinite;
}}
html:not(.alas-initial-ready) #pywebio-scope-ROOT:empty::after {{
    position: absolute;
    top: calc(50% + 34px);
    content: "AzurPilot";
    font: 600 14px/1.5 system-ui, sans-serif;
    letter-spacing: .04em;
}}
@keyframes alas-initial-spin {{
    to {{ transform: rotate(360deg); }}
}}
@media (prefers-reduced-motion: reduce) {{
    html:not(.alas-initial-ready) #pywebio-scope-ROOT:empty::before {{
        animation-duration: 1.8s;
    }}
}}
"""


class AlasGUI(
    AppShellMixin,
    StatisticsPageMixin,
    ActionPointStatisticsMixin,
    ActionPointToolbarMixin,
    ResourceStatisticsMixin,
    OpsiStatisticsMixin,
    OpsiExportMixin,
    ShipExperienceStatisticsMixin,
    CommissionIncomeStatisticsMixin,
    FleetManagementMixin,
    TaskConfigMixin,
    EventToolsMixin,
    OverviewMixin,
    DashboardMixin,
    DeveloperMenuMixin,
    DeveloperUpdateMixin,
    DeveloperSettingsMixin,
    DeveloperToolsMixin,
    InstanceMixin,
    HomeMixin,
    Frame,
):
    """组合各 WebUI 视图的会话控制器。

    Mixin 的顺序明确会话能力的组合层次。统计页入口通过 ``self`` 调用具体
    视图的渲染方法，因此各视图模块既可独立维护，也保持原有会话接口不变。
    """

    ALAS_MENU: Dict[str, Dict[str, List[str]]]
    ALAS_ARGS: Dict[str, Dict[str, Dict[str, Dict[str, str]]]]
    theme = "default"
    _log = RichLog


def debug() -> None:
    """初始化 WebUI 后进入交互式调试会话。"""
    startup()
    AlasGUI().run()


def app():
    """创建供 Uvicorn 使用的 ASGI 应用工厂。

    Returns:
        Starlette: 挂载 WebUI 页面和 MCP 子应用的 ASGI 应用。
    """
    parser = argparse.ArgumentParser(description="Alas web service")
    parser.add_argument(
        "-k", "--key", type=str, help="Password of alas. No password by default"
    )
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="Use jsdelivr cdn for pywebio static files (css, js). Self host cdn by default.",
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="Run alas by config names on startup",
    )
    args, _ = parser.parse_known_args()

    initial_theme = normalize_webui_theme(State.deploy_config.Theme)
    initial_pywebio_theme = pywebio_theme_for(initial_theme)
    AlasGUI.theme = initial_theme
    State.theme = initial_theme
    State.deploy_config.Theme = initial_theme
    initial_style_names = _initial_style_names(initial_theme)
    initial_css_files = (
        INITIAL_WEBUI_CSS,
        *(
            _versioned_static_asset(f"assets/gui/css/{name}.css")
            for name in initial_style_names[1:]
        ),
    )
    initial_loading_css = _initial_loading_css(initial_theme)
    lang.LANG = State.deploy_config.Language
    key = args.key if is_webui_password_set(args.key) else State.deploy_config.Password
    key, password_error = ensure_public_webui_password(key)
    # 由 alas-launcher 以信任密钥拉起时登记免密通道，否则整体关闭。
    from module.webui.launcher_trust import (
        TRUST_SECRET_ENV,
        configure as configure_launcher_trust,
        enabled as launcher_trust_enabled,
    )

    configure_launcher_trust(os.environ.get(TRUST_SECRET_ENV), key)
    cdn: str | bool = args.cdn if args.cdn else State.deploy_config.CDN
    runs: List[str] | None = None
    if args.run:
        runs = args.run
    elif State.deploy_config.Run:
        # deploy.yaml 的旧格式仍是逗号分隔字符串，保持兼容直到配置读取器支持列表。
        tmp = State.deploy_config.Run.split(",")
        runs = [item.strip(" ['\"]") for item in tmp if item]
    # 未传入 --run 时保持 None，由进程管理器跳过启动实例。
    instances: List[str] | None = runs

    logger.hr("[WebUI] WebUI 配置")
    logger.attr("主题", State.deploy_config.Theme)
    logger.attr("语言", lang.LANG)
    logger.attr("密码", is_webui_password_set(key))
    logger.attr("启动器免密", launcher_trust_enabled())
    logger.attr("CDN", cdn)
    logger.attr("云手机", IS_ON_PHONE_CLOUD)

    from deploy.atomic import atomic_failure_cleanup

    atomic_failure_cleanup("./config")
    # 委托收益截图目录：委托结算时落盘，统计页「查看截图」按钮按 URL 访问
    commission_rewards_dir = PROJECT_ROOT / "log" / "commission_rewards"
    commission_rewards_dir.mkdir(parents=True, exist_ok=True)
    static_mounts = {
        "/static/assets": str(PROJECT_ROOT / "assets"),
        "/static/doc": str(PROJECT_ROOT / "doc"),
        "/static/commission_rewards": str(commission_rewards_dir),
    }

    def _block_restricted_device() -> bool:
        if is_demo_mode():
            return False
        if get_device_id() not in RESTRICTED_DEVICE_IDS:
            return False
        popup(
            "安全保护",
            RESTRICTED_DEVICE_MESSAGE,
            implicit_close=False,
            closable=False,
        )
        return True

    def _block_public_webui_password_error() -> bool:
        if is_demo_mode() or password_error is None:
            return False
        popup(
            "安全保护",
            PUBLIC_WEBUI_PASSWORD_GENERATE_FAILED_MESSAGE,
            implicit_close=False,
            closable=False,
        )
        return True

    def _run_gui(initial_page: str = "home") -> None:
        session_theme = normalize_webui_theme(State.deploy_config.Theme)
        if session_theme != initial_theme:
            # 应用运行期间切换主题时，当前 HTML 仍是启动时主题，需要兼容热切换。
            AlasGUI.set_theme(theme=session_theme)
        else:
            # 正常首屏已预载正确主题，避免通过 WebSocket 删除并重复发送 CSS。
            AlasGUI.theme = session_theme
            State.theme = session_theme
        set_env(title="AzurPilot", output_animation=False)
        load_webui_styles(
            theme=AlasGUI.theme,
            is_mobile=info.user_agent.is_mobile,
            preloaded_styles=initial_style_names,
        )
        if _block_restricted_device() or _block_public_webui_password_error():
            return
        localstorage = None
        if is_webui_password_set(key):
            localstorage = get_localstorage_values(
                ("password", "clarity_notice_shown", "aside")
            )
        if is_webui_password_set(key) and not login(
            key, stored_password=localstorage.get("password")
        ):
            logger.warning(f"[WebUI] {info.user_ip} 登录失败")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        gui = AlasGUI()
        local.gui = gui
        gui.run(initial_page=initial_page, localstorage=localstorage)

    @webconfig(
        theme=initial_pywebio_theme,
        css_file=initial_css_files,
        css_style=initial_loading_css,
        js_code=INITIAL_LOADING_JS,
    )
    def index() -> None:
        _run_gui()

    @webconfig(
        theme=initial_pywebio_theme,
        css_file=initial_css_files,
        css_style=initial_loading_css,
        js_code=INITIAL_LOADING_JS,
    )
    def manage() -> None:
        _run_gui(initial_page="manage")

    from mcp_server_sse import app as mcp_app

    application = asgi_app(
        applications=[index, manage],
        cdn=cdn,
        static_mounts=static_mounts,
        debug=False,
        on_startup=[
            startup,
            lambda: ProcessManager.restart_processes(
                instances=instances, ev=updater.event
            ),
        ],
        on_shutdown=[clearup],
    )
    application.mount("/mcp", mcp_app)
    return application
