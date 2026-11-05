"""验证低耗任务的配置更新、战役加载及潜艇与索敌接入。"""

import copy
import itertools
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from module.campaign.ambush_1_1 import Ambush11, AmbushEmotion
from module.campaign.gems_farming import GemsFarming
from module.combat.emotion_state import EmotionRecoveryState
from module.config.config import AzurLaneConfig, name_to_function
from module.config.utils import read_file
from module.exception import CampaignEnd


TASKS = ('GemsFarming', 'ThreeOilLowCost')
EMOTION_TASKS = (*TASKS, 'Ambush11')
PRIORITIES = ('default_mode', 'S1_enemy_first', 'S3_enemy_first')


def make_config(task, **groups):
    """使用真实更新和绑定流程，全程在内存中操作配置。"""
    config = AzurLaneConfig('template')
    config.auto_update = False
    config.data = config.config_update({task: groups})
    config.bind(task)
    config.task = name_to_function(task)
    # These map tests pin archived fixtures rather than following the current event.
    campaign = groups.get('Campaign', {})
    if 'Event' in campaign:
        config.override(Campaign_Event=campaign['Event'])
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
            # 8c36c56e4 起低耗任务在 default.yaml 里带了专属索敌默认值，
            # 补齐旧配置时用的是它，而不是全局默认的 default_mode。
            self.assertEqual(config.EnemyPriority_EnemyScaleBalanceWeight, 'S1_enemy_first')
            self.assertEqual(config.bound['EnemyPriority_EnemyScaleBalanceWeight'],
                             f'{task}.EnemyPriority.EnemyScaleBalanceWeight')
            self.assertEqual(config.Submarine_Mode, 'hunt_only')
            self.assertEqual(config.Submarine_AutoSearchMode, 'sub_standby')
            # 全局默认就是 2_grid_to_boss（与上游一致），不是 use_open_ocean_support。
            self.assertEqual(config.Submarine_DistanceToBoss, '2_grid_to_boss')
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


class TestFarmingEmotionConfig(unittest.TestCase):
    def test_recovery_options_are_visible_and_defaults_are_preserved(self):
        args = read_file('module/config/argument/args.json')
        for task in EMOTION_TASKS:
            config = make_config(task)
            for fleet in (1, 2):
                for suffix, default in (('Recover', 'not_in_dormitory'), ('Oath', False)):
                    field = f'Fleet{fleet}{suffix}'
                    with self.subTest(task=task, field=field):
                        self.assertNotIn(args[task]['Emotion'][field].get('display'), ('hide', 'disabled'))
                        self.assertEqual(args[task]['Emotion'][field], args['Main']['Emotion'][field])
                        self.assertEqual(getattr(config, f'Emotion_{field}'), default)

    def test_recovery_options_survive_api_save_and_runtime_reload(self):
        """从界面保存到实际任务绑定，验证两队全部后宅与誓约组合。"""
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from tests.test_api import fixture

        recoveries = ('not_in_dormitory', 'dormitory_floor_1', 'dormitory_floor_2')
        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            for task, index, oath in itertools.product(EMOTION_TASKS, range(3), (False, True)):
                values = dict(Fleet1Recover=recoveries[index], Fleet1Oath=oath,
                              Fleet2Recover=recoveries[(index + 1) % 3], Fleet2Oath=not oath)
                with self.subTest(task=task, values=values):
                    service.patch('testpilot', None, [
                        ConfigChange(path=f'{task}.Emotion.{field}', value=value)
                        for field, value in values.items()
                    ])
                    saved = service.read_json(service.path('testpilot'))
                    config = make_config(task, Emotion=saved[task]['Emotion'])
                    config.data = config.config_update(config.data)
                    config.bind(task)
                    for field, value in values.items():
                        self.assertEqual(saved[task]['Emotion'][field], value)
                        self.assertEqual(getattr(config, f'Emotion_{field}'), value)

    def test_loaded_campaign_uses_recovery_settings_and_keeps_ship_change_policy(self):
        """后宅/誓约进入原心情模型，保持原有不换前排时忽略、换前排时低心情换船。"""
        start = datetime(2026, 11, 6)
        orders = ('fleet1_all_fleet2_standby', 'fleet1_standby_fleet2_all')
        for task, order, change in itertools.product(EMOTION_TASKS, orders, ('disabled', 'ship', 'ship_equip')):
            with self.subTest(task=task, order=order, change=change):
                values = {}
                for fleet, recover, oath in ((1, 'dormitory_floor_1', False), (2, 'dormitory_floor_2', True)):
                    state = EmotionRecoveryState.calibrate(40, start, recover, oath, False)
                    values.update({f'Fleet{fleet}Recover': recover, f'Fleet{fleet}Oath': oath,
                                   f'Fleet{fleet}Value': 40, f'Fleet{fleet}Record': start,
                                   f'Fleet{fleet}RecoveryState': state.export()})
                config = make_config(task, Emotion=values, Fleet={'FleetOrder': order},
                                     GemsFarming={'ChangeVanguard': change})
                runner_type = Ambush11 if task == 'Ambush11' else GemsFarming
                runner = runner_type(config=config, device=Mock())
                runner.load_campaign('campaign_1_1_f' if task == 'Ambush11' else 'campaign_2_1')
                emotion = runner.campaign.emotion
                if task == 'Ambush11':
                    self.assertIsInstance(emotion, AmbushEmotion)
                self.assertEqual(emotion.is_calculate, change != 'disabled')
                self.assertTrue(emotion.is_ignore)
                with patch('module.combat.emotion.current_time', return_value=start + timedelta(minutes=6)):
                    emotion.update()
                self.assertEqual((44, 44), (emotion.fleet_1.lower, emotion.fleet_1.upper))
                self.assertEqual((46, 46), (emotion.fleet_2.lower, emotion.fleet_2.upper))
                self.assertEqual(runner.fleet_to_attack, 2 if 'fleet2_all' in order else 1)
                emotion._check_reduce = Mock(return_value=(start, 1))
                if change == 'disabled':
                    emotion.check_reduce(1)
                    emotion._check_reduce.assert_not_called()
                else:
                    with self.assertRaises(CampaignEnd):
                        emotion.check_reduce(1)
                    self.assertTrue(runner.campaign.config.GEMS_EMOTION_TRIGGERED)


if __name__ == '__main__':
    unittest.main()
