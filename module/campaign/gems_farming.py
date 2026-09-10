"""
钻石 farming（紧急委托刷钻石）模块。

实现通过反复刷低难度关卡触发紧急委托获取钻石的自动化流程。核心逻辑：
- 使用普通稀有度航母作为旗舰（低等级，退役后可重复获取）
- 可选更换先锋驱逐舰
- 支持旗舰/先锋的装备码自动装卸
- 情绪值监控：低情绪时自动更换舰船
- 等级 32 限制：旗舰达到 32 级时自动更换（可关闭）
- 困难模式适配：困难模式下使用不同的舰队进入方式

典型使用场景：刷 2-4 关卡，旗舰升级到 32 级后更换新的 1 级航母，
通过紧急委托获取钻石。

依赖关系：
- CampaignRun：战役运行框架
- FleetEquipment：装备管理
- EquipmentCodeHandler：装备码导入导出
- Retirement：退役与船坞管理
"""

from module.base.decorator import cached_property
from module.campaign.assets import CHAPTER_NEXT, CHAPTER_PREV
from module.campaign.campaign_base import CampaignBase
from module.campaign.run import CampaignRun
from module.combat.assets import BATTLE_PREPARATION, EXP_INFO_C, EXP_INFO_D, OPTS_INFO_D
from module.combat.emotion import Emotion
from module.equipment.assets import (
    EMPTY_SHIP_R,
    FLEET_DETAIL, FLEET_DETAIL_CHECK, FLEET_DETAIL_ENTER, FLEET_DETAIL_ENTER_FLAGSHIP,
    FLEET_DETAIL_ENTER_FLAGSHIP_HARD_1, FLEET_DETAIL_ENTER_FLAGSHIP_HARD_2,
    FLEET_DETAIL_ENTER_HARD_1, FLEET_DETAIL_ENTER_HARD_2,
    FLEET_ENTER, FLEET_ENTER_FLAGSHIP,
    FLEET_ENTER_FLAGSHIP_HARD_1, FLEET_ENTER_FLAGSHIP_HARD_2,
    FLEET_ENTER_HARD_1, FLEET_ENTER_HARD_2,
    FLEET_NEXT, FLEET_PREV
)
from module.equipment.equipment_code import EquipmentCodeHandler
from module.equipment.fleet_equipment import FleetEquipment, OCR_FLEET_INDEX
from module.exception import CampaignEnd, HardNotSatisfied, ScriptError, RequestHumanTakeover
from module.retire.retirement import Retirement, TEMPLATE_COMMON_CV, TEMPLATE_COMMON_DD
from module.retire.assets import DOCK_CHECK, DOCK_SHIP_DOWN, TEMPLATE_BOGUE, TEMPLATE_HERMES, TEMPLATE_LANGLEY, TEMPLATE_RANGER, TEMPLATE_CASSIN_1, TEMPLATE_CASSIN_2, TEMPLATE_DOWNES_1, TEMPLATE_DOWNES_2, TEMPLATE_AULICK, TEMPLATE_FOOTE
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_HARD
from module.retire.scanner import ShipScanner
from module.ui.assets import BACK_ARROW, FLEET_CHECK
from module.ui.page import page_fleet

SIM_VALUE = 0.9


class GemsEmotion(Emotion):
    """钻石 farming 专用情绪管理类。

    重写情绪检查逻辑：当检测到低情绪时抛出 CampaignEnd 异常
    而不是等待恢复，以便触发舰船更换流程。

    Attributes:
        继承自 Emotion 的所有属性。
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
            logger.info('[钻石打捞] 检测到低情绪，暂停当前任务')
            raise CampaignEnd('Emotion control')

    def wait(self, fleet_index):
        pass


class GemsCampaignOverride(CampaignBase):
    """钻石 farming 专用战役覆写类。

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
            logger.hr('[战役-紧急委托] 情绪撤退')

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


