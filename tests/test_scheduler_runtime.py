"""调度宿主、SQLite 和 API 的隔离验收，不初始化设备。"""
import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.protocol import ApiError
from module.api.router import Router
from module.scheduler.engine import Engine, simulate
from module.scheduler.models import ProgramDocument, SubgraphDefinition
from module.scheduler.runtime import SchedulerRuntime
from module.scheduler.store import ProgramStore, ConflictError
from module.scheduler.templates import node, edge, default_program, enhance_program
from module.scheduler.validation import validate
from tests.test_api import fixture
from tests.test_scheduler_program import context


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.store = ProgramStore(self.directory)

    def test_simultaneous_revision_only_one_writer_wins(self):
        revision = self.store.get('pilot')['revision']
        def write(index):
            try:
                self.store.update('pilot', revision, generation=index)
                return True
            except ConflictError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(1, sum(pool.map(write, range(4))))

    def test_observations_do_not_invalidate_program_revision(self):
        current = self.store.get('pilot')
        current = self.store.update('pilot', current['revision'], draft=current['draft'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda name: self.store.observe('pilot', name, 100, '2026-09-28 10:00:00', 'fixture'), ['Oil','Coin','YellowCoin','PurpleCoin']))
        self.assertEqual(4, len(self.store.observations('pilot')))
        self.assertEqual(current['revision'], self.store.get('pilot')['revision'])

    def test_backup_and_legacy_migration(self):
        legacy = self.store.directory / 'programs/pilot.json'
        legacy.parent.mkdir(parents=True)
        document = self.store.default()
        document.update(mode='takeover', active=document['draft'], generation=3)
        legacy.write_text(json.dumps(document), encoding='utf-8')
        self.assertEqual(3, self.store.get('pilot')['generation'])
        self.assertTrue(legacy.exists())
        self.assertTrue(list((Path(self.directory) / 'storage-backups').rglob('pilot.json')))
        self.store.observe('pilot','Oil',8000,'2026-09-28 10:00:00','fixture')
        self.store.save_persistent('pilot', {'variables': {'saved': 2}, 'records': {'quota': 1}, 'inFlight': 'Main'})
        target = Path(self.directory) / 'backup/scheduler/pilot.sqlite3'
        self.store.backup('pilot', target)
        restored = ProgramStore(target.parent.parent)
        self.assertEqual(self.store.get('pilot'), restored.get('pilot'))
        self.assertEqual(self.store.persistent('pilot'), restored.persistent('pilot'))
        self.assertEqual(8000, restored.observations('pilot')['Oil']['Value'])

    def test_daily_backup_includes_sqlite(self):
        from module.base.backup import backup_config, backup_database
        self.store.observe('pilot','Oil',100,'2026-09-28 10:00:00','fixture')
        backup = Path(self.directory) / 'backup'
        backup.mkdir()
        with patch('module.base.backup.CONFIG_DIR', Path(self.directory)):
            files = backup_database(backup) + backup_config(backup)
        self.assertTrue(any('azurpilot.db' == f['name'] for f in files))
        self.assertEqual(100, ProgramStore(backup).observations('pilot')['Oil']['Value'])

    def test_read_only_does_not_touch_database(self):
        self.store.observe('pilot','Oil',1,'2026-09-28 10:00:00','fixture')
        before = self.store.path('pilot').stat().st_mtime_ns
        self.store.get('pilot'); self.store.observations('pilot'); self.store.persistent('pilot')
        self.assertEqual(before, self.store.path('pilot').stat().st_mtime_ns)


class SchedulerApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.configs = ConfigService(fixture(self.directory))
        self.router = Router(self.configs, Mock())
        self.store = ProgramStore(self.configs.directory)

    def dispatch(self, method, **params):
        return self.router.dispatch(f'scheduler.program.{method}', {'instance':'testpilot', **params})

    def test_draft_apply_conflict_and_no_worker_creation(self):
        original = self.configs.path('testpilot').read_bytes()
        initial = self.dispatch('get')
        self.assertTrue(self.dispatch('validate', document=initial['draft'])['valid'])
        saved = self.dispatch('save', revision=initial['revision'], document=initial['draft'])
        self.assertEqual('native', saved['mode'])
        applied = self.dispatch('apply', revision=saved['revision'], mode='takeover')
        self.assertEqual('takeover', applied['mode'])
        with self.assertRaises(ApiError) as error:
            self.dispatch('save', revision=saved['revision'], document=saved['draft'])
        self.assertEqual('CONFLICT', error.exception.code)
        with patch('module.runtime.process_manager.ProcessManager._processes', {}):
            self.assertEqual('idle', self.dispatch('state')['state']['status'])
        self.router.runtime.manager.assert_not_called()
        self.assertEqual(original, self.configs.path('testpilot').read_bytes())

    def test_copy_export_import_delete_and_exclude_state(self):
        current = self.dispatch('get')
        saved = self.dispatch('save', revision=current['revision'], document=current['draft'])
        self.dispatch('apply', revision=saved['revision'], mode='takeover')
        self.store.save_persistent('testpilot', {'variables':{'private':123},'records':{'private':456}})
        self.store.observe('testpilot','Oil',8000,'2026-09-28 10:00:00','fixture')
        self.configs.create('copy', source='testpilot')
        self.assertEqual('takeover', self.store.get('copy')['mode'])
        self.assertEqual({}, self.store.persistent('copy'))
        export = self.configs.export('testpilot')
        self.assertEqual({'mode','draft','active'}, set(export['_schedulerProgram']))
        self.configs.save_import('shared', json.dumps(export))
        self.configs.create('imported', import_file='shared')
        self.assertNotIn('_schedulerProgram', self.configs.read('imported')[0])
        self.assertEqual('takeover', self.store.get('imported')['mode'])
        self.assertEqual({}, self.store.observations('imported'))
        self.configs.delete('imported', self.configs.read('imported')[1])
        self.assertFalse(self.store.exists('imported'))
        self.assertTrue(self.store.database.path.exists())
        self.assertTrue(list((self.configs.directory/'backup').rglob('imported.sqlite3')))

    def test_simulation_is_same_interpreter_and_no_writes(self):
        doc = ProgramDocument(entry='start', nodes=[node('start','entry'),node('run','execute')],edges=[edge('start','run')])
        self.store.save_persistent('testpilot', {'variables':{'private':4}})
        before = self.store.persistent('testpilot')
        result = self.dispatch('simulate', document=doc.model_dump(), context=context(), steps=5)
        expected = simulate(doc, context(), steps=5)
        self.assertEqual(expected['effects'], result['effects'])
        self.assertEqual(before, self.store.persistent('testpilot'))
        self.assertFalse(self.store.exists('testpilot'))

    def test_default_simulation_uses_configured_original_priority(self):
        data = json.loads(self.configs.path('testpilot').read_text(encoding='utf-8'))
        data['General']['YukikazeTaskManager']['TaskPriorityAdjustment'] = 'Main > Commission'
        self.configs.path('testpilot').write_text(json.dumps(data), encoding='utf-8')
        supplied = context(tasks=[{'name': 'Commission', 'enabled': True, 'nextRun': '2026-09-28 09:00:00'},
                                  {'name': 'Main', 'enabled': True, 'nextRun': '2026-09-28 09:00:00'}])
        result = self.dispatch('simulate', document=default_program().model_dump(), context=supplied, steps=10)
        self.assertEqual('Main', next(effect['task'] for effect in result['effects'] if effect['kind'] == 'execute'))

    def test_invalid_simulation_and_program_are_located(self):
        document = default_program().model_dump()
        document['nodes'][4]['params']['overrides'] = {'Emulator_Serial':'private'}
        invalid = self.dispatch('validate', document=document)
        self.assertFalse(invalid['valid'])
        self.assertTrue(any(d['node']=='run' for d in invalid['diagnostics']))
        with self.assertRaises(ApiError):
            self.dispatch('simulate', document=default_program().model_dump(), context={'tasks':1})


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.configs = ConfigService(fixture(self.directory))
        self.config = Mock(data=self.configs.read('testpilot')[0], pending_task=[], waiting_task=[], hoarding=__import__('datetime').timedelta(0))
        self.script = Mock(config_name='testpilot', config=self.config)
        self.runtime = SchedulerRuntime(self.script, self.configs.directory)

    def apply(self, doc, mode='takeover'):
        current = self.runtime.store.get('testpilot')
        self.runtime.store.update('testpilot',current['revision'],mode=mode,active=doc.model_dump(),draft=doc.model_dump(),generation=current['generation']+1)

    def test_takeover_executes_disabled_task_and_parameter_cleanup(self):
        doc = ProgramDocument(entry='start', nodes=[node('start','entry'),node('run','execute',overrides={'Campaign_Name':'1-1'})],edges=[edge('start','run')])
        self.config.data['Main']['Scheduler']['Enable']=False
        self.apply(doc)
        self.assertEqual('Main', self.runtime.next_task())
        self.assertEqual('1-1', self.config.Campaign_Name)
        self.runtime.request('Commission')
        self.assertEqual('Commission', self.runtime.requests[0]['task'])
        self.runtime.task_finished('Main', True)
        self.assertEqual({}, self.runtime.overlay)
        self.assertEqual('completed', self.runtime.engine.records['lastResult']['status'])

    def test_update_yields_only_at_checkpoint(self):
        doc = ProgramDocument(entry='start', nodes=[node('start','entry'),node('run','execute')],edges=[edge('start','run')])
        self.apply(doc); self.runtime.next_task()
        self.apply(doc, 'native')
        self.assertEqual('takeover', self.runtime.mode)
        self.assertTrue(self.runtime.should_yield(self.config))
        self.runtime.task_finished('Main', True)
        self.assertEqual('yielded', self.runtime.engine.records['lastResult']['status'])
        self.assertIsNone(self.runtime.next_task())
        self.assertEqual('native', self.runtime.mode)

    def test_restart_from_entry_reports_interruption(self):
        doc = ProgramDocument(entry='start', nodes=[node('start','entry'),node('run','execute')],edges=[edge('start','run')])
        self.apply(doc); self.runtime.next_task()
        restored = SchedulerRuntime(self.script,self.configs.directory)
        restored.load_program()
        self.assertEqual('start', restored.engine.frames[0].pc)
        self.assertEqual('interrupted', restored.engine.records['results']['Main']['status'])

    def test_refresh_group_throttle_and_recovery_channel(self):
        def refreshed(_):
            self.runtime.refresh_result=True
            return True
        self.script.run.side_effect=refreshed
        self.assertTrue(self.runtime.refresh(['Oil']))
        self.assertEqual(['Coin','Oil'], self.runtime.refresh_names)
        self.assertFalse(self.runtime.refresh(['Coin']))
        self.runtime.request('Restart')
        self.assertTrue(self.runtime.recovery_requested)
        self.assertEqual([], self.runtime.requests)


