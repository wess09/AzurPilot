"""大世界商店模块。

提供碧蓝航线大世界（Operation Siren）商店的自动化购买功能，包括：
- 港口商店（Port Shop）的扫描、过滤与批量购买
- 海域内明石商店（Akashi Shop）的交互与购买
- 购买数量的智能计算（基于货币余额和库存上限）
- 黄币 / 紫币的余额管理与保留量控制
- 购买确认弹窗和数量选择器的处理
- 大世界重置周期下的货币策略调整
- 侵蚀 1 练级模式下的明石行动力购买记录

本模块整合了 PortShop 和 AkashiShop 两个子模块的功能，
通过统一的购买执行接口处理大世界中的所有商店交互。
"""
from module.base.button import Button
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.config.utils import get_os_reset_remain
from module.exception import ScriptError
from module.logger import logger
from module.os.assets import FLEET_CHOOSE
from module.os_shop.akashi_shop import AkashiShop
from module.os_shop.assets import PORT_SUPPLY_CHECK, SHOP_BUY_CONFIRM
from module.os_shop.port_shop import PortShop
from module.os_shop.ui import OS_SHOP_SCROLL
from module.shop.assets import AMOUNT_MAX, AMOUNT_MINUS, AMOUNT_PLUS, SHOP_BUY_CONFIRM_AMOUNT, SHOP_BUY_CONFIRM as OS_SHOP_BUY_CONFIRM, SHOP_CLICK_SAFE_AREA
from module.shop.clerk import OCR_SHOP_AMOUNT


