"""
勋章商店处理器。

通过模板匹配定位勋章图标，动态计算商品网格布局，
识别并过滤勋章商店中的商品，按配置购买优先级执行购买。
使用自适应滚动条实现商品列表翻页。
"""

import cv2
import numpy as np
from scipy import signal

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.decorator import cached_property, del_cached_property
from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.logger import logger
from module.map_detection.utils import Points
from module.ocr.ocr import Digit, DigitYuv, Ocr
from module.shop.assets import *
from module.shop.base import ShopItemGrid_250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus
from module.ui.scroll import Scroll


class ShopScroll(Scroll):
    def match_color(self, main):
        background_transparency = 0.2
        button_transparency = 0.5
        delta_x = 3
        area = (
            self.area[0] - delta_x,
            self.area[1],
            self.area[2] + delta_x,
            self.area[3]
        )
        image = main.image_crop(area, copy=False).astype(np.float32)
        baseline_color = np.mean(image[:, [0, -1], :], axis=1)
        masked_color = image[:, image.shape[1] // 2, :]
        background_mask = background_transparency * np.array(self.color) + (1 - background_transparency) * baseline_color
        button_mask = button_transparency * np.array(self.color) + (1 - button_transparency) * baseline_color
        err_background = np.sum((masked_color - background_mask) ** 2, axis=1)
        err_button = np.sum((masked_color - button_mask) ** 2, axis=1)
        mask = err_button < err_background
        self.length = np.sum(mask)
        return mask


MEDAL_SHOP_SCROLL_250814 = ShopScroll(
    MEDAL_SHOP_SCROLL_AREA_250814.button,
    color=(44, 48, 56),
    name="MEDAL_SHOP_SCROLL_250814"
)
MEDAL_SHOP_SCROLL_250814.drag_threshold = 0.1
# A little bit larger than 0.1 to handle bottom
MEDAL_SHOP_SCROLL_250814.edge_threshold = 0.12


class ShopPriceOcr(DigitYuv):
    def after_process(self, result):
        """OCR 后处理，修正 '00' 为 '100'（改造图纸场景）。"""
        result = Ocr.after_process(self, result)
        # 改造图纸场景下 '100' 被误识别为 '00'
        if result == '00':
            result = '100'
        return Digit.after_process(self, result)


PRICE_OCR = ShopPriceOcr([], letter=(255, 223, 57), threshold=32, name='Price_ocr')
if server.server == 'jp':
    PRICE_OCR_250814 = Digit([], lang='cnocr', letter=(235, 235, 255), threshold=128, name='Price_ocr')
else:
    PRICE_OCR_250814 = Digit([], letter=(255, 255, 255), threshold=128, name='Price_ocr')
TEMPLATE_MEDAL_ICON_3 = Template('./assets/shop/cost/Medal_3.png')


class MedalShop2_250814(ShopClerk, ShopStatus):
    @cached_property
    def shop_filter(self):
        """获取勋章商店过滤器。

        Returns:
            str: 过滤器字符串
        """
        return self.config.MedalShop2_Filter.strip()

    # New UI in 2025-08-14
    def _get_medals(self):
        """检测截图中的勋章图标位置。

        通过模板匹配在商店区域查找勋章图标，
        返回图标左上角的坐标数组。

        Returns:
            np.array: [[x1, y1], [x2, y2]]，勋章图标左上角坐标
        """
        area = (265, 317, 999, 635)
        # 复制图像以便后续绘制
        image = self.image_crop(area, copy=True)
        medals = TEMPLATE_MEDAL_ICON_3.match_multi(image, similarity=0.5, threshold=5)
        medals = Points([(0., m.area[1]) for m in medals]).group(threshold=5)
        logger.attr('勋章图标数', len(medals))
        return medals

    def wait_until_medal_appear(self, skip_first_screenshot=True):
        """等待勋章商店页面加载完成。

        进入勋章商店后，商品列表加载需要时间，
        此方法等待任意勋章图标出现。

        Args:
            skip_first_screenshot: 是否跳过首次截图
        """
        timeout = Timer(1, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            medals = self._get_medals()

            if timeout.reached():
                break
            if len(medals):
                break

    @cached_property
    def shop_grid(self):
        """获取勋章商店商品网格。"""
        return self.shop_medal_grid()

    def shop_medal_grid(self):
        """根据勋章图标位置计算商店网格。

        通过检测到的勋章图标数量和位置动态计算商品网格的
        原点、间距和行数，适配不同服务器布局。

        Returns:
            ButtonGrid: 商店商品网格
        """
        medals = self._get_medals()
        count = len(medals)
        if count == 0:
            logger.warning('未找到勋章图标，假设商品列表在顶部')
            origin_y = 228
            delta_y = 223
            row = 2
        elif count == 1:
            y_list = medals[:, 1]
            # +317, 裁剪区域顶部偏移 (_get_medals)
            # -126, 从勋章图标顶部到商品顶部的偏移
            origin_y = y_list[0] + 317 - 126
            delta_y = 223
            row = 1
        elif count == 2:
            y_list = medals[:, 1]
            y1, y2 = y_list[0], y_list[1]
            origin_y = min(y1, y2) + 317 - 126
            delta_y = abs(y1 - y2)
            row = 2
        else:
            logger.warning(f'意外的勋章图标匹配结果: {[m for m in medals]}')
            origin_y = 228
            delta_y = 223
            row = 2

        # 构建 ButtonGrid
        shop_grid = ButtonGrid(
            origin=(265, origin_y), delta=(169, delta_y), button_shape=(64, 64), grid_shape=(5, row), name='SHOP_GRID')
        return shop_grid

    shop_template_folder = './assets/shop/medal'

    @cached_property
    def shop_medal_items(self):
        """加载勋章商店商品模板和配置。

        Returns:
            ShopItemGrid_250814: 商店商品网格对象
        """
        shop_grid = self.shop_grid
        shop_medal_items = ShopItemGrid_250814(
            shop_grid,
            templates={},
            amount_area=(60, 74, 96, 95),
            cost_area=(-12, 115, 60, 155),
            price_area=(14, 122, 85, 149),
        )
        shop_medal_items.load_template_folder(self.shop_template_folder)
        shop_medal_items.load_cost_template_folder('./assets/shop/cost')
        # 降低阈值以稳定匹配 PR/DR 改造蓝图
        shop_medal_items.similarity = 0.85
        shop_medal_items.cost_similarity = 0.5
        shop_medal_items.price_ocr = PRICE_OCR_250814
        return shop_medal_items

    def shop_items(self) -> ShopItemGrid_250814:
        """获取商店商品网格的统一接口。

        所有商店共享相同的属性名。重写以添加类型提示，
        适配 run() 中的 get_soldout_count 方法。

        Returns:
            ShopItemGrid_250814: 商店商品网格
        """
        return self.shop_medal_items

    def shop_currency(self):
        """OCR 识别勋章商店货币数量。

        通过状态检测获取当前勋章余额并记录日志。

        Returns:
            int: 勋章数量
        """
        self._currency = self.status_get_medal()
        logger.info(f'[商店-勋章] 勋章: {self._currency}')
        return self._currency

    def shop_has_loaded(self, items):
        """检查商品列表是否已加载完成。

        若存在默认价格 5000 的商品，说明商店尚未加载完毕，
        此时不能安全购买。

        Args:
            items: 商品列表

        Returns:
            bool: 商品列表是否已加载完成
        """
        for item in items:
            if int(item.price) == 5000:
                return False
        return True

    def shop_interval_clear(self):
        """清除购买界面相关按钮的点击间隔。

        重置购买确认选择、数量等按钮的 interval 状态。
        """
        super().shop_interval_clear()
        self.interval_clear(SHOP_BUY_CONFIRM_SELECT)
        self.interval_clear(SHOP_BUY_CONFIRM_AMOUNT)

    def shop_buy_handle(self, item):
        """处理勋章商店购买界面。

        检测并处理购买确认选择、数量输入等界面。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否检测到购买界面并进行了处理
        """
        if self.appear(SHOP_BUY_CONFIRM_SELECT, offset=(20, 20), interval=3):
            self.shop_buy_select_execute(item)
            self.interval_reset(SHOP_BUY_CONFIRM_SELECT)
            return True
        if self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
            self.shop_buy_amount_execute(item)
            self.interval_reset(SHOP_BUY_CONFIRM_AMOUNT)
            return True

        return False

    def run(self):
        """运行勋章商店购买流程。

        Pages: in: page_shop (medal shop tab)

        按照过滤器配置购买勋章商店商品，自动翻页直到列表底部。
        已售罄商品会自动排序到后方，发现售罄时提前终止。
        """
        # Base case; exit run if filter empty
        import time
        if not self.shop_filter:
            return

        # When called, expected to be in
        # correct Medal Shop interface
        logger.hr('Medal Shop', level=1)
        # Execute buy operations
        MEDAL_SHOP_SCROLL_250814.set_top(main=self)
        time.sleep(0.5)
        while 1:
            # sold items are auto sorted behind
            # if we find any soldout items, no need to check behind
            if self.shop_items().get_soldout_count(self.device.image):
                logger.info('Medal shop early stop')
                break

            self.shop_buy()

            if MEDAL_SHOP_SCROLL_250814.at_bottom(main=self):
                logger.info('Medal shop reach bottom, stop')
                break
            else:
                MEDAL_SHOP_SCROLL_250814.next_page(main=self, page=0.66)
                del_cached_property(self, 'shop_grid')
                del_cached_property(self, 'shop_medal_items')
                continue
