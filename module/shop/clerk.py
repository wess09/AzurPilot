import re

import cv2

from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter
from module.retire.retirement import Retirement
from module.shop.assets import *
from module.shop.base import ShopBase
from module.shop.shop_select_globals import *
from module.ui.assets import SHOP_BACK_ARROW


class StockCounter(DigitCounter):
    """库存计数器 OCR，用于识别商店选择界面的库存数量。

    预处理将图像转为灰度并反转，后处理修正常见 OCR 错误
    （如 '55' 修正为 '5/5'，'1515' 修正为 '15/15'）。
    """

    def pre_process(self, image):
        """OCR 预处理：转为灰度并反转。

        Args:
            image: 输入图像

        Returns:
            np.array: 反转后的灰度图像
        """
        r, g, b = cv2.split(image)
        image = cv2.max(cv2.max(r, g), b)

        return 255 - image

    def after_process(self, result):
        """OCR 后处理：修正常见识别错误。

        将连续两位数字修正为 'X/Y' 格式（如 '55' -> '5/5'），
        将连续四位数字修正为 'XX/YY' 格式（如 '1515' -> '15/15'）。
        """
        result = super().after_process(result)

        if re.match(r'^\d\d$', result):
            # 55 -> 5/5
            new = f'{result[0]}/{result[1]}'
            logger.info(f'StockCounter result {result} is revised to {new}')
            result = new
        if re.match(r'^\d{4,}$', result):
            # 1515 -> 15/15
            new = f'{result[0:2]}/{result[2:4]}'
            logger.info(f'StockCounter result {result} is revised to {new}')
            result = new

        return result


SHOP_SELECT_PR = [SHOP_SELECT_PR1, SHOP_SELECT_PR2, SHOP_SELECT_PR3]
OCR_SHOP_SELECT_STOCK = StockCounter(SHOP_SELECT_STOCK)

OCR_SHOP_AMOUNT = Digit(SHOP_AMOUNT, letter=(239, 239, 239), name='OCR_SHOP_AMOUNT')


