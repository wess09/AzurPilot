import numpy as np

from module.base.timer import Timer
from module.base.utils import color_similar, get_color, lower_template_match_similarity
from module.base.api_client import ApiClient
from module.combat.assets import *
from module.combat.combat_auto import CombatAuto
from module.combat.combat_manual import CombatManual
from module.combat.hp_balancer import HPBalancer
from module.combat.level import Level
from module.combat.submarine import SubmarineCall
from module.combat_ui.assets import *
from module.handler.auto_search import AutoSearchHandler
from module.logger import logger
from module.map.assets import MAP_OFFENSIVE
from module.retire.retirement import Retirement
from module.statistics.azurstats import DropImage
from module.template.assets import TEMPLATE_COMBAT_LOADING
from module.ui.assets import BACK_ARROW, EXERCISE_CHECK, MUNITIONS_CHECK


class Combat(Level, HPBalancer, Retirement, SubmarineCall, CombatAuto, CombatManual, AutoSearchHandler):
    _automation_set_timer = Timer(1)
    battle_status_click_interval = 0

    def combat_appear(self):
        """
        检测是否进入战斗画面。

        Returns:
            是否已进入战斗准备或战斗加载状态。
        """
        if self.config.Campaign_UseFleetLock and not self.is_in_map():
            if self.is_combat_loading():
                return True

        if self.appear(BATTLE_PREPARATION, offset=(30, 20)):
            return True
        if self.appear(BATTLE_PREPARATION_WITH_OVERLAY, threshold=30) and self.handle_combat_automation_confirm():
            return True

        return False

    def map_offensive(self, skip_first_screenshot=True):
        """
        Pages:
            in: in_map, MAP_OFFENSIVE
            out: combat_appear
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(MAP_OFFENSIVE, interval=1):
                continue
            if self.handle_combat_low_emotion():
                self.interval_reset(MAP_OFFENSIVE)
                continue
            if self.handle_retirement():
                continue

            # 检测到战斗画面，退出循环
            if self.combat_appear():
                break
    def is_combat_loading(self):
        """
        检测是否处于战斗加载画面。

        通过底部加载条模板匹配判断，CN/EN/TW 资源相同，JP 角色较小。

        Returns:
            是否处于战斗加载状态。
        """
        image = self.image_crop((0, 620, 1280, 690), copy=False)
        # CN/EN/TW 加载条资源相同，JP 角色尺寸较小
        similarity, button = TEMPLATE_COMBAT_LOADING.match_luma_result(image)
        if similarity > lower_template_match_similarity(0.85):
            loading = (button.area[0] + 38 - LOADING_BAR.area[0]) / (LOADING_BAR.area[2] - LOADING_BAR.area[0])
            logger.attr('Loading', f'{int(loading * 100)}%')
            return True
        if self.is_combat_executing():
            logger.warning('检测到战斗状态但未检测到加载条')
            return True
        return False

    def is_combat_executing(self):
        """
        检测战斗是否正在执行中（暂停按钮可见）。

        遍历所有服务器的暂停按钮皮肤，返回匹配到的按钮。

        Returns:
            匹配到的暂停按钮，未匹配返回 False。
        """
        self.device.stuck_record_add(PAUSE)
        if self.config.SERVER in ['cn', 'en']:
            if PAUSE.match_luma(self.device.image, offset=(10, 10)):
                return PAUSE
        else:
            color = get_color(self.device.image, PAUSE.area)
            if color_similar(color, PAUSE.color) or color_similar(color, (238, 244, 248)):
                if np.max(self.image_crop(PAUSE_DOUBLE_CHECK, copy=False)) < 153:
                    return PAUSE
        if PAUSE_New.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_New
        if PAUSE_Iridescent_Fantasy.match_luma(self.device.image, offset=(10, 10)):
            return PAUSE_Iridescent_Fantasy
        if PAUSE_Christmas.match_luma(self.device.image, offset=(10, 10)):
            return PAUSE_Christmas
        # PAUSE_New、PAUSE_Cyber、PAUSE_Neon 外观相似，通过颜色区分
        if PAUSE_Neon.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_Neon
        if PAUSE_Cyber.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_Cyber
        if PAUSE_HolyLight.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_HolyLight
        # PAUSE_Pharaoh 有随机动画，资源应避开中间区域并使用 match_luma
        if PAUSE_Pharaoh.match_luma(self.device.image, offset=(10, 10)):
            return PAUSE_Pharaoh
        # PAUSE_Star 可能被误判为 PAUSE_Nurse，需优先检测
        if PAUSE_Star.match_luma(self.device.image, offset=(10, 10)):
            return PAUSE_Star
        if PAUSE_Nurse.match_luma(self.device.image, offset=(10, 10)):
            return PAUSE_Nurse
        # PAUSE_Devil 为红色主题
        if PAUSE_Devil.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_Devil
        # PAUSE_Seaside 为浅蓝色主题
        if PAUSE_Seaside.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_Seaside
        if PAUSE_Ninja.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_Ninja
        if PAUSE_ShadowPuppetry.match_luma(self.device.image, offset=(10, 10)):
            return PAUSE_ShadowPuppetry
        if PAUSE_MaidCafe.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_MaidCafe
        if PAUSE_Ancient.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_Ancient
        if PAUSE_SpringInn.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_SpringInn
        if PAUSE_ElvenVine.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_ElvenVine
        if PAUSE_GildedReverie.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_GildedReverie
        if PAUSE_AzureCore.match_template_color(self.device.image, offset=(10, 10)):
            return PAUSE_AzureCore
        return False

    def handle_combat_quit(self, offset=(20, 20), interval=3):
        """
        处理战斗退出按钮（暂停菜单中的退出）。

        遍历所有服务器的退出按钮皮肤，点击匹配到的按钮。

        Args:
            offset: 按钮匹配偏移量。
            interval: 点击间隔秒数。

        Returns:
            是否点击了退出按钮。
        """
        timer = self.get_interval_timer(QUIT, interval=interval)
        if not timer.reached():
            return False
        if QUIT.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT)
            timer.reset()
            return True
        if QUIT_New.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_New)
            timer.reset()
            return True
        if QUIT_Iridescent_Fantasy.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_Iridescent_Fantasy)
            timer.reset()
            return True
        # PAUSE_Neon 战斗界面使用 QUIT_New
        # PAUSE_Cyber 战斗界面使用 QUIT_New
        # [TW] QUIT_New 为粗体，PAUSE_Cyber 为常规字重
        if QUIT_Cyber.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_Cyber)
            timer.reset()
            return True
        if QUIT_Christmas.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_Christmas)
            timer.reset()
            return True
        # PAUSE_HolyLight 战斗界面使用 QUIT_New
        if QUIT_Pharaoh.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_Pharaoh)
            timer.reset()
            return True
        if QUIT_Nurse.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_Nurse)
            timer.reset()
            return True
        # PAUSE_Devil 战斗界面使用 QUIT_New
        if QUIT_Seaside.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_Seaside)
            timer.reset()
            return True
        if QUIT_Ninja.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_Ninja)
            timer.reset()
            return True
        if QUIT_MaidCafe.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_MaidCafe)
            timer.reset()
            return True
        if QUIT_SpringInn.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_SpringInn)
            timer.reset()
            return True
        if QUIT_GildedReverie.match_luma(self.device.image, offset=offset):
            self.device.click(QUIT_GildedReverie)
            timer.reset()
            return True
        return False

    def handle_combat_quit_reconfirm(self, interval=2):
        # QUIT_RECONFIRM 间隔应短于 QUIT，以便在 QUIT 间隔内多次重试
        if self.appear_then_click(QUIT_RECONFIRM, offset=(20, 20), interval=interval):
            # 重置 QUIT 计时器，避免重复点击 QUIT 取消 QUIT_RECONFIRM
            self.interval_reset(QUIT)
            return True
        return False

    def ensure_combat_oil_loaded(self):
        """等待战斗石油数值加载稳定。"""
        self.wait_until_stable(COMBAT_OIL_LOADING)

    def handle_combat_automation_confirm(self):
        """
        处理战斗自动化确认弹窗。

        Returns:
            是否点击了确认按钮。
        """
        if self.appear(AUTOMATION_CONFIRM_CHECK, threshold=30, interval=1):
            self.appear_then_click(AUTOMATION_CONFIRM, offset=(20, 20))
            return True

        return False

    def combat_preparation(self, balance_hp=False, emotion_reduce=False, auto='combat_auto', fleet_index=1):
        """
        战斗准备阶段：设置自动化模式、处理退役和情绪、等待进入战斗。

        Pages:
            in: BATTLE_PREPARATION
            out: is_combat_executing（暂停按钮可见）

        Args:
            balance_hp: 是否在战前进行血量平衡。
            emotion_reduce: 是否在战前等待情绪恢复。
            auto: 自动战斗模式，'combat_auto' 或其他模式。
            fleet_index: 舰队索引，1 或 2。
        """
        logger.info('Combat preparation.')
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        skip_first_screenshot = True
        interval_set = False

        if emotion_reduce:
            self.emotion.wait(fleet_index=fleet_index)
        if balance_hp:
            self.hp_balance()

        for _ in self.loop():

            if self.appear(BATTLE_PREPARATION, offset=(20, 20)):
                if self.handle_combat_automation_set(auto=auto == 'combat_auto'):
                    continue
            if self.handle_retirement():
                continue
            if self.handle_combat_low_emotion():
                continue
            if balance_hp and self.handle_emergency_repair_use():
                continue
            if self.handle_battle_preparation():
                continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue
            # 提前降低截图频率
            if not interval_set:
                if self.is_combat_loading():
                    self.device.screenshot_interval_set('combat')
                    interval_set = True

            # 检测到战斗执行中，退出准备阶段
            pause = self.is_combat_executing()
            if pause:
                logger.attr('BattleUI', pause)
                if emotion_reduce:
                    self.emotion.reduce(fleet_index)
                # 如果未检测到加载画面，兜底降低截图频率
                if not interval_set:
                    self.device.screenshot_interval_set('combat')
                break

    def handle_battle_preparation(self):
        """
        点击战斗准备按钮。

        Returns:
            是否点击了战斗准备按钮。
        """
        if self.appear_then_click(BATTLE_PREPARATION, offset=(20, 20), interval=2):
            return True

        return False

    def handle_combat_automation_set(self, auto):
        """
        设置战斗自动化开关状态。

        检测当前自动化状态（开/关），若与目标状态不一致则点击切换。

        Args:
            auto: 是否启用自动战斗。

        Returns:
            是否进行了切换操作。
        """
        if not self._automation_set_timer.reached():
            return False

        if self.appear(AUTOMATION_ON):
            logger.info('[Automation] ON')
            if not auto:
                self.device.click(AUTOMATION_SWITCH)
                self.device.sleep(1)
                self._automation_set_timer.reset()
                return True

        if self.appear(AUTOMATION_OFF):
            logger.info('[Automation] OFF')
            if auto:
                self.device.click(AUTOMATION_SWITCH)
                self.device.sleep(1)
                self._automation_set_timer.reset()
                return True

        if self.handle_combat_automation_confirm():
            self._automation_set_timer.reset()
            return True

        return False

    def handle_emergency_repair_use(self):
        if not self.config.HpControl_UseEmergencyRepair:
            return False

        if self.appear_then_click(EMERGENCY_REPAIR_CONFIRM, offset=True, interval=3):
            return True
        if self.appear(BATTLE_PREPARATION, offset=(20, 20)) and self.appear(EMERGENCY_REPAIR_AVAILABLE):
            # 进入战斗准备页面（或紧急维修后），紧急维修图标默认激活，即使没有可用道具。
            # 短暂动画后才会正常显示实际状态。
            # 使用舰队战力数值作为稳定检测器，先等待非零，再等待数值稳定。
            self.wait_until_disappear(MAIN_FLEET_POWER_ZERO, offset=(20, 20))
            stable_checker = Button(
                area=MAIN_FLEET_POWER_ZERO.area, color=(), button=MAIN_FLEET_POWER_ZERO.button, name='STABLE_CHECKER')
            self.wait_until_stable(stable_checker)
            if not self.appear(EMERGENCY_REPAIR_AVAILABLE):
                return False

            logger.info('EMERGENCY_REPAIR_AVAILABLE')
            if not len(self.hp):
                return False
            if max(self.hp[:3]) <= 0.001 or max(self.hp[3:]) <= 0.001:
                logger.warning(f'Invalid HP to use emergency repair: {self.hp}')
                return False

            hp = np.array(self.hp)
            hp = hp[hp > 0.001]
            if (len(hp) and np.min(hp) < self.config.HpControl_RepairUseSingleThreshold) \
                    or max(self.hp[:3]) < self.config.HpControl_RepairUseMultiThreshold \
                    or max(self.hp[3:]) < self.config.HpControl_RepairUseMultiThreshold:
                logger.info('Use emergency repair')
                self.device.click(EMERGENCY_REPAIR_AVAILABLE)
                self.interval_clear(EMERGENCY_REPAIR_CONFIRM)
                return True

        return False

    def combat_execute(self, auto='combat_auto', submarine='do_not_use', drop=None):
        """
        战斗执行阶段：处理自动/手动战斗、潜艇呼叫、弹窗，等待战斗结算。

        Pages:
            in: is_combat_executing（暂停按钮可见）
            out: BATTLE_STATUS / GET_ITEMS（战斗结算画面）

        Args:
            auto: 战斗模式，可选 'combat_auto'、'combat_manual'、'stand_still_in_the_middle'、'hide_in_bottom_left'。
            submarine: 潜艇模式，可选 'do_not_use'、'hunt_only'、'every_combat'。
            drop: 掉落记录对象，用于统计。
        """
        logger.info('Combat execute')
        self.submarine_call_reset()
        self.combat_auto_reset()
        self.combat_manual_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        confirm_timer = Timer(10)
        confirm_timer.start()

        for _ in self.loop():

            if not confirm_timer.reached():
                if self.handle_combat_automation_confirm():
                    continue

            if self.handle_story_skip():
                continue
            if self.handle_combat_auto(auto):
                continue
            if self.handle_combat_manual(auto):
                continue
            if auto != 'combat_auto' and self.auto_mode_checked and self.is_combat_executing():
                if self.handle_combat_weapon_release():
                    continue
            if self.handle_submarine_call(submarine):
                continue
            # 处理各种弹窗
            if self.handle_popup_confirm('COMBAT_EXECUTE'):
                continue
            if self.handle_urgent_commission():
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue

            # 战斗结算，退出循环
            if self.handle_battle_status(drop=drop) \
                    or self.handle_get_items(drop=drop):
                break

    def handle_battle_status(self, drop=None):
        """
        处理战斗结算画面（S/A/B/C/D 评价）。

        检测战斗是否仍在执行，然后按优先级匹配各评价等级的结算画面。

        Args:
            drop: 掉落记录对象，用于截图统计。

        Returns:
            是否点击了结算画面。
        """
        if self.is_combat_executing():
            return False
        if self.appear(BATTLE_STATUS_S, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_S)
            return True
        if self.appear(BATTLE_STATUS_A, interval=self.battle_status_click_interval):
            logger.warning('Battle status A')
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_A)
            return True
        if self.appear(BATTLE_STATUS_B, interval=self.battle_status_click_interval):
            logger.warning('Battle Status B')
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_B)
            return True
        if self.appear(BATTLE_STATUS_C, interval=self.battle_status_click_interval):
            logger.warning('Battle Status C')
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_C)
            return True
        if self.appear(BATTLE_STATUS_D, interval=self.battle_status_click_interval):
            logger.warning('Battle Status D')
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_D)
            return True

        return False

    def handle_get_items(self, drop=None):
        """
        处理战斗掉落物品画面。

        检测 GET_ITEMS_1/2/3 三种掉落画面并点击。

        Args:
            drop: 掉落记录对象，用于截图统计。

        Returns:
            是否点击了掉落画面。
        """
        if self.appear(GET_ITEMS_1, offset=5, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            self.device.click(GET_ITEMS_1)
            self.interval_reset(BATTLE_STATUS_S)
            self.interval_reset(BATTLE_STATUS_A)
            self.interval_reset(BATTLE_STATUS_B)
            return True
        if self.appear(GET_ITEMS_2, offset=5, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            self.device.click(GET_ITEMS_1)
            self.interval_reset(BATTLE_STATUS_S)
            self.interval_reset(BATTLE_STATUS_A)
            self.interval_reset(BATTLE_STATUS_B)
            return True
        if self.appear(GET_ITEMS_3, offset=5, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            self.device.click(GET_ITEMS_1)
            self.interval_reset(BATTLE_STATUS_S)
            self.interval_reset(BATTLE_STATUS_A)
            self.interval_reset(BATTLE_STATUS_B)
            return True

        return False

    def handle_exp_info(self):
        """
        处理经验结算画面（S/A/B 评价）。

        Returns:
            是否点击了经验结算画面。
        """
        if self.is_combat_executing():
            return False
        if self.appear_then_click(EXP_INFO_S):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(EXP_INFO_A):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(EXP_INFO_B):
            self.device.sleep((0.25, 0.5))
            return True

        return False

    def handle_get_ship(self, drop=None):
        """
        处理获得新舰船画面。

        检测 GET_SHIP 按钮并点击，若出现 NEW_SHIP 标记则记录新船获取。

        Args:
            drop: 掉落记录对象，用于截图统计。

        Returns:
            是否点击了获得舰船画面。
        """
        if self.appear_then_click(GET_SHIP, interval=1):
            if self.appear(NEW_SHIP):
                logger.info('Get a new SHIP')
                if drop:
                    drop.handle_add(self)
                self.config.GET_SHIP_TRIGGERED = True
            return True

        return False

    def handle_combat_mis_click(self):
        """
        处理战斗中的误点击（误入军需页面或演习页面）。

        Pages:
            in: MUNITIONS_CHECK 或 EXERCISE_CHECK
            out: 返回上一页面

        Returns:
            是否处理了误点击。
        """
        if self.appear(MUNITIONS_CHECK, offset=(20, 20), interval=5):
            logger.info(f'{MUNITIONS_CHECK} -> {BACK_ARROW}')
            self.device.click(BACK_ARROW)
            return True
        if self.appear(EXERCISE_CHECK, offset=(20, 20), interval=5):
            logger.info(f'{EXERCISE_CHECK} -> {BACK_ARROW}')
            self.device.click(BACK_ARROW)
            return True

        return False

    def combat_status(self, drop=None, expected_end=None):
        """
        战斗结算阶段：处理战斗评价、经验结算、掉落物品、新船获取等，直到回到预期页面。

        Pages:
            in: BATTLE_STATUS / GET_ITEMS（战斗结算画面）
            out: 根据 expected_end 返回不同页面（地图、关卡选择等）

        Args:
            drop: 掉落记录对象，用于截图统计。
            expected_end: 预期结束状态，可选 'with_searching'、'no_searching'、'in_stage'、'in_ui'，
                也可传入回调函数。
        """
        logger.info('Combat status')
        logger.attr('expected_end', expected_end.__name__ if callable(expected_end) else expected_end)
        self.device.screenshot_interval_set()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        battle_status = False
        exp_info = False  # 用于处理游戏白屏 bug
        for _ in self.loop():

            # 检测预期结束状态
            if isinstance(expected_end, str):
                if expected_end == 'in_stage' and self.handle_in_stage():
                    break
                if expected_end == 'with_searching' and self.handle_in_map_with_enemy_searching(drop=drop):
                    break
                if expected_end == 'no_searching' and self.handle_in_map_no_enemy_searching(drop=drop):
                    break
                if expected_end == 'in_ui' and self.appear(BACK_ARROW, offset=(30, 30)):
                    break
            if callable(expected_end):
                if expected_end():
                    break

            if self.handle_story_skip(drop=drop):
                continue
            # 处理战斗结算画面
            if not exp_info and self.handle_get_ship(drop=drop):
                continue
            if self.handle_get_items(drop=drop):
                continue
            if self.handle_popup_confirm('COMBAT_STATUS'):
                if battle_status and not exp_info:
                    logger.info('Locking a new ship')
                    self.config.GET_SHIP_TRIGGERED = True
                continue
            if not battle_status:
                if not exp_info and self.handle_battle_status(drop=drop):
                    battle_status = True
                    continue
                if self.handle_exp_info():
                    exp_info = True
                    continue
            else:
                # 战斗评价已点击后，优先检测经验结算画面
                if self.handle_exp_info():
                    exp_info = True
                    continue
                if not exp_info and self.handle_battle_status(drop=drop):
                    battle_status = True
                    continue
            # 处理各种弹窗
            if self.handle_popup_confirm('COMBAT_STATUS'):
                continue
            if self.handle_urgent_commission(drop=drop):
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue
            # 战斗中的额外处理器
            if self.handle_auto_search_exit(drop=drop):
                continue
            if self.handle_combat_mis_click():
                continue

            # 检测到关卡选择画面，退出循环
            if self.handle_in_stage():
                break
            if expected_end is None:
                if self.handle_in_map_with_enemy_searching(drop=drop):
                    break

    def combat(self, balance_hp=None, emotion_reduce=None, auto_mode=None, submarine_mode=None,
               save_get_items=None, expected_end=None, fleet_index=1):
        """
        执行一次完整战斗流程：准备 → 执行 → 结算。

        参数为 None 时使用用户配置文件中的默认值。

        Args:
            balance_hp: 是否进行血量平衡，None 时读取配置。
            emotion_reduce: 是否管理情绪，None 时读取配置。
            auto_mode: 战斗模式，可选 'combat_auto'、'combat_manual'、
                'stand_still_in_the_middle'、'hide_in_bottom_left'。
            submarine_mode: 潜艇模式，可选 'do_not_use'、'hunt_only'、'every_combat'。
            save_get_items: 是否保存掉落截图，可传入 DropImage 对象或 False 禁用。
            expected_end: 预期结束状态，可选字符串或回调函数。
            fleet_index: 舰队索引，1 或 2。
        """
        balance_hp = balance_hp if balance_hp is not None else self.config.HpControl_UseHpBalance
        emotion_reduce = emotion_reduce if emotion_reduce is not None else self.emotion.is_calculate
        if auto_mode is None:
            auto_mode = self.config.Fleet_Fleet1Mode if fleet_index == 1 else self.config.Fleet_Fleet2Mode
        if submarine_mode is None:
            submarine_mode = 'do_not_use'
            if self.config.Submarine_Fleet:
                submarine_mode = self.config.Submarine_Mode
        self.battle_status_click_interval = 7 if save_get_items else 0

        with self.stat.new(
                genre=self.config.campaign_name, method=self.config.DropRecord_CombatRecord
        ) as drop:
            if save_get_items is False:
                drop = None
            elif isinstance(save_get_items, DropImage):
                drop = save_get_items
            self.combat_preparation(
                balance_hp=balance_hp, emotion_reduce=emotion_reduce, auto=auto_mode, fleet_index=fleet_index)
            self.combat_execute(
                auto=auto_mode, submarine=submarine_mode, drop=drop)
            self.combat_status(
                drop=drop, expected_end=expected_end)

        logger.info('Combat end.')
