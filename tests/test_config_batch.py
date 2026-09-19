"""配置批量修改、覆盖顺序与失败重试回归。"""

import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from module.config.config import AzurLaneConfig, Function, TaskEnd
from module.config.deep import deep_get, deep_set


class ConfigBatchTests(unittest.TestCase):
    """使用真实更新、绑定和事务流程，以内存磁盘替换配置读写。"""

    def setUp(self):
        self.now = datetime(2026, 9, 19, 12)
        self.disk = {
            name: {
                'Scheduler': {'Command': name, 'Enable': False, 'NextRun': self.now},
                'Test': {'Value': 1, 'Other': 2},
            }
            for name in (
                'Main', 'Research', 'OpsiScheduling', 'OpsiMeowfficerFarming',
                'OpsiPreventActionPointOverflow', 'IslandPearlSell', 'PrivateQuarters',
            )
        }
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / 'batch.json')
        for target, value in (
            ('module.config.config.filepath_config', path),
            ('module.config.config.current_time', self.now),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        config = AzurLaneConfig.__new__(AzurLaneConfig)
        config.bound = {}
        config.config_name = 'batch'
        config.data = copy.deepcopy(self.disk)
        config._loaded_data = copy.deepcopy(self.disk)
        config.modified = {}
        config.overridden = {}
        config.auto_update = True
        config.task = Function(self.disk['Main'])
        config.read_file = Mock(side_effect=lambda name: copy.deepcopy(self.disk))
        config.write_file = Mock(side_effect=self.write_file)
        config.bind(config.task)
        self.config = config

    def write_file(self, name, data):
        """保留独立的磁盘快照，避免误把内存修改当成持久化结果。"""
        self.disk = copy.deepcopy(data)

    def test_nested_changes_and_task_delay_commit_only_once(self):
        config = self.config
        with config.multi_set():
            config.Test_Value = 3
            with config.multi_set():
                config.cross_set('Main.Test.Other', 4)
                config.task_delay(minute=90)
            config.write_file.assert_not_called()
            self.assertFalse(config.auto_update)
        config.write_file.assert_called_once()
        self.assertTrue(config.auto_update)
        self.assertEqual(self.disk['Main']['Test'], {'Value': 3, 'Other': 4})
        self.assertEqual(self.disk['Main']['Scheduler']['NextRun'], self.now + timedelta(minutes=90))
        self.assertEqual(config.modified, {})
        self.assertEqual(config.Test_Value, 3)

    def test_task_end_and_regular_exception_still_commit_pending_changes(self):
        for error in (TaskEnd('调度结束'), RuntimeError('业务异常')):
            with self.subTest(error=error):
                self.config.write_file.reset_mock()
                with self.assertRaises(type(error)) as caught:
                    with self.config.multi_set():
                        with self.config.multi_set():
                            self.config.task_delay(minute=90)
                            self.config.Test_Value = 5
                            self.config.write_file.assert_not_called()
                            raise error
                self.assertIs(caught.exception, error)
                self.config.write_file.assert_called_once()
                self.assertTrue(self.config.auto_update)
                self.assertEqual(self.disk['Main']['Scheduler']['NextRun'], self.now + timedelta(minutes=90))
                self.assertEqual(self.disk['Main']['Test']['Value'], 5)

    def test_disabled_auto_update_remains_disabled_and_pending(self):
        config = self.config
        config.auto_update = False
        with config.multi_set(), config.multi_set():
            config.Test_Value = 3
            config.task_delay(minute=30)
        self.assertFalse(config.auto_update)
        config.write_file.assert_not_called()
        self.assertEqual(config.modified['Main.Test.Value'], 3)
        # 显式 update 仍是强制提交入口，不受自动更新开关影响。
        config.update()
        config.write_file.assert_called_once()
        self.assertFalse(config.auto_update)

    def test_same_batch_wrapper_can_be_nested_and_reused(self):
        batch = self.config.multi_set()
        with batch:
            with batch:
                self.config.Test_Value = 3
            self.config.write_file.assert_not_called()
        with batch:
            self.config.Test_Other = 4
        self.assertEqual(self.config.write_file.call_count, 2)
        self.assertTrue(self.config.auto_update)

    def test_failure_in_each_update_stage_restores_auto_update(self):
        for stage in ('load', 'config_override', 'bind', 'save'):
            with self.subTest(stage=stage):
                with patch.object(self.config, stage, side_effect=RuntimeError(stage)):
                    with self.assertRaisesRegex(RuntimeError, stage):
                        with self.config.multi_set(), self.config.multi_set():
                            self.config.Test_Value = 3
                self.assertTrue(self.config.auto_update)
                self.assertEqual(self.config.modified['Main.Test.Value'], 3)

    def test_write_failure_keeps_pending_changes_for_retry(self):
        config = self.config
        pending = config.modified
        config.write_file.side_effect = OSError('磁盘写入失败')
        with self.assertRaisesRegex(OSError, '磁盘写入失败'):
            with config.multi_set():
                config.Test_Value = 3
                config.task_delay(minute=90)
        self.assertTrue(config.auto_update)
        self.assertIs(config.modified, pending)
        self.assertEqual(self.disk['Main']['Test']['Value'], 1)
        self.assertEqual(pending['Main.Test.Value'], 3)
        self.assertIn('Main.Scheduler.NextRun', pending)

        config.write_file.side_effect = self.write_file
        config.update()
        self.assertEqual(self.disk['Main']['Test']['Value'], 3)
        self.assertEqual(self.disk['Main']['Scheduler']['NextRun'], self.now + timedelta(minutes=90))
        self.assertIs(config.modified, pending)
        self.assertEqual(pending, {})

    def test_retry_after_write_failure_preserves_external_same_field_edit(self):
        config = self.config
        config.write_file.side_effect = OSError('磁盘写入失败')
        with self.assertRaises(OSError):
            config.cross_set_many({'Main.Test.Value': 3, 'Main.Test.Other': 4})
        self.disk['Main']['Test']['Value'] = 99
        config.write_file.side_effect = self.write_file
        config.update()
        self.assertEqual(self.disk['Main']['Test'], {'Value': 99, 'Other': 4})
        self.assertEqual(config.Test_Value, 99)
        self.assertEqual(config.modified, {})

    def test_update_overrides_once_after_pending_changes_before_binding(self):
        config = self.config
        config.task = Function(self.disk['Research'])
        config.bind(config.task)
        invalid_next_run = self.now + timedelta(days=3)
        observed = []
        override = config.config_override

        def record_override():
            observed.append(config.data['Research']['Scheduler']['NextRun'])
            override()

        with patch.object(config, 'config_override', side_effect=record_override):
            config.cross_set('Research.Scheduler.NextRun', invalid_next_run)
        self.assertEqual(observed, [invalid_next_run])
        self.assertEqual(config.Scheduler_NextRun, self.now)
        # save 按原契约只合并 modified，调度夹限不擅自改写用户磁盘字段。
        self.assertEqual(self.disk['Research']['Scheduler']['NextRun'], invalid_next_run)

    def test_plain_load_keeps_override_before_pending_changes(self):
        config = self.config
        pending_next_run = self.now + timedelta(days=3)
        config.modified['Research.Scheduler.NextRun'] = pending_next_run
        with patch.object(config, 'config_override', wraps=config.config_override) as override:
            config.load()
        override.assert_called_once_with()
        self.assertEqual(config.data['Research']['Scheduler']['NextRun'], pending_next_run)
        config.write_file.assert_not_called()

    def test_update_preserves_long_legitimate_schedules(self):
        for task, delay in (
            ('OpsiPreventActionPointOverflow', timedelta(hours=36)),
            ('IslandPearlSell', timedelta(days=7)),
            ('PrivateQuarters', timedelta(days=27)),
        ):
            with self.subTest(task=task):
                self.config.task = Function(self.disk[task])
                self.config.bind(self.config.task)
                self.config.task_delay(minute=delay.total_seconds() / 60)
                expected = self.now + delay
                self.assertEqual(self.config.Scheduler_NextRun, expected)
                self.assertEqual(self.disk[task]['Scheduler']['NextRun'], expected)

    def test_update_preserves_proxy_binding_and_runtime_overrides(self):
        config = self.config
        owner = config.task
        config._bind_task_override = 'OpsiMeowfficerFarming'
        config.bind(config._bind_task_override)
        config.override(Test_Value=99)
        with config.multi_set():
            config.Test_Value = 3
            config.Test_Other = 4
        self.assertIs(config.task, owner)
        self.assertEqual(config._bind_task_override, 'OpsiMeowfficerFarming')
        self.assertEqual(config.bound['Test_Value'], 'OpsiMeowfficerFarming.Test.Value')
        self.assertEqual(config.Test_Value, 99)
        self.assertEqual(config.Test_Other, 4)
        self.assertEqual(config.overridden, {'Test_Value': 99})
        self.assertEqual(self.disk['OpsiMeowfficerFarming']['Test'], {'Value': 3, 'Other': 4})

    def test_proxy_task_end_commits_delay_after_original_binding_restores(self):
        from module.os.tasks.scheduling import OpsiScheduling

        config = self.config
        config.task = Function(self.disk['OpsiScheduling'])
        config.bind(config.task)
        owner = config.task
        runner = OpsiScheduling.__new__(OpsiScheduling)
        runner.config = config
        end = TaskEnd('代理任务结束')

        def child():
            runner.delay_opsi_active_task(minute=90)
            config.write_file.assert_not_called()
            raise end

        with self.assertRaises(TaskEnd) as caught:
            with config.multi_set():
                runner._run_with_opsi_task_context('OpsiMeowfficerFarming', child)
        self.assertIs(caught.exception, end)
        self.assertIs(config.task, owner)
        self.assertNotIn('_bind_task_override', config.__dict__)
        self.assertNotIn('_opsi_task_context', config.__dict__)
        self.assertEqual(config.bound['Scheduler_NextRun'], 'OpsiScheduling.Scheduler.NextRun')
        self.assertEqual(config.Scheduler_NextRun, self.now + timedelta(minutes=90))
        self.assertEqual(self.disk['OpsiMeowfficerFarming']['Scheduler']['NextRun'], self.now)
        config.write_file.assert_called_once()
        self.assertTrue(config.auto_update)

    def test_task_call_batches_enable_and_next_run(self):
        with patch.object(self.config, 'config_override', wraps=self.config.config_override) as override:
            self.assertTrue(self.config.task_call('OpsiScheduling'))
        override.assert_called_once_with()
        self.config.write_file.assert_called_once()
        self.assertTrue(self.disk['OpsiScheduling']['Scheduler']['Enable'])
        self.assertEqual(self.disk['OpsiScheduling']['Scheduler']['NextRun'], self.now)

    def test_opsi_delay_joins_outer_batch(self):
        with self.config.multi_set():
            self.config.Test_Value = 3
            self.config.opsi_task_delay(ap_limit=True, ap_limit_minutes=90)
            self.config.write_file.assert_not_called()
        self.config.write_file.assert_called_once()
        self.assertEqual(self.disk['Main']['Test']['Value'], 3)
        self.assertEqual(
            deep_get(self.disk, 'OpsiMeowfficerFarming.Scheduler.NextRun'),
            self.now + timedelta(minutes=90),
        )

    def test_foreign_edit_between_reload_and_save_is_preserved(self):
        config = self.config
        override = config.config_override

        def edit_during_update():
            override()
            deep_set(self.disk, 'Main.Test.Value', 99)

        with patch.object(config, 'config_override', side_effect=edit_during_update):
            config.cross_set_many({'Main.Test.Value': 3, 'Main.Test.Other': 4})
        self.assertEqual(self.disk['Main']['Test'], {'Value': 99, 'Other': 4})
        self.assertEqual(config.Test_Value, 99)
        self.assertEqual(config.modified, {})
