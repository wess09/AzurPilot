import re
from datetime import datetime, timedelta

from module.base.button import Button
from module.base.timer import Timer
from module.island.island import Island
from module.island.assets import (
    ADD_TEN_A,
    ADD_TEN_B,
    ADD_TEN_C,
    AIR_DROP_RUN_AWAY,
    CANT_ACCESS,
    ISLAND_ACCESS_MAP,
    ISLAND_BACK,
    ISLAND_SHOP_CONFIRM,
    ISLAND_JUMP,
)
from module.island_pearl_sell.assets import *
from module.logger import logger
from module.ocr.ocr import Digit, Ocr


class IslandPearlSell(Island):
    """
    每周珍珠采购与售卖。

    Pages:
        in: 任意页面
        out: 岛屿主页面或岛屿手机页面
    """

    WEEKLY_TRADE_WEEKDAY = 1
    WEEKLY_TRADE_HOUR = 1
    WEEKLY_TRADE_MINUTE = 0
    DAILY_REFRESH_HOUR = 3
    DAILY_REFRESH_MINUTE = 0
    PRICE_RETRY = 3
    TRADE_COUNT_RETRY = 4
    TRADE_COUNT_MAX_CLICKS = 25
    BUY_MAX_ATTEMPTS = 2
    RANK_FIXED_SWIPE_COUNT = 10
    RANK_FIXED_SWIPE_DISTANCE = 450
    RANK_FIXED_SWIPE_AREA = (785, 210, 918, 529)
    RANK_TAB_WAIT = 3
    RANK_VISIT_SEARCH_AREA = (1030, 204, 1105, 534)
    RANK_VISIT_PRICE_OFFSET = (-192, 4, -220, -2)
    RANK_VISIT_SIMILARITY = 0.85
    RANK_VISIT_MATCH_THRESHOLD = 5
    PEARL_BUY_PRICE_RATE = 1.1
    PHASE_DONE = "done"
    PHASE_SKIPPED = "skipped"
    PHASE_DELAYED = "delayed"

    def run(self):
        logger.hr("Island Pearl Sell Run", level=1)
        now = datetime.now().replace(microsecond=0)

        pearl_trade_time = self._get_next_pearl_trade_time(now=now)

        # 判断当前触发类型
        trade_due = self._trade_due(now=now, next_time=pearl_trade_time)
        refresh_due = False if trade_due else self._refresh_due(now=now)
        logger.attr("SchedulerNextRun", self.config.Scheduler_NextRun)
        logger.attr("PearlTradeTime", pearl_trade_time)
        logger.attr("PearlTradeDue", trade_due)
        logger.attr("PearlRefreshDue", refresh_due)

        if not trade_due and not refresh_due:
            target = self._next_run(now=now)
            logger.info(f"未到珍珠任务触发时间，下次运行: {target}")
            self.config.task_delay(target=target)
            self.config.save()
            return

        # 采购售卖时间已到，执行完整周循环
        if trade_due:
            buy_status = self.run_buy_phase()
            if buy_status == self.PHASE_DONE:
                logger.info("采购流程完成，继续执行本周珍珠售卖")
            else:
                logger.info("采购流程跳过或延迟，继续执行本周珍珠售卖")

            sell_status = self.run_sell_phase()
            if sell_status == self.PHASE_DELAYED:
                self.config.save()
                return

            next_trade = self._next_trade_run(
                now=now, base=self._nearest_future_schedule(now=now)
            )
            next_run = self._delay_to_next_trade(next_trade, now=now)
            if sell_status == self.PHASE_DONE:
                logger.info(f"售卖完成，下次珍珠任务时间: {next_run}")
            else:
                logger.info(f"当前无可售珍珠，下次珍珠任务时间: {next_run}")
            self.config.save()
            return

        # 每日价格刷新
        if refresh_due:
            self.run_price_refresh()
            next_run = self._next_run(now=now)
            self.config.task_delay(target=next_run)
            logger.info(f"珍珠价格刷新完成，下次任务时间: {next_run}")
            self.config.save()
            return

    # ==================== 采购 / 售卖阶段 ====================

    def run_buy_phase(self):
        """执行采购阶段。"""
        logger.hr("Pearl buy phase", level=2)
        self._purchase_quota_exhausted = False

        # 检查购买延时——如果还没到购买时间则跳过采购，让售卖正常执行
        if not self._buy_next_run_due():
            logger.info("采购延时未到，跳过采购")
            return self.PHASE_SKIPPED

        for attempt in range(1, self.BUY_MAX_ATTEMPTS + 1):
            status, retry_reason = self.run_buy_phase_once()
            if retry_reason and attempt < self.BUY_MAX_ATTEMPTS:
                logger.warning(
                    f"{retry_reason}，重新执行采购流程 "
                    f"({attempt + 1}/{self.BUY_MAX_ATTEMPTS})"
                )
                continue
            if retry_reason:
                self._delay_buy_to_next_day_1am(retry_reason)
            return status
        return self.PHASE_SKIPPED

    def run_buy_phase_once(self):
        """执行一次采购流程，返回阶段状态和是否需要重试。"""
        buy_price_limit = int(self.config.IslandPearlSell_BuyPrice)

        if not self._enter_home_pearl_shop("assembly"):
            return self.PHASE_SKIPPED, "未进入本岛珍珠商店"
        home_price = self.ocr_pearl_price(kind="sell")
        if home_price is None:
            self._delay_buy_to_next_day_1am("本岛珍珠价格 OCR 失败")
            self.back_to_pearl_shop_or_map()
            return self.PHASE_SKIPPED, None

        in_friend_island = False
        if home_price > buy_price_limit:
            logger.info(
                f"本岛价格 {home_price} 高于采购价 {buy_price_limit}，查找好友低价"
            )
            self._rank_visit_target_selected = False
            if not self.visit_friend_by_rank(mode="buy", threshold=buy_price_limit):
                self.back_to_pearl_shop_or_map()
                if self._rank_visit_target_selected:
                    return self.PHASE_SKIPPED, "未进入好友岛"
                self._delay_buy_to_next_day_1am("好友排名未找到低于采购价的目标")
                return self.PHASE_SKIPPED, None
            in_friend_island = True
        else:
            logger.info(f"本岛价格命中采购价 {home_price}")

        if not self._goto_pearl_shop_at("port"):
            if in_friend_island:
                self.exit_friend_island()
            return self.PHASE_SKIPPED, "未进入港口珍珠采购页面"
        raw_price = self.ocr_pearl_price(kind="buy")
        if raw_price is None:
            self._delay_buy_to_next_day_1am("港口采购价格 OCR 失败")
            self.back_to_pearl_shop_or_map()
            if in_friend_island:
                self.exit_friend_island()
            return self.PHASE_SKIPPED, None

        buy_price = raw_price / self.PEARL_BUY_PRICE_RATE
        logger.info(f"港口采购侧价格: {raw_price}，折算售卖价: {buy_price:.1f}")
        if buy_price > buy_price_limit:
            self._delay_buy_to_next_day_1am(
                f"港口采购价格 {buy_price:.1f} 高于配置 {buy_price_limit}"
            )
            self.back_to_pearl_shop_or_map()
            if in_friend_island:
                self.exit_friend_island()
            return self.PHASE_SKIPPED, None

        purchasable = self.ocr_weekly_purchase_count()
        if purchasable is None:
            logger.warning("本周可采购数量 OCR 失败，仅推迟到下一天")
            self.back_to_pearl_shop_or_map()
            if in_friend_island:
                self.exit_friend_island()
            self._delay_buy_to_next_day_1am("本周可采购数量 OCR 失败")
            return self.PHASE_SKIPPED, None
        if purchasable <= 0:
            logger.info(f"本周可采购数量为 {purchasable}，跳过采购")
            self._purchase_quota_exhausted = True
            self.config.IslandPearlSell_BuyNextRun = self._nearest_future_schedule()
            self.back_to_pearl_shop_or_map()
            if in_friend_island:
                self.exit_friend_island()
            return self.PHASE_SKIPPED, None

        if not self.trade_pearl(action="buy", count=purchasable):
            if in_friend_island:
                self.back_to_pearl_shop_or_map()
                self.exit_friend_island()
            else:
                self.back_to_pearl_shop_or_map()
            self._delay_buy_to_next_day_1am("珍珠采购未完成")
            return self.PHASE_SKIPPED, None
        self.back_to_pearl_shop_or_map()
        if in_friend_island:
            self.exit_friend_island()
        self.config.IslandPearlSell_BuyNextRun = self._nearest_future_schedule()
        logger.info("采购完成")
        return self.PHASE_DONE, None

    def run_sell_phase(self):
        """执行售卖阶段。"""
        logger.hr("Pearl sell phase", level=2)
        sell_price_limit = int(self.config.IslandPearlSell_SellPrice)

        if not self._enter_home_pearl_shop("assembly"):
            self._delay_to_next_day_1am("进入本岛珍珠商店失败")
            return self.PHASE_DELAYED
        current_pearl = self.ocr_current_pearl_count()
        if current_pearl <= 0:
            logger.info(f"当前珍珠数量为 {current_pearl}，跳过售卖")
            self.back_to_pearl_shop_or_map()
            if self._purchase_quota_exhausted:
                logger.info("本周采购配额已用尽且无珍珠可售，直接等待下周")
                return self.PHASE_SKIPPED
            self._delay_to_next_day_1am("当前珍珠数量为 0")
            return self.PHASE_DELAYED

        sell_price = self.ocr_pearl_price(kind="sell")
        if sell_price is None:
            self.back_to_pearl_shop_or_map()
            self._delay_to_next_day_1am("珍珠售卖价格 OCR 失败")
            return self.PHASE_DELAYED

        in_friend_island = False
        if sell_price < sell_price_limit:
            logger.info(
                f"本岛价格 {sell_price} 低于售卖价 {sell_price_limit}，查找好友高价"
            )
            if not self.visit_friend_by_rank(mode="sell", threshold=sell_price_limit):
                self.back_to_pearl_shop_or_map()
                self._delay_to_next_day_1am("好友排名未找到高于售卖价的目标")
                return self.PHASE_DELAYED
            in_friend_island = True
            if not self._goto_pearl_shop_at("assembly", use_map=False):
                self.exit_friend_island()
                self._delay_to_next_day_1am("进入好友岛珍珠商店失败")
                return self.PHASE_DELAYED
            current_pearl = self.ocr_current_pearl_count()
            if current_pearl <= 0:
                logger.info(f"好友岛当前珍珠数量为 {current_pearl}，跳过售卖")
                self.back_to_pearl_shop_or_map()
                self.exit_friend_island()
                if self._purchase_quota_exhausted:
                    logger.info("本周采购配额已用尽且无珍珠可售，直接等待下周")
                    return self.PHASE_SKIPPED
                self._delay_to_next_day_1am("好友岛珍珠数量为 0")
                return self.PHASE_DELAYED
        else:
            logger.info(f"本岛价格满足售卖要求: {sell_price}")

        if not self.trade_pearl(action="sell", count=current_pearl):
            if in_friend_island:
                self.back_to_pearl_shop_or_map()
                self.exit_friend_island()
            else:
                self.back_to_pearl_shop_or_map()
            self._delay_to_next_day_1am("珍珠售卖未完成")
            return self.PHASE_DELAYED
        self.back_to_pearl_shop_or_map()
        if in_friend_island:
            self.exit_friend_island()
        logger.info("售卖完成")
        return self.PHASE_DONE

    # ==================== 地图与路线 ====================

    def _enter_home_pearl_shop(self, destination):
        """从本岛进入指定地点的珍珠商店。"""
        return self._goto_pearl_shop_at(destination)

    def _goto_pearl_shop_at(self, destination, use_map=True):
        """前往地图目的地并移动到珍珠商店 NPC 身旁。"""
        if use_map:
            self.island_map_goto(destination)
        if destination == "assembly":
            self.move_to_assembly_role_a()
        elif destination == "port":
            self.move_to_port_role_b()
        else:
            raise ValueError(f"未知珍珠商店地点: {destination}")
        enter_button = self.pearl_shop_enter_button(destination)
        if not self.enter_pearl_shop(enter_button):
            return False
        return True

    def move_to_assembly_role_a(self):
        self.island_up(2500)
        self.island_right(1700)
        self.island_down(1700)
        self.island_right(500)

    def move_to_port_role_b(self):
        self.island_left(2500)
        self.device.click(ISLAND_JUMP)
        self.island_left(3000)
        self.island_down(1000)

    @staticmethod
    def pearl_shop_enter_button(destination):
        if destination == "assembly":
            return ISLAND_PEARL_SHOP_SELL_ENTER
        if destination == "port":
            return ISLAND_PEARL_SHOP_BUY_ENTER
        raise ValueError(f"未知珍珠商店入口地点: {destination}")

    def enter_pearl_shop(self, enter_button):
        """进入珍珠商店。"""
        logger.info("进入珍珠商店")
        for _ in self.loop(timeout=15):
            if self.appear(ISLAND_PEARL_SHOP_CHECK, offset=(20, 20)):
                return True
            if self.appear_then_click(enter_button, offset=(20, 20), interval=2):
                continue
            if self.ui_additional():
                continue
        logger.warning("进入珍珠商店超时")
        return False

    def back_to_pearl_shop_or_map(self):
        """从购买/售卖弹窗或珍珠商店返回到上级页面。"""
        logger.info("退出珍珠交易界面")
        for _ in self.loop(timeout=10):
            if not self.appear(ISLAND_PEARL_SHOP_CHECK, offset=(20, 20)):
                return True
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self.ui_additional():
                continue
        return False

    def exit_friend_island(self):
        """退出好友岛屿。"""
        logger.info("退出好友岛屿")
        for _ in self.loop(timeout=20):
            if self.appear_then_click(AIR_DROP_RUN_AWAY, offset=(20, 20), interval=2):
                continue
            if self.appear(ISLAND_ACCESS_MAP, offset=(20, 20)):
                return True
            if self.ui_additional():
                continue
        logger.warning("退出好友岛屿超时")
        return False

    # ==================== 好友排名 ====================

    def visit_friend_by_rank(self, mode, threshold):
        """
        从珍珠商店好友排名中选择目标并拜访。

        Args:
            mode: buy 表示找低价，sell 表示找高价。
            threshold: 价格阈值。

        Returns:
            bool: 成功进入好友岛屿返回 True。
        """
        if not self.switch_to_friend_rank_tab():
            return False
        if mode == "buy":
            self.swipe_friend_rank_to_bottom()

        target = self.find_rank_visit_target(mode=mode, threshold=threshold)
        if target is None:
            return False

        self._rank_visit_target_selected = True
        logger.info(f"选择好友珍珠价格 {target['price']}")
        return self.click_rank_visit(target["visit_button"])

    def switch_to_friend_rank_tab(self):
        """切换到好友排名页签。"""
        logger.info("切换到好友排名页签")
        for _ in self.loop(timeout=10):
            if self.appear_then_click(ISLAND_PEARL_FRIEND_RANK_TAB, interval=2):
                self.wait_friend_rank_loaded()
                return True
            if self.ui_additional():
                continue
        logger.warning("切换好友排名页签超时")
        return False

    def wait_friend_rank_loaded(self):
        """切换好友排名后等待网络数据拉取。"""
        logger.info(f"等待好友排名数据加载 {self.RANK_TAB_WAIT}s")
        wait = Timer(self.RANK_TAB_WAIT).start()
        for _ in self.loop(timeout=self.RANK_TAB_WAIT + 1, skip_first=False):
            if wait.reached():
                return True
            if self.ui_additional():
                wait.reset().start()
                continue
        return True

    def swipe_friend_rank_to_bottom(self):
        """采购阶段固定滑动好友排名到底部附近。"""
        logger.info(
            f"固定滑动好友排名 {self.RANK_FIXED_SWIPE_COUNT} 次，"
            f"单次距离 {self.RANK_FIXED_SWIPE_DISTANCE}px"
        )
        for _ in range(self.RANK_FIXED_SWIPE_COUNT):
            self.device.screenshot()
            self.device.swipe_vector(
                vector=(0, -self.RANK_FIXED_SWIPE_DISTANCE),
                box=self.RANK_FIXED_SWIPE_AREA,
                name="PearlRankSwipe",
            )
            self.device.click_record_clear()
        return True

    def find_rank_visit_target(self, mode, threshold):
        """通过拜访按钮模板匹配查找满足价格条件的好友。"""
        candidates = self.find_rank_visit_candidates()
        if not candidates:
            logger.info("当前好友排名区域未识别到拜访按钮")
            return None

        valid = []
        for item in candidates:
            price = item["price"]
            if mode == "buy" and price <= threshold:
                valid.append(item)
            elif mode == "sell" and price >= threshold:
                valid.append(item)

        if not valid:
            logger.info("当前好友排名区域没有满足条件的价格")
            return None
        if mode == "buy":
            return min(valid, key=lambda item: item["price"])
        return max(valid, key=lambda item: item["price"])

    def find_rank_visit_candidates(self):
        """
        在固定区域内匹配拜访按钮，并按固定偏移 OCR 对应珍珠价格。

        价格区域以拜访按钮区域为基准偏移，后续实测只需要调整
        RANK_VISIT_SEARCH_AREA 和 RANK_VISIT_PRICE_OFFSET。
        """
        self.device.screenshot()
        region_image = self.image_crop(self.RANK_VISIT_SEARCH_AREA, copy=False)
        visit_buttons = TEMPLATE_ISLAND_PEARL_RANK_VISIT.match_multi(
            region_image,
            similarity=self.RANK_VISIT_SIMILARITY,
            threshold=self.RANK_VISIT_MATCH_THRESHOLD,
            name="pearl_rank_visit",
        )
        visit_buttons.sort(key=lambda button: button.area[1])

        candidates = []
        for index, local_button in enumerate(visit_buttons, start=1):
            visit_button = self.offset_rank_visit_button(local_button)
            price_button = self.rank_price_button_from_visit(visit_button, index=index)
            price = self._ocr_digit(price_button, name="pearl_rank_price")
            if price:
                logger.info(f"好友排名拜访按钮 {index} 对应珍珠价格: {price}")
                candidates.append(
                    {
                        "visit_button": visit_button,
                        "price": price,
                    }
                )
            else:
                logger.warning(f"好友排名拜访按钮 {index} 对应价格 OCR 无效: {price}")
        return candidates

    def offset_rank_visit_button(self, button):
        """将固定搜索区域内的局部拜访按钮转换为全屏按钮。"""
        sx, sy, _, _ = self.RANK_VISIT_SEARCH_AREA
        x1, y1, x2, y2 = button.area
        area = (x1 + sx, y1 + sy, x2 + sx, y2 + sy)
        return self._area_button(area, "ISLAND_PEARL_RANK_VISIT_MATCH")

    def rank_price_button_from_visit(self, visit_button, index):
        """按拜访按钮固定偏移计算价格 OCR 区域。"""
        x1, y1, x2, y2 = visit_button.area
        dx1, dy1, dx2, dy2 = self.RANK_VISIT_PRICE_OFFSET
        area = self._normalize_area((x1 + dx1, y1 + dy1, x2 + dx2, y2 + dy2))
        return self._area_button(
            area, f"OCR_ISLAND_PEARL_RANK_PRICE_FROM_VISIT_{index}"
        )

    def click_rank_visit(self, visit_button):
        """点击好友排名拜访按钮并等待进入好友岛屿。"""
        click_timer = Timer(3).start()
        self.device.click(visit_button)
        for _ in self.loop(timeout=30, skip_first=False):
            if self.appear(ISLAND_ACCESS_MAP, offset=(20, 20)):
                return True
            if self.appear(CANT_ACCESS, offset=(20, 20)):
                logger.info("好友不可访问")
                return False
            if click_timer.reached():
                self.device.click(visit_button)
                click_timer.reset()
            if self.ui_additional():
                continue
        logger.warning("拜访好友超时")
        return False

    # ==================== OCR ====================

    def ocr_pearl_price(self, kind):
        """OCR 珍珠价格，kind=sell/buy 控制合法范围。"""
        valid_range = (200, 1000) if kind == "sell" else (220, 1100)
        for _ in range(self.PRICE_RETRY):
            self.device.screenshot()
            price = self._ocr_digit(OCR_ISLAND_PEARL_PRICE, name="pearl_price")
            if valid_range[0] <= price <= valid_range[1]:
                logger.info(f"珍珠价格: {price}")
                return price
            logger.warning(f"珍珠价格 OCR 无效: {price}")
        return None

    def ocr_weekly_purchase_count(self):
        """OCR 本周可采购数量，识别“本周可采购数量xxx/200”中的 xxx。"""
        self.device.screenshot()
        text = self._ocr_text(
            OCR_ISLAND_PEARL_WEEKLY_PURCHASE, name="pearl_weekly_purchase"
        )
        result = re.search(r"(\d+)\s*/\s*\d+", text)
        if result:
            count = int(result.group(1))
            logger.info(f"本周可采购数量: {count}/200")
            return count
        logger.warning(f"本周可采购数量 OCR 无效: {text}")
        return None

    def ocr_current_pearl_count(self):
        """OCR 当前持有珍珠数量。"""
        self.device.screenshot()
        count = self._ocr_digit(
            OCR_ISLAND_PEARL_CURRENT_COUNT, name="pearl_current_count"
        )
        logger.info(f"当前珍珠数量: {count}")
        return count

    def ocr_trade_count(self):
        """OCR 购买/售卖弹窗中间数量。"""
        return self._ocr_digit(OCR_ISLAND_PEARL_TRADE_COUNT, name="pearl_trade_count")

    def _ocr_digit(self, button, name):
        ocr = Digit(
            button, lang="cnocr", letter=(255, 255, 255), threshold=128, name=name
        )
        try:
            return int(ocr.ocr(self.device.image))
        except (ValueError, TypeError):
            return 0

    def _ocr_text(self, button, name):
        ocr = Ocr(
            button, lang="cnocr", letter=(255, 255, 255), threshold=128, name=name
        )
        try:
            return str(ocr.ocr(self.device.image))
        except (ValueError, TypeError):
            return ""

    # ==================== 交易数量与确认 ====================

    def trade_pearl(self, action, count):
        """执行购买或售卖。"""
        if count <= 0:
            logger.info(f"珍珠{self._action_name(action)}数量为 0，跳过")
            return False

        logger.info(f"开始珍珠{self._action_name(action)}: {count}")
        for _ in self.loop(timeout=10):
            if self.appear_then_click(ISLAND_PEARL_TRADE, offset=(20, 20), interval=2):
                break
            if self.ui_additional():
                continue
        else:
            logger.warning(f"打开珍珠{self._action_name(action)}弹窗超时")
            return False

        self.add_ten_until_trade_count(count)
        if not self.confirm_trade():
            return False
        return True

    def add_ten_until_trade_count(self, target):
        """
        只使用 +10 调整数量。

        OCR 到目标即停止；如果点过头或多次 OCR 不变化，直接进入确认。
        """
        target = int(target)
        last_count = -1
        stable_count = 0
        for _ in range(self.TRADE_COUNT_MAX_CLICKS):
            self.device.screenshot()
            current = self.ocr_trade_count()
            logger.info(f"珍珠交易数量: {current}/{target}")
            if current >= target:
                return current
            if current == last_count:
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= self.TRADE_COUNT_RETRY:
                logger.warning("交易数量 OCR 多次未变化，直接确认")
                return current
            last_count = current

            for button in (ADD_TEN_A, ADD_TEN_B, ADD_TEN_C):
                self.device.click(button)
        logger.warning("交易数量 +10 超出最大点击次数，直接确认")
        return last_count

    def confirm_trade(self):
        """确认购买/售卖。"""
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop(timeout=15):
            if self.appear_then_click(ISLAND_SHOP_CONFIRM, offset=(20, 20), interval=2):
                confirm_timer.reset()
                continue
            if self.appear(ISLAND_PEARL_SHOP_CHECK, offset=(20, 20)):
                if confirm_timer.reached():
                    return True
            else:
                confirm_timer.reset()
            if self.ui_additional():
                confirm_timer.reset()
                continue
        logger.warning("确认珍珠交易超时")
        return False

    @staticmethod
    def _action_name(action):
        return "采购" if action == "buy" else "售卖"

    # ==================== 价格刷新 ====================

    def run_price_refresh(self):
        """每日 03:00 进入珍珠售卖商店后立即退出，刷新价格显示。"""
        logger.hr("Pearl price refresh", level=2)
        if not self._enter_home_pearl_shop("assembly"):
            logger.warning("价格刷新：进入珍珠商店失败")
            return False
        logger.info("价格刷新：已进入珍珠商店")
        self.back_to_pearl_shop_or_map()
        logger.info("价格刷新完成")
        return True

    # ==================== 时间与延时 ====================

    def _trade_due(self, now=None, next_time=None):
        """检查是否到了每周采购售卖的执行时间。"""
        now = now or datetime.now().replace(microsecond=0)
        next_time = next_time or self._get_next_pearl_trade_time(now=now)
        if now >= next_time:
            return True
        return False

    def _refresh_due(self, now=None):
        """检查是否到了每日价格刷新时间。"""
        if not self.config.IslandPearlSell_DailyPriceRefresh:
            return False
        now = now or datetime.now().replace(microsecond=0)
        today_refresh = now.replace(
            hour=self.DAILY_REFRESH_HOUR,
            minute=self.DAILY_REFRESH_MINUTE,
            second=0,
            microsecond=0,
        )
        if now < today_refresh:
            return False
        # 仅在未到周循环时间时才做价格刷新
        next_trade = self._get_next_pearl_trade_time(now=now)
        return now < next_trade

    def _get_next_pearl_trade_time(self, now=None):
        value = self.config.IslandPearlSell_NextPearlTradeTime
        if value in [None, ""]:
            return now or datetime.now().replace(microsecond=0)
        return value

    def _get_buy_next_run(self):
        value = self.config.IslandPearlSell_BuyNextRun
        if value in [None, ""]:
            return None
        return value

    def _next_trade_run(self, now=None, base=None):
        """计算下一次真正采购售卖时间，不包含每日价格刷新。"""
        now = now or datetime.now().replace(microsecond=0)
        candidates = [base or self._get_next_pearl_trade_time(now=now)]

        buy_next_run = self._get_buy_next_run()
        if buy_next_run and buy_next_run > now:
            candidates.append(buy_next_run)

        return min(candidates)

    def _this_week_schedule(self, now=None):
        now = now or datetime.now().replace(microsecond=0)
        monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return monday + timedelta(
            days=self.WEEKLY_TRADE_WEEKDAY,
            hours=self.WEEKLY_TRADE_HOUR,
            minutes=self.WEEKLY_TRADE_MINUTE,
        )

    def _nearest_future_schedule(self, now=None):
        now = now or datetime.now().replace(microsecond=0)
        target = self._this_week_schedule(now=now)
        if target <= now:
            target += timedelta(days=7)
        return target

    def _next_daily_refresh(self, now=None):
        """计算下一次每日价格刷新时间（今天的 03:00 或明天的 03:00）。"""
        now = now or datetime.now().replace(microsecond=0)
        today_refresh = now.replace(
            hour=self.DAILY_REFRESH_HOUR,
            minute=self.DAILY_REFRESH_MINUTE,
            second=0,
            microsecond=0,
        )
        if now < today_refresh:
            return today_refresh
        return today_refresh + timedelta(days=1)

    def _next_run(self, now=None):
        """计算珍珠任务下一次运行时间。综合周循环、采购延时和每日刷新。"""
        now = now or datetime.now().replace(microsecond=0)
        candidates = [self._next_trade_run(now=now)]

        # 每日价格刷新
        if self.config.IslandPearlSell_DailyPriceRefresh:
            candidates.append(self._next_daily_refresh(now=now))

        return min(candidates)

    def _delay_to_next_trade(self, target, now=None):
        """同步真正采购售卖时间，并按每日刷新设置计算任务调度时间。"""
        self.config.IslandPearlSell_NextPearlTradeTime = target
        next_run = self._next_run(now=now)
        self.config.task_delay(target=next_run)
        return next_run

    @staticmethod
    def next_day_1am(now=None):
        now = now or datetime.now().replace(microsecond=0)
        return (now + timedelta(days=1)).replace(
            hour=1, minute=0, second=0, microsecond=0
        )

    def _delay_to_next_day_1am(self, reason):
        target = self.next_day_1am()
        logger.info(f"{reason}，延迟到 {target}")
        self._delay_to_next_trade(target)

    def _delay_buy_to_next_day_1am(self, reason):
        """设置采购延时到次日凌晨 1 点，仅影响采购不干扰售卖。"""
        target = self.next_day_1am()
        logger.info(f"{reason}，采购延迟到 {target}")
        self.config.IslandPearlSell_BuyNextRun = target
        if target < self._get_next_pearl_trade_time():
            self.config.IslandPearlSell_NextPearlTradeTime = target

    def _buy_next_run_due(self):
        """检查是否到了允许采购的时间。"""
        value = self.config.IslandPearlSell_BuyNextRun
        if value in [None, ""]:
            return True
        now = datetime.now().replace(microsecond=0)
        return now >= value

    @staticmethod
    def _area_button(area, name):
        return Button(area=area, color=(), button=area, name=name)

    @staticmethod
    def _normalize_area(area):
        x1, y1, x2, y2 = area
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
