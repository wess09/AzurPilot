from module.base.base import ModuleBase
from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP
from module.logger import logger
from module.shop.assets import SHOP_CLICK_SAFE_AREA


class Navbar:
    def __init__(self, grids, active_color=(247, 251, 181), inactive_color=(140, 162, 181), active_threshold=180,
                 inactive_threshold=180, active_count=100, inactive_count=50, name=None):
        """
        Args:
            grids (ButtonGrid): 标签按钮网格。
            active_color (tuple[int, int, int]): 激活状态的 RGB 颜色。
            inactive_color (tuple[int, int, int]): 非激活状态的 RGB 颜色。
            active_threshold (int): 激活状态的颜色匹配阈值。
            inactive_threshold (int): 非激活状态的颜色匹配阈值。
            active_count (int): 激活状态的最小像素计数。
            inactive_count (int): 非激活状态的最小像素计数。
            name (str): 导航栏名称。
        """
        self.grids = grids
        self.active_color = active_color
        self.inactive_color = inactive_color
        self.active_threshold = active_threshold
        self.inactive_threshold = inactive_threshold
        self.active_count = active_count
        self.inactive_count = inactive_count
        self.name = name if name is not None else grids._name

    def is_button_active(self, button, main):
        """
        检测按钮是否处于激活状态。

        Args:
            button (Button): 要检测的按钮。
            main (ModuleBase): 模块基类实例。

        Returns:
            bool: 是否激活。
        """
        return main.image_color_count(
                    button, color=self.active_color, threshold=self.active_threshold, count=self.active_count)

    def is_button_inactive(self, button, main):
        """
        检测按钮是否处于非激活状态。

        Args:
            button (Button): 要检测的按钮。
            main (ModuleBase): 模块基类实例。

        Returns:
            bool: 是否非激活。
        """
        return main.image_color_count(
            button, color=self.inactive_color, threshold=self.inactive_threshold, count=self.inactive_count)

    def get_info(self, main):
        """
        获取导航栏信息：当前激活项、最左项和最右项的索引。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            int, int, int: 激活项索引、最左项索引、最右项索引。
        """
        total = []
        active = []
        for index, button in enumerate(self.grids.buttons):
            if self.is_button_active(button, main=main):
                total.append(index)
                active.append(index)
            elif self.is_button_inactive(button, main=main):
                total.append(index)

        if len(active) == 0:
            # logger.warning(f'No active nav item found in {self.name}')
            active = None
        elif len(active) == 1:
            active = active[0]
        else:
            logger.warning(f'Too many active nav items found in {self.name}, items: {active}')
            active = active[0]

        if len(total) < 2:
            logger.warning(f'Too few nav items found in {self.name}, items: {total}')
        if len(total) == 0:
            left, right = None, None
        else:
            left, right = min(total), max(total)

        return active, left, right

    def get_active(self, main):
        """
        获取当前激活的导航项索引。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            int: 激活项的索引。
        """
        return self.get_info(main=main)[0]

    def get_total(self, main):
        """
        获取可见的导航项总数。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            int: 可见导航项的数量。
        """
        _, left, right = self.get_info(main=main)
        if left is None or right is None:
            return 0
        return right - left + 1

    def _shop_obstruct_handle(self, main):
        """
        仅在商店中时，处理商店界面的遮挡物。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            bool: 是否处理了遮挡物。
        """
        # 通过名称判断导航栏是否属于商店模块
        if self.name not in ['SHOP_BOTTOM_NAVBAR', 'GUILD_SIDE_NAVBAR']:
            return False

        # 处理商店遮挡物
        if main.appear(GET_SHIP, interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if main.appear(GET_ITEMS_1, offset=(30, 30), interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if main.appear(GET_ITEMS_2, offset=(30, 30), interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True

        return False

    def set(self, main, left=None, right=None, upper=None, bottom=None, skip_first_screenshot=True):
        """
        从一个方向设置导航栏到指定位置。

        Args:
            main (ModuleBase): 模块基类实例。
            left (int): 从左数的导航项索引，从 1 开始。
            right (int): 从右数的导航项索引，从 1 开始。
            upper (int): 从上数的导航项索引，从 1 开始。
            bottom (int): 从下数的导航项索引，从 1 开始。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否设置成功。
        """
        if left is None and right is None and upper is None and bottom is None:
            logger.warning('Invalid index to set, must set an index from 1 direction')
            return False
        text = ''
        if left is None and upper is not None:
            left = upper
        if right is None and bottom is not None:
            right = bottom
        for k in ['left', 'right', 'upper', 'bottom']:
            if locals().get(k, None) is not None:
                text += f'{k}={locals().get(k, None)} '
        logger.info(f'{self.name} set to {text.strip()}')

        interval = Timer(2, count=4)
        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if timeout.reached():
                logger.warning(f'{self.name} failed to set {text.strip()}')
                return False

            if self._shop_obstruct_handle(main=main):
                interval.reset()
                timeout.reset()
                continue

            active, minimum, maximum = self.get_info(main=main)
            logger.info(f'Nav item active: {active} from range ({minimum}, {maximum})')
            # 收到纯黑截图时会返回 None
            # Active 为 None 可能是因为动画尚未加载完成
            if active is None or minimum is None or maximum is None:
                continue

            index = minimum + left - 1 if left is not None else maximum - right + 1
            if not minimum <= index <= maximum:
                logger.warning(
                    f'Index to set ({index}) is not within the nav items that appears ({minimum}, {maximum})')
                continue

            # End
            if active == index:
                return True

            if interval.reached():
                main.device.click(self.grids.buttons[index])
                interval.reset()
