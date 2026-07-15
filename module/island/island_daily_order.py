from module.island.island import Island
import module.island_daily_order.assets as daily_order_assets
from module.island_daily_order.assets import *
from module.island.assets import ISLAND_BACK, ISLAND_GET, ISLAND_CLICK_SAFE_AREA
from module.base.button import Button
from module.ui.page import page_island, page_island_phone
from module.logger import logger
from module.ocr.ocr import DigitCounter, Duration
from datetime import datetime, timedelta

from module.config.time_source import now as current_time

class IslandDailyOrder(Island):
    """
    每日订单功能。

    流程：
      ① 检测紧急委托 → 刷新时间到则交付，资源不足则 OCR 冷却
      ② 检测右侧订单页面 → 为空/紧急/可交付/驳回
      ③ 检测左侧所有挑战/轻松图标 → 逐个处理
      ④ 退出判断 → 筹备中则等待，否则延后

    Pages:
        in: page_island_phone
        out: page_island_phone
    """

    # 货物格子裁剪坐标（竖向排列，最多3个）
    SLOT_AREA_1 = (905, 255, 950, 300)
    SLOT_AREA_2 = (905, 335, 950, 380)
    SLOT_AREA_3 = (905, 415, 950, 460)
    ITEM_SLOT_AREAS = [SLOT_AREA_1, SLOT_AREA_2, SLOT_AREA_3]

    # OCR 区域
    OCR_URGENT_REMAINING = Button(
        area=(1150, 272, 1197, 292),
        color=(),
        button=(1150, 272, 1197, 292),
        name='OCR_URGENT_REMAINING'
    )
    OCR_COOLDOWN = Button(
        area=(993, 429, 1089, 452),
        color=(),
        button=(993, 429, 1089, 452),
        name='OCR_DAILY_ORDER_COOLDOWN'
    )

    # 左侧页面图标检测区域
    LEFT_PANEL_AREA = (60, 60, 832, 580)

    # 冷却时间 OCR 区域相对于紧急模板匹配左上角的偏移 (x1, y1, x2, y2)
    URGENT_COOLDOWN_OFFSET = (-54, 120, 0, 113)
    DEFAULT_URGENT_REFRESH_TIME = datetime(2020, 1, 1, 0, 0)
    URGENT_TOTAL_COUNT = 15
    FAST_POPUP_CHECK_INTERVAL = 0.5
    REWARD_POPUP_CHECK_INTERVAL = 2
    REWARD_POPUP_CHECK_LIMIT = 5
    DAILY_RUN_HOUR = 3
    URGENT_TEMPLATE_PREFIX = 'TEMPLATE_DAILY_ORDER_URGENT'
    _urgent_template_cache = None

    def run(self):
        logger.hr('Island Daily Order Run', level=1)

        self.ui_ensure(page_island)

        # 导航到岛屿手机页面
        self.ui_goto(page_island_phone, get_ship=False)

        # OCR 本周剩余紧急委托次数（仅在首次检测）
        self.device.screenshot()
        urgent_remaining = self._ocr_urgent_remaining()
        if urgent_remaining is None:
            logger.warning('[岛屿-每日订单] 本周剩余紧急委托次数 OCR 失败，继续保留紧急委托检测')
        elif urgent_remaining == 0:
            next_monday = self._next_weekday(0)
            self.config.IslandDailyOrder_UrgentDetectRefreshTime = next_monday
            logger.info(f'[岛屿-每日订单] 紧急委托次数已用尽，下次检测: {next_monday}')

        # 主流程
        self._first_right_panel_check = True
        self._should_exit_reenter = False
        self.reject_count = self.config.IslandDailyOrder_RejectCount

        self._enter_daily_order()
        self._main_loop()

        self.config.IslandDailyOrder_RejectCount = self.reject_count
        logger.info('[岛屿-每日订单] 每日订单执行完成')

    # ==================== OCR 辅助 ====================

    @staticmethod
    def _area_button(area, name):
        """将临时坐标区域包装为 Button。"""
        return Button(area=area, color=(), button=area, name=name)

    def _ocr_urgent_remaining(self):
        ocr = DigitCounter(
            self.OCR_URGENT_REMAINING,
            letter=(255, 255, 255),
            threshold=200,
            name='urgent_remaining'
        )
        try:
            current, _, total = ocr.ocr(self.device.image)
        except (ValueError, TypeError):
            logger.warning('[岛屿-每日订单] 本周剩余紧急委托次数 OCR 异常')
            return None

        if total != self.URGENT_TOTAL_COUNT:
            logger.warning(f'[岛屿-每日订单] 本周剩余紧急委托次数 OCR 总次数无效: {current}/{total}')
            return None

        logger.info(f'[岛屿-每日订单] 本周剩余紧急委托次数: {current}/{total}')
        return current

    def _ocr_cooldown_seconds(self, area=None):
        """
        OCR 冷却时间（HH:MM:SS），失败返回 None。

        Args:
            area: OCR 区域，None 则使用默认 OCR_COOLDOWN

        Returns:
            int | None: 剩余秒数，失败返回 None
        """
        if area is None:
            button = self.OCR_COOLDOWN
        elif isinstance(area, Button):
            button = area
        else:
            button = self._area_button(area, name='OCR_DAILY_ORDER_COOLDOWN')
        ocr = Duration(
            button,
            letter=(200, 200, 200),
            threshold=200
        )
        try:
            td = ocr.ocr(self.device.image)
            if td:
                return int(td.total_seconds())
        except (ValueError, TypeError):
            pass
        return None

    def _ocr_cooldown_below_urgent(self, match_x, match_y, match_w, match_h):
        """
        在紧急委托模板匹配位置下方偏移区域 OCR 冷却时间。
        失败或结果 < 1 分钟则回退到 8 小时。

        Args:
            match_x, match_y: 模板匹配左上角坐标（全屏）
            match_w, match_h: 模板宽高

        Returns:
            int: 冷却秒数
        """
        ox1, oy1, ox2, oy2 = self.URGENT_COOLDOWN_OFFSET
        ocr_area = (
            match_x + ox1,
            match_y + oy1,
            match_x + match_w + ox2,
            match_y + match_h + oy2,
        )
        seconds = self._ocr_cooldown_seconds(area=ocr_area)
        if seconds is not None and seconds >= 60:
            logger.info(f'[岛屿-每日订单] OCR 冷却时间: {seconds}秒')
            return seconds
        else:
            logger.warning(f'[岛屿-每日订单] OCR 冷却时间{"失败" if seconds is None else f"过短({seconds}秒)"}，回退到 8 小时')
            return 8 * 3600

    def _get_urgent_refresh_time(self):
        """
        读取紧急委托刷新时间，兼容配置系统返回的 datetime 或字符串。

        Returns:
            datetime | None: 有效的未来刷新时间；默认哨兵值、空值或解析失败返回 None。
        """
        value = self.config.IslandDailyOrder_UrgentDetectRefreshTime
        if value in [None, '']:
            return None

        if isinstance(value, datetime):
            refresh_time = value
        elif isinstance(value, str):
            try:
                refresh_time = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    refresh_time = datetime.fromisoformat(value)
                except ValueError:
                    logger.warning(f'[岛屿-每日订单] 紧急刷新时间格式无效: {value}')
                    return None
        else:
            logger.warning(f'[岛屿-每日订单] 紧急刷新时间类型无效: {type(value).__name__}')
            return None

        refresh_time = refresh_time.replace(microsecond=0)
        if refresh_time <= self.DEFAULT_URGENT_REFRESH_TIME:
            return None
        return refresh_time

    # ==================== 模板匹配辅助 ====================

    def _template_appears(self, template, similarity=0.80):
        region = self.image_crop(self.LEFT_PANEL_AREA, copy=False)
        return template.match(region, similarity=similarity)

    def _find_template_matches(self, template, similarity=0.85):
        """返回左侧面板中所有匹配位置（全屏坐标中心点）的列表。"""
        region = self.image_crop(self.LEFT_PANEL_AREA, copy=False)
        matches = template.match_multi(
            region, similarity=similarity, threshold=5,
            name='daily_order_matches'
        )
        results = []
        for m in matches:
            cx = (m.button[0] + m.button[2]) // 2 + self.LEFT_PANEL_AREA[0]
            cy = (m.button[1] + m.button[3]) // 2 + self.LEFT_PANEL_AREA[1]
            results.append((cx, cy))
        return results

    def _click_position(self, x, y):
        """点击全屏坐标 (x, y)。"""
        click_area = (x, y, x, y)
        btn = self._area_button(click_area, name='DAILY_ORDER_TEMP_CLICK')
        self.device.click(btn)
        self.device.sleep(0.5)

    def _is_right_panel_empty(self):
        """检测右侧订单页面是否为空。"""
        return not self.appear(DAILY_ORDER_RIGHT_PANEL_CHECK)

    def _has_reject_button(self):
        """检测右侧当前订单是否有驳回按钮。"""
        return self.appear(DAILY_ORDER_REJECT)

    def _is_preparing(self):
        """检测订单是否正在筹备中。"""
        return self.appear(DAILY_ORDER_PREPARING)

    def _get_urgent_deliver_button(self):
        """获取紧急委托专用交付按钮。"""
        return DAILY_ORDER_URGENT_DELIVER

    def _submit_order(self, button, must_appear=False):
        """
        点击交付后根据资源不足弹窗判断是否交付成功。

        Args:
            button: 交付按钮。
            must_appear: True 时先检测按钮出现再点击，用于紧急委托专用按钮。

        Returns:
            bool | None: True 表示交付成功，False 表示资源不足，None 表示按钮未检测到。
        """
        if button is None:
            logger.warning('[岛屿-每日订单] 未配置交付按钮')
            return None
        if must_appear and not self.appear(button):
            logger.warning(f'[岛屿-每日订单] 未检测到交付按钮: {button}')
            return None
        self.device.click(button)
        self.device.sleep(self.FAST_POPUP_CHECK_INTERVAL)
        self.device.screenshot()
        if self.appear(POPUP_RESOURCE_INSUFFICIENT, offset=30):
            logger.info('[岛屿-每日订单] 订单资源不足')
            self.device.sleep(3)
            return False
        self._handle_order_reward_popups()
        return True

    # ==================== 主循环 ====================

    def _main_loop(self):
        """
        主流程循环，按 ①→②→③→④ 顺序执行。
        每个步骤根据结果决定下一步跳转。
        """
        while 1:
            self.device.screenshot()

            # 处理弹窗
            if self._handle_popups():
                continue

            # ── ① 紧急委托检测 ──
            result = self._step_urgent()
            if result == 'reenter':
                self._reenter()
                continue
            elif result == 'continue':
                continue  # 回到 ① 开头
            elif result == 'next':
                pass  # 进入 ②

            # ── ② 右侧订单页面检测 ──
            result = self._step_right_panel()
            if result == 'reenter':
                self._reenter()
                continue
            elif result == 'next_day':
                self._delay_to_next_daily_run()
                break
            elif result == 'to_step3':
                pass  # 进入 ③
            elif result == 'to_step1':
                continue  # 回到 ①

            # ── ③ 挑战/轻松图标检测 ──
            result = self._step_challenge_easy()
            if result == 'reenter':
                self._reenter()
                continue
            elif result == 'next_day':
                self._delay_to_next_daily_run()
                break
            elif result == 'to_step2':
                continue  # 回到 ②（由 _step_right_panel 处理）
            elif result == 'to_step4':
                pass  # 进入 ④

            # ── ④ 退出判断 ──
            result = self._step_exit()
            if result == 'wait':
                break  # 延时等待
            elif result == 'next_day':
                self._delay_to_next_daily_run()
                break
            elif result == 'normal':
                break

        # 返回岛屿手机页面
        self._back_to_island_phone()

    # ==================== ① 紧急委托检测 ====================

    def _step_urgent(self):
        """
        ① 检测紧急委托（每次进入页面首次执行）。

        Returns:
            str: 'continue' → 回 ①; 'next' → 跳到 ②; 'reenter' → 退出重进
        """
        # 检查刷新时间
        refresh_time = self._get_urgent_refresh_time()
        if refresh_time and current_time() < refresh_time:
            logger.info(f'[岛屿-每日订单] 紧急刷新时间未到 ({refresh_time})，跳到 ②')
            return 'next'

        # 检测紧急图标，模板漏检时使用固定位置按钮兜底。
        urgent_match = self._template_click_urgent()
        if urgent_match:
            logger.info('[岛屿-每日订单] 检测到紧急委托')
        elif self.appear_then_click(DAILY_ORDER_URGENT_SPECIAL_CHECK, interval=2):
            logger.info('[岛屿-每日订单] 通过固定位置检测到紧急委托')
        else:
            logger.info('[岛屿-每日订单] 未检测到紧急图标，跳到 ②')
            return 'next'
        urgent_deliver_button = self._get_urgent_deliver_button()

        self.device.sleep(1)

        # 紧急委托没有驳回按钮，先用右侧按钮状态确认已切到紧急委托页。
        self.device.screenshot()
        if self._has_reject_button():
            logger.warning('[岛屿-每日订单] 选中紧急图标后仍检测到驳回按钮，跳到 ②')
            return 'next'

        # 点击交付（紧急委托有专用交付按钮）
        submit_result = self._submit_order(urgent_deliver_button, must_appear=True)
        if submit_result is None:
            logger.warning('[岛屿-每日订单] 紧急委托交付按钮未检测到，跳到 ②')
            return 'next'
        if not submit_result:
            logger.info('[岛屿-每日订单] 紧急委托资源不足')
            # OCR 冷却时间（从模板匹配位置下方偏移）
            if urgent_match:
                mx, my, mw, mh = urgent_match
                cooldown = self._ocr_cooldown_below_urgent(mx, my, mw, mh)
            else:
                cooldown = 8 * 3600
            refresh = current_time() + timedelta(seconds=cooldown)
            self.config.IslandDailyOrder_UrgentDetectRefreshTime = \
                refresh.replace(microsecond=0)
            logger.info(f'[岛屿-每日订单] 紧急冷却: {cooldown}秒，刷新时间: {refresh}')
            return 'continue'

        # 交付成功
        logger.info('[岛屿-每日订单] 紧急交付成功')

        # 检测右侧是否为空
        self.device.screenshot()
        if self._is_right_panel_empty():
            logger.info('[岛屿-每日订单] 紧急交付后右侧为空，退出重进')
            return 'reenter'

        return 'next'

    # ==================== ② 右侧页面检测 ====================

    def _step_right_panel(self):
        """
        ② 检测右侧订单页面状态。

        Returns:
            str: 'reenter' / 'next_day' / 'to_step3' / 'to_step1'
        """
        self.device.screenshot()

        # 1) 右侧为空
        if self._is_right_panel_empty():
            if self._first_right_panel_check:
                self._first_right_panel_check = False
                logger.info('[岛屿-每日订单] 首次进入右侧为空，延时到下一个 03:00')
                return 'next_day'
            else:
                logger.info('[岛屿-每日订单] 右侧为空，退出重进')
                return 'reenter'

        self._first_right_panel_check = False

        # 2) 没有驳回按钮 → 当前是紧急委托页面
        if not self._has_reject_button():
            logger.info('[岛屿-每日订单] 右侧无驳回按钮（紧急委托页面），跳到 ③')
            return 'to_step3'

        # 3) 命中过滤物品则直接驳回，否则尝试交付。
        if self._check_items_for_reject():
            logger.info('[岛屿-每日订单] 订单命中驳回物品过滤，执行驳回')
        else:
            logger.info('[岛屿-每日订单] 尝试交付订单')
            if self._submit_order(DAILY_ORDER_DELIVER):
                logger.info('[岛屿-每日订单] 订单交付成功')

                # 交付后检测右侧是否为空
                self.device.screenshot()
                if self._is_right_panel_empty():
                    logger.info('[岛屿-每日订单] 交付后右侧为空，退出重进')
                    return 'reenter'
                else:
                    logger.info('[岛屿-每日订单] 交付后右侧非空，退出重进刷新状态')
                    return 'reenter'

            logger.info('[岛屿-每日订单] 订单资源不足，执行驳回')

        self.appear_then_click(DAILY_ORDER_REJECT, interval=2)
        self.device.sleep(self.FAST_POPUP_CHECK_INTERVAL)

        # 检测驳回失败弹窗（当前不可替换）
        self.device.screenshot()
        if self.appear(POPUP_ORDER_CANNOT_REPLACE, offset=30):
            logger.info('[岛屿-每日订单] 驳回失败（当前不可替换），跳到 ③')
            self.device.sleep(3)  # 等待弹窗自动关闭
            return 'to_step3'

        # 驳回成功
        self.reject_count += 1
        logger.info(f'[岛屿-每日订单] 驳回成功，当前驳回次数: {self.reject_count}')
        return 'to_step3'

    # ==================== ③ 挑战/轻松检测 ====================

    def _step_challenge_easy(self):
        """
        ③ 检测左侧所有挑战/轻松图标，逐个点击处理。

        Returns:
            str: 'reenter' / 'next_day' / 'to_step2' / 'to_step4'
        """
        # 收集所有挑战和轻松图标的匹配位置
        all_matches = []
        for template, label in [
            (TEMPLATE_DAILY_ORDER_CHALLENGE, '挑战'),
            (TEMPLATE_DAILY_ORDER_EASY, '轻松'),
        ]:
            positions = self._find_template_matches(template)
            for pos in positions:
                all_matches.append((pos, template, label))

        if not all_matches:
            if self.appear_then_click(DAILY_ORDER_CHALLENGE_EASY_SPECIAL_CHECK, interval=2):
                logger.info('[岛屿-每日订单] 通过固定位置检测到挑战/轻松委托')
                self.device.sleep(1)
                self.device.screenshot()
                if self._is_preparing():
                    logger.info('[岛屿-每日订单] 挑战/轻松委托筹备中，进入退出判断')
                    return 'to_step4'
                elif self._has_reject_button():
                    logger.info('[岛屿-每日订单] 挑战/轻松委托已选中，跳到 ② 尝试交付')
                    return 'to_step2'
                else:
                    logger.warning('[岛屿-每日订单] 挑战/轻松委托状态未知，进入退出判断')
                    return 'to_step4'
            logger.info('[岛屿-每日订单] 没有更多挑战/轻松图标')
            return 'to_step4'

        # 逐个处理
        processed_positions = set()
        for pos, template, label in all_matches:
            pos_key = (pos[0] // 10 * 10, pos[1] // 10 * 10)
            if pos_key in processed_positions:
                continue
            processed_positions.add(pos_key)

            logger.info(f'[岛屿-每日订单] 处理 {label} 图标 (pos={pos_key})')
            self._click_position(pos[0], pos[1])
            self.device.sleep(1)

            # 检测右侧状态
            self.device.screenshot()
            if self._is_preparing():
                logger.info(f'[岛屿-每日订单] {label} 筹备中，继续检测下一个')
                continue
            elif self._has_reject_button():
                logger.info(f'[岛屿-每日订单] {label} 已选中，跳到 ② 尝试交付')
                return 'to_step2'
            else:
                logger.warning(f'[岛屿-每日订单] {label} 状态未知，继续下一个')
                continue

        # 所有图标处理完毕
        logger.info('[岛屿-每日订单] 所有挑战/轻松图标已处理')
        return 'to_step4'

    # ==================== ④ 退出判断 ====================

    def _step_exit(self):
        """
        ④ 退出判断。

        Returns:
            str: 'wait' → OCR 等待; 'next_day' → 下一个 03:00; 'normal' → 正常退出
        """
        self.device.screenshot()

        if self._is_preparing():
            logger.info('[岛屿-每日订单] 右侧有筹备中订单，OCR 等待时间')
            seconds = self._ocr_cooldown_seconds()
            if seconds and seconds > 0:
                target = current_time() + timedelta(seconds=seconds)
                self.config.task_delay(target=target)
                logger.info(f'[岛屿-每日订单] 筹备等待 {seconds}秒')
            else:
                logger.warning('[岛屿-每日订单] OCR 筹备时间失败，改用 1 小时')
                self.config.task_delay(minute=60)
            return 'wait'
        else:
            logger.info('[岛屿-每日订单] 右侧不是筹备中，延时到下一个 03:00')
            return 'next_day'

    # ==================== 辅助方法 ====================

    @classmethod
    def _urgent_template_sort_key(cls, item):
        name, _ = item
        if name == cls.URGENT_TEMPLATE_PREFIX:
            return 0
        suffix = name.removeprefix(cls.URGENT_TEMPLATE_PREFIX + '_')
        return int(suffix) if suffix.isdigit() else 999

    @classmethod
    def _urgent_templates(cls):
        """获取所有紧急委托模板，支持 TEMPLATE_DAILY_ORDER_URGENT_2 等编号扩展。"""
        if cls._urgent_template_cache is not None:
            return cls._urgent_template_cache

        templates = []
        for name, template in vars(daily_order_assets).items():
            if name == cls.URGENT_TEMPLATE_PREFIX:
                templates.append((name, template))
                continue
            if not name.startswith(cls.URGENT_TEMPLATE_PREFIX + '_'):
                continue
            suffix = name.removeprefix(cls.URGENT_TEMPLATE_PREFIX + '_')
            if suffix.isdigit():
                templates.append((name, template))
        cls._urgent_template_cache = tuple(sorted(templates, key=cls._urgent_template_sort_key))
        return cls._urgent_template_cache

    def _template_match_urgent(self, template, similarity=0.80):
        """
        获取紧急模板在左侧面板中的匹配位置及尺寸。

        Returns:
            tuple | None: (match_x, match_y, tw, th) 全屏左上角坐标+宽高，失败返回 None
        """
        region = self.image_crop(self.LEFT_PANEL_AREA, copy=False)
        matches = template.match_multi(
            region, similarity=similarity, threshold=5,
            name='daily_order_urgent_match'
        )
        if not matches:
            return None

        button = matches[0].move(self.LEFT_PANEL_AREA[:2])
        x1, y1, x2, y2 = button.area
        return (x1, y1, x2 - x1, y2 - y1)

    def _template_click_urgent(self, similarity=0.80):
        """点击左侧面板中第一个匹配到的紧急模板，返回匹配位置信息。"""
        for name, template in self._urgent_templates():
            match = self._template_match_urgent(template, similarity=similarity)
            if not match:
                continue
            logger.info(f'[岛屿-每日订单] 紧急委托模板匹配: {name}')
            mx, my, tw, th = match
            self._click_position(mx + tw // 2, my + th // 2)
            return match
        return None

    def _enter_daily_order(self):
        """从岛屿手机页面进入每日订单界面。"""
        logger.info('[岛屿-每日订单] 进入每日订单界面')
        while 1:
            self.device.screenshot()
            if self.appear(DAILY_ORDER_CHECK):
                logger.info('[岛屿-每日订单] 已进入每日订单界面')
                break
            if self.appear_then_click(ISLAND_PHONE_DAILY_ORDER, interval=2):
                continue
            if self._handle_popups():
                continue
            self.device.sleep(0.5)

    def _reenter(self):
        """退出每日订单界面并重新进入。"""
        logger.info('[岛屿-每日订单] 退出重进每日订单界面')
        # 点击返回按钮回到岛屿手机页面
        self._back_to_island_phone()
        # 重新进入
        self._enter_daily_order()
        # 重置首次检测标记
        self._first_right_panel_check = True

    def _back_to_island_phone(self):
        """点击返回按钮回到岛屿手机页面。"""
        logger.info('[岛屿-每日订单] 返回岛屿手机页面')
        while 1:
            self.device.screenshot()
            if self.ui_page_appear(page_island_phone):
                logger.info('[岛屿-每日订单] 已回到岛屿手机页面')
                break
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self._handle_popups():
                continue
            self.device.sleep(0.5)

    def _delay_to_next_daily_run(self):
        """延时到下一个每日运行时间（03:00）。"""
        now = current_time()
        target = now.replace(
            hour=self.DAILY_RUN_HOUR, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        self.config.task_delay(target=target)
        logger.info(f'[岛屿-每日订单] 下次每日订单运行时间: {target}')

    def _handle_popups(self):
        """处理弹窗。"""
        if self.appear(POPUP_RESOURCE_INSUFFICIENT, offset=30):
            logger.info('[岛屿-每日订单] 资源不足弹窗，等待自动关闭')
            self.device.sleep(3)
            return True
        if self.appear(POPUP_ORDER_CANNOT_REPLACE, offset=30):
            logger.info('[岛屿-每日订单] 当前不可替换弹窗，等待自动关闭')
            self.device.sleep(3)
            return True
        if self.appear(DAILY_ORDER_LEVEL_UP):
            logger.info('[岛屿-每日订单] 检测到订单等级升级，点击安全区域关闭')
            self.device.click(ISLAND_CLICK_SAFE_AREA)
            return True
        if self.appear(ISLAND_GET, offset=30):
            self.device.click(ISLAND_CLICK_SAFE_AREA)
            return True
        return False

    def _handle_order_reward_popups(self):
        """提交订单后连续处理获得奖励和订单等级升级弹窗。"""
        handled = False
        for _ in range(self.REWARD_POPUP_CHECK_LIMIT):
            self.device.sleep(self.REWARD_POPUP_CHECK_INTERVAL)
            self.device.screenshot()
            if self.appear(DAILY_ORDER_LEVEL_UP):
                logger.info('[岛屿-每日订单] 检测到订单等级升级，点击安全区域关闭')
                self.device.click(ISLAND_CLICK_SAFE_AREA)
                handled = True
                continue
            if self.appear(ISLAND_GET, offset=30):
                self.device.click(ISLAND_CLICK_SAFE_AREA)
                handled = True
                continue
        return handled

    def _check_items_for_reject(self):
        """
        检测三个货物格子是否包含配置中需要驳回的物品。
        """
        reject_filter = str(self.config.IslandDailyOrder_RejectFilter or '').lower()
        reject_cheese = 'cheese' in reject_filter
        reject_tofu = 'tofu' in reject_filter
        if not reject_cheese and not reject_tofu:
            return False

        self.device.screenshot()
        for slot_index, slot_area in enumerate(self.ITEM_SLOT_AREAS):
            slot_image = self.image_crop(slot_area, copy=False)
            if reject_cheese and \
                    TEMPLATE_CHEESE.match(slot_image, similarity=0.80):
                logger.info(f'[岛屿-每日订单] 格子 {slot_index + 1} 检测到芝士')
                return True
            if reject_tofu and \
                    TEMPLATE_TOFU.match(slot_image, similarity=0.80):
                logger.info(f'[岛屿-每日订单] 格子 {slot_index + 1} 检测到豆腐')
                return True
        return False

    @staticmethod
    def _next_weekday(target_weekday):
        today = current_time()
        days_ahead = target_weekday - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_day = today + timedelta(days=days_ahead)
        return next_day.replace(hour=0, minute=0, second=0, microsecond=0)

    def image_crop(self, area, copy=True):
        from module.base.utils import crop
        return crop(self.device.image, area, copy=copy)
