"""使用虚拟任务、时钟与临时目录验证卡片调度，不接触游戏设备。"""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from module.scheduler.engine import Engine, simulate
from module.scheduler.models import CardNode, ProgramDocument, SubgraphDefinition
from module.scheduler.store import ConflictError, ProgramStore
from module.scheduler.templates import default_program, enhance_program, node, edge
from module.scheduler.validation import validate


def context(**extra):
    return {'now': '2026-09-28 10:00:00', 'tasks': [
        {'name': 'Main', 'enabled': True, 'nextRun': '2026-09-28 09:00:00'},
        {'name': 'Research', 'enabled': False, 'nextRun': '2026-09-28 11:00:00'},
        {'name': 'Commission', 'enabled': True, 'nextRun': '2026-09-28 09:00:00'}], **extra}


class TestProgramEngine(unittest.TestCase):
    def test_default_priority_and_wait_cycle(self):
        doc = default_program()
        self.assertTrue(validate(doc)['valid'])
        result = simulate(doc, context(), steps=12)
        self.assertEqual('Commission', next(e['task'] for e in result['effects'] if e['kind'] == 'execute'))
        self.assertFalse(any(e['kind'] == 'wait' for e in result['effects']))
        idle = context(tasks=[{'name':'Main','enabled':True,'nextRun':'2026-09-28 11:00:00'}])
        waiting = simulate(doc, idle, steps=4)['effects'][-1]
        self.assertEqual('wait', waiting['kind'])
        self.assertEqual('2026-09-28 11:00:00', waiting['deadline'])

    def test_priority_ties_unlisted_and_scores(self):
        doc = default_program()
        doc.nodes[3].type='call'; doc.nodes[3].params={'graph':'builtin.priority'}
        doc.edges = [e for e in doc.edges if e.target != 'choose']
        doc.edges.append(edge('tasks','choose','value','items',True))
        priority = doc.subgraphs[0].nodes[1]
        priority.params['order'] = ['Research']
        result = simulate(doc, context(), steps=4)
        self.assertEqual('Research', next(e['task'] for e in result['effects'] if e['kind']=='execute'))
        priority.params['order'] = []
        self.assertEqual('Main', next(e['task'] for e in simulate(doc, context(), steps=4)['effects'] if e['kind']=='execute'))

    def test_unknown_resource_uses_unavailable_branch(self):
        doc = ProgramDocument(entry='start', nodes=[node('start','entry'), node('oil','resource'),
            node('check','compare',b=1000), node('branch','branch'), node('wait','wait',seconds=300)], edges=[
            edge('start','branch'), edge('oil','check','value','a',True), edge('check','branch','value','condition',True),
            edge('branch','wait','unavailable')])
        result = simulate(doc, context(), steps=10)
        self.assertEqual(1, sum(e['kind']=='refresh' for e in result['effects']))
        self.assertTrue(any(e['kind']=='wait' for e in result['effects']))

    def test_fresh_resource_and_cross_midnight(self):
        doc = ProgramDocument(entry='clock', nodes=[node('clock','time_window',start='22:00',end='06:00')])
        engine = Engine(doc); engine.context = context(now='2026-09-28 23:00:00')
        self.assertTrue(engine.evaluate(engine.frames[0],'clock'))
        doc.nodes[0] = node('oil','resource',autoRefresh=False)
        doc.entry = 'oil'
        engine = Engine(doc); engine.context = context(resources={'Oil':{'value':8000,'observedAt':'2026-09-28 09:59:00','status':'fresh'}})
        self.assertEqual(8000, engine.evaluate(engine.frames[0],'oil'))

    def test_continue_guard_is_pure_and_stale_yields(self):
        engine = Engine(default_program())
        fresh = context(resources={'Oil':{'value':4000,'observedAt':'2026-09-28 09:59:00','status':'fresh'}})
        self.assertTrue(engine.guard('builtin.oil.guard', fresh))
        fresh['resources']['Oil']['observedAt'] = '2026-09-28 08:00:00'
        self.assertFalse(engine.guard('builtin.oil.guard', fresh))

    def test_restart_only_preserves_declared_variables_and_records(self):
        doc = ProgramDocument(entry='entry', nodes=[node('entry','entry'),node('set','set_variable',name='saved',value=5)],
            edges=[edge('entry','set')], variables=[{'name':'saved','initial':0,'persistent':True}, {'name':'temporary','initial':0}])
        engine = Engine(doc); engine.advance(context()); engine.variables['temporary']=8
        restored = Engine(doc,engine.persistent())
        self.assertEqual({'saved':5,'temporary':0},restored.variables)
        self.assertEqual('entry',restored.frames[0].pc)

    def test_task_result_branches_and_loop_count(self):
        doc = default_program(); doc.nodes[1].params['count']=2
        result = simulate(doc,context(),outcomes=['yielded','recoverable'],steps=40)
        self.assertEqual(2,sum(e['kind']=='execute' for e in result['effects']))
        self.assertEqual('ended',result['state']['status'])

    def test_invalid_ports_cycles_recursive_calls_and_busy_loop(self):
        doc = default_program(); doc.edges.append(edge('run','start','completed'))
        self.assertFalse(validate(doc)['valid'])
        doc = default_program(); doc.nodes = [n for n in doc.nodes if n.id not in ('run','wait')]
        doc.edges = [edge('start','loop'),edge('loop','repeat','body')]
        self.assertFalse(validate(doc)['valid'])
        doc = default_program(); doc.subgraphs[0].nodes.append(node('recurse','call',graph='builtin.priority'))
        self.assertFalse(validate(doc)['valid'])
        doc = default_program(); doc.edges.append(edge('tasks','run','value','task',True))
        self.assertFalse(validate(doc)['valid'])

    def test_divide_by_zero_faults_with_card_position(self):
        doc = ProgramDocument(entry='start',nodes=[node('start','entry'),node('math','math',operator='/',b=0),node('branch','branch')],edges=[
            edge('start','branch'),edge('math','branch','value','condition',True)])
        result = simulate(doc,context(),steps=5)
        self.assertEqual('error',result['state']['status'])

    def test_simulation_does_not_mutate_inputs(self):
        ctx=context(); original=copy.deepcopy(ctx)
        simulate(default_program(),ctx,steps=30)
        self.assertEqual(original,ctx)

    def test_card_labels_comments_and_backward_compatibility(self):
        doc = default_program()
        # 原名优先：默认方案中的说明存放在 comment 中，卡片 label 保持为空
        enabled_node = next(n for n in doc.nodes if n.id == 'enabled')
        self.assertEqual('', enabled_node.label)
        self.assertEqual('只保留已启用任务', enabled_node.comment)
        # 反序列化兼容：旧版没有 comment 字段的节点自动填空字符串
        legacy_node = CardNode.model_validate({'id': 'legacy', 'type': 'filter', 'params': {}})
        self.assertEqual('', legacy_node.comment)
        self.assertEqual('', legacy_node.label)
        # 自定义别名与独立注释共存
        custom_node = CardNode.model_validate({'id': 'custom', 'type': 'execute', 'label': '日常出击', 'comment': '执行日常主线出击'})
        self.assertEqual('日常出击', custom_node.label)
        self.assertEqual('执行日常主线出击', custom_node.comment)
        # 注释长度上限校验
        with self.assertRaises(Exception):
            CardNode.model_validate({'id': 'long', 'type': 'execute', 'comment': 'x' * 2001})


