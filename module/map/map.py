"""地图探索和战斗编排模块。

整合舰队管理、路径规划和敌人优先级系统，
提供完整的地图探索和战斗编排逻辑。

核心功能：
- 敌人清除：按优先级选择并清除地图上的敌人
- 神秘格子处理：踩踏神秘格子获取道具/弹药
- Boss 战：定位并挑战 Boss
- 关卡全清：清除地图上所有可击败的敌人

敌人优先级系统：
- 通过 EnemyPriority 配置控制敌人选择策略
- 支持按敌人规模、类型、距离等因素排序
- 支持可移动敌人（塞壬）的追踪和预测

继承自 Fleet，组合了舰队管理、相机控制和战斗系统。
"""

import itertools
import re

from module.base.filter import Filter
from module.exception import MapEnemyMoved
from module.logger import logger
from module.map.fleet import Fleet
from module.map.map_grids import RoadGrids, SelectedGrids
from module.map_detection.grid_info import GridInfo

# 敌人过滤器
ENEMY_FILTER = Filter(regex=re.compile('^(.*?)$'), attr=('str',))


class Map(Fleet):
    """地图探索和战斗编排器。

    管理地图上的敌人清除、神秘格子处理和 Boss 战。
    通过敌人优先级系统智能选择下一个目标。
    """
    def clear_chosen_enemy(self, grid, expected=''):
        """前往指定格子并清除该处敌人。

        Args:
            grid (GridInfo): 目标格子对象。
            expected (str, optional): 预期结果类型，如 'boss'、'siren'、'fortress'。默认为 ''。

        Returns:
            bool: 战斗计数是否增加（即是否成功进行了战斗）。
        """
        logger.info('[地图-策略] 目标敌舰规模权重:%s' % (self.config.EnemyPriority_EnemyScaleBalanceWeight))
        logger.info('[地图-战斗] 清除敌舰: %s' % grid)
        expected = f'combat_{expected}' if expected else 'combat'
        battle_count = self.battle_count
        self.show_fleet()
        if self.emotion.is_calculate and self.config.Campaign_UseFleetLock:
            self.emotion.wait(fleet_index=self.fleet_current_index)
        self.goto(grid, expected=expected)

        self.full_scan()
        self.find_path_initial()
        self.map.show_cost()
        return self.battle_count >= battle_count

    def clear_chosen_mystery(self, grid):
        """前往并触发指定的神秘问号格子。

        Args:
            grid (GridInfo): 目标神秘格子对象。
        """
        logger.info('[地图-战斗] 清除神秘点: %s' % grid)
        self.show_fleet()
        self.goto(grid, expected='mystery')
        # self.mystery_count += 1
        self.map.show_cost()

    def pick_up_ammo(self, grid=None):
        """前往弹药补给格拾取弹药。

        Args:
            grid (GridInfo, optional): 目标弹药格子，为 None 时自动选取最近的可达弹药格。默认为 None。

        Returns:
            bool: 地图无可用弹药格时返回 False。
        """
        if grid is None:
            grid = self.map.select(may_ammo=True)
            if not grid:
                logger.info('[地图-弹药] 地图无弹药点')
                return False
            grid = grid[0]

        if self.ammo_count > 0 and grid.is_accessible:
            logger.info('[地图-弹药] 拾取弹药: %s' % grid)
            self.goto(grid, expected='')
            self.ensure_no_info_bar()

            # self.ammo_count -= 5 - self.battle_count
            recover = 5 - self.fleet_ammo
            recover = 3 if recover > 3 else recover
            logger.attr('获得弹药', recover)

            self.ammo_count -= recover
            self.fleet_ammo += recover

    def clear_mechanism(self, grids=None):
        """触发地图机关。

        Args:
            grids (SelectedGrids, optional): 待触发的机关格子集合。为 None 时选择所有未阻挡的机关触发格。默认为 None。

        Returns:
            bool: 始终返回 False，因为未清除任何敌人。

        Raises:
            MapEnemyMoved: 机关触发改变地图阻挡状态时抛出，用于重新规划路径。
        """
        if not self.config.MAP_HAS_LAND_BASED:
            return False

        if not grids:
            grids = self.map.select(is_mechanism_trigger=True, is_mechanism_block=False)
        else:
            grids = grids.select(is_mechanism_trigger=True, is_mechanism_block=False)
        grids = self.select_grids(grids, is_accessible=True, sort=('weight', 'cost'))

        for grid in grids:
            logger.info(f'[地图-机关] 清除机关: {grid}')
            self.goto(grid)
            self.map.show_cost()
            logger.info(f'[地图-机关] 机关触发释放: {grid.mechanism_trigger}')
            logger.info(f'[地图-机关] 机关障碍释放: {grid.mechanism_block}')
            raise MapEnemyMoved

        logger.info('[地图-机关] 所有机关已清除')
        return False

    @staticmethod
    def select_grids(grids, nearby=False, is_accessible=True, scale=(), genre=(), strongest=False, weakest=False,
                     sort=('weight', 'cost'), ignore=None):
        """按指定条件筛选并排序网格集合。

        Args:
            grids (SelectedGrids): 待筛选的网格集合。
            nearby (bool, optional): 是否仅选择当前相邻的网格。默认为 False。
            is_accessible (bool, optional): 是否仅选择当前可达的网格。默认为 True。
            scale (tuple[int, ...] | list[int], optional): 敌人规模，元组表示无序选择，列表表示按先后顺序首个匹配。默认为 ()。
            genre (tuple[str, ...] | list[str], optional): 敌人类型（如 'light', 'main', 'carrier', 'treasure'）。默认为 ()。
            strongest (bool, optional): 是否优先选择最强敌人（规模从大到小）。默认为 False。
            weakest (bool, optional): 是否优先选择最弱敌人（规模从小到大）。默认为 False。
            sort (tuple[str, ...], optional): 排序属性依据。默认为 ('weight', 'cost')。
            ignore (SelectedGrids, optional): 需要剔除的网格集合。默认为 None。

        Returns:
            SelectedGrids: 筛选与排序后的网格集合。
        """
        if nearby:
            grids = grids.select(is_nearby=True)
        if is_accessible:
            grids = grids.select(is_accessible=True)
        if ignore is not None:
            grids = grids.delete(grids=ignore)
        if len(scale):
            enemy = SelectedGrids([])
            for enemy_scale in scale:
                enemy = enemy.add(grids.select(enemy_scale=enemy_scale))
                if isinstance(scale, list) and enemy:
                    break
            grids = enemy
        if len(genre):
            enemy = SelectedGrids([])
            for enemy_genre in genre:
                # 敌人类型首字母应大写
                enemy_genre = enemy_genre[0].upper() + enemy_genre[1:] if enemy_genre[0].islower() else enemy_genre
                enemy = enemy.add(grids.select(enemy_genre=enemy_genre))
                if isinstance(genre, list) and enemy:
                    break
            grids = enemy
        if strongest:
            for scale in [3, 2, 1, 0]:
                enemy = grids.select(enemy_scale=scale)
                if enemy:
                    grids = enemy
                    break
        if weakest:
            for scale in [1, 2, 3, 0]:
                enemy = grids.select(enemy_scale=scale)
                if enemy:
                    grids = enemy
                    break

        if grids:
            grids = grids.sort(*sort)

        return grids

    @staticmethod
    def show_select_grids(grids, **kwargs):
        """在日志中显示网格筛选条件与结果列表。

        Args:
            grids (SelectedGrids): 筛选后的网格集合。
            **kwargs: 筛选参数键值对。
        """
        length = 3
        keys = list(kwargs.keys())
        for index in range(0, len(keys), length):
            text = [f'{key}={kwargs[key]}' for key in keys[index:index + length]]
            text = ', '.join(text)
            logger.info(text)

        logger.info(f'[地图] 格子: {grids}')

    def clear_all_mystery(self, **kwargs):
        """遍历并触发地图上所有可达的神秘问号事件。

        Args:
            **kwargs: 网格筛选参数。

        Returns:
            bool: 始终返回 False，因为未清除任何敌人。
        """
        kwargs['sort'] = ('cost',)
        while 1:
            grids = self.map.select(is_mystery=True)
            grids = self.select_grids(grids, **kwargs)

            if not grids:
                break

            logger.hr('清除所有神秘点')
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_mystery(grids[0])

        return False

    def clear_enemy(self, **kwargs):
        """按优先级筛选并清除一个普通敌人。

        若无合适敌人则不做任何操作。

        Args:
            **kwargs: 传给 select_grids 的筛选与排序参数。

        Returns:
            bool: 是否清除了敌人。
        """
        grids = self.map.select(is_enemy=True, is_boss=False)

        target = self.config.EnemyPriority_EnemyScaleBalanceWeight
        if target == 'S3_enemy_first':
            kwargs['strongest'] = True
        elif target == 'S1_enemy_first':
            kwargs['weakest'] = True
        elif self.config.MAP_CLEAR_ALL_THIS_TIME:
            kwargs['strongest'] = True
        grids = self.select_grids(grids, **kwargs)

        if grids:
            logger.hr('清除敌舰')
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_roadblocks(self, roads, **kwargs):
        """清除指定路线上的敌人路障。

        Args:
            roads (list[RoadGrids]): 路线列表。
            **kwargs: 筛选与排序参数。

        Returns:
            bool: 是否清除了敌人。
        """
        grids = SelectedGrids([])
        for road in roads:
            grids = grids.add(road.roadblocks())

        target = self.config.EnemyPriority_EnemyScaleBalanceWeight
        if target == 'S3_enemy_first':
            kwargs['strongest'] = True
        elif target == 'S1_enemy_first':
            kwargs['weakest'] = True
        elif self.config.MAP_CLEAR_ALL_THIS_TIME:
            kwargs['strongest'] = True
        grids = self.select_grids(grids, **kwargs)

        if grids:
            logger.hr('清除路障')
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_potential_roadblocks(self, roads, **kwargs):
        """清除潜在路障，避免路线被敌人完全封死。

        Args:
            roads (list[RoadGrids]): 路线列表。
            **kwargs: 筛选与排序参数。

        Returns:
            bool: 是否清除了敌人。
        """
        grids = SelectedGrids([])
        for road in roads:
            grids = grids.add(road.potential_roadblocks())

        target = self.config.EnemyPriority_EnemyScaleBalanceWeight
        if target == 'S3_enemy_first':
            kwargs['strongest'] = True
        elif target == 'S1_enemy_first':
            kwargs['weakest'] = True
        elif self.config.MAP_CLEAR_ALL_THIS_TIME:
            kwargs['strongest'] = True
        grids = self.select_grids(grids, **kwargs)

        if grids:
            logger.hr('避开潜在路障')
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_first_roadblocks(self, roads, **kwargs):
        """确保每条路线上首个遇到的路障敌舰被清除。

        Args:
            roads (list[RoadGrids]): 路线列表。
            **kwargs: 筛选与排序参数。

        Returns:
            bool: 是否清除了敌人。
        """
        grids = SelectedGrids([])
        for road in roads:
            grids = grids.add(road.first_roadblocks())

        grids = self.select_grids(grids, **kwargs)

        if grids:
            logger.hr('清除首个路障')
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_grids_for_faster(self, grids, **kwargs):
        """清除部分格子中的敌舰以缩短行走距离。

        Args:
            grids (SelectedGrids): 待清除的格子集合。
            **kwargs: 筛选与排序参数。

        Returns:
            bool: 是否清除了敌人。
        """

        grids = grids.select(is_enemy=True)
        grids = self.select_grids(grids, **kwargs)

        if grids:
            logger.hr('清除格子以加速')
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_boss(self):
        """清除 Boss。

        此方法适用于常规地图；复杂地图推荐使用 brute_clear_boss。

        Returns:
            bool: 是否成功清除 Boss。
        """
        grids = self.map.select(is_boss=True, is_accessible=True)
        grids = grids.add(self.map.select(may_boss=True, is_caught_by_siren=True))
        logger.info('[地图-Boss] 是否Boss: %s' % grids)
        if not grids.count:
            grids = grids.add(self.map.select(may_boss=True, is_enemy=True, is_accessible=True))
            logger.warning('[地图-Boss] 未检测到Boss，使用可能的Boss格子')
            logger.info('[地图-Boss] 可能的Boss: %s' % self.map.select(may_boss=True))
            logger.info('[地图-Boss] 可能的Boss且是敌舰: %s' % self.map.select(may_boss=True, is_enemy=True))

        if grids:
            self.submarine_move_near_boss(grids[0])
            logger.hr('清除Boss')
            grids = grids.sort('weight', 'cost')
            logger.info('[地图] 格子: %s' % str(grids))
            self.clear_chosen_enemy(grids[0], expected='boss')

        logger.warning('[地图-Boss] 未检测到Boss，尝试所有Boss出生点')
        return self.clear_potential_boss()

    def capture_clear_boss(self):
        """清除 Boss，若未检测到则撤退。

        Returns:
            bool: 是否成功清除 Boss。
        """

        grids = self.map.select(is_boss=True, is_accessible=True)
        grids = grids.add(self.map.select(may_boss=True, is_caught_by_siren=True))
        logger.info('[地图-Boss] 是否Boss: %s' % grids)
        if not grids.count:
            grids = grids.add(self.map.select(may_boss=True, is_enemy=True, is_accessible=True))
            logger.warning('[地图-Boss] 未检测到Boss，使用可能的Boss格子')
            logger.info('[地图-Boss] 可能的Boss: %s' % self.map.select(may_boss=True))
            logger.info('[地图-Boss] 可能的Boss且是敌舰: %s' % self.map.select(may_boss=True, is_enemy=True))

        if grids:
            logger.hr('清除Boss')
            grids = grids.sort('weight', 'cost')
            logger.info('[地图] 格子: %s' % str(grids))
            self.clear_chosen_enemy(grids[0])

        logger.warning('[地图-Boss] 检测到围捕作战，撤退中')
        self.withdraw()

    def clear_potential_boss(self):
        """当未直接检测到 Boss 时，尝试踩踏所有可能的 Boss 出生点。

        Returns:
            bool: 是否成功清除了潜在 Boss 或路障。
        """
        grids = self.map.select(may_boss=True, is_accessible=True).sort('weight', 'cost')
        logger.info('[地图-Boss] 可能的Boss: %s' % grids)
        battle_count = self.battle_count
        is_single_boss = self.map.select(may_boss=True).count == 1
        if is_single_boss:
            expected = 'boss'
        else:
            expected = ''

        for grid in grids:
            logger.hr('清除潜在Boss')
            grids = grids.sort('weight', 'cost')
            logger.info('[地图] 格子: %s' % str(grid))
            self.fleet_boss.clear_chosen_enemy(grid, expected=expected)
            if self.battle_count > battle_count:
                logger.info('[地图-Boss] Boss猜测正确')
                return True
            else:
                logger.info('[地图-Boss] Boss猜测错误')

        grids = self.map.select(may_boss=True, is_accessible=False).sort('weight', 'cost')
        logger.info('[地图-Boss] 可能的Boss: %s' % grids)

        for grid in grids:
            logger.hr('清除潜在Boss路障')
            roadblocks = self.brute_find_roadblocks(grid, fleet=self.fleet_boss_index)
            roadblocks = roadblocks.sort('weight', 'cost')
            logger.info('[地图] 格子: %s' % str(roadblocks))
            self.fleet_1.clear_chosen_enemy(roadblocks[0], expected=expected)
            return True

        return False

    def brute_clear_boss(self):
        """使用暴力搜索敌人路障的方式清除阻挡并击破 Boss。

        同时利用两支舰队进行协同寻路。

        Returns:
            bool: 是否成功清除路障或 Boss。
        """
        boss = self.map.select(is_boss=True)
        if boss:
            logger.info('[地图-Boss] 强制清除Boss')
            grids = self.brute_find_roadblocks(boss[0], fleet=self.fleet_boss_index)
            if grids:
                if self.brute_fleet_meet():
                    return True
                logger.info('[地图-Boss] 强制清除Boss路障')
                grids = grids.sort('weight', 'cost')
                logger.info('[地图] 格子: %s' % str(grids))
                self.clear_chosen_enemy(grids[0])
                return True
            else:
                return self.fleet_boss.clear_boss()
        elif self.map.select(may_boss=True, is_caught_by_siren=True):
            logger.info('[地图-Boss] Boss出现在舰队格子上')
            self.fleet_2.switch_to()
            return self.clear_chosen_enemy(self.map.select(may_boss=True, is_caught_by_siren=True)[0])
        else:
            logger.warning('[地图-Boss] 未检测到Boss，尝试所有Boss出生点')
            return self.clear_potential_boss()

    def brute_fleet_meet(self):
        """使用暴力搜索清除两支舰队之间的阻挡路障。

        Returns:
            bool: 是否清除了舰队之间的路障。
        """
        if self.fleet_boss_index != 2 or not self.fleet_2_location:
            return False
        grids = self.brute_find_roadblocks(self.map[self.fleet_2_location], fleet=1)
        if grids:
            logger.info('[地图-Boss] 强制清除舰队间路障')
            grids = grids.sort('weight', 'cost')
            logger.info('[地图] 格子: %s' % str(grids))
            self.clear_chosen_enemy(grids[0])
            return True
        else:
            return False

    def clear_siren(self, **kwargs):
        """清除地图上的塞壬或要塞。

        Args:
            **kwargs: 传给 select_grids 的筛选与排序参数。

        Returns:
            bool: 是否清除了敌人。
        """
        if not self.config.MAP_HAS_SIREN and not self.config.MAP_HAS_FORTRESS:
            return False

        if self.config.FLEET_2:
            kwargs['sort'] = ('weight', 'cost_2')
        grids = self.map.select(is_siren=True)
        if self.config.MAP_HAS_FORTRESS:
            grids = grids.add(self.map.select(is_fortress=True))
        grids = self.select_grids(grids, **kwargs)

        if grids:
            logger.hr('清除塞壬')
            self.show_select_grids(grids, **kwargs)
            if grids[0].is_fortress:
                expected = 'fortress'
            else:
                expected = 'siren'
            self.clear_chosen_enemy(grids[0], expected=expected)
            return True

        return False

    def clear_any_enemy(self, **kwargs):
        """清除地图上的任意敌舰（包含普通敌舰、塞壬与要塞）。

        Args:
            **kwargs: 传给 select_grids 的筛选与排序参数。

        Returns:
            bool: 是否清除了敌人。
        """
        grids = self.map.select(is_enemy=True, is_boss=False)

        if self.config.MAP_HAS_SIREN:
            grids = grids.add(self.map.select(is_siren=True))
        if self.config.MAP_HAS_FORTRESS:
            grids = grids.add(self.map.select(is_fortress=True))

        grids = self.select_grids(grids, **kwargs)

        if grids:
            logger.hr('清除敌舰')
            self.show_select_grids(grids, **kwargs)
            grid = grids[0]
            if grid.is_fortress:
                expected = 'fortress'
            elif grid.is_siren:
                expected = 'siren'
            else:
                expected = ''
            self.clear_chosen_enemy(grid, expected=expected)
            return True

        return False

    def fleet_2_step_on(self, grids, roadblocks):
        """使用第二舰队踩踏格子以减少另一支舰队的伏击频率。

        若道路被敌人阻挡，会自动调用第一舰队清除路障。

        Args:
            grids (SelectedGrids): 目标格子集合。
            roadblocks (list[RoadGrids]): 路障路线列表。

        Returns:
            bool: 是否清除了敌人。
        """
        if not self.config.FLEET_2:
            return False
        for grid in grids:
            if self.fleet_at(grid=grid, fleet=2):
                return False
        # if grids.count == len([grid for grid in grids if grid.is_enemy or grid.is_cleared]):
        #     logger.info('Fleet 2 step on, no need')
        #     return False
        all_cleared = grids.select(is_cleared=True).count == grids.count

        logger.info('[地图-舰队] 第二舰队踩点')
        for grid in grids:
            if grid.is_enemy or (not all_cleared and grid.is_cleared):
                continue
            if self.check_accessibility(grid=grid, fleet=2):
                logger.info('[地图-舰队] 第二舰队踩点 %s' % grid)
                self.fleet_2.goto(grid)
                self.fleet_1.switch_to()
                return False

        logger.info('[地图-舰队] 第二舰队踩点遇到路障')
        clear = self.fleet_1.clear_roadblocks(roadblocks)
        self.fleet_1.clear_all_mystery()
        return clear

    def fleet_2_break_siren_caught(self):
        """打破第二舰队被塞壬捕获的状态。

        Returns:
            bool: 是否进行了战斗解脱捕获。
        """
        if self.fleet_boss_index != 2:
            return False
        if not self.config.MAP_HAS_SIREN or not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False
        if not self.map.select(is_caught_by_siren=True):
            logger.info('[地图-舰队] 没有舰队被塞壬捕获')
            return False
        if not self.fleet_2_location or not self.map[self.fleet_2_location].is_caught_by_siren:
            logger.warning('[地图-舰队] 出现塞壬捕获，但不是第二舰队')
            for grid in self.map:
                grid.is_caught_by_siren = False
            return False

        logger.info(f'[地图-舰队] 打破塞壬捕获，第二舰队: {self.fleet_2_location}')
        self.fleet_2.switch_to()
        self.ensure_edge_insight()
        self.clear_chosen_enemy(self.map[self.fleet_2_location])
        self.fleet_1.switch_to()
        for grid in self.map:
            grid.is_caught_by_siren = False
        return True

    def fleet_2_push_forward(self):
        """将第二舰队移动到权重更低的格子。

        降低 Boss 舰队被敌人卡住的可能性，特别是第 7 到第 9 章的单行道地图。

        Returns:
            bool: 是否推进成功。
        """
        if self.fleet_boss_index != 2:
            return False

        logger.info('[地图-舰队] 第二舰队推进')
        grids = self.map.select(is_land=False).sort('weight', 'cost')
        if self.map[self.fleet_2_location].weight <= grids[0].weight:
            logger.info('[地图-舰队] 第二舰队已推送到目的地')
            self.fleet_1.switch_to()
            return False

        fleets = SelectedGrids([self.map[self.fleet_1_location], self.map[self.fleet_2_location]])
        grids = grids.select(is_accessible_2=True, is_sea=True).delete(fleets)
        if not grids:
            logger.info('[地图-舰队] 第二舰队无处可推')
            return False
        if self.map[self.fleet_2_location].weight <= grids[0].weight:
            logger.info('[地图-舰队] 第二舰队已推送到最近格子')
            return False

        logger.info(f'[地图] 格子: {grids}')
        logger.info(f'[地图-舰队] 推进: {grids[0]}')
        self.fleet_2.goto(grids[0])
        self.fleet_1.switch_to()
        return True

    def fleet_2_rescue(self, grid):
        """使用道中舰队救援被路障阻挡的 Boss 舰队。

        Args:
            grid (GridInfo): 目标格子，通常为 Boss 出生点。

        Returns:
            bool: 是否清除了敌人。
        """
        if self.fleet_boss_index != 2:
            return False

        grids = self.brute_find_roadblocks(grid, fleet=2)
        if not grids:
            return False
        logger.info('[地图-舰队] 第二舰队救援')
        grids = self.select_grids(grids)
        if not grids:
            return False

        self.clear_chosen_enemy(grids[0])
        return True

    def fleet_2_protect(self):
        """道中舰队在 Boss 舰队周围移动，清除逼近的塞壬。

        Returns:
            bool: 是否清除了敌人。
        """
        if not self.config.FLEET_2 or not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False

        # 双舰队模式下巡逻保护
        for n in range(20):
            if not self.map.select(is_siren=True):
                return False

            nearby = self.map.select(cost_2=1).add(self.map.select(cost_2=2))
            approaching = SelectedGrids([])
            if self.config.MAP_HAS_MOVABLE_ENEMY:
                approaching = approaching.add(nearby.select(is_siren=True))
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                approaching = approaching.add(nearby.select(is_enemy=True))
            if approaching:
                grids = self.select_grids(approaching, sort=('cost_2', 'cost_1'))
                self.clear_chosen_enemy(grids[0], expected='siren')
                return True
            else:
                grids = nearby.delete(self.map.select(is_fleet=True))
                grids = self.select_grids(grids, sort=('cost_2', 'cost_1'))
                self.goto(grids[0])
                continue

        logger.warning('[地图-舰队] 第二舰队保护：无塞壬接近')
        return False

    def clear_filter_enemy(self, string, preserve=0):
        """根据优先级过滤器表达式清除敌人。

        Args:
            string (str): 用于筛选敌人的过滤器表达式，从易到难排列。
            preserve (int, optional): 保留几个最简单的敌人用于无弹药战斗。默认为 0。

        Returns:
            bool: 是否清除了敌人。
        """
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            if self.clear_any_enemy(sort=('cost_2',)):
                return True
            return False

        if self.config.EnemyPriority_EnemyScaleBalanceWeight == 'S3_enemy_first':
            string = '3L > 3M > 3E > 3C > 2L > 2M > 2E > 2C > 1L > 1M > 1E > 1C'
            preserve = 0
        elif self.config.EnemyPriority_EnemyScaleBalanceWeight == 'S1_enemy_first':
            string = '1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C'

        ENEMY_FILTER.load(string)
        grids = self.map.select(is_enemy=True, is_accessible=True)
        if not grids:
            return False

        grids = ENEMY_FILTER.apply(grids.sort('weight', 'cost').grids)
        logger.info(f'[地图-战斗] 筛选敌舰: {grids}, 保留={preserve}')
        if preserve:
            grids = grids[preserve:]

        if grids:
            logger.hr('清除筛选敌舰')
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_bouncing_enemy(self):
        """清除在固定路线上往返弹跳的敌人。

        此方法在清除一个敌人后将被禁用，因为地图上通常只有一个弹跳敌人。

        Returns:
            bool: 是否清除了敌人。
        """
        if not self.config.MAP_HAS_BOUNCING_ENEMY:
            return False

        route = None
        for a_route in self.map.bouncing_enemy_data:
            if a_route.select(may_bouncing_enemy=True, is_accessible=True):
                route = a_route
                break
        if route is None:
            return False

        logger.hr('清除弹跳敌舰')
        logger.info(f'[地图-战斗] 清除弹跳敌舰: {route}')
        self.show_fleet()
        prev = self.battle_count
        for n, grid in enumerate(itertools.cycle(route)):
            if self.emotion.is_calculate and self.config.Campaign_UseFleetLock:
                self.emotion.wait(fleet_index=self.fleet_current_index)
            self.goto(grid, expected='combat_nothing')

            if self.battle_count > prev:
                logger.info('[地图-战斗] 已清除一个弹跳敌舰')
                route.select(may_bouncing_enemy=True).set(may_bouncing_enemy=False)
                self.full_scan()
                self.find_path_initial()
                self.map.show_cost()
                return True
            if n >= 12:
                logger.warning('[地图-战斗] 尝试12次后仍无法清除弹跳敌舰')
                return False

        return False
