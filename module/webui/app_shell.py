"""WebUI会话外壳"""

from module.webui.app_dependencies import (
    AzurLaneConfig,
    Icon,
    ProcessManager,
    State,
    alas_instance,
    clear,
    current_time,
    filepath_args,
    put_buttons,
    put_html,
    put_icon_buttons,
    put_loading_text,
    put_scope,
    queue,
    read_file,
    run_js,
    t,
    time,
    time_source_status,
    timedelta,
    timezone,
    use_scope,
    webconfig,
)


from module.webui.app_types import WebUIMixinBase


def _reload_theme_css(theme: str) -> None:
    """切换主题时移除旧主题的 <link> 与 <style>，并重新注入当前主题 CSS。

    初始 HTML 预加载的 <link> 元素（如 dark-alas.css）在切换主题后
    仍残留在 DOM 中，其 !important 规则会覆盖新主题的 CSS。需要先
    删除所有主题 CSS 的 <link> 和 <style>，再注入当前主题的 CSS。
    """
    from module.webui.app_dependencies import local
    from module.webui.utils import add_css_files, filepath_css

    run_js("""
    var links = document.querySelectorAll(
        'link[href*="dark-alas"],' +
        'link[href*="light-alas"],' +
        'link[href*="advanced-material-alas"],' +
        'link[href*="dark-advanced-material"]'
    );
    for (var i = 0; i < links.length; i++) {
        links[i].parentNode.removeChild(links[i]);
    }
    var styles = document.querySelectorAll(
        'style[id^="alas-css-"]'
    );
    for (var i = 0; i < styles.length; i++) {
        styles[i].parentNode.removeChild(styles[i]);
    }
    """)

    injected_styles = getattr(local, "webui_injected_styles", None)
    if injected_styles is not None:
        injected_styles.discard(filepath_css("light-alas"))
        injected_styles.discard(filepath_css("dark-alas"))
        injected_styles.discard(filepath_css("advanced-material-alas"))
        injected_styles.discard(filepath_css("dark-advanced-material-overrides-alas"))

    if theme == "dark":
        add_css_files((filepath_css("dark-alas"),))
    elif theme == "advanced_material":
        add_css_files((filepath_css("advanced-material-alas"),))
    elif theme == "dark_advanced_material":
        add_css_files((
            filepath_css("advanced-material-alas"),
            filepath_css("dark-advanced-material-overrides-alas"),
        ))
    else:
        add_css_files((filepath_css("light-alas"),))


