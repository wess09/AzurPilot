"""验证幽影迷城 D3 的分批刷新、目标选择和三战撤退。"""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from campaign.event_20260908_cn.d3 import MAP
from campaign.event_20260908_cn.d3_3 import Campaign, Config
from module.campaign.run import CampaignRun
from module.exception import CampaignEnd, MapEnemyMoved
from module.map.utils import location_ensure


class TestD3SirenRetreat(unittest.TestCase):
    def setUp(self):
        """复用真实地图和选敌逻辑，仅替换设备交互。"""
        self.campaign = object.__new__(Campaign)
        self.campaign.config = Config()
        self.campaign.config.FLEET_2 = False
        self.campaign.config.MAP_HAS_FORTRESS = False
        self.campaign.config.Error_HandleError = True
        self.campaign.map = copy.deepcopy(MAP)
        self.campaign.map.reset()
        self.campaign.map.load_map_data()
        self.campaign.map.load_spawn_data()
        self.campaign.map.grid_connection_initial()
        self.campaign.battle_count = 0
        self.campaign.siren_count = 0
        self.location = self.grid('D5').location
        self.targets = []
        self.campaign.withdraw = Mock(side_effect=CampaignEnd)
        self.campaign.full_scan = Mock()
        self.campaign.find_path_initial = Mock(side_effect=self.update_paths)
        self.campaign.clear_chosen_enemy = Mock(side_effect=self.finish_combat)
        self.campaign.battle_default = Mock(side_effect=AssertionError('不应攻击普通敌人'))

    def grid(self, node):
        return self.campaign.map[location_ensure(node)]

    def update_paths(self):
        """刷新后使用真实寻路计算可达性。"""
        self.campaign.map.find_path_initial(self.location, has_ambush=False)

    def spawn_siren(self, node):
        self.grid(node).is_siren = True
        self.update_paths()

    def finish_combat(self, grid, expected):
        """模拟一次已识别目标的战斗结算，不自动创造后续塞壬。"""
        self.assertTrue(grid.is_siren)
        self.assertEqual(expected, 'siren')
        self.targets.append(grid.location)
        self.location = grid.location
        grid.wipe_out()
        self.campaign.battle_count += 1
        self.campaign.siren_count += 1
        self.update_paths()
        return True

    def test_delayed_spawn_can_reuse_a_cleared_grid(self):
        self.spawn_siren('D2')
        self.spawn_siren('F2')
        self.grid('E7').is_enemy = True
        self.update_paths()
        self.assertTrue(self.campaign.execute_a_battle())
        self.assertTrue(self.campaign.execute_a_battle())
        self.campaign.withdraw.assert_not_called()

        # 第三只尚未被扫描到；验证刷新统计仍要求补齐它。
        _, missing = self.campaign.map.missing_get(battle_count=2, siren_count=2)
        self.assertEqual(missing['siren'], 1)
        first_target = self.targets[0]
        self.campaign.full_scan.side_effect = lambda **kwargs: self.spawn_siren(first_target)
        with self.assertRaises(CampaignEnd):
            self.campaign.execute_a_battle()

        self.assertEqual(self.targets, [first_target, self.targets[1], first_target])
        self.assertEqual(self.campaign.siren_count, 3)
        self.campaign.full_scan.assert_called_once_with(must_scan=self.campaign.map.camera_data)
        self.assertTrue(self.grid('E7').is_enemy)

    def test_moved_siren_uses_current_position(self):
        # 移动后的塞壬可能离开 MS 刷新格。
        self.spawn_siren('E4')
        self.assertTrue(self.campaign.execute_a_battle())
        self.assertEqual(self.targets, [self.grid('E4').location])

    def test_missing_or_blocked_siren_withdraws_without_normal_combat(self):
        for blocked in (False, True):
            with self.subTest(blocked=blocked):
                self.setUp()
                self.grid('E7').is_enemy = True
                if blocked:
                    self.spawn_siren('E3')
                    for node in ('D3', 'F3', 'E2', 'E4'):
                        self.grid(node).is_enemy = True
                self.update_paths()
                with self.assertRaises(CampaignEnd):
                    self.campaign.execute_a_battle()
                self.assertEqual(self.targets, [])
                self.campaign.full_scan.assert_called_once()

    def test_stale_target_without_combat_does_not_count_as_a_battle(self):
        self.spawn_siren('E3')
        self.campaign.clear_chosen_enemy.side_effect = None
        self.campaign.clear_chosen_enemy.return_value = True
        with self.assertRaises(CampaignEnd):
            self.campaign.execute_a_battle()
        self.assertEqual(self.campaign.battle_count, 0)
        self.campaign.full_scan.assert_called_once()

    def test_movement_exception_after_third_battle_cannot_start_fourth(self):
        self.campaign.battle_count = self.campaign.siren_count = 2
        self.spawn_siren('E3')

        def finish_with_movement(grid, expected):
            self.finish_combat(grid, expected)
            raise MapEnemyMoved

        self.campaign.clear_chosen_enemy.side_effect = finish_with_movement
        self.assertTrue(self.campaign.execute_a_battle())
        with self.assertRaises(CampaignEnd):
            self.campaign.execute_a_battle()
        self.assertEqual(self.campaign.battle_count, 3)
        self.campaign.clear_chosen_enemy.assert_called_once()

    def test_clear_all_and_poor_map_modes_still_use_siren_strategy(self):
        self.campaign.config.MAP_CLEAR_ALL_THIS_TIME = True
        self.campaign.config.POOR_MAP_DATA = True
        self.spawn_siren('E3')
        self.assertTrue(self.campaign.execute_a_battle())
        self.assertEqual(self.campaign.siren_count, 1)

    def test_unexpected_normal_combat_stops_the_run(self):
        self.campaign.battle_count = 1
        with self.assertRaises(CampaignEnd):
            self.campaign.execute_a_battle()
        self.campaign.clear_chosen_enemy.assert_not_called()

    def test_all_three_battles_preserve_enemy_searching_settlement(self):
        for battle_count in range(3):
            with self.subTest(battle_count=battle_count):
                self.campaign.battle_count = battle_count
                self.assertEqual(self.campaign._expected_end('combat_siren'), 'with_searching')
        self.assertEqual(self.campaign._map_battle, 3)
        self.assertFalse(self.campaign.config.Campaign_UseAutoSearch)

    def test_stage_alias_preserves_standard_d3(self):
        runner = object.__new__(CampaignRun)
        runner.config = SimpleNamespace(task=SimpleNamespace(command='Event'), STAGE_LOOP_ALIAS={})
        for folder in ('event_20260908_cn', 'event_20251218_cn'):
            for name, expected in (('D3-3', 'd3_3'), ('d3_3', 'd3_3'), ('d3', 'd3')):
                with self.subTest(folder=folder, name=name):
                    self.assertEqual(runner.handle_stage_name(name, folder), (expected, folder))

    def test_stage_is_main(self):
        self.assertTrue(CampaignRun.stage_is_main('7-2'))
        self.assertTrue(CampaignRun.stage_is_main('12-4'))
        self.assertTrue(CampaignRun.stage_is_main('campaign_7_2'))
        self.assertTrue(CampaignRun.stage_is_main('campaign_12_4'))

        self.assertFalse(CampaignRun.stage_is_main('D3'))
        self.assertFalse(CampaignRun.stage_is_main('d3'))
        self.assertFalse(CampaignRun.stage_is_main('D3-3'))
        self.assertFalse(CampaignRun.stage_is_main('d3-3'))
        self.assertFalse(CampaignRun.stage_is_main('d3_3'))
        self.assertFalse(CampaignRun.stage_is_main('sp'))
        self.assertFalse(CampaignRun.stage_is_main('sp1'))

    def test_gems_farming_and_three_oil_d3_alias(self):
        for command in ('GemsFarming', 'ThreeOilLowCost'):
            runner = object.__new__(CampaignRun)
            runner.config = SimpleNamespace(
                task=SimpleNamespace(command=command),
                Campaign_Event='campaign_main',
                STAGE_LOOP_ALIAS={},
                cross_get=lambda k: 'event_20260908_cn' if 'Campaign.Event' in k else None,
            )
            for name in ('D3-3', 'd3-3', 'd3_3'):
                with self.subTest(command=command, name=name):
                    self.assertEqual(
                        runner.handle_stage_name(name, folder='campaign_main'),
                        ('d3_3', 'event_20260908_cn'),
                    )

            self.assertEqual(
                runner.handle_stage_name('D3', folder='campaign_main'),
                ('d3', 'event_20260908_cn'),
            )
            self.assertEqual(
                runner.handle_stage_name('7-2', folder='campaign_main'),
                ('campaign_7_2', 'campaign_main'),
            )


if __name__ == '__main__':
    unittest.main()
