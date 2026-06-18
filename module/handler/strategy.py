from module.combat.assets import GET_ITEMS_1
from module.handler.assets import *
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.template.assets import (TEMPLATE_FORMATION_1, TEMPLATE_FORMATION_2,
                                    TEMPLATE_FORMATION_3)
from module.ui.switch import Switch

# 2023.10.19，单行图标数量从 2 个增加到 3 个
FORMATION = Switch('Formation', offset=(100, 200))
FORMATION.add_state('line_ahead', check_button=FORMATION_1)
FORMATION.add_state('double_line', check_button=FORMATION_2)
FORMATION.add_state('diamond', check_button=FORMATION_3)

SUBMARINE_HUNT = Switch('Submarine_hunt', offset=(200, 200))
SUBMARINE_HUNT.add_state('on', check_button=SUBMARINE_HUNT_ON)
SUBMARINE_HUNT.add_state('off', check_button=SUBMARINE_HUNT_OFF)

SUBMARINE_VIEW = Switch('Submarine_view', offset=(100, 200))
SUBMARINE_VIEW.add_state('on', check_button=SUBMARINE_VIEW_ON)
SUBMARINE_VIEW.add_state('off', check_button=SUBMARINE_VIEW_OFF)

MOB_MOVE_OFFSET = (120, 200)


