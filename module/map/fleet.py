"""舰队管理和地图行走模块。

管理地图探索中的舰队操作，是地图自动化的核心模块。

核心职责：
- 舰队位置追踪：实时记录舰队1、舰队2和潜艇的位置
- 舰队行走：控制舰队在网格间移动，处理移动过程中的各种事件
- 战斗管理：追踪战斗次数、弹药消耗和敌人状态
- 回合系统：管理可移动敌人和迷宫的回合机制
- 路径规划：初始化寻路系统，处理路障和可通行性
- 潜艇操作：控制潜艇移动和狩猎区域调整

行走流程：
1. 初始化地图数据和相机
2. 扫描全图发现敌人和事件
3. 规划路径到达目标格子
4. 处理行走过程中的事件（战斗、伏击、神秘格子）
5. 更新敌人状态和回合计数
6. 检查是否有敌人移动触发重新规划

继承链：Fleet -> Camera -> MapOperation -> AmbushHandler -> Combat -> ...
"""

import itertools

import numpy as np

from module.base.timer import Timer
from module.exception import MapDetectionError, MapEnemyMoved, MapWalkError
from module.handler.ambush import AmbushHandler
from module.logger import logger
from module.map.camera import Camera
from module.map.map_base import SelectedGrids, location2node, location_ensure
from module.map.submarine import SubmarineAdvanced
from module.map.utils import match_movable


