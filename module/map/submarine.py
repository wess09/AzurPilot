"""将潜艇高级出击规则接入地图策略、移动和战斗准备。"""

from module.combat.submarine_advanced import SubmarineAdvancedConfig
from module.exception import ScriptError
from module.logger import logger


class SubmarineAdvanced:
    """每张地图独立规划潜艇出击，自律寻敌不使用高级规则。"""

    submarine_advanced = None
    _submarine_advanced_target = None
    submarine_hunt_enabled = None

    def submarine_advanced_reset(self):
        """初始化弹药和支援次数，清除上一张地图的计划。"""
        self.submarine_advanced = None
        self._submarine_advanced_target = None
        self.submarine_hunt_enabled = None
        if (self.config.Submarine_Fleet and self.config.Submarine_Mode == 'advanced'
                and not self.map_is_auto_search):
            self.submarine_advanced = SubmarineAdvancedConfig(self.config.Submarine_AdvancedConfig)

    def submarine_advanced_prepare(self, location, expected):
        """在点击敌舰前配置狩猎，必要时将潜艇移到最低代价的覆盖位置。

        Pages:
            in: IN_MAP
            out: IN_MAP
        """
        state = self.submarine_advanced
        if state is None:
            return
        if not self.fleet_submarine_location:
            state.set_plan(None)
            return
        target = self.map[location]
        key = (self.battle_count, location, expected)
        if key != self._submarine_advanced_target:
            plan = None
            if 'combat' in expected or 'boss' in expected or target.is_enemy or target.is_siren or target.is_boss:
                battle = self.battle_count + 1
                boss_battles = [data['battle'] + 1 for data in self.map.spawn_data if data.get('boss', 0)]
                total = min(boss_battles) if boss_battles else None
                if total is not None and getattr(self.config, 'MAP_CLEAR_ALL_THIS_TIME', False):
                    # 全清模式会先清完道中，不能将 Boss 刷新时刻当成最后一战。
                    total = sum(data.get(kind, 0) for data in self.map.spawn_data
                                for kind in ('enemy', 'siren', 'boss'))
                if target.is_boss or 'boss' in expected:
                    total = battle
                genre = {'Light': 'L', 'Main': 'M', 'Carrier': 'C', 'Treasure': 'T'}.get(target.enemy_genre, 'E')
                enemy = f'{target.enemy_scale or 0}{genre}'
                origin = self.fleet_submarine_location
                positions = []
                # 统一准备移动候选，再按召唤优先的规则顺序判断可行性。
                if (origin and state.ammo > 0 and not state.in_range(location, origin)
                        and any(rule.get('move', False) for _, rule in state.rules)):
                    self.map.find_path_initial(origin, has_ambush=False, has_enemy=False)
                    try:
                        positions = [(grid.location, grid.cost) for grid in self.map
                                     if not grid.is_land and not grid.is_mechanism_block and grid.cost < 9999]
                    finally:
                        # 潜艇寻路会覆盖全图 cost，必须还原水面舰队寻路。
                        self.find_path_initial()
                plan = state.choose(battle, total, enemy, location, origin, positions)
                if plan is not None and plan.location is not None:
                    self.submarine_goto(plan.location)
                    if not state.in_range(location, self.fleet_submarine_location):
                        logger.warning('[地图-潜艇] 移动后未覆盖目标，取消本次潜艇出击')
                        plan = None
            state.set_plan(plan)
            self._submarine_advanced_target = key
            logger.attr('潜艇高级出击', plan)
            logger.attr('潜艇剩余弹药', state.ammo)
            logger.attr('潜艇剩余远洋支援', state.support)

        hunt = state.plan is not None and state.plan.mode == 'hunt' and not state.consumed
        if self.submarine_hunt_enabled != hunt:
            self.strategy_open()
            self.strategy_set_execute(sub_view=False, sub_hunt=hunt)
            self.strategy_close()
            if self.submarine_hunt_enabled != hunt:
                raise ScriptError('无法确认潜艇狩猎开关，高级出击已停止')

    def submarine_advanced_combat_start(self):
        """狩猎由游戏在战斗前自动执行，进入战斗时记录一次弹药消耗。"""
        if self.submarine_advanced is not None:
            self.submarine_advanced.consume('hunt')
