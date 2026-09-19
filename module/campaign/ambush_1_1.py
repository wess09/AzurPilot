"""1-1 伏击刷关模块，用于低耗练级和钻石 farming。

独立实现，不依赖 module.campaign.gems_farming 的 GemsFarming 类。
框架能力（船坞、装备码、退役、装备、UI、地图）通过继承链获得：
CampaignRun（战役运行框架）、FleetEquipment（舰队装备管理）、
Retirement（退役与船坞管理，其 MRO 链包含 Dock/Equipment/EquipmentCodeHandler）。

覆写 GemsFarming 的换船逻辑以支持编队中主舰队三个槽位的自动填充与更换。"""

from module.base.decorator import cached_property
from module.campaign.campaign_base import CampaignBase
from module.campaign.fleet_selection import FleetSelectionMixin
from module.campaign.run import CampaignRun
from module.combat.assets import BATTLE_PREPARATION, EXP_INFO_C, EXP_INFO_D, OPTS_INFO_D
from module.combat.emotion import Emotion
from module.equipment.assets import EMPTY_SHIP_R, FLEET_DETAIL, FLEET_DETAIL_CHECK, FLEET_NEXT, FLEET_PREV
from module.equipment.fleet_equipment import FleetEquipment, OCR_FLEET_INDEX
from module.exception import CampaignEnd, RequestHumanTakeover
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_HARD
from module.retire.assets import (
    DOCK_CHECK,
    DOCK_SHIP_DOWN,
    TEMPLATE_BOGUE,
    TEMPLATE_HERMES,
    TEMPLATE_LANGLEY,
    TEMPLATE_RANGER
)
from module.retire.retirement import Retirement
from module.retire.scanner import ShipScanner
from module.ui.assets import BACK_ARROW, FLEET_CHECK
from module.ui.page import page_fleet

SIM_VALUE = 0.9


class AmbushEmotion(Emotion):
    """1-1 伏击专用情绪管理类。

    重写情绪检查逻辑：当检测到低情绪时抛出 CampaignEnd 异常
    而不是等待恢复，以便触发舰船更换流程。
    """
    def check_reduce(self, battle):
        """
        重写 emotion.check_reduce()。
        进入战役前检查情绪值。

        Args:
            battle (int): 本战役中的战斗次数。

        Raises:
            CampaignEnd: 暂停当前任务以避免未来的情绪控制问题。
        """
        if not self.is_calculate:
            return

        recovered, delay = self._check_reduce(battle)
        if delay:
            self.config.GEMS_EMOTION_TRIGGERED = True
            logger.info('[战役-伏击] 检测到低情绪，暂停当前任务')
            raise CampaignEnd('Emotion control')

    def wait(self, fleet_index):
        pass


class AmbushCampaignOverride(CampaignBase):
    """1-1 伏击专用战役覆写类。

    覆写 CampaignBase 的战斗低情绪处理和经验结算处理：
    - 低情绪时根据配置选择忽略警告或撤退换船
    - 支持多种经验结算弹窗的点击处理
    """
    def handle_combat_low_emotion(self):
        """
        重写 info_handler.handle_combat_low_emotion()。
        如果启用了更换先锋，撤出战斗并更换旗舰和先锋。
        """
        if self.config.GemsFarming_IgnoreEmotionWarning or self.config.GemsFarming_ChangeVanguard == 'disabled':
            result = self.handle_popup_confirm('IGNORE_LOW_EMOTION')
            if result:
                # 避免点击 AUTO_SEARCH_MAP_OPTION_OFF
                self.interval_reset(AUTO_SEARCH_MAP_OPTION_OFF)
                if self.config.GemsFarming_IgnoreEmotionWarning and self.config.GemsFarming_ChangeVanguard != 'disabled':
                    self.config.GEMS_EMOTION_TRIGGERED = True
            return result

        if self.handle_popup_cancel('IGNORE_LOW_EMOTION'):
            self.config.GEMS_EMOTION_TRIGGERED = True
            logger.hr('[战役-伏击] 情绪撤退')

            while 1:
                self.device.screenshot()

                if self.handle_story_skip():
                    continue
                if self.handle_popup_cancel('IGNORE_LOW_EMOTION'):
                    continue

                if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                    self.device.click(BACK_ARROW)
                    continue
                if self.handle_auto_search_exit():
                    continue
                if self.is_in_stage():
                    break

                if self.is_in_map():
                    self.withdraw()
                    break

                if self.appear(FLEET_PREPARATION, offset=(20, 50), interval=2) \
                        or self.appear(MAP_PREPARATION, offset=(20, 20), interval=2) \
                        or self.appear(MAP_PREPARATION_HARD, offset=(20, 20), interval=2):
                    self.enter_map_cancel()
                    break
            raise CampaignEnd('Emotion withdraw')

    def handle_exp_info(self):
        if self.is_combat_executing():
            return False
        if super().handle_exp_info():
            return True
        if self.appear_then_click(EXP_INFO_C, threshold=10):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(EXP_INFO_D):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(OPTS_INFO_D, offset=True, similarity=0.9):
            self.device.sleep((0.25, 0.5))
            return True
        return False