class OSShop(PortShop, AkashiShop):
    """大世界商店购买执行器。

    继承港口商店（PortShop）和明石商店（AkashiShop）的功能，
    提供统一的购买执行接口和货币管理策略。

    主要功能：
    - 单个物品购买执行（含确认弹窗、数量选择、重试机制）
    - 批量物品购买循环
    - 购买数量的智能计算（基于货币余额、库存、保留量）
    - 黄币 / 紫币的可用余额计算（考虑大世界重置周期）
    - 港口商店的完整购买流程（扫描 -> 过滤 -> 购买）
    - 明石商店的购买交互（进入海域商店 -> 购买 -> 返回地图）

    Attributes:
        _shop_yellow_coins (int): 当前黄币余额（由 os_shop_get_coins 设置）。
        _shop_purple_coins (int): 当前紫币余额（由 os_shop_get_coins 设置）。
    """

    def os_shop_buy_execute(self, button, skip_first_screenshot=True) -> bool:
        """执行单个物品的购买操作。

        处理购买确认、数量选择、弹窗确认等交互流程。

        Args:
            button (Button): 待购买的物品按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 购买成功返回 True，失败返回 False。

        Pages:
            in: PORT_SUPPLY_CHECK
        """
        success = False
        from module.statistics.resource_tracking import receipt_totals
        receipts = receipt_totals(self.config)
        button._resource_purchase_quantity = 1
        amount_finish = False
        self.interval_clear([
            PORT_SUPPLY_CHECK, SHOP_BUY_CONFIRM_AMOUNT,
            SHOP_BUY_CONFIRM, OS_SHOP_BUY_CONFIRM, GET_ITEMS_1,
            SHOP_CLICK_SAFE_AREA
        ])
        set_amount_retry = 0

        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_map_get_items(interval=3):
                self.interval_clear(PORT_SUPPLY_CHECK)
                success = True
                continue

            if self.appear_then_click(SHOP_BUY_CONFIRM, offset=(20, 20), interval=3):
                self.interval_reset(SHOP_BUY_CONFIRM)
                continue

            if self.appear_then_click(OS_SHOP_BUY_CONFIRM, offset=(20, 20), interval=3):
                self.interval_reset(OS_SHOP_BUY_CONFIRM)
                continue

            if not amount_finish and self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20)):
                amount_finish = self.shop_buy_amount_handler(button)
                set_amount_retry += 1
                if not amount_finish and set_amount_retry > 3:
                    logger.warning(f'Item {button.name} cant get amount.')
                    self.close_shop_buy_confirm_amount(skip_first_screenshot)
                    break
                continue

            if amount_finish and self.appear_then_click(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
                self.interval_reset(SHOP_BUY_CONFIRM_AMOUNT)
                continue

            if self.handle_popup_confirm('SHOP_BUY'):
                continue

            if not success and self.appear(PORT_SUPPLY_CHECK, offset=(20, 20), interval=5):
                amount_finish = False
                self.device.click(button)
                continue

            # End
            if success and self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                break

        if success:
            from module.statistics.resource_tracking import record_purchase
            record_purchase(self.config, button, button._resource_purchase_quantity, receipts)
        return success

    def os_shop_buy(self, select_func) -> int:
        """批量购买物品。

        循环调用选择函数获取待购买物品，执行购买直到无物品或达到上限。

        Args:
            select_func (callable): 物品选择函数，返回待购买物品或 None。

        Returns:
            int: 成功购买的物品数量。

        Pages:
            in: PORT_SUPPLY_CHECK
        """
        count = 0
        for _ in range(12):
            button = select_func()
            if button is None:
                logger.info('[大世界商店] 大世界商店+购买完成')
                return count
            else:
                if not self.os_shop_buy_execute(button):
                    logger.warning(f'[大世界商店] 物品 {button.name} 无法购买，停止本轮选择')
                    continue
                try:
                    if not getattr(self, 'is_running_cl1_leveling', False) \
                            and not getattr(self, '_meow_searching_active', False):
                        logger.debug('[大世界商店] 非侵蚀1/耄耋相接，跳过明石行动力购买记录')
                    else:
                        name = str(getattr(button, 'name', '') or '')
                        name_l = name.lower()
                        if 'actionpoint' in name_l or ('action' in name_l and 'point' in name_l):
                            import re

                            m = re.search(r"(\d+)", name)
                            base = int(m.group(1)) if m else 0
                            amount = int(getattr(button, 'amount', 1) or 1)
                            bought_ap = base * amount

                            instance_name = getattr(self.config, 'config_name', 'default')
                            try:
                                from module.statistics.cl1_database import db as cl1_db

                                if getattr(self, 'is_running_cl1_leveling', False):
                                    cl1_db.add_akashi_ap_entry(
                                        instance=instance_name,
                                        amount=int(bought_ap),
                                        base=int(base),
                                        count=int(amount),
                                        source='akashi'
                                    )
                                    logger.info('[大世界商店] 已记录明石行动力购买数据到数据库')
                                else:
                                    from module.statistics.opsi_runtime import meow_hazard_level_from_runtime

                                    hazard_level = meow_hazard_level_from_runtime(self)
                                    cl1_db.add_meow_akashi_ap(
                                        instance=instance_name,
                                        hazard_level=hazard_level,
                                        amount=int(bought_ap),
                                    )
                                    logger.info('[大世界商店] 已记录耄耋相接明石行动力购买数据到数据库')
                            except Exception:
                                logger.exception('[大世界商店] 保存明石行动力购买数据失败')
                except Exception:
                    logger.exception('[大世界商店] 记录明石购买数据时发生异常')

                count += 1
                continue

        logger.warning('[大世界商店] 待购买物品过多，停止购买')
        return count

    def close_shop_buy_confirm_amount(self, skip_first_screenshot=True):
        """关闭购买数量确认界面。

        通过点击安全区域关闭数量选择弹窗。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Pages:
            in: SHOP_BUY_CONFIRM_AMOUNT
        """
        self.interval_clear([PORT_SUPPLY_CHECK, SHOP_BUY_CONFIRM_AMOUNT])
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                self.interval_clear(SHOP_BUY_CONFIRM_AMOUNT)
                break

            if self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
                self.device.click(SHOP_CLICK_SAFE_AREA)

    def shop_buy_amount_handler(self, item, skip_first_screenshot=True):
        """处理购买数量选择。

        根据金币数量和物品库存计算最优购买数量，
        通过加减按钮调整到目标数量。

        Args:
            item (OSShopItem): 待购买的物品。
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 数量设置成功返回 True，失败返回 False。

        Raises:
            ScriptError: OCR 识别购买上限失败时抛出。
        """
        limit = -1
        retry = Timer(0, count=3)
        retry.start()
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            limit = OCR_SHOP_AMOUNT.ocr(self.device.image)

            if limit == 0:
                logger.warning('OCR_SHOP_AMOUNT resulted 0, retrying')
                self.close_shop_buy_confirm_amount()
                return False

            if limit > 0:
                break

            if retry.reached():
                logger.critical('OCR_SHOP_AMOUNT resulted error; '
                                'asset may be compromised')
                raise ScriptError
        retry.reset()


        currency = self.get_currency_coins(item)
        count = min(int(currency // item.price), item.count)

        if count <= 0:
            return False
        if getattr(self, '_opsi_action_point_purchase', False):
            self.ui_ensure_index(count, letter=OCR_SHOP_AMOUNT, prev_button=AMOUNT_MINUS,
                                 next_button=AMOUNT_PLUS, skip_first_screenshot=True)
            item._resource_purchase_quantity = count
            return True

        if count == 1:
            item._resource_purchase_quantity = 1
            return True

        coins = self.get_coins_no_limit(item)
        total_count = min(int(coins // item.price), item.count)

        set_to_max = False
        # Avg count of all items(no PurpleCoins) is 8.9, so use 10.
        if count <= 10:
            if count - 1 > total_count - count:
                set_to_max = True
            limit = count
        elif total_count - count <= 10:
            set_to_max = True
            limit = count
        elif count >= total_count >> 1:
            set_to_max = True
            limit = total_count - 10
        else:
            limit = 10

        self.interval_clear(AMOUNT_MAX)
        while set_to_max:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(AMOUNT_MAX, offset=(50, 50), interval=3):
                continue

            if OCR_SHOP_AMOUNT.ocr(self.device.image) > 1:
                break

        self.ui_ensure_index(limit, letter=OCR_SHOP_AMOUNT, prev_button=AMOUNT_MINUS, next_button=AMOUNT_PLUS,
                             skip_first_screenshot=True)
        item._resource_purchase_quantity = limit
        return True

    def handle_port_supply_buy(self) -> bool:
        """处理港口商店购买。

        扫描所有商店页面，过滤可购买物品，按顺序执行购买。

        Returns:
            bool: 成功购买或无可购买物品返回 True，金币不足返回 False。

        Pages:
            in: PORT_SUPPLY_CHECK
        """
        self.os_shop_get_coins()
        items = self.scan_all()
        if not len(items):
            logger.warning('大世界商店+为空')
            if not getattr(self, '_opsi_action_point_purchase', False):
                self.config.cross_set("OpsiShop.Storage.Storage.BoughtAllYellowCoinItems", True)
            return False
        items = self.items_filter_in_os_shop(items)
        if not len(items):
            logger.warning('大世界商店+没有可购买物品')
            if not getattr(self, '_opsi_action_point_purchase', False):
                self.config.cross_set("OpsiShop.Storage.Storage.BoughtAllYellowCoinItems", True)
            return False
        if getattr(self, '_opsi_action_point_purchase', False):
            pass  # 行动力专购不代表普通黄币商品已买完。
        elif all(item.cost == 'PurpleCoins' for item in items):
            logger.info('港口商店黄币商品已全部购买')
            self.config.cross_set("OpsiShop.Storage.Storage.BoughtAllYellowCoinItems", True)
        else:
            logger.info('港口商店仍有黄币商品可购买')
            self.config.cross_set("OpsiShop.Storage.Storage.BoughtAllYellowCoinItems", False)
        skip_get_coins = True
        items.reverse()
        count = 0
        while len(items):
            logger.hr('大世界商店+购买', level=2)
            item = items.pop()
            if not skip_get_coins:
                self.os_shop_get_coins()
            if item.price > self.get_currency_coins(item):
                logger.info(f'货币不足，无法购买物品 {item.name}，跳过')
                if self.is_coins_both_not_enough():
                    logger.info('货币不足，无法购买任何物品，停止购买')
                    break
                continue
            logger.info(f'购买物品 {item.name}，商店 {item.shop_index + 1}，位置 {item.scroll_pos:.2f}')
            self.os_shop_side_navbar_ensure(upper=item.shop_index + 1)
            OS_SHOP_SCROLL.set(item.scroll_pos, main=self, skip_first_screenshot=False)
            _item = self.os_shop_get_items_to_buy(name=item.name, price=item.price)
            if _item is None:
                logger.warning(f'商店 {item.shop_index + 1} 的位置 {item.scroll_pos:.2f} 未找到物品 {item.name}，跳过')
                continue
            if not self.check_item_count(_item):
                logger.warning(f'物品 {_item.name} 数量识别错误，跳过')
                continue
            if self.os_shop_buy_execute(_item):
                logger.info(f'已购买物品 {_item.name}')
                skip_get_coins = False
                count += 1
            else:
                logger.warning(f'物品 {_item.name} 无法购买，跳过')
            self.device.click_record.clear()
        logger.info(f'港口商店已购买 {count} 个物品' if count else '港口商店未购买任何物品')
        return True

    @staticmethod
    def _event_safe_click_button(grid):
        """将点击限制在地图安全范围内，避免格子下沿落入固定操作栏。"""
        x1, y1, x2, y2 = grid.button
        area = (max(239, x1), max(128, y1), min(993, x2), min(628, y2))
        if area[2] - area[0] < 6 or area[3] - area[1] < 6:
            return None
        return Button(area=area, color=(), button=area, name=f'MAP_EVENT_{grid}')

    def _recover_event_page(self):
        """只处理正向识别到的误入页面；操作后由父循环获取新截图。"""
        for check, leave in (
            ('is_in_globe', 'os_globe_goto_map'),
            ('is_in_storage', 'storage_quit'),
            ('is_in_os_mission', 'os_mission_quit'),
            ('is_in_map_order', 'order_quit'),
        ):
            if hasattr(self, check) and getattr(self, check)():
                logger.info(f'[大世界-事件] 误入页面 {check}，返回地图后重新定位')
                getattr(self, leave)()
                return True
        if self.is_in_map() and hasattr(self, 'fleet_selector') and self.fleet_selector.bar_opened():
            return self.appear_then_click(FLEET_CHOOSE, offset=(20, 20), interval=2)
        return False

    def handle_akashi_supply_buy(self, grid) -> bool:
        """处理明石商店购买。

        点击明石所在的网格进入商店，执行购买后返回地图。

        Args:
            grid (Button): 明石所在的网格位置。

        Returns:
            bool: 是否确认进入商店、完成购买流程并返回地图。

        Pages:
            in: is_in_map 或 PORT_SUPPLY_CHECK
            out: 成功为 is_in_map；入口失败时保留当前画面，交由调用方恢复。
        """
        remember = getattr(self, '_remember_pending_event', None)
        if remember is not None:
            remember('is_akashi', grid)
        locate = getattr(self, '_event_global_location', None)
        target = locate(grid) if locate is not None else None
        no_progress = Timer(12).start()
        click_timer = Timer(2)
        clicks = 0
        page_recoveries = 0
        camera_budget = [2]
        for _ in self.loop():
            if self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                break
            if no_progress.reached():
                logger.warning(f'[大世界-明石] 入口无进展，已点击 {clicks}/3 次')
                return False
            if self.handle_story_skip():
                no_progress.reset()
                continue
            if self._recover_event_page():
                page_recoveries += 1
                if page_recoveries > 4:
                    logger.warning('[大世界-明石] 入口反复误入其他页面，交回地图恢复')
                    return False
                continue
            # 下拉菜单的关闭按钮有冷却，等待期间不能穿过菜单继续点格子。
            if hasattr(self, 'fleet_selector') and self.fleet_selector.bar_opened():
                continue
            if self.is_in_map() and clicks < 3 and click_timer.reached():
                if target is not None:
                    button = self._prepare_event_click(target, camera_budget=camera_budget)
                else:
                    button = self._event_safe_click_button(grid)
                # 定位期间的新截图可能已经确认进入商店，不能再盲点原目标。
                if self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                    break
                if hasattr(self, 'fleet_selector') and self.fleet_selector.bar_opened():
                    continue
                if button is None:
                    logger.warning('[大世界-明石] 无可用安全点击区域，交回地图恢复')
                    return False
                if no_progress.reached():
                    return False
                self.device.click(button)
                clicks += 1
                click_timer.reset()
        self.os_shop_buy(select_func=self.os_shop_get_item_to_buy_in_akashi)
        self.ui_back(appear_button=PORT_SUPPLY_CHECK, check_button=self.is_in_map, skip_first_screenshot=True)
        if not self.is_in_map():
            return False
        finish = getattr(self, '_finish_pending_event', None)
        if finish is not None:
            finish('is_akashi')
        return True

    def get_currency_coins(self, item):
        """获取可用于购买的货币数量。

        根据大世界重置剩余时间决定是否扣除保留数量。

        Args:
            item (OSShopItem): 待购买的物品。

        Returns:
            int: 可用货币数量。
        """
        if getattr(self, '_opsi_action_point_purchase', False):
            # 用户明确要求一次买完行动力，专购时允许使用原本为练级保留的货币。
            return self.get_coins_no_limit(item)
        if item.cost == 'YellowCoins':
            if get_os_reset_remain() == 0:
                return self._shop_yellow_coins - 100
            else:
                return self._shop_yellow_coins - self.yellow_coins_preserve

        elif item.cost == 'PurpleCoins':
            if get_os_reset_remain() == 0:
                return self._shop_purple_coins
            else:
                return self._shop_purple_coins - self.config.OS_NORMAL_PURPLE_COINS_PRESERVE

    def get_coins_no_limit(self, item):
        """获取不限制的货币数量（不扣除保留量）。

        Args:
            item (OSShopItem): 待购买的物品。

        Returns:
            int: 货币总量。
        """
        if item.cost == 'YellowCoins':
            return self._shop_yellow_coins
        elif item.cost == 'PurpleCoins':
            return self._shop_purple_coins

    def is_coins_both_not_enough(self):
        """检查黄币和紫币是否都不足。

        Returns:
            bool: 两种货币都不足返回 True，否则返回 False。
        """
        if get_os_reset_remain() == 0:
            return False
        else:
            yellow = self._shop_yellow_coins < self._shop_purple_coins
            purple = self._shop_purple_coins < self.config.OS_NORMAL_PURPLE_COINS_PRESERVE
            return yellow and purple
