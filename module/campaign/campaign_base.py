"""
战役执行基类模块。

提供战役任务的核心执行逻辑，包括：
- 战斗函数分发（根据地图数据选择不同的战斗策略）
- 战役全流程编排（进入地图、初始化、循环执行战斗、异常处理）
- 自动搜索模式支持

本模块是所有战役任务（主线、活动、作战档案等）的执行基础，
组合了 CampaignUI（UI 导航）、Map（地图操作）和 AutoSearchCombat（自动搜索战斗）
的能力。
"""

from module.base.decorator import Config, cached_property
from module.campaign.campaign_ui import CampaignUI
from module.combat.auto_search_combat import AutoSearchCombat
from module.config.recovery import read_recovery_settings
from module.exception import CampaignEnd, MapEnemyMoved, ScriptEnd, ScriptError
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON
from module.logger import logger
from module.map.map import Map
from module.map.map_base import CampaignMap


class CampaignBase(CampaignUI, Map, AutoSearchCombat):
    """战役执行基类，组合 UI 导航、地图操作和自动搜索战斗能力。

    负责战役任务的完整执行流程：从进入地图到循环执行每一场战斗，
    直到战役结束或触发异常。通过 `@Config.when` 装饰器实现多种战斗策略的
    条件分发，支持普通模式、全清模式和数据不足模式。

    战斗函数的查找机制：根据当前 battle_count 动态查找对应的战斗函数
    （如 battle_0、battle_1 等），找不到则回退到 battle_default。

    Attributes:
        FUNCTION_NAME_BASE (str): 战斗函数名称前缀，默认为 'battle_'。
        MAP (CampaignMap): 当前战役的地图数据对象，包含网格布局、敌人位置、
            出生点等信息。由子类的地图文件定义。
    """
    FUNCTION_NAME_BASE = 'battle_'
    MAP: CampaignMap
    # 三战撤退类地图（如 D3-3）置为 True：自律寻敌打满 _map_battle 后
    # 关闭自律寻敌并撤退（#275）。普通地图保持 False，避免 boss 战败后
    # 被误撤退。
    AUTO_SEARCH_WITHDRAW = False

    def battle_default(self):
        """默认战斗策略：清除所有敌人。

        作为战斗函数查找失败时的回退策略，尝试清除地图上的敌人。

        Returns:
            bool: True 表示成功执行战斗，False 表示没有执行任何战斗。
        """
        if self.clear_enemy():
            return True

        logger.warning('[战役-基础] 未执行战斗')
        return False

    def battle_boss(self):
        """Boss 战斗策略：强制清除 Boss。

        使用蛮力方式直接清除 Boss，忽略路径优化。

        Returns:
            bool: True 表示成功执行战斗，False 表示没有执行任何战斗。
        """
        if self.brute_clear_boss():
            return True

        logger.warning('[战役-基础] 未执行战斗')
        return False

    @Config.when(POOR_MAP_DATA=True, MAP_CLEAR_ALL_THIS_TIME=False)
    def battle_function(self):
        """战斗函数：地图数据不足模式。

        当地图数据不完整时使用的战斗策略。优先攻击 Boss，
        其次清除精英敌人，最后清除普通敌人。
        会优先处理被塞壬锁定的第二舰队和神秘格子。

        Returns:
            bool: True 表示成功执行战斗，False 表示没有执行任何战斗。
        """
        logger.info('[战役-基础] 使用函数: battle_with_poor_map_data')
        if self.fleet_2_break_siren_caught():
            return True
        self.clear_all_mystery()

        if self.battle_count >= 3:
            self.pick_up_ammo()

        if self.map.select(is_boss=True):
            if self.brute_clear_boss():
                return True
        else:
            if self.clear_siren():
                return True
            return self.clear_enemy()

        return False

    @Config.when(MAP_CLEAR_ALL_THIS_TIME=True)
    def battle_function(self):
        """战斗函数：全清模式。

        清除地图上所有敌人（包括精英、普通和要塞敌人）后才攻击 Boss。
        适用于需要全清才能达成三星或 100% 通关率的关卡。

        Returns:
            bool: True 表示成功执行战斗，False 表示没有执行任何战斗。
        """
        logger.info('[战役-基础] 使用函数: clear_all')
        if self.fleet_2_break_siren_caught():
            return True
        self.clear_all_mystery()

        if self.battle_count >= 3:
            self.pick_up_ammo()

        remain = self.map.select(is_enemy=True) \
            .add(self.map.select(is_siren=True)) \
            .add(self.map.select(is_fortress=True)) \
            .delete(self.map.select(is_boss=True))
        logger.info(f'[战役-基础] 剩余敌舰: {remain}')
        if remain.count > 0:
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                if self.clear_any_enemy(sort=('cost_2',)):
                    return True
                return self.battle_default()
            else:
                if self.clear_bouncing_enemy():
                    return True
                if self.clear_siren():
                    return True
                self.clear_mechanism()
                return self.battle_default()
        else:
            result = self.battle_boss()
            return result

    @Config.when(MAP_CLEAR_ALL_THIS_TIME=False, POOR_MAP_DATA=False)
    def battle_function(self):
        """战斗函数：标准模式。

        根据当前 battle_count 动态查找对应的战斗函数。
        查找顺序：battle_N -> battle_(N-1) -> ... -> battle_default。
        允许地图文件定义特定战斗步骤的自定义策略（如 battle_0 攻击 Boss，
        battle_1 清除特定敌人等）。

        Returns:
            bool: True 表示成功执行战斗，False 表示没有执行任何战斗。
        """
        func = self.FUNCTION_NAME_BASE + 'default'
        for extra_battle in range(10):
            if hasattr(self, self.FUNCTION_NAME_BASE + str(self.battle_count - extra_battle)):
                func = self.FUNCTION_NAME_BASE + str(self.battle_count - extra_battle)
                break

        logger.info(f'[战役-基础] 使用函数: {func}')
        func = self.__getattribute__(func)

        result = func()

        return result

    def execute_a_battle(self):
        """执行单场战斗。

        调用 battle_function() 执行一场战斗，处理 MapEnemyMoved 异常
        （敌人移动导致的地图状态变化）。如果战斗未成功执行且启用了
        错误处理，则撤退；否则抛出 ScriptError。

        Returns:
            bool: True 表示成功执行战斗。

        Raises:
            ScriptError: 战斗未执行且未启用错误处理时抛出。
        """
        logger.hr(f'{self.FUNCTION_NAME_BASE}{self.battle_count}', level=2)
        prev = self.battle_count
        result = False
        for _ in range(10):
            try:
                result = self.battle_function()
                break
            except MapEnemyMoved:
                if self.battle_count > prev:
                    result = True
                    break
                else:
                    continue

        if not result:
            logger.warning('[战役-基础] 脚本错误，未执行战斗')
            if read_recovery_settings(self.config).value('Error_HandleError'):
                logger.warning('[战役-基础] 脚本错误，未执行战斗，撤退中')
                self.withdraw()
            else:
                raise ScriptError('No combat executed.')

        return result

    def run(self):
        """执行完整的战役流程。

        流程：
        1. 获取地图信息并进入地图
        2. 初始化地图（锁定舰队、初始化地图数据）
        3. 循环执行战斗（最多 20 场），直到战役结束
        4. 异常处理：如果战斗函数耗尽，根据配置撤退或抛出异常

        自动搜索模式下跳过地图初始化，直接进入自动搜索战斗循环。

        Returns:
            bool: True 表示战役正常结束。

        Raises:
            ScriptError: 战斗函数耗尽且未启用错误处理时抛出。
        """
        logger.hr(self.ENTRANCE, level=2)

        resume = self.__dict__.pop('_resume_after_restart', False)
        if not resume:
            self._recovery_map_active = False
            self._recovery_map_generation = self.__dict__.get('_recovery_map_generation', 0) + 1
            self._restart_resume_guard = False
            self._restart_stop_requested = False
            # 进入地图
            self.map_get_info()
            logger.attr('地图战斗次数', self._map_battle)
            self.emotion.check_reduce(self._map_battle)
            self.ENTRANCE.area = self.ENTRANCE.button
            self.enter_map(self.ENTRANCE, mode=self.config.Campaign_Mode)

        # 地图初始化
        if resume:
            logger.info('[战役续接] 保留舰队、等级和战斗次数，继续原关卡')
            if self.__dict__.get('_restart_stop_requested', False):
                try:
                    self.auto_search_withdraw(strict=True)
                except CampaignEnd:
                    pass
                self._recovery_map_active = False
                raise ScriptEnd('[战役续接] 原有停止条件已触发')
        elif not self.map_is_auto_search:
            self.handle_map_fleet_lock()
            self.map_init(self.MAP)
        else:
            self.map = self.MAP
            self.battle_count = 0
            self.lv_reset()
            self.lv_get()

        # 执行战斗
        for _ in range(20):
            try:
                if not self.map_is_auto_search:
                    self.execute_a_battle()
                else:
                    # 三战撤退类地图：打满目标战数后关闭自律寻敌并撤退（#275）
                    if self.AUTO_SEARCH_WITHDRAW and self.battle_count >= self._map_battle:
                        logger.info(f'[战役-基础] 已完成 {self.battle_count} 战，撤退')
                        self.auto_search_withdraw()
                        return True
                    self.auto_search_execute_a_battle()
            except CampaignEnd:
                self._recovery_map_active = False
                self._restart_resume_guard = False
                logger.hr('战役结束')
                return True

        # 异常处理
        logger.warning('[战役-基础] 战斗函数已耗尽')
        if read_recovery_settings(self.config).value('Error_HandleError'):
            logger.warning('[战役-基础] 脚本错误，战斗函数已耗尽，撤退中')
            try:
                self.withdraw()
            except CampaignEnd:
                pass
        else:
            raise ScriptError('战斗函数已耗尽。')

    @cached_property
    @Config.when(MAP_CLEAR_ALL_THIS_TIME=False)
    def _map_battle(self):
        """
        获取当前地图的战斗次数（仅计算到 Boss 出现前）。

        Returns:
            int: 当前地图的战斗次数。
        """
        for data in self.MAP.spawn_data:
            if 'boss' in data:
                if 'battle' in data:
                    return data['battle'] + 1
                else:
                    logger.warning('[战役-基础] 出生点数据中无战斗计数')

        logger.warning('[战役-基础] 出生点数据中未找到Boss数据')
        return 0

    @cached_property
    @Config.when(MAP_CLEAR_ALL_THIS_TIME=True)
    def _map_battle(self):
        """
        获取当前地图的总战斗次数（全清模式，计算所有敌人）。

        Returns:
            int: 当前地图的总战斗次数。
        """
        battle_count = 0
        for data in self.MAP.spawn_data:
            if 'battle' in data:
                for k, v in data.items():
                    if k != 'battle':
                        battle_count += v
            else:
                logger.warning('[战役-基础] 出生点数据中无战斗计数')

        return battle_count

    def auto_search_execute_a_battle(self):
        """使用自动搜索模式执行单场战斗。

        通过自动搜索移动舰队并执行战斗，适用于自动搜索已开启的关卡。
        战斗完成后自动递增 battle_count。
        """
        logger.hr(f'{self.FUNCTION_NAME_BASE}{self.battle_count}', level=2)
        self._recovery_map_active = True
        self.auto_search_moving()
        self.auto_search_combat(fleet_index=self.fleet_show_index,
                                battle=(self.battle_count, self._map_battle))
        self.battle_count += 1

    def auto_search_withdraw(self, skip_first_screenshot=True, strict=False):
        """自律寻敌运行中撤退。

        先退出自律寻敌状态回到普通地图，再执行撤退。
        自律寻敌运行时地图右下角的撤退按钮（WITHDRAW）被自律寻敌开关替换，
        直接调用 withdraw() 会一直等不到按钮而卡死（#275）。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。
            strict (bool): 异常续接回退时同时确认开关颜色，避免模板重叠导致反向开启。

        Raises:
            CampaignEnd: 撤退完成时抛出 CampaignEnd('Withdraw')。

        Pages:
            in: is_in_map，自律寻敌运行中或自动搜索菜单
            out: handle_in_stage（撤退完成，raise CampaignEnd('Withdraw')）
        """
        logger.hr('地图撤退（自律寻敌）')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 自动搜索菜单已弹出（战斗间歇），直接退出，等效撤退
            if self.handle_auto_search_exit():
                continue
            if self.handle_in_stage():
                raise CampaignEnd('Withdraw')

            # 自律寻敌运行中，点击开关关闭
            running = self.is_auto_search_running() if strict \
                else self.appear(AUTO_SEARCH_MAP_OPTION_ON, offset=(5, 5))
            if running \
                    and self.appear_then_click(AUTO_SEARCH_MAP_OPTION_ON, offset=(5, 5), interval=2):
                continue
            # 关闭时可能弹出确认框
            if self.handle_popup_confirm('AUTO_SEARCH_WITHDRAW'):
                continue

            # 开关已回到 OFF，普通地图状态，交给标准撤退流程
            stopped = self.match_template_color(AUTO_SEARCH_MAP_OPTION_OFF, offset=(5, 5), threshold=10) \
                if strict else self.appear(AUTO_SEARCH_MAP_OPTION_OFF, offset=(5, 5))
            if stopped:
                break
        self.withdraw()
