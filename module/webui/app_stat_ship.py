"""WebUI 舰船经验统计视图。"""

from module.webui.app_dependencies import (
    alas_instance,
    put_button,
    put_html,
    put_row,
    put_text,
    t,
    use_scope,
)

from module.webui.app_helpers import (
    build_muted_notice,
    build_simple_table,
    build_title_block,
)


from module.webui.app_types import WebUIMixinBase


class ShipExperienceStatisticsMixin(WebUIMixinBase):
    """WebUI 舰船经验统计视图。"""

    def _render_ship_exp(self):
        try:
            from module.statistics.ship_exp_stats import get_ship_exp_stats
            from module.statistics.opsi_month import (
                get_opsi_stats as get_opsi_stats_func,
            )

            # 使用当前实例名称获取统计数据，确保不为空
            instance_name = getattr(self, "alas_name", None)
            if not instance_name:
                # 使用第一个可用的实例
                from module.config.utils import alas_instance

                all_instances = alas_instance()
                instance_name = all_instances[0] if all_instances else None
            stats = get_ship_exp_stats(instance_name=instance_name)
            if not stats.data or not stats.data.get("ships"):
                with use_scope("ship_exp_table", clear=True):
                    put_html(build_muted_notice(t("Gui.Stat.NoShipExpData")))
                return

            current_battles = (
                get_opsi_stats_func(instance_name=instance_name)
                .summary()
                .get("total_battles", 0)
            )
            target_level = stats.data.get("target_level", 125)
            exp_per_hour = stats.get_exp_per_hour()
            today_stats = stats.get_today_stats()

            # 从daily_stats获取今日战斗场次
            today_battles = today_stats.get("battle_count", 0) if today_stats else 0

            labels = [
                t("Gui.Stat.ShipSlot"),
                t("Gui.Stat.Level"),
                t("Gui.Stat.CurrentExpThisLevel"),
                t("Gui.Stat.TotalExp"),
                t("Gui.Stat.TargetExpRequired"),
                t("Gui.Stat.BattlesCompleted"),
                t("Gui.Stat.ExpRemaining"),
                t("Gui.Stat.SortiesNeeded"),
                t("Gui.Stat.EstimatedTime"),
            ]

            rows = []
            for ship in stats.data.get("ships", []):
                progress = stats.calculate_progress(ship, target_level, current_battles)
                # 使用今日daily_stats的battle_count作为已战斗场次
                rows.append(
                    [
                        progress["position"],
                        progress["level"],
                        progress["current_exp"],
                        progress["total_exp"],
                        progress["target_exp"],
                        today_battles,  # 使用今日battle_count而非计算值
                        progress["exp_needed"],
                        progress["battles_needed"],
                        progress["time_needed"],
                    ]
                )

            with use_scope("ship_exp_table", clear=True):
                put_html(
                    build_title_block(
                        t("Gui.Stat.ShipExpProgressTitle"),
                        margin_top=16,
                        margin_bottom=8,
                    )
                )
                put_text(
                    t(
                        "Gui.Stat.LastCheckTime",
                        value=stats.data.get("last_check_time", "-"),
                    )
                )

                # 显示一行统计：今日战斗 / 今日经验 / 经验效率 / 今日运行
                if today_stats:
                    run_minutes = int(today_stats.get("total_run_time", 0) // 60)
                    put_row(
                        [
                            put_text(
                                t(
                                    "Gui.Stat.TodayBattles",
                                    value=today_stats.get("battle_count", 0),
                                    unit=t("Gui.Stat.TodayBattleUnit"),
                                )
                            ),
                            put_text(
                                t(
                                    "Gui.Stat.TodayExp",
                                    value=today_stats.get("total_exp_gained", 0),
                                )
                            ),
                            put_text(
                                t(
                                    "Gui.Stat.ExpEfficiency",
                                    value=f"{exp_per_hour:.0f}",
                                    unit=t("Gui.Stat.HourUnit"),
                                )
                            ),
                            put_text(
                                t(
                                    "Gui.Stat.TodayRun",
                                    value=run_minutes,
                                    unit=t("Gui.Stat.MinuteUnit"),
                                )
                            ),
                        ]
                    )
                else:
                    put_text(t("Gui.Stat.NoTodayBattleData"))

                put_html(
                    build_simple_table(labels, rows, extra_style=" margin-top:8px;")
                )

                put_button(
                    t("Gui.Stat.Refresh"), onclick=self._render_ship_exp, color="off"
                )
        except Exception as e:
            with use_scope("ship_exp_table", clear=True):
                put_text(t("Gui.Stat.LoadShipExpFailed", e=e))
