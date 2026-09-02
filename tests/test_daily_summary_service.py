import sys
import tempfile
import types
import unittest
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alas import AzurLaneAutoScript
import module.statistics.daily_summary as daily_summary
import module.notify.notify as notify_module
from module.statistics.daily_summary import DAILY_SUMMARY_TITLE, DailySummaryService
from module.statistics.daily_summary_store import DailySummaryStore
from tests.test_daily_summary import sample_facts, summary_config, valid_report_text


class TestDailySummaryService(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = DailySummaryStore(
            Path(self.temporary_directory.name) / 'daily_summary.db'
        )
        self.service = DailySummaryService('alpha', store=self.store)
        self.start = datetime(2026, 8, 20, 20)
        self.end = datetime(2026, 8, 21, 20)
        self.key = 'cn:2026-08-21:2000'

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_due_period_is_deduplicated_and_missed_period_is_not_backfilled(self):
        config = summary_config()
        with (
            patch.object(daily_summary, 'server_time_offset_for', return_value=timedelta()),
            patch.object(daily_summary.threading, 'Thread') as thread,
        ):
            self.assertTrue(
                self.service.check_due(config, now=datetime(2026, 8, 21, 20, 2))
            )
            self.assertFalse(
                self.service.check_due(config, now=datetime(2026, 8, 21, 20, 3))
            )

        thread.assert_called_once()
        thread.return_value.start.assert_called_once_with()
        self.assertEqual('generating', self.store.get_period('alpha', self.key)['status'])

        missed = DailySummaryService('beta', store=self.store)
        with (
            patch.object(daily_summary, 'server_time_offset_for', return_value=timedelta()),
            patch.object(daily_summary.threading, 'Thread') as thread,
        ):
            self.assertFalse(
                missed.check_due(config, now=datetime(2026, 8, 21, 20, 6))
            )

        thread.assert_not_called()
        self.assertEqual('skipped', self.store.get_period('beta', self.key)['status'])

    def test_cn_0010_is_submitted_and_logged(self):
        config = summary_config(
            DailySummary_TriggerTime='00:10',
            Emulator_PackageName='auto',
            Emulator_ServerName='cn_android-0',
        )
        with (
            patch.object(daily_summary, 'server_time_offset_for', return_value=timedelta()),
            patch.object(daily_summary.threading, 'Thread') as thread,
            patch.object(daily_summary.logger, 'info') as info,
        ):
            self.assertTrue(
                self.service.check_due(config, now=datetime(2026, 8, 22, 0, 10, 2))
            )

        thread.return_value.start.assert_called_once_with()
        self.assertEqual(
            'generating',
            self.store.get_period('alpha', 'cn:2026-08-22:0010')['status'],
        )
        self.assertTrue(
            any('开始生成每日总结' in call.args[0] for call in info.call_args_list)
        )

    def test_cn_0010_runs_background_pipeline_to_sent(self):
        config = summary_config(
            DailySummary_TriggerTime='00:10',
            Emulator_PackageName='auto',
            Emulator_ServerName='cn_android-0',
        )
        with (
            patch.object(daily_summary, 'server_time_offset_for', return_value=timedelta()),
            patch('module.base.async_executor.async_executor.flush'),
            patch.object(self.service, 'build_facts', return_value=sample_facts()),
            patch.object(self.service, '_generate_report', return_value=('日报正文', 1)),
            patch.object(self.service, '_send_report', return_value=(True, 1)) as send,
        ):
            self.assertTrue(
                self.service.check_due(config, now=datetime(2026, 8, 22, 0, 10, 2))
            )
            deadline = time.monotonic() + 2
            period = self.store.get_period('alpha', 'cn:2026-08-22:0010')
            while period is not None and period['status'] == 'generating':
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
                period = self.store.get_period('alpha', 'cn:2026-08-22:0010')

        self.assertEqual('sent', period['status'])
        send.assert_called_once_with('provider: json', '日报正文')

    def test_unresolved_automatic_package_does_not_claim_a_period(self):
        config = summary_config(
            Emulator_PackageName='auto', Emulator_ServerName='disabled'
        )
        with (
            patch.object(daily_summary, 'server_time_offset_for', return_value=timedelta()),
            patch.object(daily_summary.threading, 'Thread') as thread,
        ):
            self.assertFalse(
                self.service.check_due(config, now=datetime(2026, 8, 21, 20, 2))
            )

        thread.assert_not_called()
        self.assertIsNone(self.store.get_period('alpha', self.key))

    def test_missed_check_also_cleans_expired_periods(self):
        old_start = self.start - timedelta(days=36)
        old_end = self.end - timedelta(days=36)
        old_key = 'cn:2026-07-16:2000'
        self.assertTrue(
            self.store.claim_period('alpha', old_key, 'cn', old_start, old_end)
        )

        with (
            patch.object(daily_summary, 'server_time_offset_for', return_value=timedelta()),
            patch.object(daily_summary.threading, 'Thread') as thread,
        ):
            self.assertFalse(
                self.service.check_due(summary_config(), now=datetime(2026, 8, 21, 12))
            )

        thread.assert_not_called()
        self.assertIsNone(self.store.get_period('alpha', old_key))

    def test_build_facts_uses_only_aggregated_statistics(self):
        resource_result = {
            'resources': {
                'Oil': {
                    'start': 100,
                    'end': 120,
                    'delta': 20,
                    'baseline_known': True,
                    'end_known': True,
                }
            }
        }
        commission_result = {
            'available': True,
            'settled_count': 3,
            'items': {'Gem': {'total': 1}},
        }
        cl1_result = {'available': True, 'battles': 4, 'estimated_exp': 1248}
        with (
            patch(
                'module.statistics.resource_stats.get_resource_interval_summary',
                return_value=resource_result,
            ),
            patch(
                'module.statistics.commission_income_stats.get_commission_income_interval_summary',
                return_value=commission_result,
            ),
            patch(
                'module.statistics.ship_exp_stats.get_cl1_interval_summary',
                return_value=cl1_result,
            ),
        ):
            facts = self.service.build_facts(
                server='cn', window_start=self.start, window_end=self.end
            )

        self.assertEqual('石油', facts['resources'][0]['label'])
        self.assertEqual(20, facts['resources'][0]['delta'])
        self.assertTrue(facts['commission']['available'])
        self.assertNotIn('alpha', str(facts))
        self.assertNotIn('Error_LlmApiKey', str(facts))
        self.assertNotIn('OnePush', str(facts))

    def test_facts_display_the_game_server_window(self):
        with (
            patch.object(
                daily_summary, 'server_time_offset_for', return_value=timedelta(hours=-1)
            ),
            patch.object(self.store, 'get_task_summary', return_value={'available': False}),
            patch(
                'module.statistics.resource_stats.get_resource_interval_summary',
                return_value={'resources': {}},
            ),
            patch(
                'module.statistics.commission_income_stats.get_commission_income_interval_summary',
                return_value={'available': False, 'items': {}},
            ),
            patch(
                'module.statistics.ship_exp_stats.get_cl1_interval_summary',
                return_value={'available': False},
            ),
        ):
            facts = self.service.build_facts(
                server='jp',
                window_start=datetime(2026, 8, 20, 19),
                window_end=datetime(2026, 8, 21, 19),
            )

        self.assertEqual('2026-08-20 20:00:00', facts['window']['start'])
        self.assertEqual('2026-08-21 20:00:00', facts['window']['end'])

    def test_llm_text_is_sent_without_content_validation(self):
        client = Mock()

        def response(content):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

        report_text = '# 每日总结\n\n- 魔方 2 个'
        client.chat.completions.create.return_value = response(report_text)
        openai_module = types.ModuleType('openai')
        openai_module.OpenAI = Mock(return_value=client)
        request = {
            'llm_api_key': 'test-key',
            'llm_api_base': 'https://example.invalid/v1',
            'llm_model': 'test-model',
        }
        with patch.dict(sys.modules, {'openai': openai_module}):
            report, attempts = self.service._generate_report(request, sample_facts())

        self.assertEqual(report_text, report)
        self.assertEqual(1, attempts)
        self.assertEqual(1, client.chat.completions.create.call_count)

        with patch(
            'module.notify.handle_notify',
            side_effect=[False, RuntimeError('temporary'), True],
        ) as notify:
            sent, send_attempts = self.service._send_report(
                'provider: json', report
            )

        self.assertTrue(sent)
        self.assertEqual(3, send_attempts)
        self.assertEqual(3, notify.call_count)
        for call in notify.call_args_list:
            self.assertEqual(
                DAILY_SUMMARY_TITLE.format(config_name='alpha'),
                call.kwargs['title'],
            )
            self.assertEqual(report, call.kwargs['content'])

    def test_empty_llm_response_does_not_attempt_onepush(self):
        self.assertTrue(
            self.store.claim_period('alpha', self.key, 'cn', self.start, self.end)
        )
        request = {
            'period_key': self.key,
            'server': 'cn',
            'window_start': self.start,
            'window_end': self.end,
            'llm_api_key': 'test-key',
            'llm_api_base': 'https://example.invalid/v1',
            'llm_model': 'test-model',
            'onepush_config': 'provider: json',
        }
        client = Mock()
        client.chat.completions.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''))]),
        ]
        openai_module = types.ModuleType('openai')
        openai_module.OpenAI = Mock(return_value=client)
        with (
            patch.dict(sys.modules, {'openai': openai_module}),
            patch('module.base.async_executor.async_executor.flush'),
            patch.object(self.service, 'build_facts', return_value=sample_facts()),
            patch('module.notify.handle_notify') as notify,
        ):
            self.service._generate_and_send(request)

        period = self.store.get_period('alpha', self.key)
        self.assertEqual('failed', period['status'])
        self.assertEqual('llm', period['error_kind'])
        self.assertEqual(3, client.chat.completions.create.call_count)
        notify.assert_not_called()

    def test_generate_and_send_records_sent_status(self):
        self.assertTrue(
            self.store.claim_period('alpha', self.key, 'cn', self.start, self.end)
        )
        request = {
            'period_key': self.key,
            'server': 'cn',
            'window_start': self.start,
            'window_end': self.end,
            'llm_api_key': 'test-key',
            'llm_api_base': 'https://example.invalid/v1',
            'llm_model': 'test-model',
            'onepush_config': 'provider: json',
        }
        report_text = '# 模型返回的 Markdown 也直接发送'
        with (
            patch('module.base.async_executor.async_executor.flush'),
            patch.object(self.service, 'build_facts', return_value=sample_facts()),
            patch.object(self.service, '_generate_report', return_value=(report_text, 1)),
            patch.object(self.service, '_send_report', return_value=(True, 1)) as send,
            patch.object(daily_summary.logger, 'info') as info,
        ):
            self.service._generate_and_send(request)

        period = self.store.get_period('alpha', self.key)
        self.assertEqual('sent', period['status'])
        self.assertEqual(report_text, period['report_text'])
        send.assert_called_once_with('provider: json', report_text)
        self.assertTrue(
            any('开始处理' in call.args[0] for call in info.call_args_list)
        )

    def test_missing_configuration_records_failure_without_fallback(self):
        self.assertTrue(
            self.store.claim_period('alpha', self.key, 'cn', self.start, self.end)
        )
        request = {
            'period_key': self.key,
            'server': 'cn',
            'window_start': self.start,
            'window_end': self.end,
            'llm_api_key': '',
            'llm_api_base': 'https://example.invalid/v1',
            'llm_model': 'test-model',
            'onepush_config': 'provider: json',
        }
        with (
            patch.object(self.service, 'build_facts') as facts,
            patch('module.notify.handle_notify') as notify,
        ):
            self.service._generate_and_send(request)

        period = self.store.get_period('alpha', self.key)
        self.assertEqual('failed', period['status'])
        self.assertEqual('configuration', period['error_kind'])
        facts.assert_not_called()
        notify.assert_not_called()

    def test_scheduler_check_never_initializes_device_or_restart_flow(self):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.config_name = 'alpha'
        script.failure_record = {'Commission': 2}
        script._daily_summary_settings = summary_config()
        script._daily_summary_settings_mtime = None
        service = Mock()
        script.__dict__['_daily_summary_service'] = service

        with patch('alas.current_time', return_value=datetime(2026, 8, 21, 20, 2)):
            script._check_daily_summary(script._daily_summary_settings)
            service.check_due.side_effect = RuntimeError('日报故障')
            script._check_daily_summary(script._daily_summary_settings)

        self.assertEqual(2, service.check_due.call_count)
        self.assertIsNone(service.check_due.call_args.kwargs['current_server'])
        self.assertNotIn('device', script.__dict__)
        self.assertNotIn('config', script.__dict__)
        self.assertEqual({'Commission': 2}, script.failure_record)

        script.__dict__['_daily_summary_service'] = None
        script._check_daily_summary(summary_config(DailySummary_Enable=False))
        self.assertIsNone(script._daily_summary_service)

    def test_independent_daily_summary_loop_checks_without_task_completion(self):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script._daily_summary_stop = Mock()
        script._daily_summary_stop.is_set.side_effect = [False, True]
        script._daily_summary_stop.wait.return_value = False
        script._daily_summary_thread = None
        script._daily_summary_enabled = True
        script._get_daily_summary_settings = Mock(return_value=summary_config())
        script._check_daily_summary = Mock()

        script._daily_summary_loop()

        script._check_daily_summary.assert_called_once_with(
            script._get_daily_summary_settings.return_value
        )
        self.assertNotIn('device', script.__dict__)

    def test_independent_daily_summary_scheduler_starts_a_daemon_thread(self):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.config_name = 'alpha'
        script._daily_summary_enabled = False
        script._daily_summary_stop = None
        script._daily_summary_thread = None
        script._daily_summary_settings_mtime = None
        script._daily_summary_settings = None
        script._get_daily_summary_service = Mock()
        with patch('alas.threading.Thread') as thread:
            started = script._start_daily_summary_scheduler(summary_config())

        self.assertTrue(started)
        script._get_daily_summary_service.assert_called_once_with()
        thread.assert_called_once()
        self.assertIs(thread.call_args.kwargs['target'].__self__, script)
        self.assertEqual('_daily_summary_loop', thread.call_args.kwargs['target'].__name__)
        self.assertTrue(thread.call_args.kwargs['daemon'])
        thread.return_value.start.assert_called_once_with()

    def test_disabled_daily_summary_creates_no_thread_service_or_config(self):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.config_name = 'alpha'
        script._daily_summary_enabled = False
        script._daily_summary_service = None
        script._daily_summary_stop = None
        script._daily_summary_thread = None
        script._daily_summary_settings_mtime = None
        script._daily_summary_settings = None
        script._get_daily_summary_service = Mock()

        with (
            patch('alas.threading.Event') as event,
            patch('alas.threading.Thread') as thread,
        ):
            started = script._start_daily_summary_scheduler(
                summary_config(DailySummary_Enable=False)
            )

        self.assertFalse(started)
        script._get_daily_summary_service.assert_not_called()
        event.assert_not_called()
        thread.assert_not_called()
        self.assertIsNone(script._daily_summary_service)
        self.assertIsNone(script._daily_summary_stop)
        self.assertIsNone(script._daily_summary_settings)
        self.assertNotIn('config', script.__dict__)

    def test_daily_scheduler_reads_latest_saved_settings_without_reloading_task_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / 'alpha.json'
            config_path.write_text(
                json.dumps({
                    'Alas': {
                        'DailySummary': {'Enable': True, 'TriggerTime': '00:10'},
                        'Emulator': {'PackageName': 'auto', 'ServerName': 'cn_android-0'},
                        'Error': {
                            'LlmApiKey': 'key',
                            'LlmApiBase': 'https://example.invalid/v1',
                            'LlmModel': 'model',
                            'OnePushConfig': 'provider: json',
                        },
                    },
                }),
                encoding='utf-8',
            )
            script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
            script.config_name = 'alpha'
            script._daily_summary_settings_mtime = None
            script._daily_summary_settings = summary_config()
            service = Mock()
            script.__dict__['_daily_summary_service'] = service

            with (
                patch('alas.filepath_config', return_value=str(config_path)),
                patch('alas.current_time', return_value=datetime(2026, 8, 22, 0, 10, 2)),
            ):
                script._check_daily_summary()

        service.check_due.assert_called_once()
        settings = service.check_due.call_args.args[0]
        self.assertTrue(settings.DailySummary_Enable)
        self.assertEqual('00:10', settings.DailySummary_TriggerTime)
        self.assertEqual('cn_android-0', settings.Emulator_ServerName)
        self.assertNotIn('config', script.__dict__)


class TestDailySummaryNotify(unittest.TestCase):
    def test_custom_onepush_adds_data_when_configuration_omits_it(self):
        class FakeCustom:
            name = 'Custom'
            params = {'required': []}

            def notify(self, **kwargs):
                self.kwargs = kwargs

        notifier = FakeCustom()
        with (
            patch.object(notify_module, 'get_notifier', return_value=notifier),
            patch.object(notify_module, 'Custom', FakeCustom),
        ):
            sent = notify_module.handle_notify(
                'provider: custom', title='日报标题', content='日报正文'
            )

        self.assertTrue(sent)
        self.assertEqual(
            {'title': '日报标题', 'content': '日报正文'}, notifier.kwargs['data']
        )


if __name__ == '__main__':
    unittest.main()
