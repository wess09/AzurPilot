"""WebUI仪表盘刷新逻辑"""

from module.webui.app_dependencies import (
    Function,
    LogRes,
    clear,
    current_time,
    datetime,
    deep_get,
    get_dashboard_scope_id,
    get_group_scope_id,
    put_button,
    put_column,
    put_html,
    put_row,
    put_scope,
    put_text,
    re,
    t,
    time_delta,
    use_scope,
)

from module.webui.app_helpers import (
    timedelta_to_text,
)


from module.webui.app_types import WebUIMixinBase


class DashboardMixin(WebUIMixinBase):
    """WebUI仪表盘刷新逻辑"""

    def alas_update_overview_task(self) -> None:
        if not self.visible:
            return
        if getattr(self, "page", None) != "Overview":
            return
        self.alas_config.load()
        self.alas_config.get_next_task()

        if len(self.alas_config.pending_task) >= 1:
            if self.alas.alive:
                running = self.alas_config.pending_task[:1]
                pending = self.alas_config.pending_task[1:]
            else:
                running = []
                pending = self.alas_config.pending_task[:]
        else:
            running = []
            pending = []
        waiting = self.alas_config.waiting_task

        snapshot = {
            "running": tuple((task.command, task.next_run) for task in running),
            "pending": tuple((task.command, task.next_run) for task in pending),
            "waiting": tuple((task.command, task.next_run) for task in waiting),
            "alive": self.alas.alive,
        }
        if self._overview_snapshot == snapshot:
            return
        self._overview_snapshot = snapshot

        def put_task(func: Function):
            with use_scope(f"overview-task_{func.command}"):
                put_column(
                    [
                        put_text(t(f"Task.{func.command}.name")).style("--arg-title--"),
                        put_text(str(func.next_run)).style("--arg-help--"),
                    ],
                    size="auto auto",
                )
                put_button(
                    label=t("Gui.Button.Setting"),
                    onclick=lambda: self.alas_set_group(func.command),
                    color="off",
                )

        clear("running_tasks")
        clear("pending_tasks")
        clear("waiting_tasks")
        with use_scope("running_tasks"):
            if running:
                for task in running:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")
        with use_scope("pending_tasks"):
            if pending:
                for task in pending:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")
        with use_scope("waiting_tasks"):
            if waiting:
                for task in waiting:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")

    def _update_dashboard(self, num=None, groups_to_display=None):
        x = 0
        _num = 10000 if num is None else num
        _arg_group = (
            self._log.dashboard_arg_group
            if groups_to_display is None
            else groups_to_display
        )
        time_now = current_time().replace(microsecond=0)
        for group_name in _arg_group:
            group = LogRes(self.alas_config).group(group_name)
            if group is None:
                continue

            value = str(group["Value"])
            value_total = ""
            if "Limit" in group.keys():
                value_limit = f" / {group['Limit']}"
            elif "Total" in group.keys():
                value_total = f" ({group['Total']})"
                value_limit = ""
            elif group_name == "Pt":
                value_limit = " / " + re.sub(
                    r'[,.\'"，。]',
                    "",
                    str(
                        deep_get(
                            self.alas_config.data, "EventGeneral.EventGeneral.PtLimit"
                        )
                    ),
                )
                if value_limit == " / 0":
                    value_limit = ""
            else:
                value_limit = ""
                value_total = ""

            value_time = group["Record"]
            if value_time is None or value_time == datetime(2020, 1, 1, 0, 0, 0):
                value_time = datetime(2023, 1, 1, 0, 0, 0)

            # Handle time delta
            if value_time == datetime(2023, 1, 1, 0, 0, 0):
                value = "None"
                delta = timedelta_to_text()
            else:
                delta = timedelta_to_text(time_delta(value_time - time_now))

            if group_name not in self._log.last_display_time.keys():
                self._log.last_display_time[group_name] = ""
            if (
                self._log.last_display_time[group_name] == delta
                and not self._log.first_display
            ):
                continue
            self._log.last_display_time[group_name] = delta

            # if self._log.first_display:
            # Handle width
            # value_width = len(value) * 0.7 + 0.6 if value != 'None' else 4.5
            # value_width = str(value_width/1.12) + 'rem' if self.is_mobile else str(value_width) + 'rem'
            value_limit = "" if value == "None" else value_limit
            # limit_width = len(value_limit) * 0.7
            # limit_width = str(limit_width) + 'rem'
            value_total = "" if value == "None" else value_total
            limit_style = (
                "--dashboard-limit--" if value_limit else "--dashboard-total--"
            )
            value_limit = value_limit if value_limit else value_total
            # Handle dot color
            # 旧配置可能缺少颜色字段，仍渲染条目而不是中断整个仪表盘刷新。
            color_value = deep_get(group, "Color") or ""
            _color = f"background-color:{color_value.replace('^', '#')}"
            color = f'<div class="status-point" style={_color}>'
            # 使用集中管理的辅助函数生成 scope_id，确保命名一致性和安全性
            scope_id = get_dashboard_scope_id(group_name)
            with use_scope(scope_id, clear=True):
                put_row(
                    [
                        put_html(color),
                        put_scope(
                            get_group_scope_id(group_name),
                            [
                                put_column(
                                    [
                                        put_row(
                                            [
                                                put_text(value).style(
                                                    f"--dashboard-value--"
                                                ),
                                                put_text(value_limit).style(
                                                    limit_style
                                                ),
                                            ],
                                        ).style(
                                            "grid-template-columns:min-content auto;align-items: baseline;"
                                        ),
                                        put_text(
                                            t(f"Gui.Dashboard.{group_name}")
                                            + " - "
                                            + delta
                                        ).style("---dashboard-help--"),
                                    ],
                                    size="auto auto",
                                ),
                            ],
                        ),
                    ],
                    size="20px 1fr",
                ).style("height: 1fr")
            x += 1
            if x >= _num:
                break
        if self._log.first_display:
            self._log.first_display = False

    def alas_update_dashboard(self, _clear=False):
        if not self.visible:
            return
        if getattr(self, "page", None) != "Overview":
            return
        with use_scope("dashboard", clear=_clear):
            if not self._log.display_dashboard:
                self._update_dashboard(
                    num=4, groups_to_display=["Oil", "Coin", "Gem", "Pt"]
                )
            elif self._log.display_dashboard:
                self._update_dashboard()