class ShopClerk(ShopBase, Retirement):
    """商店购买处理器基类。

    提供商品选择、数量输入、购买确认等通用逻辑。
    子类通过重写 shop_buy_handle 和 shop_interval_clear 实现差异化处理。
    """

    def shop_get_choice(self, item):
        """获取商品的配置选择项。

        根据商品组（pr/equipment 等）和等级，从配置中读取
        对应的选择值（如 PR 系列编号、装备等级）。

        Args:
            item: 商品对象，包含 group 和 tier 属性

        Returns:
            str: 配置中的选择值

        Raises:
            ScriptError: 配置项不存在时抛出
        """
        group = item.group
        if group == 'pr':
            postfix = None
            for _ in range(3):
                if _:
                    self.device.sleep((0.3, 0.5))
                    self.device.screenshot()

                for idx, btn in enumerate(SHOP_SELECT_PR):
                    if self.appear(btn, offset=(20, 20)):
                        postfix = f'{idx + 1}'
                        break

                if postfix is not None:
                    break
                logger.warning('Failed to detect PR series, '
                               'app may be lagging or frozen')
        else:
            postfix = f'_{item.tier.upper()}'

        ugroup = group.upper()
        # 2025-08-14 新商店 UI：购买 PlateT4 时，新 UI 类名为 XXXShop_250814，
        # 需要截取 "_" 前的类名
        class_name = self.__class__.__name__.split("_")[0]
        try:
            return getattr(self.config, f'{class_name}_{ugroup}{postfix}')
        except Exception:
            logger.critical(f"大叔，连配置文件都找不到吗？没有 \'{class_name}_{ugroup}{postfix}\' 这种东西啦！❤")
            raise

    def shop_get_select(self, item):
        """获取商品对应的选择网格按钮。

        根据商品组和配置选择项，定位到选择界面中对应的按钮位置。

        Args:
            item: 商品对象，包含 group 属性

        Returns:
            Button: 选择界面中的目标按钮

        Raises:
            ScriptError: 商品组不在 SELECT_ITEM_INFO_MAP 中时抛出
        """
        group = item.group
        if group not in SELECT_ITEM_INFO_MAP:
            logger.critical(f"哈？物品组 \'{group}\' 是什么鬼？大叔你是活在哪个次元？❤")
            raise ScriptError

        # 获取商品的配置选择项
        choice = self.shop_get_choice(item)

        # 获取选择界面中对应的按钮
        try:
            item_info = SELECT_ITEM_INFO_MAP[group]
            index = item_info['choices'][choice]
            if group == 'pr':
                for idx, btn in enumerate(SHOP_SELECT_PR):
                    if self.appear(btn, offset=(20, 20)):
                        series_key = f's{idx + 1}'
                        return item_info['grid'][series_key].buttons[index]
            else:
                return item_info['grid'].buttons[index]
        except Exception:
            logger.critical(f"SELECT_ITEM_INFO_MAP 配置出了这么大的错，大叔你是不是偷偷把资源文件卖了换酒喝了？❤")
            raise ScriptError

    def shop_buy_select_execute(self, item):
        """执行选择式购买操作（如装备箱、蓝图等）。

        在选择界面中点击商品、读取库存限制、调整购买数量并确认。
        使用 ui_ensure_index 防止超出库存数量购买。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否成功执行购买
        """
        select = self.shop_get_select(item)

        # 获取库存上限，不同商店可能不同
        timeout = Timer(5, count=10).start()
        skip_first_screenshot = True
        limit = 0
        while 1:
            if timeout.reached():
                break
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            _, _, limit = OCR_SHOP_SELECT_STOCK.ocr(self.device.image)
            if limit:
                break

        if not limit:
            logger.critical(f"噗噗~ 连 {item.name} 的库存都数不明白，大叔你还是回幼儿园重修数学吧❤")
            raise ScriptError

        # 间隔点击直到加减按钮出现
        click_timer = Timer(3, count=6)
        select_offset = (500, 400)
        while 1:
            if click_timer.reached():
                self.device.click(select)
                click_timer.reset()

            self.device.screenshot()
            if self.appear(SELECT_MINUS, offset=select_offset) and self.appear(SELECT_PLUS, offset=select_offset):
                break
            else:
                continue

        # 计算可购买总数（货币 / 单价）
        total = int(self._currency // item.price)
        diff = limit - total
        if diff > 0:
            limit = total

        # 包装 OCR 函数适配 ui_ensure_index，防止库存不足时超买
        def shop_buy_select_ensure_index(image):
            current, remain, _ = OCR_SHOP_SELECT_STOCK.ocr(image)
            if not current:
                group_case = item.group.title() if len(item.group) > 2 else item.group.upper()
                logger.info(f'{group_case}(s) out of stock; exit to prevent overbuying')
                return limit
            return remain

        self.ui_ensure_index(limit, letter=shop_buy_select_ensure_index, prev_button=SELECT_MINUS,
                             next_button=SELECT_PLUS,
                             skip_first_screenshot=True)
        self.device.click(SHOP_BUY_CONFIRM_SELECT)
        return True

    def shop_buy_amount_execute(self, item):
        """执行数量式购买操作（如部件箱、教材等）。

        在数量输入界面中点击最大数量、读取限制值、调整购买数量并确认。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否成功执行购买

        Raises:
            ScriptError: OCR 识别数量为 0 时抛出
        """
        index_offset = (40, 20)

        # 使用船坞 OCR 技巧精确定位数量输入区域
        self.appear(AMOUNT_MINUS, offset=index_offset)
        self.appear(AMOUNT_PLUS, offset=index_offset)
        area = OCR_SHOP_AMOUNT.buttons[0]
        OCR_SHOP_AMOUNT.buttons = [(AMOUNT_MINUS.button[2] + 3, area[1], AMOUNT_PLUS.button[0] - 3, area[3])]

        # 点击最大按钮获取可购买总数，等待图像稳定
        self.appear_then_click(AMOUNT_MAX, offset=(50, 50))
        self.device.sleep((0.3, 0.5))
        timeout = Timer(5, count=10).start()
        limit = 0
        while 1:
            if timeout.reached():
                break
            self.device.screenshot()
            limit = OCR_SHOP_AMOUNT.ocr(self.device.image)
            if limit:
                break

        if not limit:
            logger.critical("OCR_SHOP_AMOUNT 识别出来是 0 诶？难道大叔你已经穷得连底裤都没了吗？❤")
            raise ScriptError

        # 调整购买数量（货币 / 单价）
        total = int(self._currency // item.price)
        diff = limit - total
        if diff > 0:
            limit = total

        self.ui_ensure_index(limit, letter=OCR_SHOP_AMOUNT, prev_button=AMOUNT_MINUS, next_button=AMOUNT_PLUS,
                             skip_first_screenshot=True)
        self.device.click(SHOP_BUY_CONFIRM_AMOUNT)
        return True

    def shop_interval_clear(self):
        """清除购买界面相关按钮的点击间隔。

        子类可重写此方法以清除特定资产的 interval 状态。
        """
        self.interval_clear(SHOP_BACK_ARROW)
        self.interval_clear(SHOP_BUY_CONFIRM)

    def shop_buy_handle(self, item):
        """处理购买界面（子类重写）。

        子类根据自身商店特性重写，处理选择、数量等购买界面。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否检测到购买界面并进行了处理
        """
        return False

    def shop_buy_execute(self, item, skip_first_screenshot=True):
        """执行购买操作的完整状态循环。

        通过状态循环完成从点击商品到购买确认的完整流程。
        处理退役、遮挡、信息栏等意外情况。

        Args:
            item: 待购买的商品对象
            skip_first_screenshot: 是否跳过首次截图
        """
        success = False
        self.shop_interval_clear()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(SHOP_BACK_ARROW, offset=(30, 30), interval=3):
                self.device.click(item)
                continue
            if self.appear_then_click(SHOP_BUY_CONFIRM, offset=(20, 20), interval=3):
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.shop_buy_handle(item):
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.handle_retirement():
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.shop_obstruct_handle():
                self.interval_reset(SHOP_BACK_ARROW)
                success = True
                continue
            if self.info_bar_count():
                self.interval_reset(SHOP_BACK_ARROW)
                success = True
                continue

            # 结束条件
            if success and self.appear(SHOP_BACK_ARROW, offset=(30, 30)):
                break

    def shop_buy(self):
        """执行商店购买主循环。

        获取商品列表、OCR 货币余额，逐个购买直到无可用商品或余额不足。
        最多迭代 12 次防止无限循环。

        Returns:
            bool: 是否成功（True 表示购买完成或余额不足，False 表示余额为 0）
        """
        for _ in range(12):
            logger.hr('Shop buy', level=2)
            # 先获取商品列表，利用固有延迟等待 OCR 货币识别更准确
            items = self.shop_get_items()
            self.shop_currency()
            if self._currency <= 0:
                logger.warning(f'Current funds: {self._currency}, stopped')
                return False

            item = self.shop_get_item_to_buy(items)
            if item is None:
                logger.info('Shop buy finished')
                return True
            else:
                self.shop_buy_execute(item)
                continue

        logger.warning('Too many items to buy, stopped')
        return True
