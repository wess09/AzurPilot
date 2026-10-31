"""紧急委托/三油低耗：前排固定不换时按心情等待，不再强制红脸出击。"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from module.campaign.ambush_1_1 import Ambush11
from module.campaign.gems_farming import GemsFarming
from module.config.utils import read_file
from module.exception import CampaignEnd, ScriptEnd
from tests.test_farming_combat_config import make_config

NOW = datetime(2026, 10, 24, 12)
FUTURE = NOW + timedelta(hours=1)
TASKS = ('GemsFarming', 'ThreeOilLowCost', 'Ambush11')
LOW_COST_TASKS = ('GemsFarming', 'ThreeOilLowCost')
# 低耗任务用专属的前排心情组，伏击任务仍用公共 Emotion 组。
MODE_KEYS = {'GemsFarming': 'VanguardEmotion_Mode',
             'ThreeOilLowCost': 'VanguardEmotion_Mode',
             'Ambush11': 'Emotion_Mode'}


def make_runner(task, change_vanguard='ship_equip', **groups):
    """按真实配置流程加载战役，返回任务运行器。"""
    gems = dict(groups.pop('GemsFarming', {}))
    gems['ChangeVanguard'] = change_vanguard
    config = make_config(task, GemsFarming=gems, **groups)
    runner = (Ambush11 if task == 'Ambush11' else GemsFarming)(config=config, device=Mock())
    runner.load_campaign('campaign_1_1_f' if task == 'Ambush11' else 'campaign_2_1')
    return runner


def stub_popup(campaign, cancel=True):
    campaign.handle_use_data_key = Mock(return_value=False)
    campaign.handle_popup_confirm = Mock(return_value=True)
    campaign.handle_popup_cancel = Mock(return_value=cancel)
    campaign._emotion_emergency_exit = Mock()
    campaign.emotion.emergency_reset = Mock()
    campaign.emotion._check_reduce = Mock(return_value=(FUTURE, True))
    campaign.config.task_delay = Mock()


class FarmingEmotionWaitTests(unittest.TestCase):
    def test_emotion_mode_matrix(self):
        """三种前排选项各自对应忽略、计算等待、计算换船。"""
        cases = {'disabled': 'ignore', 'disabled_wait': 'calculate',
                 'ship': 'ignore_calculate', 'ship_equip': 'ignore_calculate'}
        for task in TASKS:
            for option, expected in cases.items():
                with self.subTest(task=task, option=option):
                    runner = make_runner(task, option)
                    self.assertEqual(expected, getattr(runner.campaign.config, MODE_KEYS[task]))

    def test_low_cost_ledger_uses_dedicated_group(self):
        """低耗任务的心情账本读写专属组，伏击任务仍用公共 Emotion 组。"""
        for task in LOW_COST_TASKS:
            with self.subTest(task=task):
                runner = make_runner(task, 'disabled_wait')
                self.assertEqual('VanguardEmotion_', runner.campaign.emotion.fleet_prefix)
                self.assertEqual('VanguardEmotion_Value', runner.campaign.emotion.fleet_1.value_name)
                self.assertEqual('VanguardEmotion_MinReserve', runner.campaign.emotion.min_reserve_key)
        runner = make_runner('Ambush11', 'disabled_wait')
        self.assertEqual('Emotion_Fleet1', runner.campaign.emotion.fleet_1._key_prefix)

    def test_wait_mode_delays_task_instead_of_swapping(self):
        """前排不换且心情不足时推迟任务，不进入换船编排。"""
        for task in TASKS:
            with self.subTest(task=task):
                campaign = make_runner(task, 'disabled_wait').campaign
                emotion = campaign.emotion
                emotion._check_reduce = Mock(return_value=(FUTURE, True))
                campaign.config.task_delay = Mock()
                with self.assertRaises(ScriptEnd):
                    emotion.check_reduce(5)
                campaign.config.task_delay.assert_called_once_with(target=FUTURE)
                self.assertFalse(campaign.config.GEMS_EMOTION_TRIGGERED)

    def test_wait_mode_restart_check_delays_task(self):
        """异常重启续接时心情不足同样推迟，而不是撤退换船。"""
        campaign = make_runner('GemsFarming', 'disabled_wait').campaign
        emotion = campaign.emotion
        emotion._check_fleet = Mock(return_value=FUTURE)
        campaign.config.task_delay = Mock()
        # 等待分支已委托给基类，比较发生在 module.combat.emotion 里。
        with patch('module.combat.emotion.current_time', return_value=NOW), \
                self.assertRaises(ScriptEnd):
            emotion.check_fleet(1, after_restart=True)
        campaign.config.task_delay.assert_called_once_with(target=FUTURE)
        self.assertFalse(campaign.config.GEMS_EMOTION_TRIGGERED)

    def test_migration_moves_old_emotion_settings(self):
        """旧的一队心情记录与组级开关整体迁到专属组。"""
        import json

        from module.config.config import AzurLaneConfig

        config = AzurLaneConfig('template')
        config.auto_update = False
        old = {
            'ThreeOilLowCost': {'Emotion': {
                'Fleet1Value': 42, 'Fleet1Control': 'prevent_yellow_face',
                'Fleet1Recover': 'dormitory_floor_1', 'MinReserve': 30, 'IgnoreShipwreck': True,
            }},
            'GemsFarming': {'Emotion': {'Fleet1Value': 7}},
        }
        merged = config.config_update(json.loads(json.dumps(old)))
        for task, value in (('ThreeOilLowCost', 42), ('GemsFarming', 7)):
            with self.subTest(task=task):
                self.assertEqual(value, merged[task]['VanguardEmotion']['Value'])
        group = merged['ThreeOilLowCost']['VanguardEmotion']
        self.assertEqual('prevent_yellow_face', group['Control'])
        self.assertEqual('dormitory_floor_1', group['Recover'])
        self.assertEqual(30, group['MinReserve'])
        self.assertTrue(group['IgnoreShipwreck'])

    def test_wait_mode_cancels_red_face_popup(self):
        """红脸弹窗被取消，随后撤退、清零并按恢复时间延迟，绝不确认出击。"""
        for task in TASKS:
            with self.subTest(task=task):
                campaign = make_runner(task, 'disabled_wait').campaign
                stub_popup(campaign, cancel=True)
                campaign._map_battle = 5
                with self.assertRaises(ScriptEnd):
                    campaign.handle_combat_low_emotion()
                campaign.handle_popup_cancel.assert_called_once_with('IGNORE_LOW_EMOTION')
                campaign.handle_popup_confirm.assert_not_called()
                campaign._emotion_emergency_exit.assert_called_once_with()
                campaign.emotion.emergency_reset.assert_called_once_with()
                campaign.config.task_delay.assert_called_once_with(target=FUTURE)

    def test_wait_mode_ignores_emotion_warning_switch(self):
        """同时打开「忽略心情警告弹窗」时仍按等待处理。"""
        campaign = make_runner(
            'ThreeOilLowCost', 'disabled_wait',
            GemsFarming={'IgnoreEmotionWarning': True},
        ).campaign
        stub_popup(campaign, cancel=True)
        with self.assertRaises(ScriptEnd), patch('module.campaign.gems_farming.logger') as logger:
            campaign.handle_combat_low_emotion()
        campaign.handle_popup_confirm.assert_not_called()
        logger.warning.assert_called_once()

    def test_vanguard_disabled_still_forces_red_face_sortie(self):
        """旧行为保持不变：选择「不更换（强制红脸出击）」时确认弹窗继续打。"""
        for task in TASKS:
            with self.subTest(task=task):
                campaign = make_runner(task, 'disabled').campaign
                campaign.handle_use_data_key = Mock(return_value=False)
                campaign.handle_popup_confirm = Mock(return_value=True)
                campaign.handle_popup_cancel = Mock(return_value=False)
                self.assertTrue(campaign.handle_combat_low_emotion())
                campaign.handle_popup_confirm.assert_called_once_with('IGNORE_LOW_EMOTION')
                campaign.handle_popup_cancel.assert_not_called()

    def test_ship_change_mode_keeps_swap_policy(self):
        """更换前排时仍然结束本图并交给换船编排。"""
        campaign = make_runner('GemsFarming', 'ship_equip').campaign
        emotion = campaign.emotion
        emotion._check_reduce = Mock(return_value=(FUTURE, True))
        campaign.config.task_delay = Mock()
        with self.assertRaises(CampaignEnd) as context:
            emotion.check_reduce(5)
        self.assertEqual('Emotion control', context.exception.args[0])
        self.assertTrue(campaign.config.GEMS_EMOTION_TRIGGERED)
        campaign.config.task_delay.assert_not_called()

    def test_generated_config_exposes_wait_option_and_vanguard_settings(self):
        """低耗任务用专属前排心情组，不再引用公共 Emotion 组。"""
        args = read_file('module/config/argument/args.json')
        for task in TASKS:
            option = args[task]['GemsFarming']['ChangeVanguard']
            self.assertIn('disabled_wait', option['option'])
            self.assertIn('disabled', option['option'])
        for task in LOW_COST_TASKS:
            self.assertNotIn('Emotion', args[task])
            group = args[task]['VanguardEmotion']
            for field in ('Control', 'Recover', 'Oath', 'Onsen', 'MinReserve',
                          'IgnoreShipwreck', 'Value', 'Record'):
                self.assertNotEqual('hide', group[field].get('display'))
            self.assertEqual('hide', group['Mode']['display'])

    def test_generated_i18n_has_wait_option_and_help(self):
        """四种语言的选项与专属组文案已补齐，没有残留占位键。"""
        for language in ('zh-CN', 'en-US', 'ja-JP', 'zh-TW'):
            data = read_file(f'module/config/i18n/{language}.json')
            field = data['GemsFarming']['ChangeVanguard']
            label = field['disabled_wait']
            self.assertTrue(label)
            self.assertNotEqual('disabled_wait', label)
            self.assertNotIn('GemsFarming.ChangeVanguard', label)
            self.assertNotIn('GemsFarming.ChangeVanguard', field['help'])
            group = data['VanguardEmotion']
            self.assertNotIn('VanguardEmotion', group['_info']['name'])
            self.assertNotIn('VanguardEmotion', group['Control']['name'])
            self.assertTrue(group['Control']['help'])


if __name__ == '__main__':
    unittest.main()
