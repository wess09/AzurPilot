from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.gacha.assets import *
from module.logger import logger
from module.ui.navbar import Navbar
from module.ui.page import page_build
from module.ui.ui import UI

GACHA_LOAD_ENSURE_BUTTONS = [SHOP_MEDAL_CHECK, BUILD_SUBMIT_ORDERS, BUILD_SUBMIT_WW_ORDERS, BUILD_FINISH_ORDERS, BUILD_WW_CHECK]


class GachaUI(UI):
    def gacha_load_ensure(self, skip_first_screenshot=True):
        """
        等待建造页面资源加载完成。

        切换侧边栏后需要一定的处理时间才能完全加载，
        类似大舰队后勤页面的加载过程。
        通过截图循环检测目标按钮是否出现来判断加载是否完成。

        Args:
            skip_first_screenshot: 是否跳过首次截图，复用上一次循环的截图。

        Returns:
            资源是否加载完成。
        """
        ensure_timeout = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件——检测到任意一个目标按钮出现即可
            results = [self.appear(button) for button in GACHA_LOAD_ENSURE_BUTTONS]
            if any(results):
                return True

            # 超时异常——资源加载未完成
            if ensure_timeout.reached():
                logger.warning('Wait for loaded assets is incomplete, ensure not guaranteed')
                return False

    @cached_property
    def _gacha_side_navbar(self):
        """
        获取建造页面左侧侧边导航栏。

        限时建造侧边栏有 5 个选项，常驻建造侧边栏有 4 个选项。

        Pages: page_build

        选项分布:
            限时建造 (5项): 建造、限定建造、兑换、商店、退役
            常驻建造 (4项): 建造、兑换、商店、退役
        """
        gacha_side_navbar = ButtonGrid(
            origin=(21, 126), delta=(0, 98),
            button_shape=(60, 80), grid_shape=(1, 5),
            name='GACHA_SIDE_NAVBAR')

        return Navbar(grids=gacha_side_navbar,
                      active_color=(247, 255, 173), active_threshold=221,
                      inactive_color=(140, 162, 181), inactive_threshold=221)

    def gacha_side_navbar_ensure(self, upper=None, bottom=None):
        """
        确保侧边导航栏切换到指定标签页并加载完成。

        Pages: page_build

        Args:
            upper: 从上往下数的标签序号。
                限时建造|常驻建造
                    1     -> 建造
                    2|N/A -> 限定建造（仅限时）
                    3|2   -> 兑换
                    4|3   -> 商店
                    5|4   -> 退役
            bottom: 从下往上数的标签序号。
                限时建造|常驻建造
                    5|4   -> 建造
                    4|N/A -> 限定建造（仅限时）
                    3     -> 兑换
                    2     -> 商店
                    1     -> 退役

        Returns:
            侧边导航栏是否切换成功。
        """
        retire_upper = 5 if self._gacha_side_navbar.get_total(main=self) == 5 else 4
        if upper == retire_upper or bottom == 1:
            logger.warning('Transitions to "retire" is not supported')
            return False

        if self._gacha_side_navbar.set(self, upper=upper, bottom=bottom) \
                and self.gacha_load_ensure():
            return True
        return False

    @cached_property
    def _construct_bottom_navbar(self):
        """
        获取建造页面底部标签导航栏。

        限时建造底部有 4 个标签，常驻建造底部有 3 个标签。

        Pages: page_build

        选项分布:
            限时建造 (4项): 活动、轻型、重型、特型
            常驻建造 (3项): 轻型、重型、特型
        """
        construct_bottom_navbar = ButtonGrid(
            origin=(262, 615), delta=(209, 0),
            button_shape=(70, 49), grid_shape=(4, 1),
            name='CONSTRUCT_BOTTOM_NAVBAR')

        return Navbar(grids=construct_bottom_navbar,
                      active_color=(247, 227, 148),
                      inactive_color=(189, 231, 247))

    @cached_property
    def _exchange_bottom_navbar(self):
        """
        获取兑换页面底部标签导航栏。

        兑换页面底部有 2 个标签。

        Pages: page_build

        选项分布:
            2项: 舰船、物品
        """
        exchange_bottom_navbar = ButtonGrid(
            origin=(569, 637), delta=(208, 0),
            button_shape=(70, 49), grid_shape=(2, 1),
            name='EXCHANGE_BOTTOM_NAVBAR')

        return Navbar(grids=exchange_bottom_navbar,
                      active_color=(247, 227, 148),
                      inactive_color=(189, 231, 247))

    def _gacha_bottom_navbar(self, is_build=True):
        """
        根据当前页面类型返回对应的底部导航栏。

        建造页面返回建造底部导航栏，兑换页面返回兑换底部导航栏。

        Args:
            is_build: 是否为建造页面。True 返回建造导航栏，False 返回兑换导航栏。

        Returns:
            对应页面的底部 Navbar 实例。
        """
        if is_build:
            return self._construct_bottom_navbar
        else:
            return self._exchange_bottom_navbar

    def gacha_bottom_navbar_ensure(self, left=None, right=None, is_build=True):
        """
        确保底部标签导航栏切换到指定标签页并加载完成。

        Pages: page_build

        Args:
            left: 从左往右数的标签序号。
                建造导航栏:
                    限时|常驻
                    1|N/A -> 活动
                    2|1   -> 轻型
                    3|2   -> 重型
                    4|3   -> 特型
                兑换导航栏:
                    1     -> 舰船
                    2     -> 物品
            right: 从右往左数的标签序号。
                建造导航栏:
                    限时|常驻
                    4|N/A -> 活动
                    3     -> 轻型
                    2     -> 重型
                    1     -> 特型
                兑换导航栏:
                    2     -> 舰船
                    1     -> 物品
            is_build: 是否为建造页面。

        Returns:
            底部导航栏是否切换成功。
        """
        gacha_bottom_navbar = self._gacha_bottom_navbar(is_build)
        if is_build and gacha_bottom_navbar.get_total(main=self) == 3:
            if left == 1 or right == 4:
                logger.info('Construct event not available, default to light')
                left = 1
                right = None
            if left == 4:
                left = 3

        if gacha_bottom_navbar.set(self, left=left, right=right) \
                and self.gacha_load_ensure():
            return True
        return False

    def ui_goto_gacha(self):
        """
        导航到建造页面。

        Pages: out: *, in: page_build
        """
        self.ui_ensure(page_build)


if __name__ == '__main__':
    self = GachaUI('alas')
    self.image_file = r'C:\Users\LmeSzinc\Nox_share\ImageShare\Screenshots\Screenshot_20220224-182355.png'
    res = self._gacha_side_navbar.get_info(main=self)
    print(res)