class StrategyHandler(InfoHandler):
    fleet_1_formation_fixed = False
    fleet_2_formation_fixed = False

    def strategy_open(self, skip_first_screenshot=True):
        logger.info('Strategy open')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(STRATEGY_OPENED, offset=200):
                break

            if self.appear(IN_MAP, interval=5) and not self.appear(STRATEGY_OPENED, offset=200):
                self.device.click(STRATEGY_OPEN)
                continue

            # 处理遗漏的神秘格子
            if self.appear_then_click(GET_ITEMS_1, offset=5):
                continue

    def strategy_close(self, skip_first_screenshot=True):
        logger.info('Strategy close')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(STRATEGY_OPENED, offset=200, interval=5):
                continue

            if not self.appear(STRATEGY_OPENED, offset=200):
                break

    def strategy_set_execute(self, formation=None, sub_view=None, sub_hunt=None):
        """
        执行策略设置（编队阵型、潜艇视图、潜艇狩猎）。

        Args:
            formation (str): 'line_ahead'、'double_line'、'diamond'，或 None 表示不更改。
            sub_view (bool): 是否开启潜艇视图。
            sub_hunt (bool): 是否开启潜艇狩猎。

        Pages:
            in: STRATEGY_OPENED
        """
        logger.info(f'Strategy set: formation={formation}, submarine_view={sub_view}, submarine_hunt={sub_hunt}')

        if formation is not None:
            FORMATION.set(formation, main=self)
        # 在潜艇区域图标 bug 修复前禁用此功能
        # 使用潜艇时不要启用 MAP_HAS_DYNAMIC_RED_BORDER

        # 潜艇视图检查已恢复，参见 SwitchWithHandler。

        # 不知何时游戏 bug 已修复，移除 SwitchWithHandler 的使用
        if sub_view is not None:
            if SUBMARINE_VIEW.appear(main=self):
                SUBMARINE_VIEW.set('on' if sub_view else 'off', main=self)
            else:
                logger.warning('Setting up submarine_view but no icon appears')
        if sub_hunt is not None:
            if SUBMARINE_HUNT.appear(main=self):
                SUBMARINE_HUNT.set('on' if sub_hunt else 'off', main=self)
            else:
                logger.warning('Setting up submarine_hunt but no icon appears')

    def handle_strategy(self, index):
        """
        处理舰队策略设置。

        Args:
            index (int): 舰队索引。

        Returns:
            bool: 是否进行了更改。
        """
        if self.__getattribute__(f'fleet_{index}_formation_fixed'):
            return False
        expected_formation = self.config.__getattribute__(f'Fleet_Fleet{index}Formation')
        if self._strategy_get_from_map_buff() == expected_formation and not self.config.Submarine_Fleet:
            logger.info('Skip strategy bar check.')
            self.__setattr__(f'fleet_{index}_formation_fixed', True)
            return False

        self.strategy_open()
        self.strategy_set_execute(
            formation=expected_formation,
            sub_view=False,
            sub_hunt=bool(self.config.Submarine_Fleet) and self.config.Submarine_Mode in ['hunt_only', 'hunt_and_boss']
        )
        self.strategy_close()
        self.__setattr__(f'fleet_{index}_formation_fixed', True)
        return True

    def _strategy_get_from_map_buff(self):
        """
        从地图增益图标获取当前阵型。

        Returns:
            str: 阵型名称。
        """
        image = self.image_crop(MAP_BUFF, copy=False)
        if TEMPLATE_FORMATION_2.match(image):
            buff = 'double_line'
        elif TEMPLATE_FORMATION_1.match(image):
            buff = 'line_ahead'
        elif TEMPLATE_FORMATION_3.match(image):
            buff = 'diamond'
        else:
            buff = 'unknown'

        logger.attr('Map_buff', buff)
        return buff

    def is_in_strategy_submarine_move(self):
        """
        判断是否处于潜艇移动确认界面。

        Returns:
            bool: 是否在潜艇移动确认界面。
        """
        return self.appear(SUBMARINE_MOVE_CONFIRM, offset=(20, 20))

    def strategy_submarine_move_enter(self, skip_first_screenshot=True):
        """
        进入潜艇移动界面。

        Pages:
            in: STRATEGY_OPENED, SUBMARINE_MOVE_ENTER
            out: SUBMARINE_MOVE_CONFIRM
        """
        logger.info('Submarine move enter')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(SUBMARINE_MOVE_ENTER, offset=200, interval=5):
                self.device.click(SUBMARINE_MOVE_ENTER)

            if self.appear(SUBMARINE_MOVE_CONFIRM, offset=(20, 20)):
                break

    def strategy_submarine_move_confirm(self, skip_first_screenshot=True):
        """
        确认潜艇移动。

        Pages:
            in: SUBMARINE_MOVE_CONFIRM
            out: STRATEGY_OPENED, SUBMARINE_MOVE_ENTER
        """
        logger.info('Submarine move confirm')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(SUBMARINE_MOVE_CONFIRM, offset=(20, 20), interval=5):
                pass
            if self.handle_popup_confirm('SUBMARINE_MOVE'):
                pass

            if self.appear(SUBMARINE_MOVE_ENTER, offset=200):
                break

    def strategy_submarine_move_cancel(self, skip_first_screenshot=True):
        """
        取消潜艇移动。

        Pages:
            in: SUBMARINE_MOVE_CONFIRM
            out: STRATEGY_OPENED, SUBMARINE_MOVE_ENTER
        """
        logger.info('Submarine move cancel')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(SUBMARINE_MOVE_CANCEL, offset=(20, 20), interval=5):
                pass
            if self.handle_popup_confirm('SUBMARINE_MOVE'):
                pass

            if self.appear(SUBMARINE_MOVE_ENTER, offset=200):
                break

    def is_in_strategy_mob_move(self):
        """
        判断是否处于普通舰队移动界面。

        Returns:
            bool: 是否在普通舰队移动界面。
        """
        return self.appear(MOB_MOVE_CANCEL, offset=(20, 20))

    def strategy_has_mob_move(self):
        """
        检查是否有普通舰队移动选项。

        Pages:
            in: STRATEGY_OPENED
            out: STRATEGY_OPENED
        """
        if self.match_template_color(MOB_MOVE_ENTER, offset=MOB_MOVE_OFFSET):
            return True
        else:
            return False

    def strategy_mob_move_enter(self, skip_first_screenshot=True):
        """
        进入普通舰队移动界面。

        Pages:
            in: STRATEGY_OPENED, MOB_MOVE_ENTER
            out: MOB_MOVE_CANCEL
        """
        logger.info('Mob move enter')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(MOB_MOVE_CANCEL, offset=(20, 20)):
                break

            if self.appear_then_click(MOB_MOVE_ENTER, offset=MOB_MOVE_OFFSET, interval=5):
                continue

    def strategy_mob_move_cancel(self, skip_first_screenshot=True):
        """
        取消普通舰队移动。

        Pages:
            in: MOB_MOVE_CANCEL
            out: STRATEGY_OPENED, MOB_MOVE_ENTER
        """
        logger.info('Mob move cancel')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(MOB_MOVE_ENTER, offset=MOB_MOVE_OFFSET):
                break

            if self.appear_then_click(MOB_MOVE_CANCEL, offset=(20, 20), interval=5):
                continue

    def is_in_strategy_air_strike(self):
        """
        判断是否处于空袭确认界面。

        Returns:
            bool: 是否在空袭确认界面。
        """
        return self.appear(AIR_STRIKE_CONFIRM, offset=(20, 20))

    def strategy_has_air_strike(self):
        """
        检查是否有空袭选项。

        Pages:
            in: STRATEGY_OPENED
            out: STRATEGY_OPENED
        """
        if self.match_template_color(AIR_STRIKE_ENTER, offset=(150, 200)):
            return True
        else:
            return False

    def strategy_air_strike_enter(self, skip_first_screenshot=True):
        """
        进入空袭界面。

        Pages:
            in: STRATEGY_OPENED, AIR_STRIKE_ENTER
            out: AIR_STRIKE_CONFIRM
        """
        logger.info('Air strike enter')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(AIR_STRIKE_CONFIRM, offset=(20, 20)):
                break

            if self.appear_then_click(AIR_STRIKE_ENTER, offset=(150, 200), interval=5):
                continue

    def strategy_air_strike_confirm(self, skip_first_screenshot=True):
        """
        确认空袭。

        Pages:
            in: AIR_STRIKE_CONFIRM
            out: STRATEGY_OPENED, AIR_STRIKE_ENTER
        """
        logger.info('Air strike confirm')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(AIR_STRIKE_ENTER, offset=(150, 200)):
                break

            if self.appear_then_click(AIR_STRIKE_CONFIRM, offset=(20, 20), interval=5):
                continue