class Ambush11(FleetSelectionMixin, CampaignRun, FleetEquipment, Retirement):
    """1-1 伏击刷关任务主类。

    组合战役运行、舰队装备管理、退役与船坞管理能力，
    实现完整的 1-1 伏击刷关自动化流程。

    核心流程：
    1. 加载 1-1 地图并以普通稀有度航母为旗舰出击
    2. 在 B1/C1 之间来回移动触发伏击战斗
    3. 监控旗舰等级和情绪值，达到 32 级或情绪过低时更换新船
    4. 可选同时更换先锋驱逐舰
    5. 通过装备码自动装卸旗舰/先锋装备

    Attributes:
        _trigger_lv32 (bool): 是否触发了等级 32 限制。
        _trigger_emotion (bool): 是否触发了情绪限制。
        hard_mode (bool): 是否处于困难模式（影响舰队进入方式）。
        page_fleet_check_button (Button): 舰队页面的检查按钮。
        fleet_detail_enter_flagship (Button): 进入旗舰详情的按钮。
        fleet_detail_enter (Button): 进入先锋详情的按钮。
        fleet_enter_flagship (Button): 从船坞进入旗舰位的按钮。
        fleet_enter (Button): 从船坞进入先锋位的按钮。
    """
    _trigger_lv32 = False
    _trigger_emotion = False
    # 初始旗舰等级检查是否已完成（进程内持久化，说明见 GemsFarming 同名字段）。
    _initial_flagship_check_done = False

    # ==================== 配置属性 ====================

    @property
    def emotion_lower_bound(self):
        """情绪值下限，根据当前地图的战斗次数动态计算。"""
        return 4 + self.campaign._map_battle * 2

    @property
    def change_flagship(self):
        """配置中包含 'ship' 时返回 True。"""
        return 'ship' in self.config.GemsFarming_ChangeFlagship

    @property
    def change_flagship_equip(self):
        """配置中包含 'equip' 时返回 True。"""
        return 'equip' in self.config.GemsFarming_ChangeFlagship

    @property
    def change_vanguard(self):
        """配置中包含 'ship' 时返回 True。"""
        return 'ship' in self.config.GemsFarming_ChangeVanguard

    @property
    def change_vanguard_equip(self):
        """配置中包含 'equip' 时返回 True。"""
        return 'equip' in self.config.GemsFarming_ChangeVanguard

    @property
    def fleet_to_attack(self):
        """获取出击舰队编号，fleet1_standby_fleet2_all 模式下使用第二舰队。"""
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            return self.config.Fleet_Fleet2
        else:
            return self.config.Fleet_Fleet1

    # ==================== 装备码 ====================

    @property
    def equipment_code_config_key(self):
        """获取装备码配置的键路径，如 'Ambush11.GemsFarming.EquipmentCode'。"""
        command = self.config.task.command if hasattr(self.config, 'task') and self.config.task else 'Ambush11'
        return f"{command}.GemsFarming.EquipmentCode"

    def current_ship(self, skip_first_screenshot=True):
        """
        复用 module.retire.assets 中的模板，需要不同的缩放比例来匹配当前旗舰。

        Pages:
            in: gear_code
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            # 结束条件
            if not self.appear(EMPTY_SHIP_R):
                break
            else:
                logger.info('[战役-伏击] 等待舰船图标加载。')

        if TEMPLATE_BOGUE.match(self.device.image, scaling=1.46):  # image has rotation
            return 'bogue'
        if TEMPLATE_HERMES.match(self.device.image, scaling=124 / 89):
            return 'hermes'
        if TEMPLATE_RANGER.match(self.device.image, scaling=4 / 3):
            return 'ranger'
        if TEMPLATE_LANGLEY.match(self.device.image, scaling=25 / 21):
            return 'langley'
        return 'DD'

    def clear_all_equip(self):
        """导出当前旗舰的装备码并清空所有装备。

        Returns:
            bool: 是否成功清空。

        Raises:
            RequestHumanTakeover: 装备码导出失败时抛出，防止装备状态丢失。
        """
        success = self.code_clear()
        if not success:
            logger.warning('[战役-伏击] 装备码导出失败，停止换船以避免装备状态丢失。')
            raise RequestHumanTakeover
        return success

    def apply_equip_code(self, code=None):
        """应用装备码到当前舰船。

        Args:
            code (str, optional): 装备码字符串。为 None 时使用上次导出的装备码。

        Returns:
            bool: 是否成功应用。

        Raises:
            RequestHumanTakeover: 装备码应用失败时抛出。
        """
        if code is None:
            success = self.code_apply()
        else:
            success = self._code_apply(code=code)
        if not success:
            logger.warning('[战役-伏击] 装备码应用失败，请人工检查当前舰队装备。')
            raise RequestHumanTakeover
        return success

    # ==================== 模式与页面导航 ====================


    def load_campaign(self, name, folder='campaign_main'):
        """加载战役地图模块并注入伏击专用覆写。

        在父类 load_campaign() 基础上，将 Campaign 替换为继承了
        AmbushCampaignOverride 的子类，注入 AmbushEmotion 情绪管理。
        根据是否更换先锋舰船设置情绪管理模式。

        Args:
            name (str): 地图文件名。
            folder (str): 地图文件夹名。
        """
        super().load_campaign(name, folder)

        class AmbushCampaign(AmbushCampaignOverride, self.module.Campaign):

            @cached_property
            def emotion(self) -> AmbushEmotion:
                return AmbushEmotion(config=self.config)

        self.campaign = AmbushCampaign(device=self.campaign.device, config=self.campaign.config)
        if self.change_vanguard:
            self.campaign.config.override(Emotion_Mode='ignore_calculate')
            self.campaign.config.override(EnemyPriority_EnemyScaleBalanceWeight='S1_enemy_first')
        else:
            self.campaign.config.override(Emotion_Mode='ignore')

    def _fleet_detail_enter(self, fleet):
        """进入指定舰队的编辑页面（普通模式）。

        Args:
            fleet (int): 舰队编号。
        """
        self.ui_ensure(page_fleet)
        self.ui_ensure_index(fleet, letter=OCR_FLEET_INDEX,
                             next_button=FLEET_NEXT, prev_button=FLEET_PREV, skip_first_screenshot=True)

    def _ship_detail_enter(self, button):
        """进入指定舰船的装备详情页面（普通模式）。

        从舰队页面进入舰队详情，再进入指定舰船的装备页面。

        Args:
            button (Button): 舰船位置的按钮。
        """
        self.ui_click(FLEET_DETAIL, appear_button=page_fleet.check_button,
                      check_button=FLEET_DETAIL_CHECK, skip_first_screenshot=True)
        self.equip_enter(button, long_click=False)


    def _ship_detail_enter_hard(self, button):
        """进入指定舰船的装备详情页面（困难模式）。

        困难模式下直接通过装备进入按钮操作。

        Args:
            button (Button): 舰船位置的按钮。
        """
        self.equip_enter(button)

    def _fleet_back(self):
        """从装备详情返回到舰队页面（普通模式）。"""
        self.ui_back(FLEET_DETAIL_CHECK)
        self.ui_back(FLEET_CHECK)

    def _fleet_back_hard(self):
        """从装备详情返回到准备页面（困难模式）。"""
        self.ui_back(self.page_fleet_check_button)

    def _dock_reset(self):
        """重置船坞筛选和排序状态。"""
        self.dock_favourite_set(False, wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        self.dock_filter_set()

    def _ship_change_confirm(self, button):
        """选择舰船并确认更换。

        Args:
            button (Button): 要选择的舰船按钮。
        """
        self.dock_select_one(button)
        self._dock_reset()
        self.dock_select_confirm(check_button=self.page_fleet_check_button)

    def ship_down_hard(self):
        """困难模式下将舰船从舰队中移除。

        如果存在离队按钮则点击，否则返回准备页面。
        """
        if self.appear(DOCK_SHIP_DOWN):
            self.ui_click(DOCK_SHIP_DOWN,
                            appear_button=DOCK_CHECK, check_button=self.page_fleet_check_button, skip_first_screenshot=True)
        else:
            self.ui_back(check_button=FLEET_PREPARATION)


    # ==================== 更换旗舰/先锋 ====================


    def flagship_change_with_emotion(self, ship):
        """更换旗舰并计算情绪值。"""
        target_ship = max(ship, key=lambda s: (s.level, s.emotion))
        if self.change_vanguard:
            self.set_emotion(min(self.get_emotion(), target_ship.emotion))
        elif self.config.GemsFarming_AllowHighFlagshipLevel:
            self.set_emotion(target_ship.emotion)
        self._ship_change_confirm(target_ship.button)

    def vanguard_change_with_emotion(self, ship):
        """更换先锋并计算情绪值。"""
        target_ship = max(ship, key=lambda s: s.emotion)
        if self.change_vanguard:
            self.set_emotion(target_ship.emotion)
        self._ship_change_confirm(target_ship.button)

    def flagship_change_execute(self):
        """
        执行旗舰更换，填充主舰队 3 个后排槽位。

        Returns:
            bool: 是否成功。

        Pages:
            in: page_fleet
            out: page_fleet
        """
        from module.base.button import Button

        # Coordinates for the 3 rear ships in Formation screen
        MAIN_1 = Button(area=(771, 80, 832, 106), color=(), button=(771, 80, 832, 106), name='FLEET_ENTER_MAIN_1')
        MAIN_3 = Button(area=(771, 320, 832, 346), color=(), button=(771, 320, 832, 346), name='FLEET_ENTER_MAIN_3')
        MAIN_2 = Button(area=(771, 200, 832, 226), color=(), button=(771, 200, 832, 226), name='FLEET_ENTER_MAIN_2')

        success = False
        # Main 2 is flagship and must be set first to avoid empty fleet errors
        for button in [MAIN_2]:
            if self.hard_mode:
                if not self.dock_enter(self.fleet_detail_enter_flagship):
                    continue
                self.ship_down_hard()

            if not self.dock_enter(button):
                continue

            ship = self.get_common_rarity_cv()
            if ship:
                self.flagship_change_with_emotion(ship)
                logger.info(f'[战役-伏击] 更换旗舰 {button.name} 成功')
                success = True
            else:
                logger.info(f'[战役-伏击] 更换旗舰 {button.name} 失败，无通用稀有度航母')
                if self.config.SERVER in ['cn']:
                    max_level = 100
                else:
                    max_level = 70
                # Fallback logic
                ship = self.get_common_rarity_cv(lv=max_level, emotion=0)
                if ship and self.hard_mode:
                    self.flagship_change_with_emotion(ship)
                else:
                    if self.hard_mode:
                        raise RequestHumanTakeover
                    self._dock_reset()
                    self.ui_back(check_button=self.page_fleet_check_button)

        return success

    def vanguard_change_execute(self):
        """
        执行先锋更换，使用正确的先锋点击坐标。

        Returns:
            bool: 是否成功。

        Pages:
            in: page_fleet
            out: page_fleet
        """
        from module.base.button import Button
        VANGUARD_1 = Button(area=(315, 256, 397, 331), color=(), button=(315, 256, 397, 331), name='FLEET_ENTER_VANGUARD_1')

        if self.hard_mode:
            if not self.dock_enter(self.fleet_detail_enter):
                return True
            self.ship_down_hard()
        if not self.dock_enter(VANGUARD_1):
            return True

        ship = self.get_common_rarity_dd()
        if ship:
            self.vanguard_change_with_emotion(ship)
            logger.info('更换前排舰船成功')
            return True
        else:
            logger.info('更换前排舰船失败，无通用稀有度驱逐舰。')
            ship = self.get_common_rarity_dd(emotion=0)
            if ship and self.hard_mode:
                self.vanguard_change_with_emotion(ship)
            else:
                if self.hard_mode:
                    raise RequestHumanTakeover
                self._dock_reset()
                self.ui_back(check_button=self.page_fleet_check_button)
            return False

    # ==================== 选船逻辑 ====================


    def get_common_rarity_dd(self, emotion=16):
        """
        Ambush 1-1 specific DD finding logic.
        Ensures level limits are strictly followed and defaults to < 28 if not set.
        """
        # Strictly follow GUI settings
        min_level = self.config.GemsFarming_VanguardLevelMin
        max_level = self.config.GemsFarming_VanguardLevelMax

        # User explicitly requested 28 as default for 1-1
        # If it's still at absolute defaults (1, 125), we force it to 1-28
        if min_level <= 1 and max_level >= 125:
            logger.info('[战役-伏击] 前排等级限制为默认值(1-125)，强制改为1-28')
            max_level = 28

        logger.info(f'查找等级前排: {min_level} ~ {max_level}')

        # Implementation similar to GemsFarming but without the 100-level fallback
        rarity = 'common'
        extra = 'can_limit_break'
        if self.config.GemsFarming_CommonDD in ['any', 'custom']:
            faction = ['eagle', 'iron']
        elif self.config.GemsFarming_CommonDD == 'favourite':
            faction = 'all'
        elif self.config.GemsFarming_CommonDD == 'z20_or_z21':
            faction = 'iron'
        elif self.config.GemsFarming_CommonDD == 'DDG':
            faction = 'dragon'
            rarity = 'super_rare'
            extra = 'no_limit'
        elif self.config.GemsFarming_CommonDD in ['aulick_or_foote', 'cassin_or_downes']:
            faction = 'eagle'
        else:
            faction = ['eagle', 'iron']

        favourite = self.config.GemsFarming_CommonDD == 'favourite'
        self.dock_favourite_set(favourite, wait_loading=False)
        self.dock_sort_method_dsc_set(True, wait_loading=False)
        self.dock_filter_set(index='dd', rarity=rarity, faction=faction, extra=extra)

        emotion_lower_bound = 0 if emotion == 0 else self.emotion_lower_bound
        scanner = ShipScanner(level=(min_level, max_level), emotion=(emotion_lower_bound, 150),
                              fleet=[0, self.fleet_to_attack], status='free')
        scanner.disable('rarity')

        if self.config.GemsFarming_UseEmotionFirst:
            if self.config.GemsFarming_CommonDD == 'custom':
                filter_string = self.config.GemsFarming_CommonDDFilter
                common_ship = self.get_common_ship_filter(filter_string, ship_type='dd')
            elif self.config.GemsFarming_CommonDD == 'any':
                filter_string = self.config.COMMON_DD_FILTER
                common_ship = self.get_common_ship_filter(filter_string, ship_type='dd')
            elif self.config.GemsFarming_CommonDD == 'cassin_or_downes':
                common_ship = ['cassin', 'downes']
            elif self.config.GemsFarming_CommonDD == 'aulick_or_foote':
                common_ship = ['aulick', 'foote']
            elif self.config.GemsFarming_CommonDD == 'z20_or_z21':
                common_ship = ['z20', 'z21']
            else:
                common_ship = None

            if common_ship is not None:
                candidates = self.find_all_vanguard_candidates(scanner, common_ship)
                if candidates:
                    return candidates

                logger.info('未找到指定驱逐舰，尝试反向顺序。')
                self.dock_sort_method_dsc_set(False)
                candidates = self.find_all_vanguard_candidates(scanner, common_ship)
                if not candidates and self.config.GemsFarming_CommonDD == 'custom':
                    return scanner.scan(self.device.image, output=False)
                return candidates
            else:
                candidates = scanner.scan(self.device.image, output=False)
                if candidates:
                    candidates.sort(key=lambda s: s.emotion, reverse=True)
                    return candidates

        if self.config.GemsFarming_CommonDD in ['any', 'favourite', 'z20_or_z21', 'DDG']:
            return scanner.scan(self.device.image)
        elif self.config.GemsFarming_CommonDD == 'custom':
            candidates = self.find_custom_candidates(scanner, ship_type='dd')
            return candidates if candidates else scanner.scan(self.device.image, output=False)
        else:
            candidates = self.find_candidates(self.get_templates(self.config.GemsFarming_CommonDD), scanner)
            if candidates:
                return candidates
            self.dock_sort_method_dsc_set(False)
            return self.find_candidates(self.get_templates(self.config.GemsFarming_CommonDD), scanner)


    # ==================== 停止条件与情绪 ====================

    def get_emotion(self):
        """从配置中获取舰队情绪值。"""
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            return self.campaign.config.Emotion_Fleet2Value
        else:
            return self.campaign.config.Emotion_Fleet1Value

    def set_emotion(self, emotion):
        """设置舰队情绪值。"""
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            self.campaign.config.set_record(Emotion_Fleet2Value=emotion)
        else:
            self.campaign.config.set_record(Emotion_Fleet1Value=emotion)


    # ==================== 运行器 ====================

    def run(self, name='campaign_1_1_f', folder='campaign_main', mode='normal', total=0):
        """
        Specialized runner for 1-1 Ambush.
        Forces auto-search and clear mode off, then uses the ship
        switching logic before executing the map script.
        """
        logger.hr('1-1伏击运行器', level=1)

        # Enforce manual play and disable clear mode options
        self.config.override(Campaign_UseClearMode=False, Campaign_UseAutoSearch=False)
        self.config.override(Campaign_Name=name, Campaign_Event=folder)

        name, folder = self.handle_stage_name(name, folder, mode=mode)
        self.load_campaign(name, folder=folder)

        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount

        self.config.STOP_IF_REACH_LV32 = self.change_flagship and not self.config.GemsFarming_AllowHighFlagshipLevel
        initial_check = (
            self.change_flagship
            and not self.config.GemsFarming_AllowHighFlagshipLevel
            and not Ambush11._initial_flagship_check_done
        )
        Ambush11._initial_flagship_check_done = True

        while 1:
            self._trigger_lv32 = initial_check
            initial_check = False
            is_limit = self.config.StopCondition_RunCount

            # Use the map script's run inside loop for standard behavior
            try:
                # We do not use super().run here because it loops infinitely inside map.
                # However, campaign_1_1_f loops infinitely inside itself!
                # So we simply ensure UI, do configs, handle ships, then call campaign.run() and handle End exceptions.
                logger.hr(name, level=1)
                if self.config.StopCondition_RunCount > 0:
                    logger.info(f'[战役-伏击] 剩余次数: {self.config.StopCondition_RunCount}')
                else:
                    logger.info(f'[战役-伏击] 计数: {self.run_count}')

                self.device.stuck_record_clear()
                self.device.click_record_clear()
                if not self.device.has_cached_image:
                    self.device.screenshot()
                self.campaign.device.image = self.device.image

                if self.campaign.is_in_map():
                    logger.info('[战役-伏击] 已在地图中，撤退中')
                    try:
                        self.campaign.withdraw()
                    except CampaignEnd:
                        pass

                self.campaign.ensure_campaign_ui(name=self.stage, mode=mode)
                self.disable_raid_on_event()
                self.handle_commission_notice()

                # Check level to trigger ship switching
                self.campaign.lv_get()

                if self.triggered_stop_condition(oil_check=False):
                    if self._trigger_lv32 or self._trigger_emotion:
                        # Ship switching triggered, skip run and proceed to switching block
                        pass
                    else:
                        break
                else:
                    self.device.stuck_record_clear()
                    self.device.click_record_clear()
                    # Run map loop
                    self.campaign.run()

            except CampaignEnd as e:
                # E.g. ship leveled up or emotion triggered, handled normally
                if e.args[0] == 'Emotion control':
                    self._trigger_emotion = True
                elif e.args[0] == 'Emotion withdraw':
                    self._trigger_emotion = True
                    self.set_emotion(0)
                pass

            # Post-run ship switching block
            if self._trigger_lv32 or self._trigger_emotion:
                success = True
                self.hard_mode_override()
                emotion = self.get_emotion()
                if self.change_flagship:
                    success = self.flagship_change()
                if self.change_vanguard and success:
                    success = self.vanguard_change()
                    if not success and self.config.GemsFarming_AllowHighFlagshipLevel:
                        self.set_emotion(emotion)

                if is_limit and self.config.StopCondition_RunCount <= 0:
                    logger.hr('[战役-伏击] 触发停止条件: 运行次数')
                    self.config.StopCondition_RunCount = 0
                    self.config.Scheduler_Enable = False
                    break

                self._trigger_lv32 = False
                self.config.LV32_TRIGGERED = False
                self.campaign.config.LV32_TRIGGERED = False
                self.campaign.config.GEMS_EMOTION_TRIGGERED = False

                if self.config.task_switched():
                    self._trigger_emotion = False
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_stop()
                elif not success and (self.config.GemsFarming_DelayTaskIFNoFlagship \
                        or self._trigger_emotion):
                    self._trigger_emotion = False
                    self.config.task_delay(server_update=True)
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_stop()

            else:
                # If we legitimately exited the map script without exception, we're likely done with runs.
                break