class ExtraEngineTests(unittest.TestCase):
    def test_port_families_are_symmetric_and_boolean_is_not_number(self):
        from module.scheduler.validation import compatible
        for left, right in (('number','duration'),('tasks','list'),('resource','object')):
            self.assertTrue(compatible(left,right))
            self.assertTrue(compatible(right,left))
        self.assertFalse(compatible('number','boolean'))
        self.assertFalse(compatible('duration','time'))

    def test_program_state_queue_is_bounded_and_run_id_isolated(self):
        import queue
        import threading
        from module.scheduler import state_channel
        from module.runtime.process_manager import ProcessManager
        output = queue.Queue(maxsize=2)
        with patch.object(state_channel,'_output',output), patch.object(state_channel,'_run_id','current'):
            for index in range(3):
                state_channel.publish({'node':str(index)})
        self.assertEqual(2,output.qsize())
        output.get_nowait()
        current = output.get_nowait()
        self.assertEqual('2',current['state']['node'])
        manager = ProcessManager.__new__(ProcessManager)
        manager.run_id, manager.program_state, manager._runtime_lock = 'current', None, threading.RLock()
        output.put_nowait({'runId':'old','state':{'node':'wrong'}})
        output.put_nowait(current)
        with patch.object(ProcessManager,'_is_process_alive',return_value=False):
            manager._thread_program_queue_handler(output,'current',None)
        self.assertEqual({'node':'2'},manager.program_state)
        output.put_nowait({'runId':'old','state':{'node':'wrong'}})
        manager._thread_program_queue_handler(output,'old',None)
        self.assertEqual({'node':'2'},manager.program_state)
        self.assertEqual(1,output.qsize())

    def test_pure_composites_do_not_share_cached_frames(self):
        doc = ProgramDocument(entry='start', nodes=[node('start','entry'),node('sum','math'),node('a','call',graph='identity', value=2),node('b','call',graph='identity', value=7),node('debug','debug')],
            edges=[edge('start','debug'),edge('a','sum','value','a',True),edge('b','sum','value','b',True),edge('sum','debug','value','value',True)],
            subgraphs=[SubgraphDefinition(id='identity',name='恒等',pure=True,entry='input',inputs=[{'name':'value','type':'number'}],outputs=[{'name':'value','type':'number'}],nodes=[node('input','input',name='value')])])
        self.assertTrue(validate(doc)['valid'])
        result=simulate(doc,context())
        self.assertTrue(any(t.get('value')==9 for t in result['state']['trace']))

    def test_variable_types_and_busy_composite_path(self):
        doc=ProgramDocument(entry='start',variables=[{'name':'n','type':'number','initial':'bad'}],nodes=[node('start','entry')])
        self.assertFalse(validate(doc)['valid'])
        doc=default_program()
        sub=SubgraphDefinition(id='skip',name='可能不等待',entry='entry',nodes=[node('entry','entry'),node('branch','branch'),node('wait','wait')],edges=[edge('entry','branch'),edge('branch','wait','yes')])
        doc.subgraphs.append(sub)
        doc.nodes[4]=node('run','call',graph='skip')
        doc.nodes=[n for n in doc.nodes if n.id!='wait']
        doc.edges=[e for e in doc.edges if e.source!='run' and e.target not in ('run','wait') and e.source!='wait']
        doc.edges.extend([edge('loop','run','body'),edge('run','repeat')])
        self.assertFalse(validate(doc)['valid'])

    def test_rotation_advances_when_task_is_dispatched(self):
        doc=default_program(); doc.nodes[3].type='call'; doc.nodes[3].params={'graph':'builtin.rotation'}
        doc.edges = [e for e in doc.edges if e.target != 'choose']
        doc.edges.append(edge('tasks','choose','value','items',True))
        result=simulate(doc,context(),steps=30)
        tasks=[e['task'] for e in result['effects'] if e['kind']=='execute']
        self.assertEqual(['Main','Research','Commission'],tasks[:3])

    def test_digit_empty_is_not_observation_and_zero_is_valid(self):
        from module.ocr.ocr import Digit
        ocr=Digit.__new__(Digit); ocr.SHOW_REVISE_WARNING=False
        self.assertEqual(0,ocr.after_process('')); self.assertFalse(ocr.last_valid)
        self.assertEqual(0,ocr.after_process('0')); self.assertTrue(ocr.last_valid)

    def test_stable_refresh_uses_visible_consecutive_frames(self):
        from module.scheduler.resources import stable_read
        ui=SimpleNamespace(loop=lambda: iter(range(4)))
        values=iter([None,0,0])
        self.assertEqual(0,stable_read(ui,lambda:True,lambda:next(values)))


if __name__ == '__main__':
    unittest.main()
