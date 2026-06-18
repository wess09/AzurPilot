import numpy as np
from scipy import signal

# 此文件处理进入关卡前的编队准备（Fleet Preparation）逻辑。
# 包含编队的选择与重置、潜艇部署设置以及满足困难地图条件限制的检查、请求人工接管等操作。
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import *
from module.exception import RequestHumanTakeover
from module.handler.assets import AUTO_SEARCH_SET_MOB, AUTO_SEARCH_SET_BOSS, \
    AUTO_SEARCH_SET_ALL, AUTO_SEARCH_SET_STANDBY, \
    AUTO_SEARCH_SET_SUB_AUTO, AUTO_SEARCH_SET_SUB_STANDBY
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.assets import *


class FleetOperator:
    FLEET_BAR_SHAPE_Y = 33
    FLEET_BAR_MARGIN_Y = 9
    FLEET_BAR_ACTIVE_STD = 45  # 激活时: 67，未激活时: 12。
    FLEET_IN_USE_STD = 27  # 使用中: 52，未使用: (3, 6)。

    OFFSET = (-20, -80, 20, 5)

    def __init__(self, choose, advice, bar, clear, in_use, hard_satisfied, main):
        """
        Args:
            choose (Button): 激活或关闭下拉菜单的按钮。
            advice (Button): 推荐舰船的按钮。
            bar (Button): 舰队选择的下拉菜单。
            clear (Button): 清除当前舰队的按钮。
            in_use (Button): 检测是否正在使用当前舰队的按钮。
            hard_satisfied (Button): 检测舰队是否满足困难模式限制的区域。
            main (InfoHandler): Alas 模块实例。
        """
        self._choose = choose
        self._advice = advice
        self._bar = bar
        self._clear = clear
        self._in_use = in_use
        self._hard_satisfied = hard_satisfied
        self.main = main

        if main.appear(clear, offset=FleetOperator.OFFSET):
            choose.load_offset(clear)
            bar.load_offset(clear)
            in_use.load_offset(clear)
            hard_satisfied.load_offset(clear)

    def __str__(self):
        return str(self._choose)[:-7]

    def parse_fleet_bar(self, image):
        """
        Args:
            image (np.ndarray): 下拉菜单的图像。

        Returns:
            list[int]: 当前选中的舰队编号列表，范围 1 到 6。
        """
        width, height = image_size(image)
        result = []
        for index, y in enumerate(range(0, height, self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y)):
            area = (0, y, width, y + self.FLEET_BAR_SHAPE_Y)
            mean = get_color(image, area)
            if np.std(mean, ddof=1) > self.FLEET_BAR_ACTIVE_STD:
                result.append(index + 1)
        logger.info('Current selected: %s' % str(result))
        return result

    def get_button(self, index):
        """将舰队索引转换为下拉菜单上的 Button 对象。

        Args:
            index (int): 舰队索引，1-6。

        Returns:
            Button: Button 实例。
        """
        bar = self._bar.button
        area = area_offset(area=(
            0,
            (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1),
            bar[2] - bar[0],
            (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1) + self.FLEET_BAR_SHAPE_Y
        ), offset=(bar[0:2]))
        return Button(area=(), color=(), button=area, name='%s_INDEX_%s' % (str(self._bar), str(index)))

    def allow(self):
        """
        Returns:
            bool: 当前舰队是否允许被选择。
        """
        return self.main.appear(self._clear, offset=FleetOperator.OFFSET)

    def is_hard(self):
        """
        Returns:
            bool: 是否有推荐按钮。如果有，则该关卡为困难战役。
        """
        return self.main.appear(self._advice, offset=FleetOperator.OFFSET)

    def is_hard_satisfied(self):
        """检测有多少条浅橙色线条。
        有线条表示当前地图有属性限制且用户至少满足其中一项，因此这是困难地图。

        Returns:
            bool: 当前舰队是否满足困难模式限制。
                如果不是困难模式则返回 None。
        """
        if not self.is_hard():
            return None

        area = self._hard_satisfied.button
        image = color_similarity_2d(self.main.image_crop(area, copy=False), color=(249, 199, 0))
        height = cv2.reduce(image, 1, cv2.REDUCE_AVG).flatten()
        parameters = {'height': 180, 'distance': 5}
        peaks, _ = signal.find_peaks(height, **parameters)
        lines = len(peaks)
        # logger.attr('Light_orange_line', lines)
        return lines > 0

    def raise_hard_not_satisfied(self):
        if self.is_hard_satisfied() is False:
            stage = self.main.config.Campaign_Name
            logger.critical(f'关卡 "{stage}" 是困难模式，'
                            f'请在运行 Alas 之前在游戏中准备好您的舰队 "{str(self)}"')
            raise RequestHumanTakeover('Hard not satisfied', str(self))

    def clear(self, skip_first_screenshot=True):
        """清除选中的舰队。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 清除困难舰队时的弹窗
            if self.main.handle_popup_confirm(str(self._clear)):
                continue

            # 检查 CLEAR 按钮以避免在弹窗动画期间提前停止
            if self.allow():
                # 结束
                if not self.in_use():
                    break

                # 点击
                if click_timer.reached():
                    main.device.click(self._clear)
                    click_timer.reset()

    def recommend(self, skip_first_screenshot=True):
        """推荐舰队。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 结束
            if self.in_use():
                break

            # 点击
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def open(self, skip_first_screenshot=True):
        """激活舰队选择的下拉菜单。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 结束
            if self.bar_opened():
                break

            # 点击
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def close(self, skip_first_screenshot=True):
        """关闭舰队选择的下拉菜单。
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 结束
            if not self.bar_opened():
                break

            # 点击
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def click(self, index, skip_first_screenshot=True):
        """在下拉菜单中选择一个舰队，然后关闭下拉菜单。

        Args:
            index (int): 舰队索引，1-6。
            skip_first_screenshot (bool): 是否跳过第一张截图。
        """
        main = self.main
        button = self.get_button(index)
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if not self.bar_opened():
                # 结束
                if self.in_use():
                    break
                else:
                    self.open()

            # 点击
            if click_timer.reached():
                main.device.click(button)
                click_timer.reset()

    def selected(self):
        """
        Returns:
            list[int]: 当前选中的舰队编号列表，范围 1 到 6。
        """
        data = self.parse_fleet_bar(self.main.image_crop(self._bar.button, copy=False))
        return data

    def in_use(self):
        """
        Returns:
            bool: 是否已选择任何舰队。
        """
        # 处理自动搜索的信息栏。
        # if area_cross_area(self._in_use.area, INFO_BAR_1.area):
        #     self.main.handle_info_bar()

        # 裁剪 FLEET_*_IN_USE 以避免检测 info_bar，也能达到同样效果。
        # 这也避免了在处理 info_bar 上浪费时间。
        image = self.main.image_crop(self._in_use.button, copy=False)

        # 珀尔修斯皮肤的特殊修复，其颜色过于平坦
        # https://github.com/LmeSzinc/AzurLaneAutoScript/issues/5678
        # 无舰船时颜色为 (71, 70, 63)
        color = cv2.mean(image)[:3]
        if color_similar(color, (224, 154, 114), threshold=30):
            return True

        gray = rgb2gray(image)
        return np.std(gray.flatten(), ddof=1) > self.FLEET_IN_USE_STD

    def bar_opened(self):
        """
        Returns:
            bool: 下拉菜单是否已打开。
        """
        # 检查菜单区域最右侧列的亮度。
        luma = rgb2gray(self.main.image_crop(self._bar.button, copy=False))[:, -1]
        # FLEET_PREPARATION 的亮度约为 146~155
        return np.sum(luma > 168) / luma.size > 0.5

    def ensure_to_be(self, index):
        """设置为指定的舰队。

        Args:
            index (int): 舰队索引，1-6。
        """
        self.open()
        if index in self.selected():
            self.close()
        else:
            self.click(index)