class AppShellMixin(WebUIMixinBase):
    """WebUI会话外壳"""

    def initial(self) -> None:
        from module.webui.app_cache import get_cached_menu_args

        menu, args = get_cached_menu_args(
            self.alas_mod,
            read_file,
            filepath_args,
        )
        self.ALAS_MENU = menu
        self.ALAS_ARGS = args

    def __init__(self) -> None:
        super().__init__()
        # 已修改的配置键，来自 pin_wait_change() 的返回值
        self.modified_config_queue = queue.Queue()
        # 当前 Alas 配置名称
        self.alas_name = ""
        self.alas_mod = "alas"
        self.alas_config = AzurLaneConfig("template")
        self.initial()
        # 已渲染的状态缓存
        self.rendered_cache = []
        self.inst_cache = []
        self._shell_mounted = False
        self._active_aside = None
        self._stored_aside = None
        self._overview_snapshot = None
        self.af_flag = False
        self._last_announcement_id = None
        self._announcement_result = None
        self._announcement_fetching = False
        self._announcement_force = False
        self._update_notified = False
        self._simulator = None
        self._simulator_logger_pm = None
        self._overview_log = None
        self._overview_log_config_name = None

    @property
    def simulator(self):
        """在首次进入大世界模拟器时再加载其运行时依赖。"""
        if self._simulator is None:
            import sys

            from module.webui.fake_pil_module import remove_fake_pil_module

            # matplotlib 需要真实 PIL；仅移除 WebUI 启动阶段安装的替身，
            # 避免其他会话已加载真实 PIL 时再次从模块缓存中删除它。
            if not hasattr(sys.modules.get("PIL"), "__path__"):
                remove_fake_pil_module()
            from module.os_simulator.simulator import OSSimulator

            self._simulator = OSSimulator()
        return self._simulator

    def _close_update_notice(self) -> None:
        run_js(
            r"""
            (function () {
                var el = document.getElementById('alas-update-notice');
                if (!el) return;
                el.classList.add('is-leaving');
                setTimeout(function () {
                    if (el && el.parentNode) {
                        el.parentNode.removeChild(el);
                    }
                }, 180);
            })();
            """
        )

    def _remove_update_notice(self) -> None:
        run_js(
            r"""
            (function () {
                var el = document.getElementById('alas-update-notice');
                if (el && el.parentNode) {
                    el.parentNode.removeChild(el);
                }
            })();
            """
        )

    def _show_update_notice(self, onclick) -> None:
        self._remove_update_notice()
        scope = f"update_notice_{int(time.time() * 1000)}"

        def handle_later():
            self._close_update_notice()

        with use_scope("ROOT"):
            put_html(
                f"""
                <div id="alas-update-notice" class="alas-update-notice" role="status" aria-live="polite">
                    <div class="alas-update-notice__halo"></div>
                    <div class="alas-update-notice__icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                             stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <path d="M7 10l5 5 5-5"></path>
                            <path d="M12 15V3"></path>
                        </svg>
                    </div>
                    <div class="alas-update-notice__body">
                        <div class="alas-update-notice__eyebrow">发现新版本</div>
                        <div class="alas-update-notice__title">有可用更新！</div>
                        <div class="alas-update-notice__text">
                            建议及时更新，以获得更稳定的脚本运行体验。
                        </div>
                        <div id="pywebio-scope-{scope}" class="alas-update-notice__actions"></div>
                    </div>
                </div>
                """
            )
            put_buttons(
                [
                    {
                        "label": "立即更新",
                        "value": "update",
                        "color": "danger",
                    },
                    {
                        "label": "稍后再说",
                        "value": "later",
                        "color": "secondary",
                    },
                ],
                onclick=[onclick, handle_later],
                small=True,
                scope=scope,
            )

    @use_scope("aside", clear=True)
    def set_aside(self) -> None:
        # TODO: 更新 put_icon_buttons()

        current_date = current_time().date()
        if current_date.month == 4 and current_date.day == 1:
            self.af_flag = True

        put_scope("aside_home")
        put_scope("aside_instance")
        put_scope("aside_manage")
        self.refresh_aside_labels()
        self.refresh_aside_instances(force=True)

    def refresh_aside_labels(self) -> None:
        """语言变化时只更新主边栏中的静态按钮。"""
        with use_scope("aside_home", clear=True):
            put_icon_buttons(
                Icon.DEVELOP,
                "false",
                buttons=[
                    {
                        "label": t("Gui.Aside.Home"),
                        "value": "Home",
                        "color": "aside",
                    }
                ],
                onclick=[self.ui_develop],
            )
        with use_scope("aside_manage", clear=True):
            put_icon_buttons(
                Icon.SETTING,
                "false",
                buttons=[
                    {
                        "label": t("Gui.AddAlas.Manage"),
                        "value": "Manage",
                        "color": "aside",
                    }
                ],
                onclick=[self.ui_manage],
            )
        aside_name = self._active_aside or self._stored_aside or "Home"
        self.active_button("aside", aside_name)

    @use_scope("aside_instance")
    def refresh_aside_instances(self, force=False) -> None:
        """仅在实例集合或运行状态变化时更新实例侧栏。"""
        instances = alas_instance()
        rebuild = (
            force
            or instances != self.inst_cache
            or len(self.rendered_cache) != len(instances)
        )

        def update(name, seq):
            with use_scope(f"alas-instance-{seq}", clear=True):
                rendered_state = ProcessManager.get_manager(name).state
                if rendered_state == 1:
                    icon_html = Icon.RUNNING
                elif rendered_state == 3:
                    icon_html = Icon.ERROR
                elif rendered_state == 4:
                    icon_html = Icon.UPDATE
                else:
                    icon_html = Icon.RUN
                status_signal = "false" if rendered_state in (1, 3, 4) else "true"
                if rendered_state == 1 and getattr(self, "af_flag", False):
                    icon_html = icon_html[:31] + " anim-rotate" + icon_html[31:]
                put_icon_buttons(
                    icon_html,
                    status_signal,
                    buttons=[{"label": name, "value": name, "color": "aside"}],
                    onclick=self.ui_alas,
                )
            return rendered_state

        changed = rebuild
        if rebuild:
            self.inst_cache = instances
            self.rendered_cache.clear()
            clear()
            for index, _ in enumerate(instances):
                put_scope(f"alas-instance-{index}")
            for index, inst in enumerate(instances):
                self.rendered_cache.append(update(inst, index))
        else:
            for index, inst in enumerate(instances):
                state = ProcessManager.get_manager(inst).state
                if state != self.rendered_cache[index]:
                    self.rendered_cache[index] = update(inst, index)
                    changed = True

        if changed:
            aside_name = self._active_aside or self._stored_aside or "Home"
            self.active_button("aside", aside_name)

    def set_aside_status(self) -> None:
        self.refresh_aside_instances()

    @use_scope("header_status")
    def set_status(self, state: int) -> None:
        """
        Args:
            state (int):
                1 (running)
                2 (not running)
                3 (warning, stop unexpectedly)
                4 (stop for update)
                0 (hide)
                -1 (*state not changed)
        """
        if state == -1:
            return
        clear()

        if state == 1:
            put_loading_text(t("Gui.Status.Running"), color="success")
        elif state == 2:
            put_loading_text(t("Gui.Status.Inactive"), color="secondary", fill=True)
        elif state == 3:
            put_loading_text(t("Gui.Status.Warning"), shape="grow", color="warning")
        elif state == 4:
            put_loading_text(t("Gui.Status.Updating"), shape="grow", color="success")

    @staticmethod
    def _format_tz_offset(offset: timedelta) -> str:
        seconds = int(offset.total_seconds())
        sign = "+" if seconds >= 0 else "-"
        seconds = abs(seconds)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        return f"UTC{sign}{hours:02d}:{minutes:02d}"

    def _time_status_text(self) -> str:
        data = time_source_status()
        local_offset = current_time(timezone.utc).astimezone().utcoffset()
        local_tz = self._format_tz_offset(local_offset or timedelta(0))
        sync_text = "已同步" if data["synced"] else "本机时间"
        enabled_text = "NTP" if data["enabled"] else "NTP关闭"
        return (
            f"{enabled_text} {sync_text} · 偏移 {data['offset']:+.3f}s · "
            f"本机 {local_tz}"
        )

    @classmethod
    def set_theme(cls, theme="default") -> None:
        if theme == "apple":
            theme = "advanced_material"
        if theme not in (
            "default",
            "dark",
            "light",
            "advanced_material",
            "dark_advanced_material",
        ):
            theme = "default"
        cls.theme = theme
        State.deploy_config.Theme = theme
        State.theme = theme

        # PyWebIO 仅提供 dark/default 等主题，没有 light.min.css，
        # 因此 light 统一回退到 default（default.min.css 即亮色主题）。
        pywebio_theme = "dark" if theme == "dark" else "default"

        webconfig(theme=pywebio_theme)  

        run_js("""
        document.querySelectorAll(
            'link[href*="advanced-material-alas"],' +
            'link[href*="dark-advanced-material-overrides-alas"]'
        ).forEach(function(e) {
            e.remove();
        });
        """)

        run_js(f"""
        (function() {{
            var link = document.querySelector('link[href*="bs-theme/"]');
            if (link) {{
                link.href = link.href.replace(
                    /bs-theme\\/\\S+\\.min\\.css/,
                    'bs-theme/{pywebio_theme}.min.css'
                );
            }}
            document.body.className = document.body.className
                .replace(/webio-theme-\\S+/g, '')
                + ' webio-theme-{pywebio_theme}';
        }})();
        """)

        # 清空会话注入追踪中的主题 CSS 记录，然后重新调用 load_webui_styles
        # 为当前主题注入正确的 CSS。旧主题残留的 !important 规则会被新 CSS 覆盖。
        _reload_theme_css(theme)

        run_js(f"""
        window.dispatchEvent(
            new CustomEvent(
                "alas-theme-change",
                {{detail: "{theme}"}}
            )
        );
        """)