class TestProgramStore(unittest.TestCase):
    def setUp(self):
        self.directory=self.enterContext(tempfile.TemporaryDirectory())
        self.store=ProgramStore(self.directory)

    def test_revision_drafts_and_activation(self):
        first=self.store.get('testpilot')
        self.assertEqual('native',first['mode'])
        self.assertFalse(self.store.path('testpilot').exists())
        second=self.store.update('testpilot',first['revision'],draft=enhance_program().model_dump())
        self.assertEqual('native',second['mode'])
        with self.assertRaises(ConflictError):
            self.store.update('testpilot',first['revision'],mode='takeover')

    def test_observation_same_value_refreshes_time(self):
        self.store.observe('testpilot','Oil',8000,'2026-09-28 10:00:00','test')
        self.store.observe('testpilot','Oil',8000,'2026-09-28 10:01:00','test')
        self.assertEqual('2026-09-28 10:01:00',self.store.observations('testpilot')['Oil']['observedAt'])

    def test_copy_excludes_live_state_and_archive(self):
        current=self.store.get('testpilot')
        self.store.update('testpilot',current['revision'],mode='takeover',active=current['draft'])
        self.store.save_persistent('testpilot',{'variables':{'secret':123}})
        self.store.copy('testpilot','other')
        self.assertEqual({},self.store.persistent('other'))
        backup=Path(self.directory)/'backup'
        self.store.archive('testpilot',backup)
        self.assertTrue((backup/'business/testpilot.sqlite3').exists())
        self.assertFalse(self.store.exists('testpilot'))
        self.assertEqual({}, self.store.persistent('testpilot'))
        self.assertTrue(self.store.path('other').exists())

    def test_path_traversal_rejected(self):
        with self.assertRaises(Exception):
            self.store.get('../outside')

    def test_store_persists_card_label_and_comment(self):
        doc = default_program()
        loop_node = next(n for n in doc.nodes if n.id == 'loop')
        loop_node.label = '主循环'
        loop_node.comment = '每轮重新评估所有任务与资源'
        revision = self.store.get('testpilot')['revision']
        updated = self.store.update('testpilot', revision, draft=doc.model_dump())
        reloaded = ProgramDocument.model_validate(updated['draft'])
        reloaded_loop = next(n for n in reloaded.nodes if n.id == 'loop')
        self.assertEqual('主循环', reloaded_loop.label)
        self.assertEqual('每轮重新评估所有任务与资源', reloaded_loop.comment)


