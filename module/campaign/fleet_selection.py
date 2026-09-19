"""低耗战役共用的选船与舰队交互，任务等级策略由调用方保留。"""

from module.equipment.assets import (
    FLEET_DETAIL_ENTER,
    FLEET_DETAIL_ENTER_FLAGSHIP,
    FLEET_DETAIL_ENTER_FLAGSHIP_HARD_1,
    FLEET_DETAIL_ENTER_FLAGSHIP_HARD_2,
    FLEET_DETAIL_ENTER_HARD_1,
    FLEET_DETAIL_ENTER_HARD_2,
    FLEET_ENTER,
    FLEET_ENTER_FLAGSHIP,
    FLEET_ENTER_FLAGSHIP_HARD_1,
    FLEET_ENTER_FLAGSHIP_HARD_2,
    FLEET_ENTER_HARD_1,
    FLEET_ENTER_HARD_2
)
from module.exception import ScriptError
from module.retire.retirement import TEMPLATE_COMMON_CV, TEMPLATE_COMMON_DD
from module.retire.assets import (
    DOCK_CHECK,
    TEMPLATE_CASSIN_1,
    TEMPLATE_CASSIN_2,
    TEMPLATE_DOWNES_1,
    TEMPLATE_DOWNES_2,
    TEMPLATE_AULICK,
    TEMPLATE_FOOTE
)
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_HARD
from module.retire.scanner import ShipScanner
from module.ui.assets import BACK_ARROW
from module.ui.page import page_fleet

SIM_VALUE = 0.9


class FleetSelectionMixin:
    """依赖宿主提供船坞、装备与战役能力；放在 CampaignRun 之前。

    仅共享相同的选船行为，先锋等级策略与实际换船执行仍由任务覆写。
    停止条件通过 super() 继续调用宿主原有的战役停止检查。
    """

    def hard_mode_override(self):
        """根据当前战役模式切换舰队进入方式。

        困难模式下使用不同的按钮进入舰队编辑页面（通过战役准备界面），
        普通模式下直接通过 page_fleet 进入。根据舰队顺序配置选择
        对应的旗舰/先锋进入按钮。
        """
        if self.campaign.config.Campaign_Mode == 'hard':
            logger.info('[战役-选船] 在困难模式，切换换船方式')
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

        logger.hr('[战役-选船] 查找旗舰')

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

                logger.info('[战役-选船] 未找到指定航母，尝试倒序排列。')
                self.dock_sort_method_dsc_set(True)
                candidates = self.find_all_backline_candidates(scanner, common_ship)
                if candidates:
                    return [candidates[0]]

                # 恢复排序方式，因为已更改但未找到结果
                self.dock_sort_method_dsc_set(False)
            logger.info('[战役-选船] UseEmotionFirst 未找到候选舰船，回退到原始选择方法')

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

            logger.info('[战役-选船] 未找到指定航母，尝试倒序排列。')
            self.dock_sort_method_dsc_set(True)

            candidates = [ship for ship in scanner.scan(self.device.image)
                          if template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]

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
            logger.warning(f'[战役-选船] 无效的舰船类型: {ship_type}')
            return []

        ship_type = ship_type.upper()
        logger.info(f'[战役-选船] 搜索普通 {ship_type}。')
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
                    logger.info(f'[战役-选船] 找到通用 {ship_type} {name}')
                    return candidates

            common_ship_candidates[name] = candidates

        logger.info(f'[战役-选船] 未找到合适的 {ship_type}，尝试倒序排列。')
        self.dock_sort_method_dsc_set(not sort_dsc_first)

        for name in common_ship:
            template = templates[name.upper()]
            candidates = self.find_candidates(template, scanner)

            if candidates:
                logger.info(f'[战役-选船] 找到通用驱逐舰 {name}')
                return candidates
            elif common_ship_candidates[name]:
                logger.info(f'[战役-选船] 找到通用驱逐舰 {name}')
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
            logger.error(f'[战役-选船] 无效的通用驱逐舰设置: {common_dd}')
            raise ScriptError(f'Invalid CommonDD setting: {common_dd}')

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
            logger.hr('[战役-选船] 触发等级32限制')
            return True

        if self.campaign.config.GEMS_EMOTION_TRIGGERED:
            self._trigger_emotion = True
            logger.hr('[战役-选船] 触发情绪限制')
            return True

        return super().triggered_stop_condition(oil_check=oil_check)