class FleetPreparation(InfoHandler):
    map_fleet_checked = False
    map_is_hard_mode = False

    def fleet_preparation(self, skip_first_screenshot=True):
        """更换舰队。

        Returns:
            bool: 是否进行了更换。
        """
        logger.info(f'Using fleet: {[self.config.Fleet_Fleet1, self.config.Fleet_Fleet2, self.config.Submarine_Fleet]}')
        if self.map_fleet_checked:
            return False

        if self.appear(FLEET_1_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_MOB.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_BOSS.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_ALL.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_STANDBY.load_offset(FLEET_1_CLEAR)
        if self.appear(SUBMARINE_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_SUB_AUTO.load_offset(SUBMARINE_CLEAR)
            AUTO_SEARCH_SET_SUB_STANDBY.load_offset(SUBMARINE_CLEAR)

        fleet_1 = FleetOperator(
            choose=FLEET_1_CHOOSE, advice=FLEET_1_ADVICE, bar=FLEET_1_BAR, clear=FLEET_1_CLEAR,
            in_use=FLEET_1_IN_USE, hard_satisfied=FLEET_1_HARD_SATIESFIED, main=self)
        y = FLEET_1_CLEAR.button[1] - FLEET_1_CLEAR.area[1]
        if y < -10:
            logger.info('FLEET_1_CLEAR moves up, load W15 assets')
            in_use = FLEET_2_IN_USE_W15
        else:
            in_use = FLEET_2_IN_USE
        fleet_2 = FleetOperator(
            choose=FLEET_2_CHOOSE, advice=FLEET_2_ADVICE, bar=FLEET_2_BAR, clear=FLEET_2_CLEAR,
            in_use=in_use, hard_satisfied=FLEET_2_HARD_SATIESFIED, main=self)
        submarine = FleetOperator(
            choose=SUBMARINE_CHOOSE, advice=SUBMARINE_ADVICE, bar=SUBMARINE_BAR, clear=SUBMARINE_CLEAR,
            in_use=SUBMARINE_IN_USE, hard_satisfied=SUBMARINE_HARD_SATIESFIED, main=self)

        # 检查是否为困难模式地图
        h1, h2, h3 = fleet_1.is_hard_satisfied(), fleet_2.is_hard_satisfied(), submarine.is_hard_satisfied()
        self.map_is_hard_mode = h1 is not None or h2 is not None or h3 is not None

        # 潜艇。
        # 缓存 submarine.allow() 以避免设置 fleet_2 后的不一致
        # 因为展开的 fleet_2 可能会遮挡潜艇按钮
        map_allow_submarine = submarine.allow()
        logger.attr('map_allow_submarine', map_allow_submarine)

        # 在困难模式下使用推荐舰队
        if self.map_is_hard_mode and self.config.Campaign_UseRecommendFleet:
            logger.info('Using recommend fleet for hard mode')
            click_timer = Timer(3, count=6)
            self.device.screenshot()

            # 点击 RECOMMEND_A 推荐第一舰队
            if fleet_1.allow():
                logger.info('Click RECOMMEND_A')
                self.device.click(RECOMMEND_A)                
            # 点击 RECOMMEND_B 推荐第二舰队
            if fleet_2.allow():
                logger.info('Click RECOMMEND_B')
                self.device.click(RECOMMEND_B)                
            # 点击 RECOMMEND_C 推荐潜艇
            if map_allow_submarine:
                if self.config.Submarine_Fleet:
                    logger.info('Click RECOMMEND_C')
                    self.device.click(RECOMMEND_C)
                else:
                    submarine.clear()
            else:
                self.config.SUBMARINE = 0
            
            # 等待动画
            self.device.sleep(0.5)
            self.device.screenshot()

            # 推荐后重新检查困难模式限制
            h1, h2, h3 = fleet_1.is_hard_satisfied(), fleet_2.is_hard_satisfied(), submarine.is_hard_satisfied()

        logger.info(f'Hard satisfied: Fleet_1: {h1}, Fleet_2: {h2}, Submarine: {h3}')
        if self.config.SERVER in ['cn', 'en', 'jp']:
            if self.config.Fleet_Fleet1:
                fleet_1.raise_hard_not_satisfied()
            if self.config.Fleet_Fleet2:
                fleet_2.raise_hard_not_satisfied()
            if self.config.Submarine_Fleet:
                submarine.raise_hard_not_satisfied()

        # 困难模式下跳过舰队编成（或处理推荐后）
        if self.map_is_hard_mode:
            logger.info('Hard Campaign. No fleet preparation')
            # 如果用户未设置潜艇舰队则清除潜艇
            if submarine.allow():
                if self.config.Submarine_Fleet:
                    pass
                else:
                    submarine.clear()
            self.map_fleet_checked = True
            return False

        if map_allow_submarine:
            if self.config.Submarine_Fleet:
                if fleet_2.allow():
                    self.device.click(fleet_2._clear)
                    # 无需重新截图，因为潜艇检查不需要第二舰队部分
                submarine.ensure_to_be(self.config.Submarine_Fleet)
            else:
                # 使用简单点击同时清除潜艇和第二舰队
                # 这样更快，因为无需等待点击动画消失
                # 点击成功可由后续 clear() 调用保证
                op = False
                if fleet_2.allow():
                    self.device.click(fleet_2._clear)
                    op = True
                if submarine.allow():
                    self.device.click(submarine._clear)
                    op = True
                if op:
                    self.device.screenshot()

        # 不需要，这可能会误清除 FLEET_2，在地图配置中清除 FLEET_2。
        # if not fleet_2.allow():
        #     self.config.FLEET_2 = 0

        if self.config.Fleet_Fleet2:
            # 使用两支舰队。
            # 强制重新设置。
            # 舰队可能颠倒，因为 AL 不再将较小索引的舰队视为第一舰队
            fleet_2.clear()
            fleet_1.ensure_to_be(self.config.Fleet_Fleet1)
            fleet_2.ensure_to_be(self.config.Fleet_Fleet2)
        else:
            # 不使用第二舰队。
            if fleet_2.allow():
                fleet_2.clear()
            fleet_1.ensure_to_be(self.config.Fleet_Fleet1)

        # 再次检查潜艇是否为空。
        if map_allow_submarine:
            if self.config.Submarine_Fleet:
                pass
            else:
                submarine.clear()
        else:
            self.config.SUBMARINE = 0

        if self.appear(FLEET_1_CLEAR, offset=(-20, -80, 20, 5)):
            AUTO_SEARCH_SET_MOB.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_BOSS.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_ALL.load_offset(FLEET_1_CLEAR)
            AUTO_SEARCH_SET_STANDBY.load_offset(FLEET_1_CLEAR)

        timeout = Timer(1, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                break

            if self.appear(SUBMARINE_CLEAR, offset=(-20, -80, 20, 5)):
                AUTO_SEARCH_SET_SUB_AUTO.load_offset(SUBMARINE_CLEAR)
                AUTO_SEARCH_SET_SUB_STANDBY.load_offset(SUBMARINE_CLEAR)
                break

        return True
