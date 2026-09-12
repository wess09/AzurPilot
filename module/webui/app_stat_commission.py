"""WebUI 委托收益统计视图。"""

from html import escape

from module.webui.app_dependencies import (
    logger,
    put_button,
    put_buttons,
    put_html,
    put_row,
    put_text,
    t,
    use_scope,
)


from module.webui.app_types import WebUIMixinBase


_COMMISSION_RECENT_PAGE_SIZE = 10
_COMMISSION_RECENT_TOTAL = 50


class CommissionIncomeStatisticsMixin(WebUIMixinBase):
    """WebUI 委托收益统计视图。"""

    def _render_commission_income(self):
        try:
            income_data = self._load_commission_income_data()
            if income_data is None:
                self._show_commission_income_no_data()
                return

            summary_html, table_html, recent_html = self._build_commission_income_html(
                income_data
            )
            self._output_commission_income(
                summary_html,
                table_html,
                recent_html,
                income_data["period"],
                len(income_data["recent"]),
            )
        except Exception as e:
            with use_scope("commission_income", clear=True):
                put_text(t("Gui.Stat.CommissionIncomeNoData"))
                logger.warning(f"[WebUI-统计] 委托收入渲染失败: {e}")

    def _load_commission_income_data(self):
        from datetime import datetime
        from module.statistics.commission_income_stats import (
            get_commission_income_summary,
            get_recent_commission_entries,
            COMMISSION_ITEM_META,
            COMMISSION_ITEM_NAME_MAP,
            COMMISSION_TRACKED_ITEMS,
        )

        instance_name = getattr(self, "alas_name", None)
        if not instance_name:
            from module.config.utils import alas_instance

            all_instances = alas_instance()
            instance_name = all_instances[0] if all_instances else None
        if not instance_name:
            return None

        item_name_map = {
            "Gem": t("Gui.Stat.CommissionIncomeItemGem"),
            "Cube": t("Gui.Stat.CommissionIncomeItemCube"),
            "Chip": t("Gui.Stat.CommissionIncomeItemChip"),
            "Oil": t("Gui.Stat.CommissionIncomeItemOil"),
            "Coin": t("Gui.Stat.CommissionIncomeItemCoin"),
        }
        item_icon_map = {
            "Gem": "static/assets/gui/icon/icon_1.png",
            "Cube": "static/assets/gui/icon/icon_2.png",
            "Chip": "static/assets/gui/icon/icon_3.png",
            "Oil": "static/assets/gui/icon/icon_4.png",
            "Coin": "static/assets/gui/icon/icon_5.png",
        }
        period = self._commission_income_period

        return {
            "period": period,
            "summary": get_commission_income_summary(instance_name, period=period),
            "recent": get_recent_commission_entries(
                instance_name, limit=_COMMISSION_RECENT_TOTAL
            ),
            "item_name_map": item_name_map,
            "item_icon_map": item_icon_map,
            "datetime": datetime,
            "item_meta": COMMISSION_ITEM_META,
            "item_name_lookup": COMMISSION_ITEM_NAME_MAP,
            "tracked_items": COMMISSION_TRACKED_ITEMS,
        }

    def _build_commission_income_html(self, income_data):
        summary = income_data["summary"]
        rows = summary.get("detail_rows", [])
        has_data = rows and not all(row["total"] == 0 for row in rows)
        item_name_map = income_data["item_name_map"]
        item_icon_map = income_data["item_icon_map"]
        return (
            self._build_commission_summary_html(rows, item_name_map, item_icon_map),
            self._build_commission_table_html(
                rows,
                has_data,
                item_name_map,
                item_icon_map,
            ),
            self._build_commission_recent_html(
                income_data["recent"],
                summary,
                item_name_map,
                item_icon_map,
                income_data["datetime"],
                income_data["item_meta"],
                income_data["item_name_lookup"],
                income_data["tracked_items"],
            ),
        )

    def _build_commission_summary_html(self, rows, item_name_map, item_icon_map):
        html = """
                <style>
                    #commission_income_container > div,
                    #commission_income_container table {
                        width: 100% !important;
                        max-width: 100% !important;
                    }
                    #commission_income_container img {
                        background: transparent !important;
                        border: none !important;
                        box-shadow: none !important;
                        margin: 0 !important;
                        padding: 0 !important;
                    }
                </style>
                <div id="commission_income_container" class="commission-income-summary" style="padding: 0; width: 100%; box-sizing: border-box;">
                """

        html += f'<div style="font-size: 1rem; font-weight: 600; color: inherit; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid rgba(128, 128, 128, 0.2);">{t("Gui.Stat.CommissionIncomeTitle")}</div>'

        html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 12px; margin-bottom: 20px; width: 100%;">'
        for row in rows:
            display_name = item_name_map.get(row["name"], row["name"])
            icon_path = item_icon_map.get(row["name"], "")
            total_str = f"+{row['total']:,}" if row["total"] > 0 else "0"

            icon_html = (
                (
                    f'<div style="width: 34px; height: 34px; display: flex; align-items: center; justify-content: center; background: {row["color"]}1a; border-radius: 8px; flex-shrink: 0;">'
                    f'<img src="{icon_path}" style="width: 24px; height: 24px; object-fit: contain; background: transparent;">'
                    f"</div>"
                )
                if icon_path
                else f'<div style="width: 12px; height: 12px; border-radius: 50%; background: {row["color"]}; flex-shrink: 0;"></div>'
            )

            html += f"""
                    <div class="commission-income-metric-card" style="display: flex; align-items: center; gap: 10px; padding: 12px 14px; background: rgba(128, 128, 128, 0.05); border-radius: 6px; border: 1px solid rgba(128, 128, 128, 0.15);">
                        {icon_html}
                        <div style="display: flex; flex-direction: column; gap: 1px;">
                            <span style="font-size: 0.78rem; opacity: 0.65;">{display_name}</span>
                            <span style="font-size: 1.15rem; font-weight: 400; color: inherit;">{total_str}</span>
                        </div>
                    </div>"""
        return html + "</div>"

    def _build_commission_table_html(self, rows, has_data, item_name_map, item_icon_map):
        html = '<div class="commission-income-table-wrap" style="width: 100% !important; max-width: none !important; display: block !important; box-sizing: border-box;">'
        if not has_data:
            html += f'<p style="margin: 12px 0; opacity: 0.6; font-size: 13px;">{t("Gui.Stat.CommissionIncomeNoData")}</p>'
        else:
            html += '<table class="commission-income-table" style="width: 100% !important; max-width: none !important; border-collapse: collapse; font-size: 0.85rem; table-layout: fixed; display: table;">'
            html += '<colgroup><col style="width: 40%;"><col style="width: 20%;"><col style="width: 20%;"><col style="width: 20%;"></colgroup>'
            html += "<thead><tr>"
            html += f'<th style="text-align: left !important; padding: 8px 10px; background: rgba(128, 128, 128, 0.1); border-bottom: 1px solid rgba(128, 128, 128, 0.2); font-weight: 500; opacity: 0.8; font-size: 0.8rem;">{t("Gui.Stat.CommissionIncomeHeaderItem")}</th>'
            html += f'<th style="text-align: right !important; padding: 8px 10px; background: rgba(128, 128, 128, 0.1); border-bottom: 1px solid rgba(128, 128, 128, 0.2); font-weight: 500; opacity: 0.8; font-size: 0.8rem;">{t("Gui.Stat.CommissionIncomeHeaderTotal")}</th>'
            html += f'<th style="text-align: right !important; padding: 8px 10px; background: rgba(128, 128, 128, 0.1); border-bottom: 1px solid rgba(128, 128, 128, 0.2); font-weight: 500; opacity: 0.8; font-size: 0.8rem;">{t("Gui.Stat.CommissionIncomeHeaderCount")}</th>'
            html += f'<th style="text-align: right !important; padding: 8px 10px; background: rgba(128, 128, 128, 0.1); border-bottom: 1px solid rgba(128, 128, 128, 0.2); font-weight: 500; opacity: 0.8; font-size: 0.8rem;">{t("Gui.Stat.CommissionIncomeHeaderAvg")}</th>'
            html += "</tr></thead><tbody>"

            for row in rows:
                if row["total"] == 0:
                    continue
                display_name = item_name_map.get(row["name"], row["name"])
                icon_path = item_icon_map.get(row["name"], "")

                icon_html = (
                    (
                        f'<div style="width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; background: {row["color"]}1a; border-radius: 4px; flex-shrink: 0;">'
                        f'<img src="{icon_path}" style="width: 18px; height: 18px; object-fit: contain; background: transparent;">'
                        f"</div>"
                    )
                    if icon_path
                    else f'<div style="width: 8px; height: 8px; border-radius: 50%; background: {row["color"]}; flex-shrink: 0;"></div>'
                )

                html += '<tr style="border-bottom: 1px solid rgba(128, 128, 128, 0.1);">'
                html += f'<td style="padding: 7px 10px;"><div style="display: flex; align-items: center; gap: 6px;">{icon_html}{display_name}</div></td>'
                html += f'<td style="padding: 7px 10px; text-align: right; font-family: monospace;">{row["total"]:,}</td>'
                html += f'<td style="padding: 7px 10px; text-align: right; font-family: monospace; opacity: 0.7;">{row["count"]}</td>'
                html += f'<td style="padding: 7px 10px; text-align: right; font-family: monospace; opacity: 0.7;">{row["avg"]}</td>'
                html += "</tr>"

            html += "</tbody></table>"

        return html

    def _build_commission_recent_html(
        self,
        recent,
        summary,
        item_name_map,
        item_icon_map,
        datetime_class,
        item_meta,
        item_name_lookup,
        tracked_items,
    ):
        # 最近委托记录分页：仅渲染当前页的 10 条
        total_pages = (
            (len(recent) + _COMMISSION_RECENT_PAGE_SIZE - 1)
            // _COMMISSION_RECENT_PAGE_SIZE
            if recent
            else 0
        )
        page = getattr(self, "_commission_recent_page", 0)
        page = max(0, min(page, total_pages - 1)) if total_pages else 0
        self._commission_recent_page = page
        start = page * _COMMISSION_RECENT_PAGE_SIZE
        recent_page = recent[start : start + _COMMISSION_RECENT_PAGE_SIZE]

        html = '<div class="commission-income-recent" style="width: 100% !important; max-width: none !important; display: block !important; box-sizing: border-box;">'
        if recent_page:
            html += f'<div style="height: 1px; background: rgba(128, 128, 128, 0.2); margin: 24px 0;"></div>'
            html += f'<div style="font-size: 0.9rem; font-weight: 500; color: inherit; margin-bottom: 10px;">{t("Gui.Stat.CommissionIncomeRecentTitle")}</div>'
            html += '<div style="font-size: 13px; width: 100%;">'
            for entry in recent_page:
                ts = entry.get("ts", "")
                try:
                    dt = datetime_class.fromisoformat(ts)
                    time_str = dt.strftime("%m-%d %H:%M")
                except Exception:
                    time_str = ts[:16] if ts else "--"
                items = entry.get("items", {})
                item_parts = []
                for raw_name, amount in items.items():
                    if not amount or int(amount) <= 0:
                        continue
                    mapped_name = item_name_lookup.get(raw_name, raw_name)
                    if mapped_name not in tracked_items:
                        continue
                    meta = item_meta.get(mapped_name, {"color": "#888"})
                    icon_path = item_icon_map.get(mapped_name, "")
                    display = item_name_map.get(mapped_name, mapped_name)

                    icon_html = (
                        (
                            f'<div style="width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; background: {meta["color"]}1a; border-radius: 4px; margin-right: 6px; vertical-align: middle;">'
                            f'<img src="{icon_path}" style="width: 16px; height: 16px; object-fit: contain; background: transparent;">'
                            f"</div>"
                        )
                        if icon_path
                        else f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: {meta["color"]}; margin-right: 4px;"></span>'
                    )

                    item_parts.append(
                        f'<span style="display: inline-flex; align-items: center; margin-right: 12px; height: 24px;">'
                        f"{icon_html}"
                        f'<span style="color: inherit;">{display}</span>'
                        f'<span style="opacity: 0.65; margin-left: 2px;">x{int(amount)}</span>'
                        f"</span>"
                    )
                items_str = (
                    "".join(item_parts)
                    if item_parts
                    else '<span style="opacity: 0.6;">--</span>'
                )

                # 查看截图按钮：跟随在记录行内，点击在新标签页单独打开截图
                shots = entry.get("screenshots") or []
                shot_links = ""
                for shot_index, shot in enumerate(shots):
                    label = "查看截图" if shot_index == 0 else f"查看截图{shot_index + 1}"
                    shot_links += (
                        f'<a href="/static/commission_rewards/{escape(shot, quote=True)}" '
                        f'target="_blank" rel="noopener" '
                        f'style="flex-shrink: 0; margin-left: 8px; font-size: 0.7rem; padding: 2px 10px; '
                        f'border: 1px solid rgba(128, 128, 128, 0.35); border-radius: 4px; '
                        f'background: rgba(128, 128, 128, 0.08); color: inherit; text-decoration: none; '
                        f'cursor: pointer;">{label}</a>'
                    )

                html += (
                    f'<div class="commission-income-recent-row" style="display: flex; align-items: center; flex-wrap: wrap; padding: 6px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.1);">'
                    f'<span style="opacity: 0.65; min-width: 80px; font-size: 12px; flex-shrink: 0;">{time_str}</span>'
                    f'<span>{items_str}</span>'
                    f"{shot_links}"
                    f"</div>"
                )
            html += "</div>"

        html += f'<p style="font-size: 0.75rem; opacity: 0.5; margin-top: 10px;">{t("Gui.Stat.CommissionIncomeTotalCommissions", value=summary["total_commissions"])}</p>'
        return html + "</div>"

    def _output_commission_income(
        self, summary_html, table_html, recent_html, period, recent_count
    ):
        with use_scope("commission_income", clear=True):
            put_html(summary_html)

            def on_period_click(selected_period):
                self._commission_income_period = selected_period
                self._commission_recent_page = 0
                self._render_commission_income()

            put_buttons(
                [
                    {
                        "label": t("Gui.Stat.CommissionIncomeDay"),
                        "value": "day",
                        "color": "primary" if period == "day" else "secondary",
                    },
                    {
                        "label": t("Gui.Stat.CommissionIncomeWeek"),
                        "value": "week",
                        "color": "primary" if period == "week" else "secondary",
                    },
                    {
                        "label": t("Gui.Stat.CommissionIncomeMonth"),
                        "value": "month",
                        "color": "primary" if period == "month" else "secondary",
                    },
                ],
                onclick=on_period_click,
                small=True,
                scope="commission_income",
            )
            put_html(table_html, scope="commission_income")
            put_button(
                t("Gui.Stat.Refresh"),
                onclick=self._render_commission_income,
                color="secondary",
                small=True,
                scope="commission_income",
            )
            put_html(recent_html, scope="commission_income")
            if recent_count > _COMMISSION_RECENT_PAGE_SIZE:
                self._output_recent_pagination(recent_count)

    def _output_recent_pagination(self, recent_count):
        """渲染最近委托记录的分页控件。"""
        total_pages = (
            recent_count + _COMMISSION_RECENT_PAGE_SIZE - 1
        ) // _COMMISSION_RECENT_PAGE_SIZE
        page = getattr(self, "_commission_recent_page", 0)
        page = max(0, min(page, total_pages - 1))
        self._commission_recent_page = page

        def on_pagination(value):
            new_page = getattr(self, "_commission_recent_page", 0)
            if value == "prev":
                new_page -= 1
            elif value == "next":
                new_page += 1
            else:
                new_page = int(value)
            new_page = max(0, min(new_page, total_pages - 1))
            self._commission_recent_page = new_page
            self._render_commission_income()

        pagination_buttons = [
            {"label": "上一页", "value": "prev", "color": "secondary"},
        ]
        for index in range(1, min(5, total_pages) + 1):
            pagination_buttons.append(
                {
                    "label": str(index),
                    "value": index - 1,
                    "color": "primary" if (index - 1) == page else "secondary",
                }
            )
        pagination_buttons.append(
            {"label": "下一页", "value": "next", "color": "secondary"}
        )

        put_row(
            [
                put_buttons(
                    pagination_buttons,
                    onclick=on_pagination,
                    small=True,
                ).style("font-size: 0.65rem; gap: 4px;"),
                put_text(f"第 {page + 1} / {total_pages} 页").style(
                    "font-size: 0.65rem; opacity: 0.7; margin-left: 8px;"
                ),
            ],
            scope="commission_income",
        )

    @staticmethod
    def _show_commission_income_no_data():
        with use_scope("commission_income", clear=True):
            put_text(t("Gui.Stat.CommissionIncomeNoData"))
