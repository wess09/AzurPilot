from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.shop.ui import ShopUI
from module.ui.navbar import Navbar


class PQShopUI(ShopUI):
    @cached_property
    def _shop_bottom_navbar(self):
        """
        商店底部导航栏，包含 4 个选项卡。

        Options:
            全部 / 礼物 / 家具 / 杂物

        Returns:
            Navbar: 底部导航栏实例
        """
        shop_navgrid = ButtonGrid(
            origin=(465, 600), delta=(200, 0), button_shape=(20, 20), grid_shape=(4, 1),
            name='PRIVATE_QUARTERS_BOTTOM_BUTTON_GRID')

        return Navbar(shop_navgrid,
                      active_color=(186, 226, 245), inactive_color=(236, 237, 243),
                      active_count=350, inactive_count=350,
                      active_threshold=221, inactive_threshold=221,
                      name='PRIVATE_QUARTERS_BOTTOM_NAVBAR')

    def shop_bottom_navbar_ensure(self, left=None, right=None):
        """
        切换商店底部标签页并等待页面加载完成。

        二选一使用 left 或 right，不要同时传入。

        Args:
            left (int): 从左起第 N 个标签（从 1 开始）
            right (int): 从右起第 N 个标签（从 1 开始）

        Returns:
            bool: 标签切换是否成功
        """
        if self._shop_bottom_navbar.set(self, left=left, right=right):
            return True
        return False

    @cached_property
    def _shop_left_navbar(self):
        """
        商店左侧导航栏，包含 5 个房间入口。

        Options:
            主页 / 天狼星 / 能代 / 安克雷奇 / 新泽西
        """
        shop_navgrid = ButtonGrid(
            origin=(152, 158), delta=(0, 105), button_shape=(15, 15), grid_shape=(1, 5),
            name='PRIVATE_QUARTERS_LEFT_BUTTON_GRID')

        return Navbar(shop_navgrid,
                      active_color=(255, 255, 255), inactive_color=(176, 245, 250),
                      active_count=200, inactive_count=200,
                      active_threshold=221, inactive_threshold=221,
                      name='PRIVATE_QUARTERS_LEFT_NAVBAR')

    def shop_left_navbar_ensure(self, upper=None, bottom=None):
        """
        切换商店左侧房间标签页并等待页面加载完成。

        二选一使用 upper 或 bottom，不要同时传入。

        Args:
            upper (int): 从上起第 N 个标签（从 1 开始）
            bottom (int): 从下起第 N 个标签（从 1 开始）

        Returns:
            bool: 标签切换是否成功
        """
        if self._shop_left_navbar.set(self, upper=upper, bottom=bottom):
            return True
        return False
