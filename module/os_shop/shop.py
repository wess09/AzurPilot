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
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.config.utils import get_os_reset_remain
from module.exception import ScriptError
from module.logger import logger
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

    # 本次战役是否已处理过明石商店（避免强制移动等后续环节重复进入商店）
    _akashi_handled = False

    def os_shop_buy_execute(self, button, skip_first_screenshot=True) -> bool:
        """执行单个物品的购买操作。

        处理购买确认、数量选择、弹窗确认等交互流程。

        Args:
            button: 待购买的物品按钮。
            skip_first_screenshot: 是否跳过首次截图。

        Returns:
            bool: 购买成功返回 True，失败返回 False。

        Pages:
            in: PORT_SUPPLY_CHECK
        """
        success = False
        amount_finish = False
        self.interval_clear([
            PORT_SUPPLY_CHECK, SHOP_BUY_CONFIRM_AMOUNT,
            SHOP_BUY_CONFIRM, OS_SHOP_BUY_CONFIRM, GET_ITEMS_1,
            SHOP_CLICK_SAFE_AREA
        ])
        set_amount_retry = 0
        # 购买重试计数器，防止代币不足时无限重试点击商品和确认按钮
        buy_retry = 0
        buy_retry_limit = 3

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
                    logger.warning(f'[大世界商店] 物品 {button.name} 无法识别购买数量')
                    self.close_shop_buy_confirm_amount(skip_first_screenshot)
                    break
                continue

            if amount_finish and self.appear_then_click(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
                self.interval_reset(SHOP_BUY_CONFIRM_AMOUNT)
                continue

            if self.handle_popup_confirm('SHOP_BUY'):
                continue

            if not success and self.appear(PORT_SUPPLY_CHECK, offset=(20, 20), interval=5):
                buy_retry += 1
                if buy_retry > buy_retry_limit:
                    logger.warning(f'[大世界商店] 物品 {button.name} 达到购买重试上限，可能货币不足')
                    break
                amount_finish = False
                self.device.click(button)
                continue

            # 结束条件
            if success and self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                break

        return success

    def os_shop_buy(self, select_func) -> int:
        """批量购买物品。

        循环调用选择函数获取待购买物品，执行购买直到无物品或达到上限。

        Args:
            select_func: 物品选择函数，返回待购买物品或 None。

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
                self.os_shop_buy_execute(button)
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
            skip_first_screenshot: 是否跳过首次截图。

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
            item: 待购买的物品。
            skip_first_screenshot: 是否跳过首次截图。

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
                logger.warning('[大世界商店] OCR_SHOP_AMOUNT 识别为 0，正在重试')
                self.close_shop_buy_confirm_amount()
                return False

            if limit > 0:
                break

            if retry.reached():
                logger.critical('[大世界商店+] OCR_SHOP_AMOUNT 识别结果错误，请检查资源文件')
                raise ScriptError
        retry.reset()


        currency = self.get_currency_coins(item)
        count = min(int(currency // item.price), item.count)

        if count == 1:
            return True

        coins = self.get_coins_no_limit(item)
        total_count = min(int(coins // item.price), item.count)

        set_to_max = False
        # 所有物品平均数量（不含紫币）约为 8.9，因此使用 10 作为阈值
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
        # amount_max_stall: 记录AMOUNT_MAX点击后数量未变化的次数，防止按钮无效时死循环
        amount_max_stall = 0
        amount_max_stall_limit = 5
        while set_to_max:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(AMOUNT_MAX, offset=(50, 50), interval=3):
                continue

            current_amount = OCR_SHOP_AMOUNT.ocr(self.device.image)
            if current_amount > 1:
                break

            # AMOUNT_MAX点击后数量仍为1，说明按钮可能被游戏禁用（如商品只能逐个购买）
            amount_max_stall += 1
            if amount_max_stall >= amount_max_stall_limit:
                logger.info(f'[大世界商店] AMOUNT_MAX 点击 {amount_max_stall} 次后数量仍为 {current_amount}，改用 AMOUNT_PLUS')
                break

        # 仅在已点击AMOUNT_MAX且数量成功增加时，才能读取游戏端实际允许的最大数量
        if set_to_max:
            game_max = OCR_SHOP_AMOUNT.ocr(self.device.image)
            if game_max > 1 and limit > game_max:
                logger.info(f'计算购买上限 {limit} 超过游戏上限 {game_max}，使用游戏上限')
                limit = game_max

        self.ui_ensure_index(limit, letter=OCR_SHOP_AMOUNT, prev_button=AMOUNT_MINUS, next_button=AMOUNT_PLUS,
                             skip_first_screenshot=True)
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
            self.config.cross_set("OpsiShop.Storage.Storage.BoughtAllYellowCoinItems", True)
            return False
        items = self.items_filter_in_os_shop(items)
        if not len(items):
            logger.warning('大世界商店+没有可购买物品')
            self.config.cross_set("OpsiShop.Storage.Storage.BoughtAllYellowCoinItems", True)
            return False
        if all(item.cost == 'PurpleCoins' for item in items):
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

    def handle_akashi_supply_buy(self, grid):
        """处理明石商店购买。

        点击明石所在的网格进入商店，执行购买后返回地图。

        Args:
            grid: 明石所在的网格位置。

        Pages:
            in: is_in_map
            out: is_in_map
        """
        if self._akashi_handled:
            logger.info("[大世界-明石] 本次战役已处理过明石，跳过重复进入商店")
            # 若明石商店已经弹出，关闭它，避免移动等待流程重复检测到商店而卡住
            if self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                self.ui_back(appear_button=PORT_SUPPLY_CHECK, check_button=self.is_in_map,
                             skip_first_screenshot=True)
            return

        self.ui_click(grid, appear_button=self.is_in_map, check_button=PORT_SUPPLY_CHECK,
                      additional=self.handle_story_skip, skip_first_screenshot=True)
        self.os_shop_buy(select_func=self.os_shop_get_item_to_buy_in_akashi)
        self.ui_back(appear_button=PORT_SUPPLY_CHECK, check_button=self.is_in_map, skip_first_screenshot=True)
        self._akashi_handled = True

    def get_currency_coins(self, item):
        """获取可用于购买的货币数量。

        根据大世界重置剩余时间决定是否扣除保留数量。

        Args:
            item: 待购买的物品。

        Returns:
            int: 可用货币数量。
        """
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
            item: 待购买的物品。

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
