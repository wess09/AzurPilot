"""累计正常心情消耗不应中断战役或请求重启，设备与配置仅使用内存夹具。"""

import unittest
from itertools import product
from types import SimpleNamespace
from unittest.mock import Mock, patch

import module.campaign.run as campaign_source
import module.combat.emotion as production
from dev_tools.emotion_simulate import Clock, LuaOracle, MemoryConfig, QuietLogger, ShipSpec
from module.campaign.run import CampaignRun


class CampaignEmotionRestartTests(unittest.TestCase):
    def test_continuous_campaign_keeps_accounting_without_requesting_restart(self):
        cases = product(('calculate', 'ignore', 'calculate_ignore'), (False, True),
                        (False, True), (False, True), (False, True))
        for mode, public, double_book, shipwreck, ignore_shipwreck in cases:
            with self.subTest(mode=mode, public=public, double_book=double_book,
                              shipwreck=shipwreck, ignore_shipwreck=ignore_shipwreck):
                cost = 4 if double_book else 2
                spec = ShipSpec('dormitory_floor_2', True)
                clock = Clock(500_000, LuaOracle(spec, 150, 500_000, 0))
                ledger = MemoryConfig(clock, spec, 150, cost, 'prevent_red_face', public)
                ledger.Emotion_Mode = mode
                ledger.Emotion_IgnoreShipwreck = ignore_shipwreck
                emotion = production.Emotion(ledger)
                emotion.map_is_2x_book = double_book
                config = SimpleNamespace(
                    StopCondition_RunCount=0, StopCondition_MapAchievement='non_stop',
                    modified={}, override=Mock(), task_call=Mock(),
                    task_switched=Mock(return_value=False))
                runner = object.__new__(CampaignRun)
                runner.__dict__['config'] = config
                runner.__dict__['device'] = Mock(has_cached_image=True)
                runner.stage = '2-4'
                runner.handle_stage_name = Mock(return_value=('2-4', 'campaign_main'))
                runner.load_campaign = Mock()
                runner.ui_page_appear = Mock(return_value=False)
                runner.disable_raid_on_event = Mock()
                runner.handle_commission_notice = Mock()
                runner.triggered_stop_condition = Mock(return_value=False)
                campaign = Mock()
                campaign.config = SimpleNamespace(Campaign_Mode='normal', modified={}, MAP_IS_ONE_TIME_STAGE=False)
                campaign.emotion = emotion
                campaign.map_is_auto_search = True
                campaign.get_event_pt_limit.return_value = 0
                campaign.event_time_limit_triggered.return_value = False
                campaign.is_in_map.return_value = False
                campaign.is_in_auto_search_menu.return_value = True
                runner.campaign = campaign

                def battle():
                    emotion.check_reduce(1)
                    emotion.reduce(1)
                    if shipwreck:
                        emotion.reduce(1, shipwreck=True)

                campaign.run.side_effect = battle
                per_battle = cost + (10 if shipwreck and not ignore_shipwreck else 0)
                # 超过旧阈值的最大值，同时确保每场真实账本仍有足够心情。
                runs = 105 // per_battle + 1
                with patch.object(production, 'current_time', clock.now), \
                        patch.object(production, 'logger', QuietLogger()), \
                        patch.object(campaign_source, 'logger', QuietLogger()):
                    runner._run('2-4', total=runs)
                    emotion.update()
                expected = 150 if mode == 'ignore' else 150 - runs * per_battle
                fleet = emotion.public_fleet if public else emotion.fleet_1
                self.assertEqual((expected, expected), (fleet.lower, fleet.upper))
                self.assertEqual(expected, fleet.value)
                self.assertEqual(runs, campaign.run.call_count)
                self.assertEqual(runs, runner.run_count)
                config.task_call.assert_not_called()
                campaign.ensure_auto_search_exit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
