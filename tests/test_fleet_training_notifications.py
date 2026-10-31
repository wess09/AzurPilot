"""验证真实配置路径、三阶段内容和失败推送；渠道全部替换，不发送外部消息。"""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.api.protocol import ConfigChange
from module.campaign.fleet_rotation import preflight_rotation
from module.campaign.fleet_training_notify import notify_event, notify_failure
from module.config.config import TaskEnd
from module.dorm.fleet_rotation import DormArrangeError, FleetRotationDorm
from module.exception import FleetManagementError, GameStuckError, ScriptEnd
import tests.test_fleet_training as training_cases
import tests.test_fleet_equipment as equipment_cases


class FleetTrainingNotificationTests(unittest.TestCase):
    def setUp(self):
        self.case = training_cases.TrainingIntegrationTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.configure()
        self.config = self.case.config
        self.case.manager.config = self.config
        self.queue = []
        self.enterContext(patch('module.campaign.fleet_training_notify.async_executor.submit',
                                side_effect=lambda task: self.queue.append(task)))
        self.remote = self.enterContext(patch('module.campaign.fleet_training_notify.handle_notify', return_value=True))
        self.local = self.enterContext(patch('module.campaign.fleet_training_notify.notify_webui', return_value=True))

    def enable(self):
        current = self.case.service.get('testpilot')
        # 走真实配置校验，不能在不存在的 General.Error 路径造测试数据。
        self.case.service.patch('testpilot', current['revision'], [
            ConfigChange(path='FleetInfo.FleetTraining.Notify', value=True),
            ConfigChange(path='Alas.Error.OnePushConfig', value='provider: weworkbot\nkey: testing-secret'),
        ])
        self.config.update()
        self.assertEqual('provider: weworkbot\nkey: testing-secret', self.config.Error_OnePushConfig)

    def drain(self):
        tasks, self.queue = self.queue, []
        for task in tasks:
            task()
        return [call.kwargs for call in self.remote.call_args_list]

    def test_real_global_channel_is_used_even_when_launcher_fails_and_payload_is_frozen(self):
        self.enable()
        self.local.return_value = False
        self.assertTrue(notify_event(self.config, '培养检查结果', '本次等级119'))
        self.config.cross_set('Alas.Error.OnePushConfig', 'provider: null')
        events = self.drain()
        self.remote.assert_called_once()
        self.assertEqual('provider: weworkbot\nkey: testing-secret', self.remote.call_args.args[0])
        self.assertIn('本次等级119', events[0]['content'])
        self.assertIn('培养检查结果', events[0]['title'])

    def test_onepush_failure_is_logged_without_credentials_and_launcher_is_still_attempted(self):
        self.enable()
        self.remote.side_effect = RuntimeError('secret URL testing-secret')
        with patch('module.campaign.fleet_training_notify.logger') as log:
            notify_event(self.config, '换船失败', '卡面无法确认')
            self.drain()
        self.local.assert_called_once()
        self.assertIn('RuntimeError', str(log.warning.call_args_list))
        self.assertNotIn('testing-secret', str(log.mock_calls))

    def test_notification_switch_never_adds_a_post_swap_scan(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.case.configure()
                if enabled:
                    self.enable()
                self.case.profile[self.case.names[1, 4]]['level'] = 120
                preflight_rotation(self.case.runner, 5, 'normal')
                self.assertEqual([1, 3], [fleet for fleet, _, _ in self.case.read_calls])
                if enabled:
                    self.assertEqual(3, len(self.drain()))
                else:
                    self.assertEqual([], self.queue)

    def test_periodic_check_sends_one_current_report_and_waits_for_the_existing_interval(self):
        self.enable()
        preflight_rotation(self.case.runner, 5, 'normal')
        preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(1, len(events))
        self.assertIn('培养检查结果', events[0]['title'])
        self.assertIn('等级80', events[0]['content'])
        self.case.manager.rotate_slot.assert_not_called()
        self.assertEqual([(1, [4], {'level': 120})], self.case.read_calls)

    def test_graduation_emits_three_ordered_reports_reusing_existing_reads(self):
        for mood in (False, True):
            with self.subTest(mood=mood):
                self.case.configure(mood=mood)
                self.enable()
                self.remote.reset_mock()
                old, incoming = self.case.names[1, 4], self.case.names[3, 4]
                self.case.profile[old]['level'] = 120
                self.case.profile[incoming]['level'] = 99
                preflight_rotation(self.case.runner, 5, 'normal')
                events = self.drain()
                self.assertEqual(3, len(events))
                self.assertTrue(events[0]['title'].endswith('培养检查结果'))
                self.assertTrue(events[1]['title'].endswith('培养目标达成'))
                self.assertTrue(events[2]['title'].endswith('换船完成'))
                self.assertIn(f'{old}：等级120', events[0]['content'])
                self.assertIn(f'{old}：等级120', events[1]['content'])
                self.assertIn(f'{incoming}：等级99', events[2]['content'])
                self.assertIn(f'{old} → {incoming}', events[2]['content'])
                self.assertEqual([1, 3], [fleet for fleet, _, _ in self.case.read_calls])
                self.case.manager.run.assert_called()

    def test_only_one_of_two_goals_sends_check_without_graduation_or_swap(self):
        self.case.configure(level=True, affinity=True)
        self.enable()
        self.case.profile[self.case.names[1, 4]] = dict(level=120, affinity=99)
        preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(1, len(events))
        self.assertIn('好感99', events[0]['content'])
        self.case.manager.rotate_slot.assert_not_called()

    def test_post_swap_report_uses_the_previous_read_without_checking_the_live_profile_again(self):
        self.enable()
        self.config.cross_set('FleetInfo.FleetAffinityTraining.Enabled', True)
        self.case.profile[self.case.names[1, 4]] = dict(level=120, affinity=100)
        rotate = self.case.manager.rotate_slot.side_effect

        def replace(*args):
            result = rotate(*args)
            self.case.profile[self.case.names[1, 4]]['affinity'] = None
            return result

        self.case.manager.rotate_slot.side_effect = replace
        preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(3, len(events))
        self.assertTrue(events[-1]['title'].endswith('换船完成'))
        self.assertIn('好感50', events[-1]['content'])
        self.assertIn('最近记录', events[-1]['content'])
        self.assertEqual([1, 3], [fleet for fleet, _, _ in self.case.read_calls])

    def test_two_of_three_ships_graduate_and_reports_keep_the_third_ship_in_training(self):
        self.case.configure(slots=(4, 5, 6))
        self.enable()
        old = [self.case.names[1, slot] for slot in (4, 5, 6)]
        for name, level in zip(old, (120, 120, 109)):
            self.case.profile[name]['level'] = level
        incoming = [self.case.names[3, slot] for slot in (4, 5)]
        for name, level in zip(incoming, (99, 90)):
            self.case.profile[name]['level'] = level
        preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(3, len(events))
        self.assertIn(f'{old[2]}：等级109', events[0]['content'])
        self.assertNotIn(old[2], events[1]['content'])
        for name, level in zip(incoming + [old[2]], (99, 90, 109)):
            self.assertIn(f'{name}：等级{level}', events[2]['content'])
        self.assertEqual([(1, [4, 5, 6]), (3, [4]), (3, [5])],
                         [(fleet, slots) for fleet, slots, _ in self.case.read_calls])

    def test_morale_rotation_without_a_candidate_notifies_and_keeps_the_existing_wait_path(self):
        self.case.configure(mood=True, level=False)
        self.enable()
        self.case.live[1][4] = 2
        self.case.live[3][4] = 2
        preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(1, sum(event['title'].endswith('换船失败') for event in events))
        self.assertTrue(any('保留当前编队' in event['content'] for event in events))
        self.case.manager.rotate_slot.assert_not_called()

    def test_no_candidate_reports_graduation_then_failure_without_a_fake_success(self):
        self.enable()
        for fleet in (1, 3):
            self.case.profile[self.case.names[fleet, 4]]['level'] = 120
        with self.assertRaises(ScriptEnd):
            preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(3, len(events))
        self.assertTrue(events[-1]['title'].endswith('换船失败'))
        self.assertIn('没有合适候补', events[-1]['content'])
        self.assertFalse(any(event['title'].endswith('换船完成') for event in events))

    def test_swap_error_is_reported_once_and_preserves_exception_and_pending_jobs(self):
        self.enable()
        self.case.profile[self.case.names[1, 4]]['level'] = 120
        failure = FleetManagementError('目标舰位卡面未确认')
        self.case.manager.rotate_slot.side_effect = failure
        with self.assertRaises(FleetManagementError) as raised:
            preflight_rotation(self.case.runner, 5, 'normal')
        self.assertIs(failure, raised.exception)
        events = self.drain()
        self.assertEqual(3, len(events))
        self.assertIn('目标舰位卡面未确认', events[-1]['content'])
        self.assertTrue(self.config.cross_get('FleetInfo.FleetTraining.State')['pending'])

    def test_stop_mode_reports_checks_and_stop_without_replacement_or_failure(self):
        self.enable()
        self.config.cross_set('FleetInfo.FleetTraining.StopOnComplete', True)
        self.case.profile[self.case.names[1, 4]]['level'] = 120
        with self.assertRaises(TaskEnd):
            preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(2, len(events))
        self.assertTrue(events[1]['title'].endswith('培养完成，已停止练级'))
        self.case.manager.rotate_slot.assert_not_called()

    def test_dorm_skip_reports_reason_and_still_leaves_and_returns_false(self):
        self.enable()
        dorm = FleetRotationDorm.__new__(FleetRotationDorm)
        dorm.config = self.config
        dorm._arrange = Mock(side_effect=DormArrangeError('未确认足够的后宅栏位'))
        dorm._leave = Mock()
        self.assertFalse(dorm.run(1))
        dorm._leave.assert_called_once()
        events = self.drain()
        self.assertEqual(1, len(events))
        self.assertTrue(events[0]['title'].endswith('后宅安排失败'))
        self.assertIn('未确认足够的后宅栏位', events[0]['content'])

    def test_dorm_failure_does_not_block_the_three_training_reports_or_task_navigation(self):
        self.enable()
        self.case.profile[self.case.names[1, 4]]['level'] = 120
        self.config.cross_set('FleetInfo.FleetDorm.Enabled', True)
        dorm = FleetRotationDorm.__new__(FleetRotationDorm)
        dorm.config = self.config
        dorm._arrange = Mock(side_effect=DormArrangeError('后宅栏位不足'))
        dorm._leave = Mock()
        with patch('module.dorm.fleet_rotation.FleetRotationDorm', return_value=dorm):
            preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(4, len(events))
        self.assertTrue(events[2]['title'].endswith('换船完成'))
        self.assertTrue(events[3]['title'].endswith('后宅安排失败'))
        self.case.campaign.ensure_campaign_ui.assert_called_once()
        self.assertEqual({}, self.config.cross_get('FleetInfo.FleetTraining.State')['pending'])

    def test_equipment_failure_after_swap_keeps_three_reports_and_notifies_only_the_equipment_error(self):
        self.enable()
        self.case.profile[self.case.names[1, 4]]['level'] = 120
        self.config.cross_set('FleetInfo.FleetEquipment.Enabled', True)
        case = equipment_cases.FleetEquipmentFlowTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        gear = case.handler
        gear.config = self.config
        gear._code_apply = Mock(side_effect=[True, False])
        with patch('module.campaign.fleet_training.FleetRotationEquipment', return_value=gear):
            with self.assertRaises(FleetManagementError):
                preflight_rotation(self.case.runner, 5, 'normal')
        events = self.drain()
        self.assertEqual(4, len(events))
        self.assertTrue(events[2]['title'].endswith('换船完成'))
        self.assertTrue(events[3]['title'].endswith('装备更换失败'))
        self.assertIn('1:4', self.config.cross_get('FleetInfo.FleetEquipment.State'))
        self.assertEqual({}, self.config.cross_get('FleetInfo.FleetTraining.State')['pending'])

    def test_equipment_failure_is_reported_and_pending_state_is_preserved_without_success_notice(self):
        self.enable()
        case = equipment_cases.FleetEquipmentFlowTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        handler = case.handler
        handler.config.config_name = self.config.config_name
        handler.config.task = self.config.task
        case.store.update({'FleetInfo.FleetTraining.Notify': True,
                           'Alas.Error.OnePushConfig': self.config.Error_OnePushConfig})
        handler.clear_outgoing(6, [4])
        self.assertEqual([], self.queue)
        before = deepcopy(case.pending())
        handler._code_apply = Mock(return_value=False)
        with self.assertRaises(FleetManagementError):
            handler.apply_pending()
        events = self.drain()
        self.assertEqual(1, len(events))
        self.assertTrue(events[0]['title'].endswith('装备更换失败'))
        self.assertEqual(set(before), set(case.pending()))

    def test_exception_conversion_does_not_duplicate_stage_failure_notices(self):
        self.enable()

        class Operation:
            config = self.config

            @notify_failure('装备更换失败', '未完成换装')
            def inner(self):
                raise GameStuckError('交互超时')

            @notify_failure('换船失败', '上层恢复')
            def outer(self):
                try:
                    self.inner()
                except GameStuckError as exc:
                    raise FleetManagementError('本轮未完成') from exc

        with self.assertRaises(FleetManagementError):
            Operation().outer()
        events = self.drain()
        self.assertEqual(1, len(events))
        self.assertTrue(events[0]['title'].endswith('装备更换失败'))
