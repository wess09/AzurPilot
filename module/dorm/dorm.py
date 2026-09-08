"""
后宅（宿舍）任务模块。

自动执行后宅的日常维护操作，包括：
- 收取宿舍中的爱心和金币
- 使用食物喂食舰船（支持长按喂食和多次点击）
- 购买食物并管理食物库存
- 计算下次任务延迟时间

食物喂食支持多种控制后端：minitouch、MaaTouch、uiautomator2、nemu_ipc。
通过 OCR 识别食物数量和饱食度，通过模板匹配识别爱心和金币。
"""
import time
import typing as t

from module.base.button import ButtonGrid
from module.base.decorator import Config, cached_property
from module.base.filter import Filter
from module.base.mask import Mask
from module.base.timer import Timer
from module.base.utils import *
from module.dorm.assets import *
from module.dorm.buy_furniture import BuyFurniture
from module.handler.assets import POPUP_CONFIRM
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter
from module.template.assets import TEMPLATE_DORM_COIN, TEMPLATE_DORM_LOVE
from module.ui.assets import DORM_CHECK
from module.ui.page import page_dorm, page_dormmenu
from module.ui.ui import UI

MASK_DORM = Mask(file='./assets/mask/MASK_DORM.png')
DORM_CAMERA_SWIPE = (300, 250)
DORM_CAMERA_RANDOM = (-20, -20, 20, 20)
OCR_SLOT = DigitCounter(OCR_DORM_SLOT, letter=(107, 89, 82), threshold=128, name='OCR_DORM_SLOT')
OCR_BUY_FOOD_AMOUNT = Digit(OCR_DORM_BUY_FOOD_AMOUNT, letter=(96, 96, 100), threshold=128, name='OCR_DORM_BUY_FOOD_AMOUNT')


class OcrDormFood(DigitCounter):
    """宿舍食物 OCR，识别食物数量格式如 `1000/5800`。"""

    def pre_process(self, image):
        orange = color_similarity_2d(image, color=(239, 158, 49))
        gray = color_similarity_2d(image, color=(99, 97, 99))
        # image = cv2.subtract(255, cv2.max(orange, gray))
        # image = cv2.multiply(image, 2)
        cv2.max(orange, gray, dst=gray)
        cv2.bitwise_not(gray, dst=gray)
        cv2.convertScaleAbs(gray, alpha=2, dst=gray)
        return gray

    def after_process(self, result):
        result = super().after_process(result)

        if '/' not in result:
            for exp in range(40000, 90001, 1000):
                res = re.match(rf'^(\d+){exp}$', result)
                if res:
                    # 10005800 -> 1000/5800
                    new = f'{res.group(1)}/{exp}'
                    logger.info(f'[宿舍-OCR] 食物OCR结果 {result} 修正为 {new}')
                    result = new
                    break

        return result


OCR_FILL = OcrDormFood(OCR_DORM_FILL, name='OCR_DORM_FILL')


class Food:
    """食物数据类，包含单次喂食量和数量。"""

    def __init__(self, feed, amount):
        self.feed = feed
        self.amount = amount

    def __str__(self):
        return f'Food_{self.feed}'

    def __eq__(self, other):
        return str(self) == str(other)


FOOD_FEED_AMOUNT = [1000, 2000, 3000, 5000, 10000, 20000]
FOOD_FILTER = Filter(regex=re.compile(r'(\d+)'), attr=['feed'])


