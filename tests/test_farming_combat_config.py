"""验证低耗任务的配置更新、战役加载及潜艇与索敌接入。"""

import copy
import itertools
import unittest
from unittest.mock import Mock

from module.campaign.gems_farming import GemsFarming
from module.config.config import AzurLaneConfig, name_to_function
from module.config.utils import read_file


TASKS = ('GemsFarming', 'ThreeOilLowCost')
PRIORITIES = ('default_mode', 'S1_enemy_first', 'S3_enemy_first')


def make_config(task, **groups):
    """使用真实更新和绑定流程，全程在内存中操作配置。"""
    config = AzurLaneConfig('template')
    config.auto_update = False
    config.data = config.config_update({task: groups})
    config.bind(task)
    config.task = name_to_function(task)
    return config


class TestFarmingCombatConfig(unittest.TestCase):
    def test_submarine_options_are_editable_and_survive_reload(self):
        """覆盖所有解锁选项，防止界面可选但加载后被隐藏覆盖值重置。"""
        args = read_file('module/config/argument/args.json')
        reference = args['Main']['Submarine']
        for task in TASKS:
            for name, definition in reference.items():
                with self.subTest(task=task, name=name):
                    actual = args[task]['Submarine'][name]
                    self.assertNotIn(actual.get('display'), ('hide', 'disabled'))
                    self.assertEqual(actual.get('option'), definition.get('option'))
            combinations = itertools.product(
                reference['Mode']['option'], reference['AutoSearchMode']['option'],
                reference['DistanceToBoss']['option'],
            )
            for mode, auto, distance in combinations:
                with self.subTest(task=task, mode=mode, auto=auto, distance=distance):
                    values = dict(Fleet=2, Mode=mode, AutoSearchMode=auto, DistanceToBoss=distance)
                    config = make_config(task, Submarine=values)
                    config.data = config.config_update(config.data)
                    config.bind(task)
                    for name, value in values.items():
                        self.assertEqual(getattr(config, f'Submarine_{name}'), value)

    def test_old_config_gets_priority_without_changing_submarine_defaults(self):
        """旧配置补齐索敌选项，并保留原有潜艇行为和任务边界。"""
        for task in TASKS:
            config = make_config(task, Submarine={'Fleet': 1, 'Mode': 'hunt_only'})
            self.assertEqual(config.EnemyPriority_EnemyScaleBalanceWeight, 'default_mode')
            self.assertEqual(config.bound['EnemyPriority_EnemyScaleBalanceWeight'],
                             f'{task}.EnemyPriority.EnemyScaleBalanceWeight')
            self.assertEqual(config.Submarine_Mode, 'hunt_only')
            self.assertEqual(config.Submarine_AutoSearchMode, 'sub_standby')
            self.assertEqual(config.Submarine_DistanceToBoss, 'use_open_ocean_support')
        config = make_config('Ambush11', Submarine={'AutoSearchMode': 'sub_auto_call'})
        self.assertEqual(config.Submarine_AutoSearchMode, 'sub_standby')

    def load_campaign(self, task, priority='default_mode', vanguard='disabled', **submarine):
        config = make_config(
            task, EnemyPriority={'EnemyScaleBalanceWeight': priority},
            GemsFarming={'ChangeVanguard': vanguard}, Submarine=submarine,
        )
        runner = GemsFarming(config=config, device=Mock())
        runner.load_campaign('campaign_2_1')
        return runner.campaign

    def test_priority_reaches_target_selection_with_or_without_ship_changes(self):
        """经任务加载后使用真实地图选敌，避免只验证配置字段。"""
        for task, priority, vanguard in itertools.product(TASKS, PRIORITIES, ('disabled', 'ship_equip')):
            with self.subTest(task=task, priority=priority, vanguard=vanguard):
                campaign = self.load_campaign(task, priority, vanguard)
                self.assertEqual(campaign.config.EnemyPriority_EnemyScaleBalanceWeight, priority)
                campaign.map = copy.deepcopy(campaign.MAP)
                campaign.map.reset()
                campaign.config.override(MAP_CLEAR_ALL_THIS_TIME=False, MAP_HAS_MOVABLE_NORMAL_ENEMY=False)
                for scale in (1, 2, 3):
                    grid = campaign.map[(scale - 1, 0)]
                    grid.is_enemy = True
                    grid.cost = 1
                    grid.enemy_scale = scale
                    grid.enemy_genre = 'Light'
                    grid.weight = 0 if scale == 2 else 10
                campaign.clear_chosen_enemy = Mock()
                expected = {'default_mode': 2, 'S1_enemy_first': 1, 'S3_enemy_first': 3}[priority]
                self.assertTrue(campaign.clear_enemy())
                self.assertEqual(campaign.clear_chosen_enemy.call_args.args[0].enemy_scale, expected)
                self.assertTrue(campaign.clear_filter_enemy('2L > 1L > 3L', preserve=0))
                self.assertEqual(campaign.clear_chosen_enemy.call_args.args[0].enemy_scale, expected)

    def test_submarine_modes_reach_campaign_handlers(self):
        """验证 Boss 召唤、高级规则及自律方案使用任务中的实际配置。"""
        for task in TASKS:
            for mode in ('boss_only', 'hunt_and_boss'):
                campaign = self.load_campaign(task, Fleet=1, Mode=mode)
                self.assertEqual(campaign._submarine_mode('combat'), 'do_not_use')
                self.assertEqual(campaign._submarine_mode('combat_boss'), 'every_combat')
            campaign = self.load_campaign(task, Fleet=1, Mode='advanced', AutoSearchMode='sub_auto_call')
            campaign.map_is_auto_search = False
            campaign.submarine_advanced_reset()
            self.assertIsNotNone(campaign.submarine_advanced)
            campaign.map_is_auto_search = True
            campaign.submarine_advanced_reset()
            self.assertIsNone(campaign.submarine_advanced)
            campaign.fleet_preparation_sidebar_ensure = Mock()
            campaign.auto_search_setting_ensure = Mock(return_value=True)
            self.assertTrue(campaign.handle_auto_search_setting())
            campaign.auto_search_setting_ensure.assert_any_call('sub_auto_call')


if __name__ == '__main__':
    unittest.main()