class GemsEquipmentHandler(EquipmentCodeHandler):
    """钻石 farming 装备处理器。

    继承 EquipmentCodeHandler，提供装备码的导入导出功能。
    根据当前旗舰类型（航母/驱逐舰）自动识别装备码配置路径。

    Attributes:
        继承自 EquipmentCodeHandler 的所有属性。
    """


    def __init__(self, config, device=None, task=None):
        super().__init__(config=config, device=device, task=task)

    @property
    def equipment_code_config_key(self):
        """获取装备码配置的键路径。

        Returns:
            str: 配置键路径，如 'GemsFarming.GemsFarming.EquipmentCode'。
        """
        command = self.config.task.command if hasattr(self.config, 'task') and self.config.task else 'GemsFarming'
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
                logger.info('[战役-紧急委托] 等待舰船图标加载。')

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

        通过装备码功能保存当前装备配置后卸下所有装备，
        以便后续应用到新旗舰上。

        Returns:
            bool: 是否成功清空。

        Raises:
            RequestHumanTakeover: 装备码导出失败时抛出，防止装备状态丢失。
        """
        success = self.code_clear()
        if not success:
            logger.warning('[战役-紧急委托] 装备码导出失败，停止换船以避免装备状态丢失。')
            raise RequestHumanTakeover
        return success

    def apply_equip_code(self, code=None):
        """应用装备码到当前舰船。

        将之前导出的装备码应用到新旗舰上，恢复装备配置。

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
            logger.warning('[战役-紧急委托] 装备码应用失败，请人工检查当前舰队装备。')
            raise RequestHumanTakeover
        return success