class TestProgramIntegration(unittest.TestCase):
    def test_takeover_business_requests_never_enable_tasks(self):
        from module.config.config import AzurLaneConfig
        config=AzurLaneConfig.__new__(AzurLaneConfig)
        config.bound={}; config.data={}
        runtime=Mock(mode='takeover'); runtime.request.return_value=True
        config._scheduler_runtime=runtime
        self.assertTrue(config.task_call('Commission'))
        runtime.request.assert_called_once_with('Commission')
        self.assertEqual({},config.data)

    def test_task_switch_uses_program_and_preserves_stop_event(self):
        from module.config.config import AzurLaneConfig
        config=AzurLaneConfig.__new__(AzurLaneConfig); config.bound={}; config.stop_event=None
        runtime=Mock(mode='takeover'); runtime.should_yield.return_value=True; config._scheduler_runtime=runtime
        self.assertTrue(config.task_switched())
        runtime.should_yield.assert_called_once_with(config)
        config.stop_event=Mock(); config.stop_event.is_set.return_value=True
        self.assertTrue(config.task_switched())

    def test_overlay_survives_binding_and_does_not_save(self):
        from module.config.config import AzurLaneConfig
        config=AzurLaneConfig.__new__(AzurLaneConfig)
        config.bound={}; config.overridden={}; config.modified={}; config.auto_update=False
        config.data={'Main':{'Campaign':{'Name':'12-4'},'StopCondition':{'RunCount':10}}}
        config._scheduler_overrides={'Campaign_Name':'1-1','StopCondition_RunCount':2}
        config.bind('Main'); self.assertEqual('1-1',config.Campaign_Name)
        config.StopCondition_RunCount=1
        config.cross_set_many({'Main.Campaign.Name':'2-1'})
        self.assertEqual({},config.modified)
        config.bind('Main'); self.assertEqual(1,config.StopCondition_RunCount)
        config._scheduler_overrides={}; config.bind('Main')
        self.assertEqual('12-4',config.Campaign_Name)
        self.assertEqual(10,config.StopCondition_RunCount)


if __name__=='__main__':
    unittest.main()
