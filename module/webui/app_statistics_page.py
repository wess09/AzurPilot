"""WebUI 统计页装配器。"""

from datetime import date
from pathlib import Path

import module.webui.lang as lang
from module.webui.app_dependencies import put_button, put_scope, run_js, t, use_scope
from module.webui.app_types import WebUIMixinBase


class StatisticsPageMixin(WebUIMixinBase):
    """惰性装配并复用统计子视图，同时支持概览页内嵌与独立统计页。"""

    def _mount_stat_panels(self) -> None:
        """创建并渲染统计图表面板（含周期刷新），渲染到当前所在作用域。

        统计图表既可整体铺满页面，也可内嵌到概览页的右侧区域，
        因此单独抽出为面板装配方法，由调用方决定其渲染位置。
        """
        if not hasattr(self, "_ap_chart_view"):
            self._ap_chart_view = "line"
        if not hasattr(self, "_commission_income_period"):
            self._commission_income_period = "month"

        # 独立 scope 使周期刷新不会清空其他统计区域。
        # 顶部资源概览（排除行动力/黄币/紫币，避免与下方行动力图表重复）
        put_scope("stat_resources", []).style(
            "display:flex;flex-wrap:wrap;gap:.4rem .8rem;align-items:center;"
            "border:1px solid var(--alas-entry-border,#dde0e5);"
            "padding:.45rem .7rem;margin-bottom:.6rem;"
            "position:sticky;top:0;z-index:10;"
            "background:var(--alas-entry-surface,#fff);"
        )
        # 重新挂载时重置去重状态，避免浏览器刷新后因增量去重导致资源不渲染
        self._dashboard_last_display_time = {}
        self._dashboard_first_display = True
        # 不再同步渲染：后台任务注册后 next_run=now 会立即在任务线程执行，
        # 页面切换只做轻量的空容器挂载，避免统计视图的数据库读取与图表构建
        # 阻塞总览页/页面切换的响应。
        self.task_handler.add(self.alas_update_stat_resources, 10, True)
        put_scope("ap_chart", [])
        self.task_handler.add(self._render_ap_chart, 60, True)
        # 隐藏全资源变化趋势图表（始终不渲染、不注册周期刷新）
        # 确保页面加载、刷新、切换选项卡等任何交互后均保持隐藏状态
        # put_scope("resource_chart", [])
        # self._render_resource_chart()
        # self.task_handler.add(self._render_resource_chart, 60, True)
        put_scope("opsi_stats", [])
        self.task_handler.add(self._render_opsi_stats, 60, True)
        put_scope("ship_exp_table", [])
        self.task_handler.add(self._render_ship_exp, 60, True)
        put_scope("commission_income", [])
        self.task_handler.add(self._render_commission_income, 60, True)

    def alas_set_stat(self) -> None:
        """显示统计页，已装配的内容会直接复用。"""
        self.init_menu(name="Stat")
        self.set_title(t("Gui.Overview.Stat"))
        if not hasattr(self, "_ap_chart_view"):
            self._ap_chart_view = "line"
        if not hasattr(self, "_commission_income_period"):
            self._commission_income_period = "month"

        cache_key = self._get_statistics_cache_key()
        cached_key = getattr(self, "_statistics_cache_key", None)

        if cached_key != cache_key:
            self._mount_statistics_page(cache_key)
        else:
            self._refresh_statistics_if_changed()

        # 原先的 5 个任务会在进页后立即各重绘一次。现在仅轮询本地数据源
        # 版本并提示存在新数据，不再打断用户正在查看的图表状态。
        self.task_handler.add(self._refresh_statistics_if_changed, 15, True)

    def _mount_statistics_page(self, cache_key) -> None:
        """为当前实例首次创建统计内容。"""
        with self._page_lock:
            if getattr(self, "page", None) != "Stat":
                return
            if getattr(self, "_statistics_cache_key", None) is not None:
                self.cleanup_client_resources(
                    "__apChartCleanups",
                    "__resourceChartCleanups",
                )

            with use_scope("statistics-content", clear=True):
                put_scope(
                    "statistics-toolbar",
                    [
                        put_button(
                            t("Gui.Stat.Refresh"),
                            onclick=self._refresh_statistics_page,
                            color="off",
                        )
                    ],
                ).style(
                    "display:flex;justify-content:flex-end;margin-bottom:.5rem;"
                )
                put_scope("ap_chart", [])
                put_scope("resource_chart", [])
                put_scope("opsi_stats", [])
                put_scope("ship_exp_table", [])
                put_scope("commission_income", [])

            self._statistics_cache_key = cache_key
            self._render_statistics_sections()
            self._statistics_source_signature = (
                self._get_statistics_source_signature()
            )
            self._statistics_refresh_pending = False

    def _refresh_statistics_page(self) -> None:
        """刷新已挂载的全部统计模块。"""
        with self._page_lock:
            if getattr(self, "page", None) != "Stat":
                return
            if getattr(self, "_statistics_cache_key", None) is None:
                return

            self._render_statistics_sections()
            self._statistics_source_signature = (
                self._get_statistics_source_signature()
            )
            self._set_statistics_refresh_pending(False)

    def _refresh_statistics_if_changed(self) -> None:
        """检测当前实例的本地统计数据变化并更新刷新提示。"""
        if getattr(self, "page", None) != "Stat":
            return
        if (
            getattr(self, "_statistics_cache_key", None)
            != self._get_statistics_cache_key()
        ):
            return

        source_signature = self._get_statistics_source_signature()
        self._set_statistics_refresh_pending(
            source_signature
            != getattr(self, "_statistics_source_signature", None)
        )

    def _set_statistics_refresh_pending(self, pending: bool) -> None:
        """只更新刷新提示，不替换用户正在查看的统计 DOM。"""
        if pending == getattr(self, "_statistics_refresh_pending", False):
            return
        self._statistics_refresh_pending = pending
        run_js(
            """
            (function () {
                var toolbar = document.getElementById(
                    "pywebio-scope-statistics-toolbar"
                );
                var button = toolbar && toolbar.querySelector("button");
                if (!button) return;
                button.classList.toggle("statistics-refresh-pending", pending);
                button.title = pending ? refreshHint : "";
                button.setAttribute(
                    "aria-label",
                    pending ? refreshHint : button.textContent.trim()
                );
            })();
            """,
            pending=pending,
            refreshHint=t("Gui.Stat.NewDataAvailable"),
        )

    def _render_statistics_sections(self) -> None:
        """统一刷新各统计子视图。"""
        self._render_ap_chart()
        self._render_resource_chart()
        self._render_opsi_stats()
        self._render_ship_exp()
        self._render_commission_income()

    def _get_statistics_cache_key(self):
        """返回会影响统计页文案与数据归属的键。"""
        return getattr(self, "alas_name", None), lang.LANG

    def _get_statistics_source_signature(self):
        """以廉价的文件版本检查代替重复解析和绘图。"""
        project_root = Path(__file__).resolve().parents[2]
        instance_name = getattr(self, "alas_name", None) or "default"
        paths = (
            project_root / "config" / "cl1_data.db",
            project_root / "config" / "cl1_data.db-wal",
            project_root / "config" / "azurstats_local.db",
            project_root / "config" / "azurstats_local.db-wal",
            project_root / "log" / "cl1" / instance_name / "ship_exp_data.json",
        )
        return date.today().isoformat(), tuple(
            self._get_statistics_file_version(path) for path in paths
        )

    @staticmethod
    def _get_statistics_file_version(path: Path):
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size
