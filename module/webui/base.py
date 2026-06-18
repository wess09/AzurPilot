import threading

from pywebio.output import clear, put_html, put_scope, put_text, use_scope
from pywebio.session import defer_call, info, run_js

from module.webui.utils import Icon, WebIOTaskHandler, set_localstorage


class Base:
    """WebUI 应用的基础类，管理生命周期和任务调度。"""

    def __init__(self) -> None:
        self.alive = True
        # 窗口是否可见（切换页面时置为 False 阻止旧页面的任务继续执行）
        self.visible = True
        # 是否为移动端设备
        self.is_mobile = info.user_agent.is_mobile
        # 任务处理器，用于管理后台异步任务
        self.task_handler = WebIOTaskHandler()
        defer_call(self.stop)

    def stop(self) -> None:
        self.alive = False
        self.task_handler.stop()


class Frame(Base):
    """WebUI 页面框架，管理侧边栏、菜单和内容区域的切换与导航。"""

    def __init__(self) -> None:
        super().__init__()
        self.page = "Home"
        self._page_lock = threading.Lock()

    def init_aside(self, expand_menu: bool = True, name: str = None) -> None:
        """
        侧边栏按钮点击时的初始化回调。

        清空菜单区域，展开菜单，并高亮指定按钮。

        Args:
            expand_menu: 是否展开菜单。
            name: 需要高亮的按钮名称（标签）。
        """
        self.visible = True
        self.task_handler.remove_pending_task()
        clear("menu")
        if expand_menu:
            self.expand_menu()
        if name:
            self.active_button("aside", name)
            set_localstorage("aside", name)

    def init_menu(self, collapse_menu: bool = True, name: str = None) -> None:
        """
        菜单按钮点击时的初始化回调。

        清空内容区域，折叠菜单，并高亮指定按钮。

        Args:
            collapse_menu: 是否折叠菜单。
            name: 需要高亮的按钮名称（标签）。
        """
        self.visible = True
        self.page = name
        self.task_handler.remove_pending_task()
        with self._page_lock:
            clear("content")
        if collapse_menu:
            self.collapse_menu()
        if name:
            self.active_button("menu", name)

    @staticmethod
    @use_scope("ROOT", clear=True)
    def _show() -> None:
        put_scope(
            "header",
            [
                put_html(Icon.ALAS).style("--header-icon--"),
                put_text("港区OA").style("--header-text--"),
                put_scope("header_status"),
                put_scope("header_title"),
            ],
        )
        put_scope(
            "contents",
            [
                put_scope("aside"),
                put_scope("menu"),
                put_scope("content"),
            ],
        )

    @staticmethod
    @use_scope("header_title", clear=True)
    def set_title(text=""):
        put_text(text)

    @staticmethod
    def collapse_menu() -> None:
        run_js(
            f"""
            $("#pywebio-scope-menu").addClass("container-menu-collapsed");
            $(".container-content-collapsed").removeClass("container-content-collapsed");
        """
        )

    @staticmethod
    def expand_menu() -> None:
        run_js(
            f"""
            $(".container-menu-collapsed").removeClass("container-menu-collapsed");
            $("#pywebio-scope-content").addClass("container-content-collapsed");
        """
        )

    @staticmethod
    def active_button(position, value) -> None:
        run_js(
            f"""
            $("button.btn-{position}").removeClass("btn-{position}-active");
            $("div[style*='--{position}-{value}--']>button").addClass("btn-{position}-active");
        """
        )

    @staticmethod
    def pin_set_invalid_mark(keys) -> None:
        if isinstance(keys, str):
            keys = [keys]
        keys = ["_".join(key.split(".")) for key in keys]
        js = "".join(
            [
                f"""$(".form-control[name='{key}']").addClass('is-invalid');"""
                for key in keys
            ]
        )
        if js:
            run_js(js)

    @staticmethod
    def pin_remove_invalid_mark(keys) -> None:
        if isinstance(keys, str):
            keys = [keys]
        keys = ["_".join(key.split(".")) for key in keys]
        js = "".join(
            [
                f"""$(".form-control[name='{key}']").removeClass('is-invalid');"""
                for key in keys
            ]
        )
        if js:
            run_js(js)