class RewardDorm(UI):
    """
    后宅奖励处理器，负责宿舍的日常维护操作。

    继承自 UI，提供以下功能：
    - 收取宿舍中的爱心和金币（手动点击或快捷收取）
    - 使用食物喂食舰船（支持多种喂食方式）
    - 购买食物并管理食物库存
    - 获取宿舍舰船数量并计算任务延迟

    Attributes:
        _dorm_food (ButtonGrid): 食物按钮网格，6 种食物从左到右排列。
        _dorm_food_ocr (Digit): 食物数量 OCR，识别每种食物的库存。
    """

    def _dorm_receive_click(self):
        """
        点击宿舍中的爱心和金币进行收取。

        Returns:
            int: 收取数量。

        Pages:
            in: page_dorm
            out: page_dorm, with info_bar
        """
        image = MASK_DORM.apply(self.device.image)
        loves = TEMPLATE_DORM_LOVE.match_multi(image, name='DORM_LOVE')
        coins = TEMPLATE_DORM_COIN.match_multi(image, name='DORM_COIN')
        logger.info(f'[宿舍-收取] 爱心: {len(loves)}, 金币: {len(coins)}')
        # 复杂的宿舍背景可能导致误检
        if len(loves) > 6:
            logger.warning('[宿舍-收取] 爱心数量超过6个，限制为6')
            loves = loves[:6]
        if len(coins) > 6:
            logger.warning('[宿舍-收取] 金币数量超过6个，限制为6')
            coins = coins[:6]

        count = 0
        for button in loves:
            count += 1
            # 禁用点击记录检查，因为可能有太多金币或爱心
            self.device.click(button, control_check=False)
            self.device.sleep((0.5, 0.8))
        for button in coins:
            count += 1
            self.device.click(button, control_check=False)
            self.device.sleep((0.5, 0.8))

        return count

    @Config.when(DEVICE_CONTROL_METHOD='minitouch')
    def _dorm_feed_long_tap(self, button, count):
        # 长按喂食，需要 minitouch 支持。
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)
        builder = self.device.minitouch_builder
        builder.down(x, y).commit()
        builder.send()

        while 1:
            builder.move(x, y).commit().wait(10)
            builder.send()
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        builder.up().commit()
        builder.send()

    @Config.when(DEVICE_CONTROL_METHOD='MaaTouch')
    def _dorm_feed_long_tap(self, button, count):
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)
        builder = self.device.maatouch_builder
        builder.down(x, y).commit()
        builder.send()

        while 1:
            builder.move(x, y).commit().wait(10)
            builder.send()
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        builder.up().commit()
        builder.send()

    @Config.when(DEVICE_CONTROL_METHOD='uiautomator2')
    def _dorm_feed_long_tap(self, button, count):
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)
        self.device.u2.touch.down(x, y)

        while 1:
            self.device.u2.touch.move(x, y)
            time.sleep(.01)
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        self.device.u2.touch.up(x, y)

    @Config.when(DEVICE_CONTROL_METHOD='nemu_ipc')
    def _dorm_feed_long_tap(self, button, count):
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)

        while 1:
            self.device.nemu_ipc.down(x, y)
            time.sleep(.01)
            self.device.screenshot()

            if not self._dorm_has_food(button) \
                    or self.handle_info_bar() \
                    or self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break
            if timeout.reached():
                logger.warning('[宿舍-喂食] 喂食等待超时')
                break

        self.device.nemu_ipc.up()

    @Config.when(DEVICE_CONTROL_METHOD=None)
    def _dorm_feed_long_tap(self, button, count):
        logger.warning(f'[宿舍-喂食] 当前控制方式 {self.config.Emulator_ControlMethod} '
                       f'不支持DOWN/UP事件，使用多次点击代替')
        self.device.multi_click(button, count)

    def dorm_view_reset(self):
        """
        通过进入宿舍管理界面再返回来重置宿舍视角。

        Pages:
            in: page_dorm
            out: page_dorm
        """
        logger.info('[宿舍-视角] 重置宿舍视角')
        for _ in self.loop():
            # 结束
            if self.appear(DORM_MANAGE_CHECK, offset=(20, 20)):
                break

            if self.appear_then_click(DORM_MANAGE, offset=(20, 20), interval=3):
                continue
            # 处理所有弹窗
            if self.ui_additional(get_ship=False):
                continue
            if self.appear_then_click(DORM_FURNITURE_CONFIRM, offset=(30, 30), interval=3):
                continue

        for _ in self.loop():
            if self.appear(DORM_MANAGE, offset=(20, 20)):
                break

            if self.appear(DORM_MANAGE_CHECK, offset=(20, 20), interval=3):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                continue

    def dorm_collect(self):
        """
        使用一键收取按钮收取宿舍中所有的金币和爱心。

        Pages:
            in: page_dorm
            out: page_dorm
        """
        logger.hr('后宅收取')

        self.ensure_no_info_bar()

        # 设置计时器，防止 Alas 偶尔未能检测到 info_bar
        timeout = Timer(1.5, count=3).start()

        for _ in self.loop():
            # 处理所有弹窗
            if self.ui_additional(get_ship=False):
                continue

            # 通过快捷收取按钮收取金币和爱心
            if self.appear_then_click(DORM_QUICK_COLLECT, offset=(20, 20), interval=1):
                continue

            # 正常结束
            if self.info_bar_count() > 0:
                break

            # 超时结束
            if timeout.reached():
                logger.warning('[宿舍-收取] 收取超时，可能未检测到信息栏')
                break

    @cached_property
    def _dorm_food(self):
        return ButtonGrid(origin=(395, 410), delta=(129, 0), button_shape=(105, 70), grid_shape=(6, 1), name='FOOD')

    @cached_property
    def _dorm_food_ocr(self):
        grids = self._dorm_food.crop((54, 41, 101, 66), name='FOOD_AMOUNT')
        return Digit(grids.buttons, letter=(255, 255, 255), threshold=128, name='OCR_DORM_FOOD')

    def _dorm_has_food(self, button):
        """
        检测指定食物按钮是否有食物（非空槽位）。

        Args:
            button (Button): 食物按钮。

        Returns:
            bool: 有食物返回 True，空槽位返回 False。
        """
        return np.min(rgb2gray(self.image_crop(button, copy=False))) < 127

    def _dorm_feed_click(self, button, count):
        """
        点击食物按钮进行喂食。

        Args:
            button (Button): 食物按钮。
            count (int): 食物使用次数。

        Pages:
            in: DORM_FEED_CHECK
        """
        logger.info(f'[宿舍-喂食] 喂食 {button} x {count}')
        if count <= 3:
            for _ in range(count):
                self.device.click(button)
                self.device.sleep((0.5, 0.8))
            skip_first_screenshot = False
        else:
            self._dorm_feed_long_tap(button, count)
            skip_first_screenshot = True

        self.popup_interval_clear()
        for _ in self.loop(skip_first=skip_first_screenshot):
            # 结束
            if self.appear(DORM_FEED_CHECK, offset=(20, 20)):
                break
            # 点击
            if self.handle_popup_cancel('DORM_FEED'):
                continue

    def dorm_food_get(self):
        """
        获取当前食物信息和饱食度。

        Returns:
            list[Food]: 食物列表。
            int: 剩余可喂食量。

        Pages:
            in: DORM_FEED_CHECK
        """
        has_food = [self._dorm_has_food(button) for button in self._dorm_food.buttons]
        amount = self._dorm_food_ocr.ocr(self.device.image)
        amount = [a if hf else 0 for a, hf in zip(amount, has_food)]
        food = [Food(feed=f, amount=a) for f, a in zip(FOOD_FEED_AMOUNT, amount)]
        _, fill, total = OCR_FILL.ocr(self.device.image)
        if total == 0:
            fill = -1
        logger.info(f'[宿舍-食物] 食物库存: {[f.amount for f in food]}, 需填充: {fill}')
        return food, fill

    def dorm_feed_once(self):
        """
        执行一次喂食操作。

        Returns:
            bool: 是否执行了喂食。

        Pages:
            in: DORM_FEED_CHECK
        """
        timeout = Timer(1.5, count=3).start()
        food: t.List[Food] = []
        fill: int = 0
        for _ in self.loop():
            # 结束
            if timeout.reached():
                logger.warning('[宿舍-食物] 获取食物信息超时，可能食物为空')
                break

            if self.handle_info_bar():
                continue

            # 获取食物信息
            food, fill = self.dorm_food_get()
            if fill == -1:
                continue
            if sum([f.amount for f in food]) > 0:
                break
        if fill < 0:
            fill = 0

        FOOD_FILTER.load(self.config.Dorm_FeedFilter)
        for selected in FOOD_FILTER.apply(food):
            button = self._dorm_food.buttons[food.index(selected)]
            if selected.amount > 0 and fill > selected.feed:
                count = min(fill // selected.feed, selected.amount)
                self._dorm_feed_click(button=button, count=count)
                return True

        return False

    def dorm_feed(self):
        """
        循环执行喂食直到食物用完或饱食度满。

        Returns:
            int: 执行喂食的次数。

        Pages:
            in: DORM_FEED_CHECK
        """
        logger.hr('后宅喂食')

        for n in range(10):
            if not self.dorm_feed_once():
                logger.info('[宿舍-喂食] 喂食完成')
                return n

        logger.warning('[宿舍-喂食] 喂食次数达到上限')
        return 10

    def dorm_feed_enter(self):
        """
        从宿舍主页进入喂食界面。

        处理可能遇到的管理界面、家具商店等中间状态。

        Pages:
            in: DORM_CHECK
            out: DORM_FEED_CHECK
        """
        self.interval_clear(DORM_CHECK)
        for _ in self.loop(skip_first=False):
            # 结束
            if self.appear(DORM_FEED_CHECK, offset=(20, 20)):
                break

            if self.ui_additional(get_ship=False):
                self.interval_clear(DORM_CHECK)
                continue
            if self.appear(DORM_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_FEED_ENTER)
                continue
            if self.appear(DORM_MANAGE_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                logger.info(f'[宿舍-视角] {DORM_MANAGE_CHECK} -> {DORM_FURNITURE_SHOP_QUIT}')
                continue
            if self.appear(DORM_FURNITURE_SHOP_FIRST, offset=(20, 20), interval=5):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                logger.info(f'[宿舍-视角] {DORM_FURNITURE_SHOP_FIRST} -> {DORM_FURNITURE_SHOP_QUIT}')
                continue
            if self.appear(DORM_FURNITURE_SHOP_FIRST_SELECTED, offset=(20, 20), interval=5):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                logger.info(f'[宿舍-视角] {DORM_FURNITURE_SHOP_FIRST_SELECTED} -> {DORM_FURNITURE_SHOP_QUIT}')
                continue

    def dorm_feed_quit(self):
        """
        从喂食界面返回宿舍主页。

        Pages:
            in: DORM_FEED_CHECK
            out: DORM_CHECK
        """
        self.interval_clear(DORM_FEED_CHECK)
        for _ in self.loop():
            # 结束
            if self.appear(DORM_CHECK):
                break

            if self.appear(DORM_FEED_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_FEED_ENTER)
                continue
            if self.handle_popup_cancel('DORM_FEED'):
                self.interval_clear(DORM_CHECK)
                continue
            if self.ui_additional(get_ship=False):
                self.interval_clear(DORM_CHECK)
                continue

    def dorm_buy_food_enter(self):
        """
        从喂食界面进入购买食物界面。

        Pages:
            in: DORM_FEED_CHECK
            out: DORM_BUY_FOOD_CHECK
        """
        self.interval_clear(DORM_FEED_CHECK)
        for _ in self.loop():
            # 结束
            if self.appear(DORM_BUY_FOOD_CHECK, offset=(20, 20)):
                break

            if self.match_template_color(DORM_FEED_CHECK, offset=(20, 20), interval=5):
                self.device.click(DORM_BUY_FOOD_ENTER)
                continue

    def dorm_buy_food(self, amount):
        """
        设置购买食物的数量。

        Pages:
            in: DORM_BUY_FOOD_CHECK
            out: DORM_BUY_FOOD_CHECK
        """
        logger.hr('后宅购买食物')
        index_offset = (20, 20)
        # 防止 +/- 按钮位置偏移，使用船坞 OCR 技巧准确解析
        self.appear(FOOD_PLUS, offset=index_offset)
        self.appear(FOOD_MINUS, offset=index_offset)

        self.ui_ensure_index(amount, letter=OCR_BUY_FOOD_AMOUNT, prev_button=FOOD_MINUS, next_button=FOOD_PLUS,
                             skip_first_screenshot=True)
        return True

    def dorm_buy_food_confirm(self):
        """
        确认购买食物并返回喂食界面。

        Pages:
            in: DORM_BUY_FOOD_CHECK
            out: DORM_FEED_CHECK
        """
        self.interval_clear(DORM_BUY_FOOD_CONFIRM)
        for _ in self.loop():
            # 结束
            if self.match_template_color(DORM_FEED_CHECK, offset=(20, 20)):
                break

            if self.appear_then_click(DORM_BUY_FOOD_CONFIRM, offset=(20, 20), interval=5):
                continue

    def dorm_food_run(self, amount):
        """
        执行购买食物的完整流程。

        Args:
            amount (int): 购买食物的数量。

        Pages:
            in: 任意页面
            out: page_dorm
        """
        if amount <= 0:
            return

        self.ui_ensure(page_dormmenu)
        self.handle_info_bar()
        self.ui_goto(page_dorm, skip_first_screenshot=True)
        logger.hr('后宅购买食物', level=1)
        self.dorm_feed_enter()
        self.dorm_buy_food_enter()
        self.dorm_buy_food(amount=amount)
        self.dorm_buy_food_confirm()
        self.dorm_feed_quit()

    def dorm_run(self, feed=True, collect=True, buy_furniture=False):
        """
        执行宿舍操作：喂食、收取、购买家具。

        操作顺序：先喂食（处理 DORM_INFO 弹窗避免遮挡），再收取金币和爱心，
        最后购买家具。

        Args:
            feed (bool): 是否执行喂食。
            collect (bool): 是否收取金币和爱心。
            buy_furniture (bool): 是否购买家具。

        Pages:
            in: 任意页面
            out: page_dorm
        """
        if not feed and not collect and not buy_furniture:
            return

        self.ui_ensure(page_dormmenu)
        self.handle_info_bar()
        # 2025.10.17 移除 DORM_RED_DOT 检查，因为宿舍卡片有缓慢的出现动画
        # if not self.appear(DORM_RED_DOT, offset=(30, 30)):
        #     logger.info('Nothing to collect. Dorm collecting skipped.')
        #     collect = False
        #     if not feed and not buy_furniture:
        #         return
        self.ui_goto(page_dorm, skip_first_screenshot=True)

        # 先喂食以处理 DORM_INFO
        # DORM_INFO 可能会遮挡宿舍金币和爱心
        if feed:
            logger.hr('后宅喂食', level=1)
            self.dorm_feed_enter()
            self.dorm_feed()
            self.dorm_feed_quit()

        if collect:
            logger.hr('后宅收取', level=1)
            self.dorm_collect()

        if buy_furniture:
            logger.hr('后宅购买家具', level=1)
            BuyFurniture(self.config, self.device).run()

    def get_dorm_ship_amount(self):
        """
        获取宿舍中的舰船数量。

        Returns:
            int: 宿舍中的舰船数量。

        Pages:
            in: page_dorm
        """
        timeout = Timer(2, count=4).start()
        current = 0
        for _ in self.loop():
            # 处理弹窗
            if self.appear_then_click(DORM_FURNITURE_CONFIRM, offset=(30, 30), interval=3):
                timeout.reset()
                continue
            if self.ui_additional(get_ship=False):
                timeout.reset()
                continue

            current, _, total = OCR_SLOT.ocr(self.device.image)

            if timeout.reached():
                logger.warning('[宿舍-栏位] 获取宿舍栏位超时')
                break
            if total == 0:
                continue
            elif current not in [0, 1, 2, 3, 4, 5, 6]:
                logger.warning(f'[宿舍-栏位] 无效的宿舍栏位数量: {current}')
                continue
            else:
                break

        return current

    def cal_dorm_delay(self, ships):
        """
        计算宿舍任务的延迟时间（分钟）。

        计算公式：(任务延迟) = 20000 / (每 15 秒食物消耗) * 15 / 60

        | 宿舍舰船数 | 每 15 秒食物消耗 | 任务延迟（分钟） |
        | ----------- | ---------------- | ---------------- |
        | 0           | 0                | 278              |
        | 1           | 5                | 1000             |
        | 2           | 9                | 556              |
        | 3           | 12               | 417              |
        | 4           | 14               | 358              |
        | 5           | 16               | 313              |
        | 6           | 18               | 278              |

        Args:
            ships (int): 宿舍中的舰船数量。

        Returns:
            int: 延迟分钟数。

        Pages:
            in: page_dorm
        """
        dict_delay = {
            0: self.config.Scheduler_SuccessInterval,
            1: 1000,
            2: 556,
            3: 417,
            4: 358,
            5: 313,
            6: 278,
        }
        delay = dict_delay.get(ships, self.config.Scheduler_SuccessInterval)
        return delay

    def run(self):
        """
        执行宿舍任务的主入口。

        Pages:
            in: 任意页面
            out: page_dorm
        """
        if not self.config.Dorm_Feed and not self.config.Dorm_Collect \
                and not self.config.BuyFurniture_Enable:
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        self.dorm_run(feed=self.config.Dorm_Feed,
                      collect=self.config.Dorm_Collect,
                      buy_furniture=self.config.BuyFurniture_Enable)

        # Scheduler
        ships = self.get_dorm_ship_amount()
        delay = self.cal_dorm_delay(ships)
        logger.info(f'[宿舍-调度] 宿舍舰船数: {ships}, 任务延迟: {delay}')
        self.config.task_delay(minute=delay)