class GemsFarming(CampaignRun, FleetEquipment, GemsEquipmentHandler, Retirement):
    """钻石 farming 任务主类。

    组合战役运行、装备管理、装备码处理和退役管理的能力，
    实现完整的钻石 farming 自动化流程。

    核心流程：
    1. 加载战役地图并以普通稀有度航母为旗舰出击
    2. 监控旗舰等级和情绪值
    3. 旗舰达到 32 级或情绪过低时，自动更换新的低等级航母
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

    def hard_mode_override(self):
        """根据当前战役模式切换舰队进入方式。

        困难模式下使用不同的按钮进入舰队编辑页面（通过战役准备界面），
        普通模式下直接通过 page_fleet 进入。根据舰队顺序配置选择
        对应的旗舰/先锋进入按钮。
        """
        if self.campaign.config.Campaign_Mode == 'hard':
            logger.info('[钻石打捞] 在困难模式，切换换船方式')
            self.hard_mode = True
            self._ship_detail_enter = self._ship_detail_enter_hard
            self._fleet_detail_enter = self._fleet_detail_enter_hard
            self._fleet_back = self._fleet_back_hard
            self.page_fleet_check_button = FLEET_PREPARATION
            if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
                self.fleet_detail_enter_flagship = FLEET_DETAIL_ENTER_FLAGSHIP_HARD_2
                self.fleet_enter_flagship = FLEET_ENTER_FLAGSHIP_HARD_2
                self.fleet_detail_enter = FLEET_DETAIL_ENTER_HARD_2
                self.fleet_enter = FLEET_ENTER_HARD_2
            else:
                self.fleet_detail_enter_flagship = FLEET_DETAIL_ENTER_FLAGSHIP_HARD_1
                self.fleet_enter_flagship = FLEET_ENTER_FLAGSHIP_HARD_1
                self.fleet_detail_enter = FLEET_DETAIL_ENTER_HARD_1
                self.fleet_enter = FLEET_ENTER_HARD_1
        else:
            self.hard_mode = False
            self.page_fleet_check_button = page_fleet.check_button
            self.fleet_detail_enter_flagship = FLEET_DETAIL_ENTER_FLAGSHIP
            self.fleet_detail_enter = FLEET_DETAIL_ENTER
            self.fleet_enter_flagship = FLEET_ENTER_FLAGSHIP
            self.fleet_enter = FLEET_ENTER

    def load_campaign(self, name, folder='campaign_main'):
        """加载战役地图模块并注入钻石 farming 专用覆写。

        在父类 load_campaign() 基础上，将 Campaign 替换为继承了
        GemsCampaignOverride 的子类，注入 GemsEmotion 情绪管理。
        根据是否更换先锋舰船设置情绪管理模式。

        Args:
            name (str): 地图文件名。
            folder (str): 地图文件夹名。
        """
        super().load_campaign(name, folder)

        class GemsCampaign(GemsCampaignOverride, self.module.Campaign):


            @cached_property
            def emotion(self) -> GemsEmotion:
                return GemsEmotion(config=self.config)

        self.campaign = GemsCampaign(device=self.campaign.device, config=self.campaign.config)
        if self.change_vanguard:
            self.campaign.config.override(Emotion_Mode='ignore_calculate')
            self.campaign.config.override(EnemyPriority_EnemyScaleBalanceWeight='S1_enemy_first')
        else:
            self.campaign.config.override(Emotion_Mode='ignore')

    @property
    def emotion_lower_bound(self):
        """情绪值下限。

        根据当前地图的战斗次数动态计算情绪值下限，
        确保舰船在整场战役中有足够的情绪值。

        Returns:
            int: 情绪值下限。
        """
        return 4 + self.campaign._map_battle * 2

    @property
    def change_flagship(self):
        """是否需要更换旗舰舰船。

        Returns:
            bool: 配置中包含 'ship' 时返回 True。
        """
        return 'ship' in self.config.GemsFarming_ChangeFlagship

    @property
    def change_flagship_equip(self):
        """是否需要更换旗舰装备。

        Returns:
            bool: 配置中包含 'equip' 时返回 True。
        """
        return 'equip' in self.config.GemsFarming_ChangeFlagship

    @property
    def change_vanguard(self):
        """是否需要更换先锋舰船。

        Returns:
            bool: 配置中包含 'ship' 时返回 True。
        """
        return 'ship' in self.config.GemsFarming_ChangeVanguard

    @property
    def change_vanguard_equip(self):
        """是否需要更换先锋装备。

        Returns:
            bool: 配置中包含 'equip' 时返回 True。
        """
        return 'equip' in self.config.GemsFarming_ChangeVanguard

    @property
    def fleet_to_attack(self):
        """获取出击舰队编号。

        根据舰队顺序配置返回实际使用的舰队编号。
        fleet1_standby_fleet2_all 模式下使用第二舰队。

        Returns:
            int: 舰队编号。
        """
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            return self.config.Fleet_Fleet2
        else:
            return self.config.Fleet_Fleet1

    def _fleet_detail_enter(self, fleet):
        """进入指定舰队的编辑页面（普通模式）。

        通过 page_fleet 导航到指定舰队。

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

    def _fleet_detail_enter_hard(self, fleet):
        """进入指定舰队的编辑页面（困难模式）。

        困难模式下通过战役准备界面进入舰队编辑，
        需要先导航到关卡入口并进入准备界面。

        Args:
            fleet (int): 舰队编号（困难模式下未使用，固定通过准备界面进入）。
        """
        if self.appear(FLEET_PREPARATION, offset=(20, 50)):
            return
        self.campaign.ensure_campaign_ui(self.stage)
        self.ui_click(
            click_button=self.campaign.ENTRANCE,
            appear_button=BACK_ARROW,
            check_button=lambda: self.appear(MAP_PREPARATION, offset=(20, 20))
            or self.appear(MAP_PREPARATION_HARD, offset=(20, 20)),
        )
        while 1:
            self.device.screenshot()

            if self.appear_then_click(MAP_PREPARATION, interval=1):
                continue
            if self.appear_then_click(MAP_PREPARATION_HARD, interval=1):
                continue

            if self.handle_retirement():
                continue

            # 退役/强化流程会离开关卡准备界面并退回关卡选择界面，
            # 此时关卡入口重新可见，需要重新点进去，
            # 否则循环会一直等不到 FLEET_PREPARATION 而卡死
            if self.appear_then_click(self.campaign.ENTRANCE, interval=2):
                continue

            if self.appear(FLEET_PREPARATION, offset=(20, 50)):
                break

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

    def flagship_change(self):
        """
        更换旗舰并使用装备码更换旗舰装备。

        Returns:
            bool: 是否成功更换旗舰。
        """

        logger.hr('更换旗舰', level=1)
        logger.attr('更换旗舰', self.config.GemsFarming_ChangeFlagship)
        self._fleet_detail_enter(self.fleet_to_attack)
        if self.change_flagship_equip:
            logger.hr('卸下旗舰装备', level=2)
            self._ship_detail_enter(self.fleet_detail_enter_flagship)
            self.clear_all_equip()
            self._fleet_back()

        logger.hr('更换旗舰', level=2)
        success = self.flagship_change_execute()

        if self.change_flagship_equip:
            logger.hr('装备旗舰装备', level=2)
            self._ship_detail_enter(self.fleet_detail_enter_flagship)
            self.apply_equip_code()
            self._fleet_back()

        return success

    def vanguard_change(self):
        """
        更换先锋并使用装备码更换先锋装备。

        Returns:
            bool: 是否成功更换先锋。
        """
        logger.hr('更换前排', level=1)
        logger.attr('更换前排', self.config.GemsFarming_ChangeVanguard)
        self._fleet_detail_enter(self.fleet_to_attack)
        if self.change_vanguard_equip:
            logger.hr('卸下前排装备', level=2)
            self._ship_detail_enter(self.fleet_detail_enter)
            self.clear_all_equip()
            self._fleet_back()

        logger.hr('更换前排', level=2)
        success = self.vanguard_change_execute()

        if self.change_vanguard_equip:
            logger.hr('装备前排装备', level=2)
            self._ship_detail_enter(self.fleet_detail_enter)
            self.apply_equip_code()
            self._fleet_back()


        return success

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

    def get_common_rarity_cv(self, lv=31, emotion=16):
        """
        根据 config.GemsFarming_CommonCV 获取普通稀有度航母。
        如果 config.GemsFarming_CommonCV == 'any'，返回等级 1~33 的普通航母。

        调用后需要调用 _dock_reset()。

        Args:
            lv (int): 普通航母的最大等级。
            emotion (int): 普通航母的最低情绪值。

        Returns:
            Ship: 匹配的舰船。
        """
        faction = 'eagle' if self.config.GemsFarming_CommonCV == 'eagle' else 'all'
        extra = 'can_limit_break' if self.config.GemsFarming_AllowHighFlagshipLevel else 'enhanceable'
        self.dock_favourite_set(False, wait_loading=False)
        self.dock_sort_method_dsc_set(False, wait_loading=False)
        self.dock_filter_set(
            index='cv', rarity='common', faction=faction, extra=extra, sort='total')

        logger.hr('[战役-紧急委托] 查找旗舰')

        if self.config.GemsFarming_AllowHighFlagshipLevel:
            if self.config.SERVER in ['cn']:
                max_level = 100
            else:
                max_level = 70
            min_level = max_level
        else:
            max_level = lv
            min_level = 1
        emotion_lower_bound = 0 if emotion == 0 else self.emotion_lower_bound
        fleet = [0, self.fleet_to_attack] if self.config.GemsFarming_AllowHighFlagshipLevel else self.fleet_to_attack

        if self.config.GemsFarming_UseEmotionFirst:
            scanner = ShipScanner(
                level=(min_level, max_level), emotion=(emotion_lower_bound, 150), fleet=[0, self.fleet_to_attack], status='free')
            scanner.disable('rarity')

            if self.config.GemsFarming_CommonCV in ['custom', 'any', 'eagle']:
                if self.config.GemsFarming_CommonCV == 'custom':
                    filter_string = self.config.GemsFarming_CommonCVFilter
                else:
                    filter_string = self.config.COMMON_CV_FILTER
                common_ship = self.get_common_ship_filter(filter_string, ship_type='cv')
            else:
                common_ship = [self.config.GemsFarming_CommonCV]

            if common_ship is not None:
                candidates = self.find_all_backline_candidates(scanner, common_ship)
                if candidates:
                    return [candidates[0]]

                logger.info('[战役-紧急委托] 未找到指定航母，尝试倒序排列。')
                self.dock_sort_method_dsc_set(True)
                candidates = self.find_all_backline_candidates(scanner, common_ship)
                if candidates:
                    return [candidates[0]]

                # 恢复排序方式，因为已更改但未找到结果
                self.dock_sort_method_dsc_set(False)
            logger.info('[战役-紧急委托] UseEmotionFirst 未找到候选舰船，回退到原始选择方法')

        scanner = ShipScanner(
            level=(min_level, max_level), emotion=(emotion_lower_bound, 150), fleet=fleet, status='free')
        scanner.disable('rarity')

        if not self.config.GemsFarming_AllowHighFlagshipLevel:
            ships = scanner.scan(self.device.image)
            if ships:
                # 不需要更换当前舰船
                return ships

            # 更换为任意舰船
            scanner.set_limitation(fleet=0)

        if self.config.GemsFarming_CommonCV in ['custom', 'any', 'eagle']:
            candidates = self.find_custom_candidates(scanner, ship_type='cv')

            if candidates:
                # 更换为指定舰船
                return candidates

            return scanner.scan(self.device.image, output=False)

        else:
            template = TEMPLATE_COMMON_CV[f'{self.config.GemsFarming_CommonCV.upper()}']

            candidates = [ship for ship in scanner.scan(self.device.image, output=False)
                          if template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]

            if candidates:
                # 更换为指定舰船
                return candidates

            logger.info('[战役-紧急委托] 未找到指定航母，尝试倒序排列。')
            self.dock_sort_method_dsc_set(True)

            candidates = [ship for ship in scanner.scan(self.device.image)
                          if template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]

            return candidates

    def get_common_rarity_dd(self, emotion=16):
        """
        获取等级为 100（非 CN 服务器为 70）且情绪值 >= self.emotion_lower_bound 的普通稀有度驱逐舰。

        调用后需要调用 _dock_reset()。

        Args:
            emotion (int): 普通驱逐舰的最低情绪值。

        Returns:
            Ship: 匹配的舰船。
        """
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
            logger.error(f'[钻石打捞] 无效的通用驱逐舰设置: {self.config.GemsFarming_CommonDD}')
            raise ScriptError('Invalid GemsFarming_CommonDD')
        favourite = self.config.GemsFarming_CommonDD == 'favourite'
        self.dock_favourite_set(favourite, wait_loading=False)
        self.dock_sort_method_dsc_set(True, wait_loading=False)
        self.dock_filter_set(
            index='dd', rarity=rarity, faction=faction, extra=extra)

        logger.hr('[战役-紧急委托] 查找先锋')

        min_level, max_level = self.config.GemsFarming_VanguardLevelMin, self.config.GemsFarming_VanguardLevelMax
        
        # 如果新设置保持在绝对默认值 (1, 125)，回退到旧逻辑
        # 以防止破坏隐式依赖 100/70 的现有 GemsFarming 配置。
        if min_level <= 1 and max_level >= 125:
            if self.config.SERVER in ['cn']:
                max_level = 100
            else:
                max_level = 70
            if getattr(self.config, 'GemsFarming_CommonDD', '') == 'DDG':
                max_level = 125
            if getattr(self.config, 'GemsFarming_AllowLowVanguardLevel', False):
                min_level = 30
            else:
                min_level = max_level
            if self.hard_mode:
                min_level = max(min_level, 70)
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

                logger.info('[战役-紧急委托] 未找到指定驱逐舰，尝试倒序排列。')
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
            # 更换为任意舰船
            return scanner.scan(self.device.image)

        elif self.config.GemsFarming_CommonDD == 'custom':
            candidates = self.find_custom_candidates(scanner, ship_type='dd')

            if candidates:
                # 更换为指定舰船
                return candidates

            return scanner.scan(self.device.image, output=False)

        else:
            candidates = self.find_candidates(self.get_templates(self.config.GemsFarming_CommonDD), scanner)

            if candidates:
                # 更换为指定舰船
                return candidates

            logger.info('[战役-紧急委托] 未找到指定驱逐舰，尝试倒序排列。')
            self.dock_sort_method_dsc_set(False)

            # 更换为指定舰船
            candidates = self.find_candidates(self.get_templates(self.config.GemsFarming_CommonDD), scanner)
            return candidates

    def match_ship_to_template(self, ship, template):
        """检查舰船图标是否匹配给定模板。

        Args:
            ship (Ship): 舰船对象。
            template: 模板对象或模板列表。

        Returns:
            bool: 是否匹配。
        """
        if isinstance(template, list):
            return any(item.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE) for item in template)
        else:
            return template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)

    def find_all_vanguard_candidates(self, scanner, common_ship):
        """
        扫描并查找 common_ship 列表的所有匹配候选舰船，按 (情绪值, -优先级索引) 降序返回。
        """
        templates_list = [TEMPLATE_COMMON_DD[name.upper()] for name in common_ship]
        all_ships = scanner.scan(self.device.image, output=False)
        matched_candidates = []
        for ship in all_ships:
            for i, template in enumerate(templates_list):
                if self.match_ship_to_template(ship, template):
                    matched_candidates.append((ship, i))
                    break
        # 按情绪值（降序）和优先级索引（升序）排序
        matched_candidates.sort(key=lambda x: (x[0].emotion, -x[1]), reverse=True)
        return [x[0] for x in matched_candidates]

    def find_all_backline_candidates(self, scanner, common_ship):
        """
        扫描并查找 common_ship 列表的所有匹配候选舰船，按以下顺序排序：
        1. 情绪值（降序）
        2. 等级（升序）
        3. 优先级索引（升序）
        """
        templates_list = [TEMPLATE_COMMON_CV[name.upper()] for name in common_ship]
        all_ships = scanner.scan(self.device.image, output=False)
        matched_candidates = []
        for ship in all_ships:
            for i, template in enumerate(templates_list):
                if self.match_ship_to_template(ship, template):
                    matched_candidates.append((ship, i))
                    break
        # 按情绪值（降序）、等级（升序）和优先级索引（升序）排序
        matched_candidates.sort(key=lambda x: (x[0].emotion, -x[0].level, -x[1]), reverse=True)
        return [x[0] for x in matched_candidates]

    def find_custom_candidates(self, scanner, ship_type='cv'):
        """
        获取普通稀有度航母/驱逐舰的候选舰船，仅用于 'custom' GemsFarming_CommonCV/DD 设置。

        Args:
            scanner (ShipScanner): 舰船扫描器。
            ship_type (str): 'cv' 或 'dd'。
        """
        if ship_type.lower() not in ['cv', 'dd']:
            logger.warning(f'[钻石打捞] 无效的舰船类型: {ship_type}')
            return []

        ship_type = ship_type.upper()
        logger.info(f'[战役-紧急委托] 搜索普通 {ship_type}。')
        if ship_type.lower() == 'cv' and self.config.GemsFarming_CommonCV != 'custom':
            filter_string = self.config.COMMON_CV_FILTER
        else:
            filter_string =  self.config.__getattribute__(f'GemsFarming_Common{ship_type}Filter')
        sort_dsc_first = ship_type.lower() == 'dd'
    
        common_ship = self.get_common_ship_filter(filter_string, ship_type=ship_type)
        templates = globals()[f'TEMPLATE_COMMON_{ship_type}']
        find_first = True
        common_ship_candidates = {}
        for name in common_ship:
            template = templates[name.upper()]
            candidates = self.find_candidates(template, scanner)

            if find_first:
                find_first = False
                if candidates:
                    logger.info(f'[钻石打捞] 找到通用 {ship_type} {name}')
                    return candidates

            common_ship_candidates[name] = candidates

        logger.info(f'[战役-紧急委托] 未找到合适的 {ship_type}，尝试倒序排列。')
        self.dock_sort_method_dsc_set(not sort_dsc_first)

        for name in common_ship:
            template = templates[name.upper()]
            candidates = self.find_candidates(template, scanner)

            if candidates:
                logger.info(f'[钻石打捞] 找到通用驱逐舰 {name}')
                return candidates
            elif common_ship_candidates[name]:
                logger.info(f'[钻石打捞] 找到通用驱逐舰 {name}')
                self.dock_sort_method_dsc_set(sort_dsc_first, wait_loading=False)
                return common_ship_candidates[name]

        return []

    def find_candidates(self, template, scanner):
        """
        基于模板匹配查找候选舰船。
        """
        candidates = []
        if isinstance(template, list):
            for item in template:
                candidates = [ship for ship in scanner.scan(self.device.image, output=False)
                            if item.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]
                if candidates:
                    break
        else:
            candidates = [ship for ship in scanner.scan(self.device.image, output=False)
                          if template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]
        return candidates

    @staticmethod
    def get_templates(common_dd):
        """
        根据 CommonDD 设置返回对应的模板列表。
        """
        if common_dd == 'aulick_or_foote':
            return [
                TEMPLATE_AULICK,
                TEMPLATE_FOOTE
            ]
        elif common_dd == 'cassin_or_downes':
            return [
                TEMPLATE_CASSIN_1, TEMPLATE_CASSIN_2,
                TEMPLATE_DOWNES_1, TEMPLATE_DOWNES_2
            ]
        else:
            logger.error(f'[钻石打捞] 无效的通用驱逐舰设置: {common_dd}')
            raise ScriptError(f'Invalid CommonDD setting: {common_dd}')

    def ship_down_hard(self):
        """困难模式下将舰船从舰队中移除。

        如果存在离队按钮则点击，否则返回准备页面。
        """
        if self.appear(DOCK_SHIP_DOWN):
            self.ui_click(DOCK_SHIP_DOWN,
                            appear_button=DOCK_CHECK, check_button=self.page_fleet_check_button, skip_first_screenshot=True)
        else:
            self.ui_back(check_button=FLEET_PREPARATION)

    def dock_enter(self, button):
        """进入船坞页面。

        从舰队页面点击指定位置的按钮进入船坞。

        Args:
            button (Button): 要点击的按钮。

        Returns:
            bool: True 表示成功进入，False 表示遇到游戏提示未进入。
        """
        for _ in self.loop():
            if self.appear(DOCK_CHECK, offset=(20, 20)):
                break
            if self.appear(self.page_fleet_check_button, offset=(30, 30), interval=5):
                self.device.click(button)
                continue
            # 2025.05.29 进入船坞时游戏会弹出皮肤功能提示
            if self.handle_game_tips():
                return False
        return True

    def flagship_change_with_emotion(self, ship):
        """
        更换旗舰并计算情绪值。
        """
        target_ship = max(ship, key=lambda s: (s.level, s.emotion))
        if self.change_vanguard:
            self.set_emotion(min(self.get_emotion(), target_ship.emotion))
        elif self.config.GemsFarming_AllowHighFlagshipLevel:
            self.set_emotion(target_ship.emotion)
        self._ship_change_confirm(target_ship.button)

    def flagship_change_execute(self):
        """
        执行旗舰更换。

        Returns:
            bool: 是否成功。

        Pages:
            in: page_fleet
            out: page_fleet
        """
        if self.hard_mode:
            if not self.dock_enter(self.fleet_detail_enter_flagship):
                return True
            self.ship_down_hard()  
        if not self.dock_enter(self.fleet_enter_flagship):
            return True

        ship = self.get_common_rarity_cv()
        if ship:
            self.flagship_change_with_emotion(ship)
            logger.info('[战役-紧急委托] 更换旗舰成功')
            return True
        else:
            logger.info('[战役-紧急委托] 更换旗舰失败，没有普通稀有度航母。')

            if self.config.SERVER in ['cn']:
                max_level = 100
            else:
                max_level = 70
            ship = self.get_common_rarity_cv(lv=max_level, emotion=0)
            if ship and self.hard_mode:
                self.flagship_change_with_emotion(ship)
            else:
                if self.hard_mode:
                    raise RequestHumanTakeover
                self._dock_reset()
                self.ui_back(check_button=self.page_fleet_check_button)
            return False

    def vanguard_change_with_emotion(self, ship):
        """
        更换先锋并计算情绪值。
        """
        target_ship = max(ship, key=lambda s: s.emotion)
        if self.change_vanguard:
            self.set_emotion(target_ship.emotion)
        self._ship_change_confirm(target_ship.button)

    def vanguard_change_execute(self):
        """
        执行先锋更换。

        Returns:
            bool: 是否成功。

        Pages:
            in: page_fleet
            out: page_fleet
        """
        if self.hard_mode:
            if not self.dock_enter(self.fleet_detail_enter):
                return True
            self.ship_down_hard()  
        if not self.dock_enter(self.fleet_enter):
            return True

        ship = self.get_common_rarity_dd()
        if ship:
            self.vanguard_change_with_emotion(ship)
            logger.info('[战役-紧急委托] 更换先锋舰船成功')
            return True
        else:
            logger.info('[战役-紧急委托] 更换先锋舰船失败，没有普通稀有度驱逐舰。')
            ship = self.get_common_rarity_dd(emotion=0)
            if ship and self.hard_mode:
                self.vanguard_change_with_emotion(ship)
            else:
                if self.hard_mode:
                    raise RequestHumanTakeover
                self._dock_reset()
                self.ui_back(check_button=self.page_fleet_check_button)
            return False

    _trigger_lv32 = False
    _trigger_emotion = False
    # 初始旗舰等级检查是否已完成。
    # 使用类属性做进程内持久化：任务实例与 config 实例会随调度器切换或配置重载而重建，
    # 类属性在进程生命周期内保持不变，确保初始检查只在进程内执行一次。
    _initial_flagship_check_done = False

    def triggered_stop_condition(self, oil_check=True):
        """检查钻石 farming 的停止条件。

        在父类停止条件基础上增加了：
        - 等级 32 限制：旗舰达到 32 级时触发（需要更换旗舰）
        - 情绪限制：情绪值过低时触发（需要更换舰船）

        Args:
            oil_check (bool): 是否检查石油限制。

        Returns:
            bool: 是否触发停止条件。
        """
        # 等级 32 限制
        if self._trigger_lv32 or (
                self.change_flagship and self.campaign.config.LV32_TRIGGERED
                and not self.config.GemsFarming_AllowHighFlagshipLevel):
            self._trigger_lv32 = True
            logger.hr('[战役-打捞] 触发等级32限制')
            return True

        if self.campaign.config.GEMS_EMOTION_TRIGGERED:
            self._trigger_emotion = True
            logger.hr('[战役-打捞] 触发情绪限制')
            return True

        return super().triggered_stop_condition(oil_check=oil_check)

    def get_emotion(self):
        """
        从配置中获取舰队情绪值。
        """
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            return self.campaign.config.Emotion_Fleet2Value
        else:
            return self.campaign.config.Emotion_Fleet1Value

    def set_emotion(self, emotion):
        """
        设置舰队情绪值。
        """
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            self.campaign.config.set_record(Emotion_Fleet2Value=emotion)
        else:
            self.campaign.config.set_record(Emotion_Fleet1Value=emotion)

    def run(self, name, folder='campaign_main', mode='normal', total=0):
        """
        运行钻石 farming 任务。

        Args:
            name (str): .py 文件名称。
            folder (str): campaign 下的文件夹名称。
            mode (str): `normal` 或 `hard`。
            total (int): 总运行次数限制。
        """
        self.config.STOP_IF_REACH_LV32 = self.change_flagship and not self.config.GemsFarming_AllowHighFlagshipLevel
        # 初始检查旗舰等级。
        # 如果启用了旗舰更换，在开始时强制更换旗舰。
        # 解决脚本以 32 级旗舰启动但未退役的问题。
        initial_check = (
            self.change_flagship
            and not self.config.GemsFarming_AllowHighFlagshipLevel
            and not GemsFarming._initial_flagship_check_done
        )
        GemsFarming._initial_flagship_check_done = True
        while 1:
            self._trigger_lv32 = initial_check
            initial_check = False
            is_limit = self.config.StopCondition_RunCount
            try:
                super().run(name=name, folder=folder, total=total)
            except CampaignEnd as e:
                if e.args[0] == 'Emotion control':
                    self._trigger_emotion = True
                elif e.args[0] == 'Emotion withdraw':
                    self._trigger_emotion = True
                    self.set_emotion(0)
                else:
                    raise e
            except HardNotSatisfied:
                try:
                    if self.change_flagship and self.change_vanguard:
                        self.hard_mode_override()
                        self.vanguard_change()
                        self.flagship_change()
                    else:
                        raise RequestHumanTakeover
                except RequestHumanTakeover:
                    raise
                except Exception:
                    from module.exception import GameStuckError
                    raise GameStuckError
            except RequestHumanTakeover as e:
                try:
                    if e.args and e.args[0] == 'Hard not satisfied' and self.change_flagship and self.change_vanguard:
                        self.hard_mode_override()
                        self.vanguard_change()
                        self.flagship_change()
                    else:
                        raise
                except RequestHumanTakeover:
                    raise
                except Exception:
                    from module.exception import GameStuckError
                    raise GameStuckError

            # 结束条件
            if self._trigger_lv32 or self._trigger_emotion:
                success = True
                self.hard_mode_override()
                emotion = self.get_emotion()
                vanguard_success = True
                flagship_success = True
                if self.change_vanguard:
                    vanguard_success = self.vanguard_change()
                if self.change_flagship and (vanguard_success or self._trigger_lv32):
                    flagship_success = self.flagship_change()
                    if not flagship_success and self.config.GemsFarming_AllowHighFlagshipLevel:
                        self.set_emotion(emotion)
                success = vanguard_success and flagship_success

                if is_limit and self.config.StopCondition_RunCount <= 0:
                    logger.hr('触发停止条件: 运行次数')
                    self.config.StopCondition_RunCount = 0
                    self.config.Scheduler_Enable = False
                    break

                self._trigger_lv32 = False
                self.campaign.config.LV32_TRIGGERED = False
                self.campaign.config.GEMS_EMOTION_TRIGGERED = False

                # 调度器
                if self.config.task_switched():
                    self._trigger_emotion = False
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_stop()
                elif not success and (self.config.GemsFarming_DelayTaskIFNoFlagship \
                        or self._trigger_emotion):
                    self._trigger_emotion = False
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_delay(minute=60)
                    self.config.task_stop()

                self._trigger_emotion = False
                continue
            else:
                break