class Fleet(SubmarineAdvanced, Camera, AmbushHandler):
    """舰队管理和地图行走控制器。

    追踪多个舰队的位置、战斗状态和弹药，并提供完整的地图行走逻辑。
    行走过程中自动处理战斗、伏击、空袭、神秘格子等事件。

    Attributes:
        fleet_1_location (tuple): 舰队1的全局坐标位置。
        fleet_2_location (tuple): 舰队2的全局坐标位置。
        fleet_submarine_location (tuple): 潜艇的全局坐标位置。
        battle_count (int): 当前地图中的战斗次数。
        mystery_count (int): 当前地图中的神秘事件次数。
        siren_count (int): 当前地图中的塞壬（精英敌人）战斗次数。
        fleet_ammo (int): 舰队剩余弹药数，初始为 5。
        ammo_count (int): 地图中的弹药补给格数量。
        round (int): 当前回合数，用于可移动敌人系统。
        enemy_round (dict): 敌人出现的回合记录，键为回合数，值为敌人数量。
    """
    fleet_1_location = ()
    fleet_2_location = ()
    fleet_submarine_location = ()
    battle_count = 0
    mystery_count = 0
    siren_count = 0
    fleet_ammo = 5
    ammo_count = 3

    @property
    def fleet_1(self):
        if self.fleet_current_index != 1:
            self.fleet_ensure(index=1)
        return self

    @fleet_1.setter
    def fleet_1(self, value):
        self.fleet_1_location = value

    @property
    def fleet_2(self):
        if self.config.FLEET_2:
            if self.fleet_current_index != 2:
                self.fleet_ensure(index=2)
        return self

    @fleet_2.setter
    def fleet_2(self, value):
        self.fleet_2_location = value

    @property
    def fleet_submarine(self):
        return self

    @fleet_submarine.setter
    def fleet_submarine(self, value):
        self.fleet_submarine_location = value

    @property
    def fleet_current(self):
        if self.fleet_current_index == 2:
            return self.fleet_2_location
        else:
            return self.fleet_1_location

    @fleet_current.setter
    def fleet_current(self, value):
        if self.fleet_current_index == 2:
            self.fleet_2_location = value
        else:
            self.fleet_1_location = value

    @property
    def fleet_boss(self):
        if self.config.FLEET_BOSS == 2 and self.config.FLEET_2:
            return self.fleet_2
        else:
            return self.fleet_1

    @property
    def fleet_boss_index(self):
        if self.config.FLEET_BOSS == 2 and self.config.FLEET_2:
            return 2
        else:
            return 1

    @property
    def fleet_step(self):
        if not self.config.MAP_HAS_FLEET_STEP:
            return 0
        if self.fleet_current_index == 2:
            if self.fleets_reversed:
                return self.config.Fleet_Fleet1Step
            else:
                return self.config.Fleet_Fleet2Step
        else:
            if self.fleets_reversed:
                return self.config.Fleet_Fleet2Step
            else:
                return self.config.Fleet_Fleet1Step

    def fleet_ensure(self, index):
        if self.fleet_set(index=index):
            self.camera = self.fleet_current
            self.update()
            self.find_path_initial()
            self.map.show_cost()
            self.show_fleet()
            self.hp_get()
            self.lv_get()
            self.handle_strategy(index=self.fleet_show_index)
            return True
        else:
            return False

    def switch_to(self):
        pass

    round = 0
    enemy_round = {}

    def round_next(self):
        """舰队到达后调用此方法。
        """
        if not self.config.MAP_HAS_MOVABLE_ENEMY and not self.config.MAP_HAS_MAZE:
            return False
        self.round += 1
        logger.info(f'[地图-回合] 回合: {self.round}, 敌方回合: {self.enemy_round}')

    def round_battle(self, after_battle=True):
        """清除敌人后调用此方法。
        """
        if not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False
        if not self.map.select(is_siren=True):
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                if not self.map.select(is_enemy=True):
                    self.enemy_round = {}
            else:
                self.enemy_round = {}
        try:
            data = self.map.spawn_data[self.battle_count]
        except IndexError:
            data = {}
        enemy = data.get('siren', 0)
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            enemy += data.get('enemy', 0)
        if enemy > 0:
            r = self.round
            self.enemy_round[r] = self.enemy_round.get(r, 0) + enemy

    def round_reset(self):
        """进入地图后调用此方法。
        """
        self.round = 0
        self.enemy_round = {}

    @property
    def round_enemy_turn(self):
        """
        Returns:
            tuple[int]: 敌人移动回合数，即玩家移动 X 次后敌人移动一次。
                        返回元组因为不同敌人可能有不同的 X 值。
        """
        if self.config.MAP_HAS_MOVABLE_ENEMY:
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                return tuple(set((list(self.config.MOVABLE_ENEMY_TURN) + list(self.config.MOVABLE_NORMAL_ENEMY_TURN))))
            else:
                return self.config.MOVABLE_ENEMY_TURN
        else:
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                return self.config.MOVABLE_NORMAL_ENEMY_TURN
            else:
                return tuple()

    @property
    def round_is_new(self):
        """通常 MOVABLE_ENEMY_TURN = 2，即一个行走回合为 `玩家-玩家-敌人`，玩家移动两次，敌人移动一次。

        不同塞壬有不同的 MOVABLE_ENEMY_TURN：
            2: 非塞壬精英, SIREN_CL
            3: SIREN_CA

        Returns:
            bool: 是否为新的行走回合（即敌人已移动）。
        """
        if not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False
        for enemy in self.enemy_round.keys():
            for turn in self.round_enemy_turn:
                if self.round - enemy > 0 and (self.round - enemy) % turn == 0:
                    return True

        return False

    @property
    def round_wait(self):
        """
        Returns:
            float: 等待敌人移动的秒数。
        """
        second = 0
        if self.config.MAP_HAS_MOVABLE_ENEMY:
            count = 0
            for enemy, c in self.enemy_round.items():
                for turn in self.round_enemy_turn:
                    if self.round + 1 - enemy > 0 and (self.round + 1 - enemy) % turn == 0:
                        count += c
                        break
            second += count * self.config.MAP_SIREN_MOVE_WAIT

        if self.config.MAP_HAS_MAZE:
            if (self.round + 1) % 3 == 0:
                second += 1.0

        if self.config.MAP_HAS_BOUNCING_ENEMY:
            for route in self.map.bouncing_enemy_data:
                if route.select(may_bouncing_enemy=True):
                    second += self.config.MAP_SIREN_MOVE_WAIT

        return second

    @property
    def round_maze_changed(self):
        """
        Returns:
            bool: 迷宫是否在本轮开始时发生变化。
        """
        if not self.config.MAP_HAS_MAZE:
            return False
        return self.round != 0 and self.round % 3 == 0

    def maze_active_on(self, grid):
        """
        Args:
            grid: 格子坐标。

        Returns:
            bool: 迷宫墙壁是否在指定格子上。
        """
        if not self.config.MAP_HAS_MAZE:
            return False

        grid = self.map[location_ensure(grid)]
        if not grid.is_maze:
            return False
        return self.round % self.map.maze_round in grid.maze_round

    movable_before: SelectedGrids
    movable_before_normal: SelectedGrids

    @property
    def _walk_sight(self):
        sight = self.map.camera_sight
        return (sight[0], 0, sight[2], sight[3])

    def _goto(self, location, expected=''):
        """直接前往目标格子，并处理伏击、空袭、神秘事件、战斗。

        Args:
            location (tuple, str, GridInfo): 目标格子。
            expected (str): 目标格子上的预期结果，如 'combat'、'combat_siren'、'mystery'。
                到达时结果不符将发出警告。
        """
        location = location_ensure(location)
        result_mystery = ''
        self.movable_before = self.map.select(is_siren=True)
        self.movable_before_normal = self.map.select(is_enemy=True)
        if self.hp_retreat_triggered():
            self.withdraw()
        is_portal = self.map[location].is_portal
        while 1:
            self.fleet_ensure(self.fleet_current_index)
            self.submarine_advanced_prepare(location, expected)
            # 潜艇可能刚刚移动，使用最新位置判断图标是否遮挡目标舰队。
            may_submarine_icon = self.map.grid_covered(self.map[location], location=[(0, -1)])
            may_submarine_icon = may_submarine_icon and self.fleet_submarine_location == may_submarine_icon[0].location
            self.in_sight(location, sight=self._walk_sight)
            self.focus_to_grid_center()
            grid = self.convert_global_to_local(location)

            self.ambush_color_initial()
            self.enemy_searching_color_initial()
            grid.__str__ = location
            result = 'nothing'

            self.device.click(grid)
            arrived = False
            # Wait to confirm fleet arrived. It does't appear immediately if fleet in combat.
            extra = 0
            if self.config.Submarine_Mode in ['hunt_only', 'hunt_and_boss'] or self.submarine_hunt_enabled:
                extra += 4.5
            if self.config.MAP_HAS_LAND_BASED and grid.is_mechanism_trigger:
                extra += grid.mechanism_wait
            # 等待确认舰队到达。如果舰队在战斗中，不会立即出现。
            arrive_timer = Timer(0.5 + self.round_wait + extra, count=2)
            arrive_unexpected_timer = Timer(1.5 + self.round_wait + extra, count=6)
            # 伏击后的等待。
            ambushed_retry = Timer(0.5 + self.round_wait + extra, count=2)
            # 如果没有事件发生，重新点击。
            walk_timeout = Timer(20)
            walk_timeout.start()

            while 1:
                self.device.screenshot()
                self.view.update(image=self.device.image)
                if is_portal:
                    self.update(allow_error=True)
                    grid = self.view[self.view.center_loca]

                # 战斗
                if self.config.Campaign_UseFleetLock and not self.is_in_map():
                    if self.handle_retirement():
                        self.map_offensive()
                        walk_timeout.reset()
                    if self.handle_combat_low_emotion():
                        walk_timeout.reset()
                if self.combat_appear():
                    self.submarine_advanced_combat_start()
                    self.combat(
                        expected_end=self._expected_end(expected),
                        fleet_index=self.fleet_show_index,
                        submarine_mode=self._submarine_mode(expected)
                    )
                    self.hp_get()
                    self.lv_get(after_battle=True)
                    arrived = True if not self.config.MAP_HAS_MOVABLE_ENEMY else False
                    result = 'combat'
                    self.battle_count += 1
                    self.fleet_ammo -= 1
                    if 'siren' in expected or (self.config.MAP_HAS_MOVABLE_ENEMY and not expected):
                        self.siren_count += 1
                    elif self.map[location].may_enemy:
                        self.map[location].is_cleared = True

                    if self.catch_camera_repositioning(self.map[location]):
                        self.handle_boss_appear_refocus()
                        if sum(self.hp) < 0.01:
                            logger.warning('[地图-血量] 所有槽位血量为空，重试获取血量')
                            self.hp_get()
                    if self.config.MAP_FOCUS_ENEMY_AFTER_BATTLE:
                        self.camera = location
                        self.update()
                    grid = self.convert_global_to_local(location)
                    arrive_timer = Timer(0.5 + extra, count=2)
                    arrive_unexpected_timer = Timer(1.5 + extra, count=6)
                    walk_timeout.reset()
                    if not (grid.predict_fleet() and grid.predict_current_fleet()):
                        ambushed_retry.start()

                # 伏击
                if self.handle_ambush():
                    self.hp_get()
                    self.lv_get(after_battle=True)
                    walk_timeout.reset()
                    self.view.update(image=self.device.image)
                    if not (grid.predict_fleet() and grid.predict_current_fleet()):
                        ambushed_retry.start()

                # 神秘事件
                mystery = self.handle_mystery(button=grid)
                if mystery:
                    self.mystery_count += 1
                    result = 'mystery'
                    result_mystery = mystery

                # 猫咪攻击动画
                if self.handle_map_cat_attack():
                    # 已到达，战斗稍后出现，但仍需等待塞壬移动
                    arrive_timer.reset()
                    arrive_unexpected_timer.reset()
                    walk_timeout.reset()
                    continue

                # 大舰队弹窗
                # 通常在 combat_status 中处理，但在慢速 PC 上有时会延迟到战斗结束后才出现。
                if self.handle_guild_popup_cancel():
                    walk_timeout.reset()
                    continue

                # 企鹅 GIF 动画
                if self.handle_manjuu():
                    walk_timeout.reset()
                    continue

                if self.handle_walk_out_of_step():
                    raise MapWalkError('walk_out_of_step')

                # 到达
                arrive_predict = ''
                arrive_checker = False
                if self.is_in_map():
                    if not may_submarine_icon and grid.predict_fleet():
                        arrive_predict = '(is_fleet)'
                        arrive_checker = True
                    elif may_submarine_icon and grid.predict_current_fleet():
                        arrive_predict = '(may_submarine_icon, is_current_fleet)'
                        arrive_checker = True
                    elif self.config.MAP_WALK_USE_CURRENT_FLEET \
                            and expected != 'combat_boss' \
                            and not ('combat' in expected and grid.may_boss) \
                            and (grid.predict_fleet() or grid.predict_current_fleet()):
                        arrive_predict = '(MAP_WALK_USE_CURRENT_FLEET, is_current_fleet)'
                        arrive_checker = True
                    elif walk_timeout.reached() and grid.predict_current_fleet():
                        arrive_predict = '(walk_timeout, is_current_fleet)'
                        arrive_checker = True
                if arrive_checker:
                    if not arrive_timer.started():
                        logger.info(f'[地图-移动] 到达 {location2node(location)} {arrive_predict}'.strip())
                    arrive_timer.start()
                    arrive_unexpected_timer.start()
                    if result == 'nothing' and not arrive_timer.reached():
                        continue
                    if expected and result not in expected:
                        if arrive_unexpected_timer.reached():
                            logger.warning('[地图-移动] 到达结果异常')
                        else:
                            continue
                    if is_portal:
                        location = self.map[location].portal_link
                        self.camera = location
                    logger.info(f'[地图-移动] 到达 {location2node(location)} 确认。结果: {result}，预期: {expected}')
                    arrived = True
                    break
                else:
                    if arrive_timer.started():
                        arrive_timer.reset()
                    if arrive_unexpected_timer.started():
                        arrive_unexpected_timer.reset()

                # 剧情
                if expected == 'story':
                    if self.handle_story_skip():
                        result = 'story'
                        continue

                # 结束
                if ambushed_retry.started() and ambushed_retry.reached():
                    break
                if walk_timeout.reached():
                    logger.warning('[地图-移动] 移动超时，重试中')
                    self.predict()
                    self.ensure_edge_insight(skip_first_update=False)
                    break

            # 结束
            if arrived:
                # 弹药格子需要再次点击，否则下一次点击不会生效。
                if self.map[location].may_ammo:
                    self.device.click(grid)
                break

        self.map[self.fleet_current].is_fleet = False
        self.map[location].wipe_out()
        self.map[location].is_fleet = True
        self.__setattr__('fleet_%s_location' % self.fleet_current_index, location)
        if result_mystery == 'get_carrier':
            self.full_scan_carrier()
        if result == 'combat':
            self.round_battle(after_battle=True)
            self.predict()
        self.round_next()
        if self.round_is_new:
            if result != 'combat':
                self.predict()
            self.full_scan_movable(enemy_cleared=result == 'combat')
            self.find_path_initial()
            raise MapEnemyMoved
        if self.round_maze_changed:
            self.find_path_initial()
            raise MapEnemyMoved
        self.find_path_initial()
        if self.config.MAP_HAS_DECOY_ENEMY:
            if result == 'nothing' and expected == 'combat':
                raise MapEnemyMoved

    def goto(self, location, expected='', step_optimize=None, turning_optimize=None):
        """
        Args:
            location (tuple, str, GridInfo): 目标格子。
            expected (str): 目标格子上的预期结果，如 'combat'、'combat_siren'、'mystery'。
                到达时结果不符将发出警告。
            step_optimize (bool): 为 True 时按舰队步数行走。
            turning_optimize (bool): 为 True 时优化路线以减少伏击。
        """
        location = location_ensure(location)
        if step_optimize is None:
            step_optimize = self.config.MAP_HAS_FLEET_STEP
            if self.config.MAP_HAS_PORTAL or self.config.MAP_HAS_MAZE:
                step_optimize = True
        if turning_optimize is None:
            turning_optimize = self.config.MAP_HAS_AMBUSH

        # self.device.sleep(1000)
        if step_optimize or turning_optimize:
            step = self.fleet_step if step_optimize else 0
            nodes = self.map.find_path(location, step=step, turning_optimize=turning_optimize)
            for node in nodes:
                if self.maze_active_on(node):
                    logger.info(f'[地图-机关] 迷宫激活于 {location2node(node)}，弹跳等待')
                    for _ in range(10):
                        grids = self.map[node].maze_nearby.delete(self.map.select(is_fleet=True))
                        if grids.select(is_enemy=False):
                            grids = grids.select(is_enemy=False)
                        grids = grids.sort('cost')
                        self._goto(grids[0], expected='')
                try:
                    self._goto(node, expected=expected if node == nodes[-1] else '')
                except MapWalkError:
                    logger.warning('[地图-移动] 地图移动错误')
                    self.predict()
                    self.ensure_edge_insight()
                    nodes_ = self.map.find_path(node, step=1, turning_optimize=False)
                    for node_ in nodes_:
                        self._goto(node_, expected=expected if node == nodes[-1] else '')
        else:
            self._goto(location, expected=expected)

    def find_path_initial(self):
        """舰队移动或进入地图后调用此方法。
        """
        if self.fleet_1_location:
            self.map[self.fleet_1_location].is_fleet = True
        if self.fleet_2_location:
            self.map[self.fleet_2_location].is_fleet = True
        location_dict = {}
        if self.fleet_2_location:
            location_dict[2] = self.fleet_2_location
        location_dict[1] = self.fleet_1_location
        # 释放要塞阻塞
        if self.config.MAP_HAS_FORTRESS:
            if not self.map.select(is_fortress=True):
                self.map.select(is_mechanism_block=True).set(is_mechanism_block=False)
        self.map.find_path_initial_multi_fleet(
            location_dict, current=self.fleet_current, has_ambush=self.config.MAP_HAS_AMBUSH)

    def show_fleet(self):
        fleets = []
        for n in [1, 2]:
            fleet = self.__getattribute__('fleet_%s_location' % n)
            if len(fleet):
                text = 'Fleet_%s: %s' % (n, location2node(fleet))
                if self.fleet_current_index == n:
                    text = '[%s]' % text
                fleets.append(text)
        logger.info('[地图-舰队] ' + ' '.join(fleets))

    def show_submarine(self):
        logger.info(f'[地图-潜艇] 潜艇位置: {location2node(self.fleet_submarine_location)}')

    def full_scan(self, queue=None, must_scan=None, mode='normal'):
        if self.config.MAP_HAS_DECOY_ENEMY and mode == 'normal':
            mode = 'decoy'
        super().full_scan(
            queue=queue, must_scan=must_scan, battle_count=self.battle_count, mystery_count=self.mystery_count,
            siren_count=self.siren_count, carrier_count=self.carrier_count, mode=mode)

        if self.config.FLEET_2 and not self.fleet_2_location:
            fleets = self.map.select(is_fleet=True, is_current_fleet=False)
            if fleets.count:
                logger.info(f'[地图-舰队] 预测第二舰队为 {fleets[0]}')
                self.fleet_2_location = fleets[0].location

        for loca in [self.fleet_1_location, self.fleet_2_location]:
            if len(loca) and loca in self.map:
                grid = self.map[loca]
                if grid.may_boss and grid.is_caught_by_siren:
                    # 仅当 Boss 出现在舰队面前时
                    pass
                else:
                    self.map[loca].wipe_out()

    def full_scan_carrier(self):
        """在神秘事件中获得敌人搜索时调用此方法。
        """
        prev = self.map.select(is_enemy=True)
        self.full_scan(mode='carrier')
        diff = self.map.select(is_enemy=True).delete(prev)
        logger.info(f'[地图-舰队] 航母出生点: {diff}')

    def full_scan_movable(self, enemy_cleared=True):
        """敌人移动后调用此方法。

        Args:
            enemy_cleared (bool): 为 True 表示已清除敌人且需要扫描新生成的敌人。
                                  为 False 表示只是简单行走，仅需扫描可移动的敌人。
        """
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            if self.config.MAP_HAS_MOVABLE_ENEMY:
                for grid in self.movable_before:
                    grid.wipe_out()
                for grid in self.movable_before_normal:
                    grid.wipe_out()
                self.full_scan(mode='movable')
                self.track_movable(enemy_cleared=enemy_cleared, siren=True)
                self.track_movable(enemy_cleared=enemy_cleared, siren=False)
            else:
                for grid in self.movable_before_normal:
                    grid.wipe_out()
                self.full_scan(mode='movable')
                self.track_movable(enemy_cleared=enemy_cleared, siren=False)

        elif self.config.MAP_HAS_MOVABLE_ENEMY:
            for grid in self.movable_before:
                grid.wipe_out()
            self.full_scan(queue=None if enemy_cleared else self.movable_before,
                           must_scan=self.movable_before, mode='movable')
            self.track_movable(enemy_cleared=enemy_cleared, siren=True)

    def track_movable(self, enemy_cleared=True, siren=True):
        """追踪敌人移动并预测缺失的敌人。

        Args:
            enemy_cleared (bool): 为 True 表示已清除敌人且需要扫描新生成的敌人。
                                  为 False 表示只是简单行走，仅需扫描可移动的敌人。
            siren (bool): 为 True 时追踪塞壬，为 False 时追踪普通敌人。
        """
        # Track siren moving
        before = self.movable_before if siren else self.movable_before_normal
        after = self.map.select(is_siren=True) if siren else self.map.select(is_enemy=True)
        step = self.config.MOVABLE_ENEMY_FLEET_STEP if siren else 1
        spawn = self.map.select(may_siren=True) if siren else self.map.select(may_enemy=True)
        matched_before, matched_after = match_movable(
            before=before.location,
            spawn=spawn.location,
            after=after.location,
            fleets=[self.fleet_current] if enemy_cleared else [],
            fleet_step=step
        )
        matched_before = self.map.to_selected(matched_before)
        matched_after = self.map.to_selected(matched_after)
        logger.info(f'[地图-敌舰] 可移动敌舰 {before} -> {after}')
        logger.info(f'[地图-敌舰] 跟踪敌舰 {matched_before} -> {matched_after}')

        # 删除错误预测
        # 如果 MAP_HAS_MOVABLE_NORMAL_ENEMY 则保留，这种情况比较混乱
        if not self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            for grid in after.delete(matched_after):
                if not grid.may_siren:
                    logger.warning(f'[地图-检测] 错误检测: {grid}')
                    grid.wipe_out()

        # 预测缺失的塞壬
        diff = before.delete(matched_before)
        _, missing = self.map.missing_get(
            self.battle_count, self.mystery_count, self.siren_count, self.carrier_count, mode='normal')
        missing = missing['siren'] if siren else missing['enemy']
        if diff and missing != 0:
            logger.warning(f'[地图-敌舰] 可移动敌舰跟踪丢失: {diff}')

            # 计算被覆盖的格子
            covered = self.map.grid_covered(self.map[self.fleet_current], location=[(0, -2)])
            if self.fleet_1_location:
                covered = covered.add(self.map.grid_covered(self.map[self.fleet_1_location], location=[(0, -1)]))
            if self.fleet_2_location:
                covered = covered.add(self.map.grid_covered(self.map[self.fleet_2_location], location=[(0, -1)]))
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY and not self.config.MAP_ENEMY_TEMPLATE:
                # 右侧格子的 enemy_scale 图标可能被舰队覆盖
                # 如果敌人模板为空，必须通过 enemy_scale 预测
                if self.fleet_1_location:
                    covered = covered.add(self.map.grid_covered(self.map[self.fleet_1_location], location=[(1, 0)]))
                if self.fleet_2_location:
                    covered = covered.add(self.map.grid_covered(self.map[self.fleet_2_location], location=[(1, 0)]))
            covered = covered.add(self.map._map_covered)
            if siren:
                for grid in after:
                    covered = covered.add(self.map.grid_covered(grid))
            else:
                for grid in self.map.select(is_siren=True):
                    covered = covered.add(self.map.grid_covered(grid))
            logger.attr('敌舰覆盖', covered)

            # 计算塞壬可达格子
            accessible = SelectedGrids([])
            if self.config.MAP_HAS_WALL:
                # 塞壬无视墙壁
                self.map.grid_connection_initial(
                    wall=False,
                    portal=self.config.MAP_HAS_PORTAL,
                )
            for grid in diff:
                self.map.find_path_initial(grid, has_ambush=False)
                accessible = accessible.add(self.map.select(cost=0)).add(self.map.select(cost=1))
                if siren:
                    accessible = accessible.add(self.map.select(cost=2))
            # 恢复寻路结果
            if self.config.MAP_HAS_WALL:
                self.map.grid_connection_initial(
                    wall=self.config.MAP_HAS_WALL,
                    portal=self.config.MAP_HAS_PORTAL,
                )
            self.map.find_path_initial(self.fleet_current, has_ambush=self.config.MAP_HAS_AMBUSH)
            logger.attr('敌舰可达', accessible)

            # 取交集进行预测
            predict = accessible.intersect(covered).select(is_sea=True, is_fleet=False)
            logger.info(f'[地图-敌舰] 可移动敌舰预测: {predict}')
            matched_after = matched_after.add(predict)
            for grid in predict:
                if siren:
                    grid.is_siren = True
                grid.is_enemy = True
        elif missing == 0:
            logger.info(f'[地图-敌舰] 可移动敌舰跟踪丢弃: {diff}')

        for grid in matched_after:
            if grid.location != self.fleet_current:
                grid.is_movable = True

    def find_all_fleets(self):
        logger.hr('查找所有舰队')
        queue = self.map.select(is_spawn_point=True)
        while queue:
            queue = queue.sort_by_camera_distance(self.camera)
            self.in_sight(queue[0], sight=(-1, 0, 1, 2))
            grid = self.convert_global_to_local(queue[0])
            if grid.predict_fleet():
                if grid.predict_current_fleet():
                    self.fleet_1 = queue[0].location
                else:
                    self.fleet_2 = queue[0].location
            queue = queue[1:]

    def find_current_fleet(self):
        logger.hr('查找当前舰队')
        if not self.config.POOR_MAP_DATA:
            fleets = self.map.select(is_fleet=True, is_spawn_point=True)
        else:
            fleets = self.map.select(is_fleet=True)
        logger.info('[地图-舰队] 舰队: %s' % str(fleets))
        count = fleets.count
        if count == 1:
            if not self.config.FLEET_2:
                self.fleet_1 = fleets[0].location
            else:
                logger.info('[地图-舰队] 未检测到第二舰队')
                if self.config.POOR_MAP_DATA and not self.map.select(is_spawn_point=True):
                    self.fleet_1 = fleets[0].location
                elif self.map.select(is_spawn_point=True).count == 2:
                    logger.info('[地图-舰队] 预测舰队为出生点')
                    another = self.map.select(is_spawn_point=True).delete(SelectedGrids([fleets[0]]))[0]
                    if fleets[0].is_current_fleet:
                        self.fleet_1 = fleets[0].location
                        self.fleet_2 = another.location
                    else:
                        self.fleet_1 = another.location
                        self.fleet_2 = fleets[0].location
                else:
                    cover = self.map.grid_covered(fleets[0], location=[(0, -1)])
                    if fleets[0].is_current_fleet and len(cover) and cover[0].is_spawn_point:
                        self.fleet_1 = fleets[0].location
                        self.fleet_2 = cover[0].location
                    else:
                        self.find_all_fleets()
        elif count == 2:
            current = self.map.select(is_current_fleet=True)
            if current.count == 1:
                self.fleet_1 = current[0].location
                self.fleet_2 = fleets.delete(current)[0].location
            else:
                fleets = fleets.sort_by_camera_distance(self.camera)
                self.in_sight(fleets[0], sight=(-1, 0, 1, 2))
                if self.convert_global_to_local(fleets[0]).predict_current_fleet():
                    self.fleet_1 = fleets[0].location
                    self.fleet_2 = fleets[1].location
                else:
                    self.in_sight(fleets[1], sight=(-1, 0, 1, 2))
                    if self.convert_global_to_local(fleets[1]).predict_current_fleet():
                        self.fleet_1 = fleets[1].location
                        self.fleet_2 = fleets[0].location
                    else:
                        logger.warning('[地图-舰队] 未找到当前舰队')
                        self.fleet_1 = fleets[0].location
                        self.fleet_2 = fleets[1].location
        else:
            if count == 0:
                logger.warning('[地图-舰队] 未检测到任何舰队')
                fleets = self.map.select(is_current_fleet=True)
                if fleets.count:
                    self.fleet_1 = fleets[0].location
            if count > 2:
                logger.warning('[地图-舰队] 舰队过多: %s' % str(fleets))
            self.find_all_fleets()

        self.show_fleet()
        return self.fleet_current

    def find_all_submarines(self):
        logger.hr('查找所有潜艇')
        queue = self.map.select(is_submarine_spawn_point=True)
        while queue:
            queue = queue.sort_by_camera_distance(self.camera)
            self.in_sight(queue[0], sight=(-2, -1, 2, -1))
            grid = self.convert_global_to_local(queue[0])
            if grid.predict_submarine():
                self.fleet_submarine = queue[0].location
                break
            queue = queue[1:]

    def find_submarine(self):
        if not (self.config.SUBMARINE and self.map.select(is_submarine_spawn_point=True)):
            return False

        fleets = self.map.select(is_submarine=True)
        count = fleets.count
        if count == 1:
            self.fleet_submarine = fleets[0].location
        elif count == 0:
            logger.info('[地图-潜艇] 未找到潜艇')
            # 尝试出生点
            spawn_point = self.map.select(is_submarine_spawn_point=True)
            if spawn_point.count == 1:
                logger.info(f'[地图-潜艇] 预测唯一潜艇出生点 {spawn_point[0]} 为潜艇')
                self.fleet_submarine = spawn_point[0].location
            else:
                logger.info(f'[地图-潜艇] 存在多个潜艇出生点: {spawn_point}')
                # 尝试被覆盖的格子
                covered = SelectedGrids([])
                for grid in spawn_point:
                    covered = covered.add(self.map.grid_covered(grid, location=[(0, 1)]))
                covered = covered.filter(lambda g: g.is_enemy or g.is_fleet or g.is_siren or g.is_boss)
                if covered.count == 1:
                    spawn_point = self.map.grid_covered(covered[0], location=[(0, -1)])
                    logger.info(f'[地图-潜艇] 潜艇 {spawn_point[0]} 被 {covered[0]} 覆盖')
                    self.fleet_submarine = spawn_point[0].location
                else:
                    logger.info('[地图-潜艇] 发现多个潜艇出生点被覆盖')
                    # 放弃预测，全面搜索
                    self.find_all_submarines()
        else:
            logger.warning('[地图-潜艇] 潜艇过多: %s' % str(fleets))
            self.find_all_submarines()

        if not len(self.fleet_submarine_location):
            if self.submarine_advanced is not None:
                logger.warning('[地图-潜艇] 无法确认潜艇位置，跳过高级出击')
                return False
            logger.warning('[地图-潜艇] 无法找到潜艇，假设在地图中心')
            shape = self.map.shape
            center = (shape[0] // 2, shape[1] // 2)
            self.fleet_submarine = self.map.select(is_land=False).sort_by_camera_distance(center)[0].location

        self.show_submarine()
        return self.fleet_submarine_location

    def map_init(self, map_):
        """进入地图后、执行任何操作前应调用此方法。

        Args:
            map_ (CampaignMap): 战役地图对象。
        """
        logger.hr('地图初始化')
        self.map_data_init(map_)
        self.map_control_init()

    def map_data_init(self, map_):
        """根据设置和地图状态初始化地图数据。
        仅进行数据处理，不进行截图和点击操作。

        Args:
            map_ (CampaignMap): 战役地图对象。
        """
        self.fleet_1_location = ()
        self.fleet_2_location = ()
        self.fleet_submarine_location = ()
        self.fleet_current_index = 1
        self.battle_count = 0
        self.submarine_advanced_reset()
        self.mystery_count = 0
        self.carrier_count = 0
        self.siren_count = 0
        self.ammo_count = 3
        self.map = map_
        self.map.reset()
        self.handle_clear_mode_config_cover()
        self.map.poor_map_data = self.config.POOR_MAP_DATA
        self.map.load_map_data(use_loop=self.map_is_clear_mode)
        self.map.load_spawn_data(use_loop=self.map_is_clear_mode)
        self.map.grid_connection_initial(
            wall=self.config.MAP_HAS_WALL,
            portal=self.config.MAP_HAS_PORTAL,
        )
        self.map.load_mechanism(
            land_based=self.config.MAP_HAS_LAND_BASED,
            maze=self.config.MAP_HAS_MAZE,
            fortress=self.config.MAP_HAS_FORTRESS,
            bouncing_enemy=self.config.MAP_HAS_BOUNCING_ENEMY,
        )

    def map_control_init(self):
        """操作前的准备工作。
        包括选择策略、计算血量和等级、初始化相机位置、执行首次地图扫描。
        """
        self.update()
        switched = self.handle_fleet_reverse()
        if not switched:
            switched = self.fleet_set(index=1)
        # infobar might cover bottom edge, causing retries in ensure_edge_insight
        # if map surface is dark and fleet spawn point is near bottom edge,
        # MAP_FLEET_REVERSE_WAIT_INFO_BAR to prevent that happens
        if switched and self.config.MAP_FLEET_REVERSE_WAIT_INFO_BAR:
            # info bar might not appear immediately, use ensure_no_info_bar to wait until appear with timeout
            self.ensure_no_info_bar()
        self.handle_strategy(index=self.fleet_show_index)
        self.hp_reset()
        self.hp_get()
        self.lv_reset()
        self.lv_get()
        self.ensure_edge_insight(preset=self.map.in_map_swipe_preset_data)
        self.handle_info_bar()  # "切换到第二舰队" 的信息栏会遮挡弹药图标
        self.full_scan(must_scan=self.map.camera_data_spawn_point, mode='init')
        self.find_current_fleet()
        self.find_submarine()
        self.find_path_initial()
        self.map.show_cost()
        self.round_reset()
        self.round_battle(after_battle=False)

    def handle_clear_mode_config_cover(self):
        if not self.map_is_clear_mode:
            return False

        if self.config.POOR_MAP_DATA and self.map.is_map_data_poor:
            self.config.POOR_MAP_DATA = False
        self.map.fortress_data = [(), ()]
        self.map.bouncing_enemy_data = []

        return True

    def _expected_end(self, expected):
        for data in self.map.spawn_data:
            if data.get('battle') == self.battle_count and 'boss' in expected:
                return 'in_stage'
            if data.get('battle') == self.battle_count + 1:
                if data.get('enemy', 0) + data.get('siren', 0) + data.get('boss', 0) > 0:
                    return 'with_searching'
                else:
                    return 'no_searching'

        if 'boss' in expected:
            return 'in_stage'

        matched = False
        for data in self.map.spawn_data:
            if data.get('battle') == self.battle_count + 1:
                matched = True
        if not len(self.map.spawn_data) or matched:
            # No spawn_data
            # spawn_data is not continuous, some battles are missing
            return None
        else:
            # Out of the spawn_data, nothing will spawn
            return 'no_searching'

    def _submarine_mode(self, expected):
        if self.config.Submarine_Mode == 'advanced':
            state = self.submarine_advanced
            if state is not None and state.plan is not None and state.plan.mode == 'call' and not state.consumed:
                return 'advanced_call'
            return 'do_not_use'
        if self.is_call_submarine_at_boss:
            if 'boss' in expected:
                return 'every_combat'
            else:
                return 'do_not_use'
        else:
            return None

    def fleet_at(self, grid, fleet=None):
        """
        Args:
            grid (Grid): 格子对象。
            fleet (int): 舰队编号，1 或 2。

        Returns:
            bool: 舰队是否在指定格子上。
        """
        if fleet is None:
            return self.fleet_current == grid.location
        if fleet == 1:
            return self.fleet_1_location == grid.location
        else:
            return self.fleet_2_location == grid.location

    def check_accessibility(self, grid, fleet=None):
        """
        Args:
            grid (Grid): 格子对象。
            fleet (int, str): 舰队编号，1、2 或 'boss'。

        Returns:
            bool: 是否可达。
        """
        if fleet is None:
            return grid.is_accessible
        if isinstance(fleet, str) and fleet.isdigit():
            fleet = int(fleet)
        if fleet == 'boss':
            fleet = self.fleet_boss_index

        if fleet == self.fleet_current_index:
            return grid.is_accessible
        else:
            backup = self.fleet_current_index
            self.fleet_current_index = fleet
            self.find_path_initial()
            result = grid.is_accessible

            self.fleet_current_index = backup
            self.find_path_initial()
            return result

    def brute_find_roadblocks(self, grid, fleet=None):
        """
        Args:
            grid (Grid): 目标格子。
            fleet (int): 1 或 2，默认为当前舰队。

        Returns:
            SelectedGrids: 路障格子集合。
        """
        if fleet is not None and fleet != self.fleet_current_index:
            backup = self.fleet_current_index
            self.fleet_current_index = fleet
            self.find_path_initial()
        else:
            backup = None

        if grid.is_accessible:
            if backup is not None:
                self.fleet_current_index = backup
                self.find_path_initial()
            return SelectedGrids([])

        enemies = self.map.select(is_enemy=True)
        logger.info(f'[地图-路障] 潜在敌舰路障: {enemies}')
        for repeat in range(1, enemies.count + 1):
            for select in itertools.product(enemies, repeat=repeat):
                for block in select:
                    block.is_enemy = False
                self.find_path_initial()
                for block in select:
                    block.is_enemy = True

                if grid.is_accessible:
                    select = SelectedGrids(list(select))
                    logger.info(f'[地图-路障] 敌舰路障: {select}')
                    if backup is not None:
                        self.fleet_current_index = backup
                        self.find_path_initial()
                    return select

        logger.warning('[地图-路障] 敌舰路障尝试耗尽')

    def catch_camera_repositioning(self, destination):
        """
        Args:
            destination (GridInfo): 全局地图格子。
        """
        appear = False
        for data in self.map.spawn_data:
            if data.get('battle') == self.battle_count and data.get('boss', 0):
                logger.info('[地图-摄像机] Boss出现后摄像机重新定位')
                appear = True

        # if self.config.POOR_MAP_DATA:
        #     self.device.screenshot()
        #     grids = Grids(self.device.image, config=self.config)
        #     grids.predict()
        #     grids.show()
        #     for grid in grids:
        #         if grid.is_boss:
        #             logger.info('[地图-摄像机] Boss出现后摄像机重新定位')
        #             appear = True
        #             for g in self.map:
        #                 g.wipe_out()
        #             break

        return appear

    def handle_boss_appear_refocus(self, preset=None):
        """Boss 出现后重新聚焦到之前的相机位置。

        Args:
            preset (tuple): 预设的滑动偏移量 (x, y)。
        """
        camera = self.camera
        if preset is None:
            preset = self.config.MAP_BOSS_APPEAR_REFOCUS_SWIPE

        if preset is not None and np.linalg.norm(preset) > 0:
            try:
                self.update()
            except MapDetectionError:
                logger.info(f'[地图-摄像机] Boss出现后发生地图检测错误，尝试滑动预设 {preset}')
                # Swipe optimize here may not be accurate.
                self.map_swipe(preset)
            self.ensure_edge_insight()
        else:
            self.update()
            self.ensure_edge_insight()

        logger.info('[地图-摄像机] 重新聚焦到之前的摄像机位置')
        self.focus_to(camera)

    def fleet_checked_reset(self):
        self.map_fleet_checked = False
        self.fleet_1_formation_fixed = False
        self.fleet_2_formation_fixed = False

    def _submarine_goto(self, location):
        """移动潜艇到指定位置。

        Args:
            location (tuple, str, GridInfo): 目标位置。

        Returns:
            bool: 潜艇是否移动了。

        Pages:
            in: SUBMARINE_MOVE_CONFIRM
            out: SUBMARINE_MOVE_CONFIRM
        """
        location = location_ensure(location)
        moved = True
        while 1:
            self.in_sight(location, sight=self._walk_sight)
            self.focus_to_grid_center()
            grid = self.convert_global_to_local(location)
            grid.__str__ = location

            self.device.click(grid)
            arrived = False
            # Usually no need to wait
            # 通常不需要等待
            arrive_timer = Timer(0.1, count=0)
            # 如果没有事件发生，重新点击。
            walk_timeout = Timer(2, count=6).start()

            while 1:
                self.device.screenshot()
                self.view.update(image=self.device.image)

                # Arrive
                arrive_checker = grid.predict_submarine_move()
                if grid.predict_submarine() or (walk_timeout.reached() and grid.predict_fleet()):
                    arrive_checker = True
                    moved = False
                if arrive_checker:
                    if not arrive_timer.started():
                        logger.info(f'[地图-移动] 到达 {location2node(location)}')
                    arrive_timer.start()
                    if not arrive_timer.reached():
                        continue
                    logger.info(f'[地图-潜艇] 潜艇到达 {location2node(location)} 确认')
                    if not moved:
                        logger.info(f'[地图-潜艇] 潜艇已在 {location2node(location)}')
                    arrived = True
                    break

                # End
                if walk_timeout.reached():
                    logger.warning('[地图-移动] 移动超时，重试中')
                    self.predict()
                    self.ensure_edge_insight(skip_first_update=False)
                    break

            # End
            if arrived:
                break

        return moved

    def submarine_goto(self, location):
        """打开策略面板，移动潜艇到指定位置，关闭策略面板。

        Args:
            location (tuple, str, GridInfo): 目标位置。

        Returns:
            bool: 潜艇是否移动了。

        Pages:
            in: IN_MAP
            out: IN_MAP
        """
        self.strategy_open()
        self.strategy_submarine_move_enter()
        if self._submarine_goto(location):
            self.strategy_submarine_move_confirm()
            self.fleet_submarine = location_ensure(location)
            result = True
        else:
            self.strategy_submarine_move_cancel()
            self.fleet_submarine = location_ensure(location)
            result = False
        # 进入潜艇移动模式后，游戏会重新启用狩猎区域视图
        self.strategy_set_execute(sub_view=False)
        self.strategy_close()
        return result

    def submarine_move_near_boss(self, boss):
        """将潜艇移动到 Boss 附近。

        Args:
            boss (tuple, str, GridInfo): Boss 目标位置。

        Returns:
            bool: 潜艇是否移动了。
        """
        if not (self.is_call_submarine_at_boss and self.map.select(is_submarine_spawn_point=True)):
            return False
        if self.config.Submarine_DistanceToBoss == 'use_open_ocean_support':
            logger.info('[地图-潜艇] 将使用远洋支援，跳过移动潜艇')
            return False

        boss = location_ensure(boss)
        logger.info(f'[地图-潜艇] 移动潜艇到 {location2node(boss)} 附近')

        self.map.find_path_initial(self.fleet_submarine_location, has_ambush=False, has_enemy=False)
        self.map.show_cost()

        def get_location(distance=2):
            grids = self.map.select(is_land=False).filter(
                lambda grid: np.sum(np.abs(np.subtract(grid.location, boss))) <= distance)
            if grids:
                return grids.sort('cost')[0].location
            elif distance > 0:
                logger.info(f'[地图-潜艇] 无法在距离 {distance} 内找到Boss附近格子，回退到 {distance - 1}')
                return get_location(distance - 1)
            else:
                logger.warning(f'[地图-潜艇] 无法在距离 {distance} 内找到Boss附近格子，返回Boss位置')
                return boss

        distance_dict = {
            'to_boss_position': 0,
            '1_grid_to_boss': 1,
            '2_grid_to_boss': 2
        }
        distance_to_boss = distance_dict.get(self.config.Submarine_DistanceToBoss, 0)
        logger.attr('距Boss距离', distance_to_boss)

        if np.sum(np.abs(np.subtract(self.fleet_submarine_location, boss))) <= distance_to_boss:
            logger.info('[地图-潜艇] Boss已在狩猎区域内')
            self.find_path_initial()
            return False
        else:
            near = get_location(distance_to_boss)
            self.find_path_initial()
            logger.info(f'[地图-潜艇] 移动潜艇到 {location2node(near)}')
            return self.submarine_goto(near)
