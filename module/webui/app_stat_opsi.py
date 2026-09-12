"""WebUI 大世界统计视图。"""

from module.webui.app_dependencies import (
    current_time,
    put_button,
    put_html,
    put_row,
    put_scope,
    put_text,
    t,
    time,
    use_scope,
)

from module.webui.app_helpers import (
    build_muted_notice,
    build_simple_table,
    build_title_block,
)


from module.webui.app_types import WebUIMixinBase


class OpsiStatisticsMixin(WebUIMixinBase):
    """WebUI 大世界统计视图。"""

    def _render_opsi_stats(self):
        dependencies = self._load_opsi_stats_dependencies()
        if dependencies is None:
            return

        (
            instance_name,
            summary,
            cl1_db,
            compute_monthly_cl1_akashi_ap,
            get_ship_exp_stats,
        ) = dependencies
        exp_data = self._load_ship_exp_data(get_ship_exp_stats, instance_name)
        if exp_data is None:
            return

        exp_stats, ships_data, target_level, last_check_time = exp_data
        self._render_daily_exp_stats(
            instance_name,
            exp_stats,
            ships_data,
            target_level,
            last_check_time,
        )
        labels, values, ap_bought = self._build_cl1_summary(
            instance_name,
            summary,
            compute_monthly_cl1_akashi_ap,
            get_ship_exp_stats,
        )
        meow_rows = self._build_meow_rows(cl1_db, instance_name)
        self._render_opsi_summary(labels, values, ap_bought, meow_rows)

    def _load_opsi_stats_dependencies(self):
        try:
            from module.statistics.opsi_month import (
                get_opsi_stats,
                compute_monthly_cl1_akashi_ap,
            )
            from module.statistics.cl1_database import db as cl1_db
            from module.statistics.ship_exp_stats import get_ship_exp_stats

            instance_name = getattr(self, "alas_name", None)
            if not instance_name:
                from module.config.utils import alas_instance

                all_instances = alas_instance()
                instance_name = all_instances[0] if all_instances else None
            summary = get_opsi_stats(instance_name=instance_name).summary()
        except Exception as e:
            with use_scope("opsi_stats", clear=True):
                put_text(t("Gui.Stat.LoadOpsiStatsFailed", e=e))
            return None

        return (
            instance_name,
            summary,
            cl1_db,
            compute_monthly_cl1_akashi_ap,
            get_ship_exp_stats,
        )

    def _load_ship_exp_data(self, get_ship_exp_stats, instance_name):
        try:
            exp_stats = get_ship_exp_stats(instance_name=instance_name)
            exp_data = exp_stats.data
            ships_data = exp_data.get("ships", []) if exp_data else []
            target_level = exp_data.get("target_level", 125) if exp_data else 125
            last_check_time = exp_data.get("last_check_time", "-") if exp_data else "-"
        except Exception as e:
            with use_scope("opsi_stats", clear=True):
                put_text(t("Gui.Stat.LoadExpStatsFailed", e=e))
            return None

        return exp_stats, ships_data, target_level, last_check_time

    def _render_daily_exp_stats(
        self, instance_name, exp_stats, ships_data, target_level, last_check_time
    ):
        with use_scope("opsi_stats", clear=True):
            put_html(build_title_block(t("Gui.Stat.DailyExpCheckTitle")))
            put_row(
                [
                    put_text(t("Gui.Stat.CheckTime", value=last_check_time)),
                    put_text(t("Gui.Stat.TargetLevel", value=target_level)),
                ]
            )
            if ships_data:
                exp_labels = [
                    t("Gui.Stat.ShipSlot"),
                    t("Gui.Stat.Level"),
                    t("Gui.Stat.CurrentExpThisLevel"),
                    t("Gui.Stat.TotalExp"),
                    t("Gui.Stat.ExpToTarget"),
                    t("Gui.Stat.SortiesNeeded"),
                    t("Gui.Stat.EstimatedTime"),
                ]
                exp_rows = []
                from module.statistics.opsi_month import (
                    get_opsi_stats as get_opsi_stats_inner,
                )

                current_battles = (
                    get_opsi_stats_inner(instance_name=instance_name)
                    .summary()
                    .get("total_battles", 0)
                )
                for ship in ships_data:
                    progress = exp_stats.calculate_progress(
                        ship, target_level, current_battles
                    )
                    exp_rows.append(
                        [
                            progress["position"],
                            progress["level"],
                            progress["current_exp"],
                            progress["total_exp"],
                            progress["exp_needed"]
                            if progress["exp_needed"] > 0
                            else "-",
                            progress["battles_needed"]
                            if progress["battles_needed"] > 0
                            else "-",
                            progress["time_needed"],
                        ]
                    )

                put_html(build_simple_table(exp_labels, exp_rows))
            else:
                put_html(build_muted_notice(t("Gui.Stat.NoExpData")))

    def _build_cl1_summary(
        self,
        instance_name,
        summary,
        compute_monthly_cl1_akashi_ap,
        get_ship_exp_stats,
    ):
        month = summary.get("month", "-")
        total = summary.get("total_battles", "-")
        try:
            tb = int(total)
            rounds = (tb + 1) // 2
            sortie_cost = rounds * 5
        except Exception:
            tb = total
            rounds = "-"
            sortie_cost = "-"

        akashi = summary.get("akashi_encounters", 0)
        try:
            ak = int(akashi)
        except Exception:
            ak = akashi

        try:
            if isinstance(rounds, int) and rounds > 0:
                rate = float(ak) / float(rounds)
                akashi_rate = f"{rate * 100:.2f}%"
            else:
                akashi_rate = "-"
        except Exception:
            akashi_rate = "-"

        try:
            siren_research = int(summary.get("siren_research_devices", 0) or 0)
        except Exception:
            siren_research = 0

        try:
            if isinstance(rounds, int) and rounds > 0:
                siren_research_rate = f"{siren_research / float(rounds) * 100:.2f}%"
            else:
                siren_research_rate = "-"
        except Exception:
            siren_research_rate = "-"

        try:
            ap_bought = compute_monthly_cl1_akashi_ap(instance_name=instance_name)
        except Exception:
            ap_bought = "-"

        try:
            if isinstance(ap_bought, (int, float)) and isinstance(ak, int) and ak > 0:
                avg_ap = int(float(ap_bought) / ak + 0.5)
            else:
                try:
                    ap_tmp = int(ap_bought)
                    if isinstance(ak, int) and ak > 0:
                        avg_ap = int(ap_tmp / ak + 0.5)
                    else:
                        avg_ap = "-"
                except Exception:
                    avg_ap = "-"
        except Exception:
            avg_ap = "-"

        try:
            net_ap = int(ap_bought) - int(sortie_cost)
        except Exception:
            net_ap = "-"

        try:
            eff = int(net_ap) / int(sortie_cost) * 100
            loop_eff = f"{eff:.2f}%"
        except Exception:
            loop_eff = "-"

        # 获取侵蚀1的平均时长
        try:
            exp_stats = get_ship_exp_stats(instance_name=instance_name)
            avg_cl1_battle_time = exp_stats.get_average_battle_time()
            avg_cl1_round_time = exp_stats.get_average_round_time()
            exp_per_hour = exp_stats.get_exp_per_hour()

            avg_cl1_battle_str = f"{avg_cl1_battle_time:.1f}{t('Gui.Stat.SecondUnit')}"
            avg_cl1_round_str = f"{avg_cl1_round_time:.1f}{t('Gui.Stat.SecondUnit')}"
            exp_per_hour_str = f"{exp_per_hour:.0f}/{t('Gui.Stat.HourUnit')}"
        except Exception:
            avg_cl1_battle_str = "-"
            avg_cl1_round_str = "-"
            exp_per_hour_str = "-"

        labels = [
            t("Gui.Stat.Month"),
            t("Gui.Stat.BattleCount"),
            t("Gui.Stat.BattleRounds"),
            t("Gui.Stat.SortieCost"),
            t("Gui.Stat.AkashiEncounters"),
            t("Gui.Stat.AkashiRate"),
            t("Gui.Stat.AverageAP"),
            t("Gui.Stat.NetAP"),
            t("Gui.Stat.LoopEfficiency"),
            t("Gui.Stat.SirenResearchDevices"),
            t("Gui.Stat.SirenResearchRate"),
            t("Gui.Stat.ExpEfficiencyHeader"),
            t("Gui.Stat.AvgBattleTimeHeader"),
            t("Gui.Stat.AvgRoundTime"),
        ]

        values = [
            month,
            tb,
            rounds,
            sortie_cost,
            ak,
            akashi_rate,
            avg_ap,
            net_ap,
            loop_eff,
            siren_research,
            siren_research_rate,
            exp_per_hour_str,
            avg_cl1_battle_str,
            avg_cl1_round_str,
        ]

        return labels, values, ap_bought

    def _build_meow_rows(self, cl1_db, instance_name):
        meow_rows = []
        try:
            now = current_time()
            for hazard_level in (3, 5):
                meow_data = cl1_db.get_meow_stats(
                    instance_name or "default",
                    now.year,
                    now.month,
                    hazard_level=hazard_level,
                )
                meow_effective_rounds = float(
                    meow_data.get("effective_rounds", 0) or 0
                )
                meow_rounds = round(meow_effective_rounds, 1)
                if abs(meow_rounds - int(meow_rounds)) < 1e-6:
                    meow_rounds = int(meow_rounds)

                meow_avg_time = float(meow_data.get("avg_round_time", 0.0) or 0)
                meow_avg_battle_time = float(
                    meow_data.get("avg_battle_time", 0.0) or 0
                )
                siren_count = int(meow_data.get("siren_research_devices", 0) or 0)
                siren_rate = float(meow_data.get("siren_research_rate", 0.0) or 0)

                avg_time_str = (
                    f"{meow_avg_time:.1f}{t('Gui.Stat.SecondUnit')}"
                    if meow_avg_time > 0
                    else "-"
                )
                avg_battle_time_str = (
                    f"{meow_avg_battle_time:.1f}{t('Gui.Stat.SecondUnit')}"
                    if meow_avg_battle_time > 0
                    else "-"
                )
                siren_rate_str = (
                    f"{siren_rate * 100:.2f}%" if meow_effective_rounds > 0 else "-"
                )

                # 明石统计（按侵蚀等级，与侵蚀一表格口径一致）
                akashi_encounters = int(
                    meow_data.get("akashi_encounters", 0) or 0
                )
                akashi_ap = int(meow_data.get("akashi_ap", 0) or 0)
                akashi_rate_str = (
                    f"{akashi_encounters / meow_rounds * 100:.2f}%"
                    if meow_rounds > 0
                    else "-"
                )
                avg_ap_str = (
                    str(int(akashi_ap / akashi_encounters + 0.5))
                    if akashi_encounters > 0
                    else "-"
                )

                # 净赚体力 = 该侵蚀等级购买体力 - 每轮消耗体力 × 出击轮次
                # 侵蚀3 每轮消耗 15，侵蚀5 每轮消耗 30
                cost_per_round = {3: 15, 5: 30}.get(hazard_level, 0)
                net_ap = int(
                    round(akashi_ap - meow_effective_rounds * cost_per_round)
                )

                meow_rows.append(
                    [
                        meow_data.get("month", "-"),
                        hazard_level,
                        int(meow_data.get("battle_count", 0) or 0),
                        meow_rounds,
                        siren_count,
                        siren_rate_str,
                        akashi_encounters,
                        akashi_rate_str,
                        avg_ap_str,
                        net_ap,
                        avg_battle_time_str,
                        avg_time_str,
                    ]
                )
        except Exception:
            return []

        return meow_rows

    def _render_opsi_summary(self, labels, values, ap_bought, meow_rows):
        with use_scope("opsi_stats", clear=True):
            put_html(build_title_block(t("Gui.Stat.OpsiDataCollectionTitle")))
            put_row([put_text(t("Gui.Stat.MonthlyPurchasedAP", value=ap_bought))])
            put_html(build_simple_table(labels, [values]))

            meow_refresh_token = int(time.time() * 1000)

            meow_labels = [
                t("Gui.Stat.Month"),
                t("Gui.Stat.HazardLevel"),
                t("Gui.Stat.BattleCount"),
                t("Gui.Stat.MeowRounds"),
                t("Gui.Stat.SirenResearchDevices"),
                t("Gui.Stat.SirenResearchRate"),
                t("Gui.Stat.AkashiEncounters"),
                t("Gui.Stat.AkashiRate"),
                t("Gui.Stat.AverageAP"),
                t("Gui.Stat.NetAP"),
                t("Gui.Stat.AvgBattleTimeHeader"),
                t("Gui.Stat.AvgMeowRoundTime"),
            ]

            put_html(
                build_title_block(
                    t("Gui.Stat.MeowDataCollectionTitle"),
                    margin_top=20,
                    margin_bottom=8,
                )
            )
            put_html(f"<!-- meow-stats-refresh-token:{meow_refresh_token} -->")
            put_html(build_simple_table(meow_labels, meow_rows))

            put_scope("meow_loot_scope")

            self._render_meowofficer_farming()

            put_row(
                [
                    put_button(
                        t("Gui.Stat.Refresh"),
                        onclick=self._render_opsi_stats,
                        color="off",
                    ),
                    put_button(
                        t("Gui.Stat.ExportAndSaveDesktop"),
                        onclick=lambda: self._export_opsi_csv(True),
                        color="off",
                    ),
                ],
                size="auto",
            )
