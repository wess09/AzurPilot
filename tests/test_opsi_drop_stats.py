"""大世界掉落统计：任务范围、开关语义与按窗口汇总。

背景：掉落统计原先只认短猫相接、且只有「上传」档才解析入库（2026-09-25 改）。
现在除侵蚀1练级外的所有大世界任务都会解析，且「保存」与「上传」都算，区别只在
要不要把截图落盘。展示金菜、SSR/UR研发图纸、指定研发材料、实验计划及突破部件，
其余物品照常入库、只是不展示。这里用真临时 SQLite 验证范围与汇总。
"""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from module.config.config import AzurLaneConfig, Function
from module.config.redirect_utils.utils import OPSI_RECORD_ARGS
from module.statistics import azurstats, opsi_drop_stats
from tests.opsi_test_support import install_store
from module.statistics import opsi_secure
from module.statistics.azurstats import AzurStats, is_opsi_drop_genre

DEVICE = 'test-device'
INSTANCE = 'test-instance'


def make_config(task, values=None):
    """造一个绑定了 `task` 的配置对象，DropRecord 取值由 `values` 指定。

    Args:
        task (str): 当前任务名，会成为 `config.task.command`。
        values (dict): DropRecord 组下要覆盖的取值，其余按 do_not 填。

    Returns:
        AzurLaneConfig: 只填了 DropRecord 与 Scheduler.Command 的配置对象。
    """
    record = {arg: 'do_not' for arg in OPSI_RECORD_ARGS}
    record.update(values or {})
    record['RetentionDays'] = 0
    record['SaveFolder'] = './screenshots'

    config = AzurLaneConfig.__new__(AzurLaneConfig)
    config.bound = {}
    config.modified = {}
    config.overridden = {}
    config.auto_update = False
    config.data = {
        'Alas': {'DropRecord': record, 'Scheduler': {'Command': 'Alas'}},
    }
    if task != 'Alas':
        config.data[task] = {'Scheduler': {'Command': task}}
    config.config_name = INSTANCE
    config.task = Function(config.data[task])
    config.bind(config.task)
    return config


class TestGenreScope(unittest.TestCase):
    """哪些分类算「要解析的大世界掉落」。"""

    def test_opsi_tasks_are_included(self):
        for genre in ('opsi_meowfficer_farming', 'opsi_daily', 'opsi_obscure',
                      'opsi_abyssal', 'opsi_stronghold', 'opsi_explore',
                      'opsi_month_boss', 'opsi_archive', 'opsi_cross_month'):
            with self.subTest(genre=genre):
                self.assertTrue(is_opsi_drop_genre(genre))

    def test_corrosion_one_is_excluded(self):
        """侵蚀1练级另有「大世界总结」页，掉落不入库。"""
        self.assertFalse(is_opsi_drop_genre('opsi_hazard1_leveling'))

    def test_other_genres_are_excluded(self):
        for genre in ('research', 'commission', 'meowfficer', '', None, 'opsi'):
            with self.subTest(genre=genre):
                self.assertFalse(is_opsi_drop_genre(genre))


class TestDropRecordSwitch(unittest.TestCase):
    """「保存」与「上传」都统计，只有「不记录」什么都不做。"""

    def test_save_and_upload_both_parse(self):
        stats = AzurStats(make_config('OpsiAbyssal', {'OpsiAbyssal': 'save'}))
        drop = stats.new(genre='opsi_abyssal', method='save')
        self.assertTrue(drop.save)
        self.assertTrue(drop.local)

        drop = stats.new(genre='opsi_abyssal', method='upload')
        self.assertFalse(drop.save)
        self.assertTrue(drop.local)

        drop = stats.new(genre='opsi_abyssal', method='save_and_upload')
        self.assertTrue(drop.save)
        self.assertTrue(drop.local)

    def test_do_not_records_nothing(self):
        drop = AzurStats(make_config('OpsiStronghold')).new(
            genre='opsi_stronghold', method='do_not')
        self.assertFalse(drop.save)
        self.assertFalse(drop.local)
        self.assertFalse(bool(drop))

    def test_corrosion_one_never_parses(self):
        """侵蚀1在任何档位都不入库；「保存」仍按原样落盘截图。"""
        stats = AzurStats(make_config('OpsiHazard1Leveling'))
        drop = stats.new(genre='opsi_hazard1_leveling', method='upload')
        self.assertFalse(drop.local)
        self.assertFalse(bool(drop))

        drop = stats.new(genre='opsi_hazard1_leveling', method='save')
        self.assertTrue(drop.save)
        self.assertFalse(drop.local)

    def test_research_path_unchanged(self):
        """科研走自己的解析链路（analyze），仍只在非「不记录」时统计。"""
        stats = AzurStats(make_config('Alas'))
        drop = stats.new(genre='research', method='upload')
        self.assertTrue(drop.analyze)
        self.assertFalse(drop.local)

        drop = stats.new(genre='research', method='do_not')
        self.assertFalse(drop.analyze)
        self.assertFalse(bool(drop))


class TestShowScope(unittest.TestCase):
    """统计范围与模板名称、游戏物品名称保持一致。"""

    def test_kind_of(self):
        for name in ('PlateGeneralT4', 'PlateGunT4', 'PlateTorpedoT4',
                     'PlateAntiAirT4', 'PlatePlaneT4'):
            with self.subTest(name=name):
                self.assertEqual(opsi_drop_stats.kind_of(name), opsi_drop_stats.KIND_PLATE)
        for name in ('GearDesignPlanGunT5', 'GearDesignPlanTorpedoT5',
                     'GearDesignPlanAntiAirT5', 'GearDesignPlanPlaneT5',
                     'GearDesignPlanGunT4', 'GearDesignPlanTorpedoT4',
                     'GearDesignPlanAntiAirT4', 'GearDesignPlanPlaneT4'):
            with self.subTest(name=name):
                self.assertEqual(opsi_drop_stats.kind_of(name), opsi_drop_stats.KIND_DESIGN)
        for name in ('Ultra_High_Purity_Metals', 'Military_Grade_Electronic_Components',
                     'HBX_Blend_Gunpowder', 'High_Durability_Elastomers',
                     'Superconductive_Metals', 'Corrosion_Resistant_Alloys'):
            with self.subTest(name=name):
                self.assertEqual(opsi_drop_stats.kind_of(name), opsi_drop_stats.KIND_MATERIAL)
        for name in ('OrdnanceTestingReportT4', 'OrdnanceTestingReportT5'):
            self.assertEqual(opsi_drop_stats.kind_of(name), opsi_drop_stats.KIND_REPORT)
        self.assertEqual(opsi_drop_stats.kind_of('PrototypeGearPartsT5'), opsi_drop_stats.KIND_PROTOTYPE)

    def test_scope_excludes_other_items(self):
        """仍排除低级物品及本次未指定的材料、部件和货币。"""
        for name in ('PlateGeneralT3', 'GearDesignPlanGunT3', 'OrdnanceTestingReportT3',
                     'PrototypeGearPartsT4', 'SpecialGearPrototype', 'Specially_Smelted_Metals',
                     'CoordinateAbyssal', 'CatT3', 'OperationCoin', 'Coins'):
            with self.subTest(name=name):
                self.assertFalse(opsi_drop_stats.should_show(name))

    def test_item_info_falls_back_to_template_name(self):
        self.assertEqual(opsi_drop_stats.item_info('PlateGeneralT4')['zh'], '通用部件T4')
        self.assertEqual(opsi_drop_stats.item_info('UnknownThing')['zh'], 'UnknownThing')

    def test_legacy_popup_report_name_uses_its_actual_rarity(self):
        self.assertTrue(opsi_drop_stats.should_show('OrdnanceTestingReportT2'))
        self.assertEqual(opsi_drop_stats.item_info('OrdnanceTestingReportT2')['zh'], '机密实验计划')

    def test_requested_items_have_names_rarities_and_icons(self):
        expected = {
            'GearDesignPlanGunT4': ('舰炮研发图纸SSR型', 4),
            'GearDesignPlanTorpedoT4': ('鱼雷研发图纸SSR型', 4),
            'GearDesignPlanAntiAirT4': ('防空炮研发图纸SSR型', 4),
            'GearDesignPlanPlaneT4': ('舰载机研发图纸SSR型', 4),
            'Ultra_High_Purity_Metals': ('特种钢材', 4),
            'Military_Grade_Electronic_Components': ('军工级电子元件', 4),
            'HBX_Blend_Gunpowder': ('HBX炸药', 4),
            'High_Durability_Elastomers': ('氟橡胶', 4),
            'Superconductive_Metals': ('超导铜', 4),
            'Corrosion_Resistant_Alloys': ('钛合金', 4),
            'OrdnanceTestingReportT4': ('机密实验计划', 4),
            'OrdnanceTestingReportT5': ('绝密实验计划', 5),
            'PrototypeGearPartsT5': ('特装型突破部件', 5),
        }
        for name, (zh, rarity) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, opsi_drop_stats.SHOW_ITEMS)
                info = opsi_drop_stats.item_info(name)
                self.assertEqual((info['zh'], info['rarity']), (zh, rarity))
                self.assertTrue(info['en'])
                self.assertTrue(Path('assets/stats/opsi_reward_items', f'{name}.png').is_file())

    def test_zone_text(self):
        self.assertEqual(
            opsi_drop_stats.zone_text('STRONGHOLD', 'East Continental Shelf E', 3),
            '要塞海域 East Continental Shelf E（侵蚀3）')
        self.assertEqual(opsi_drop_stats.zone_text('UNKNOWN', '', 0), '未知海域')


class TestCollect(unittest.TestCase):
    """按时间窗口汇总掉落明细（真临时 SQLite）。"""

    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        install_store(self, self.directory)
        self.enterContext(patch.object(AzurStats, 'LOCAL_DB', str(Path(self.directory) / 'config' / 'azurstats_local.db')))
        self.enterContext(patch.object(azurstats, 'get_device_id', return_value=DEVICE))
        self.now = datetime.now().replace(microsecond=0)
        self.patch = patch.object(opsi_drop_stats, '_task_names', None)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def insert(self, genre, items, moment, imgid, zone_type='DANGEROUS', zone='Mediterranee A',
               hazard=5, device=DEVICE, instance=INSTANCE):
        rows = [
            {
                'imgid': imgid, 'server': 'cn', 'zone': zone, 'zone_type': zone_type,
                'zone_id': 1, 'hazard_level': hazard, 'item': name, 'amount': amount,
                'tag': None, 'device_id': device, 'instance': instance, 'genre': genre,
                'combat_count': 2, 'created_at': int(moment.timestamp()),
            }
            for name, amount in items.items()
        ]
        AzurStats._insert_local_opsi_items(rows)

    def collect(self, days=7, **kwargs):
        return opsi_drop_stats.collect(
            INSTANCE, self.now - timedelta(days=days), self.now + timedelta(seconds=1), **kwargs)

    def test_aggregates_only_scope_items(self):
        self.insert('opsi_stronghold',
                    {'PlateGeneralT4': 4, 'PlateGunT4': 1, 'OperationCoin': 3596},
                    self.now - timedelta(hours=1), 'a')
        self.insert('opsi_meowfficer_farming',
                    {'GearDesignPlanPlaneT5': 1, 'Coins': 200},
                    self.now - timedelta(hours=2), 'b')

        summary = self.collect()
        by_name = {item['name']: item for item in summary['items']}
        self.assertEqual(by_name['PlateGeneralT4']['amount'], 4)
        self.assertEqual(by_name['GearDesignPlanPlaneT5']['amount'], 1)
        # 口径外的物品（黄币、物资）入库了，但既不出现在明细里，也不计入总数
        self.assertNotIn('OperationCoin', by_name)
        self.assertNotIn('Coins', by_name)
        self.assertEqual(summary['total'], 6)
        self.assertEqual(summary['record_count'], 2)

    def test_existing_records_include_new_items_without_database_migration(self):
        """已入库的指定物品立即纳入汇总，同包多格累加但只计一次掉落记录。"""
        items = {
            'GearDesignPlanGunT4': 2, 'GearDesignPlanTorpedoT4': 3,
            'GearDesignPlanAntiAirT4': 1, 'GearDesignPlanPlaneT4': 4,
            'Ultra_High_Purity_Metals': 5, 'Military_Grade_Electronic_Components': 6,
            'HBX_Blend_Gunpowder': 7, 'High_Durability_Elastomers': 8,
            'Superconductive_Metals': 9, 'Corrosion_Resistant_Alloys': 10,
            'OrdnanceTestingReportT4': 2, 'OrdnanceTestingReportT5': 1,
            'PrototypeGearPartsT5': 1,
        }
        self.insert('opsi_month_boss', {**items, 'OperationCoin': 500},
                    self.now - timedelta(hours=1), 'new-items')
        self.insert('opsi_month_boss', {'PrototypeGearPartsT5': 2},
                    self.now - timedelta(hours=1), 'new-items')
        summary = self.collect(task='opsi_month_boss')
        by_name = {item['name']: item for item in summary['items']}
        self.assertEqual(summary['total'], sum(items.values()) + 2)
        self.assertEqual(summary['record_count'], 1)
        for name, amount in items.items():
            with self.subTest(name=name):
                expected = amount + 2 if name == 'PrototypeGearPartsT5' else amount
                self.assertEqual(by_name[name]['amount'], expected)
                self.assertEqual(by_name[name]['count'], 1)
                self.assertEqual(by_name[name]['avg'], expected)
                self.assertIn(f"{by_name[name]['zh']} x{expected}", summary['records'][0][3])
        self.assertNotIn('作战补给凭证', summary['records'][0][3])
        self.assertEqual(self.collect(days=0)['record_count'], 0)
        self.assertEqual(self.collect(task='opsi_daily')['total'], 0)

    def test_legacy_gold_report_merges_with_current_name(self):
        self.insert('opsi_daily', {'OrdnanceTestingReportT2': 2},
                    self.now - timedelta(hours=1), 'legacy-report')
        self.insert('opsi_daily', {'OrdnanceTestingReportT4': 1},
                    self.now - timedelta(hours=2), 'current-report')
        summary = self.collect()
        by_name = {item['name']: item for item in summary['items']}
        self.assertEqual(by_name['OrdnanceTestingReportT4']['amount'], 3)
        self.assertEqual(by_name['OrdnanceTestingReportT4']['count'], 2)
        self.assertNotIn('OrdnanceTestingReportT2', by_name)
        self.assertEqual(summary['total'], 3)

    def test_report_keeps_new_item_metrics_icons_and_records(self):
        """验证真正的统计 API 结果，避免只有 mock 页面增加了物品。"""
        from module.api.statistics_service import report

        self.insert('opsi_daily', {'Ultra_High_Purity_Metals': 2, 'OrdnanceTestingReportT5': 1,
                                   'PrototypeGearPartsT5': 1}, self.now - timedelta(minutes=1), 'api-items')
        with patch.object(AzurStats, 'load_meowofficer_farming', return_value=[]):
            result = report(SimpleNamespace(path=lambda instance: None), INSTANCE, 'loot',
                            self.now.strftime('%Y-%m'), 7, 'month')
        metrics = {item['label']: item for item in result['metrics']}
        self.assertEqual(metrics['特种钢材']['value'], 2)
        self.assertEqual(metrics['绝密实验计划']['icon'], 'opsi:OrdnanceTestingReportT5')
        self.assertEqual(metrics['特装型突破部件']['value'], 1)
        self.assertEqual(metrics['选定月份总计']['value'], 4)
        detail = next(table for table in result['tables'] if table['title'] == '大世界掉落明细')
        self.assertIn(['opsi:OrdnanceTestingReportT5', '绝密实验计划', '彩', 1, 1, 1.0], detail['rows'])
        self.assertIn('六种金色研发材料', detail['note'])
        records = next(table for table in result['tables'] if table['title'] == '掉落记录')
        self.assertIn('特装型突破部件 x1', records['rows'][0][3])

    def test_corrosion_one_rows_are_ignored(self):
        self.insert('opsi_hazard1_leveling', {'OperationCoin': 100},
                    self.now - timedelta(hours=1), 'c')
        summary = self.collect()
        self.assertEqual(summary['record_count'], 0)
        self.assertEqual(summary['total'], 0)

    def test_other_instances_and_devices_are_isolated(self):
        self.insert('opsi_stronghold', {'PlateGunT4': 2}, self.now - timedelta(hours=1),
                    'd', instance='other-instance')
        self.insert('opsi_stronghold', {'PlateGunT4': 3}, self.now - timedelta(hours=1),
                    'e', device='other-device')
        self.assertEqual(self.collect()['total'], 0)

    def test_time_window_is_respected(self):
        self.insert('opsi_daily', {'PlatePlaneT4': 1}, self.now - timedelta(days=3), 'f')
        self.assertEqual(self.collect(days=1)['total'], 0)
        self.assertEqual(self.collect(days=7)['total'], 1)

    def test_task_filter_and_options(self):
        self.insert('opsi_stronghold', {'PlateGeneralT4': 4}, self.now - timedelta(hours=1), 'g')
        self.insert('opsi_meowfficer_farming', {'PlateGunT4': 1}, self.now - timedelta(hours=1), 'h')

        summary = self.collect(task='opsi_stronghold')
        self.assertEqual(summary['total'], 4)
        self.assertEqual([record[1] for record in summary['records']], ['塞壬要塞'])

        # 下拉选项是全部大世界任务（含窗口内没有记录的），并带上窗口内的记录数
        options = {item['key']: item for item in self.collect()['tasks']}
        self.assertEqual(options['opsi_stronghold']['label'], '塞壬要塞')
        self.assertEqual(options['opsi_stronghold']['count'], 1)
        self.assertEqual(options['opsi_daily']['count'], 0)
        self.assertNotIn('opsi_hazard1_leveling', options)

    def test_records_only_include_scope_items(self):
        self.insert('opsi_daily', {'OperationCoin': 500}, self.now - timedelta(hours=1), 'i')
        self.insert('opsi_daily', {'PlateAntiAirT4': 1, 'OperationCoin': 500},
                    self.now - timedelta(hours=2), 'j')

        summary = self.collect()
        self.assertEqual(len(summary['records']), 1)
        # 时间倒序；只列口径内的物品
        self.assertEqual(summary['records'][0][3], '防空炮部件T4 x1')

    def test_filter_keeps_other_task_options_and_counts(self):
        self.insert('opsi_stronghold', {'PlateGeneralT4': 4}, self.now - timedelta(hours=1), 'filter-a')
        self.insert('opsi_month_boss', {'GearDesignPlanT5': 1}, self.now - timedelta(hours=2), 'filter-b')
        summary = self.collect(task='opsi_stronghold')
        self.assertEqual(summary['total'], 4)
        self.assertEqual(summary['record_count'], 1)
        options = {item['key']: item['count'] for item in summary['tasks']}
        self.assertEqual(options['opsi_stronghold'], 1)
        self.assertEqual(options['opsi_month_boss'], 1)

    def test_shared_tasks_and_generic_design_plan_are_always_visible(self):
        summary = self.collect()
        options = {item['key'] for item in summary['tasks']}
        self.assertTrue({'opsi_month_boss', 'opsi_archive', 'opsi_cross_month'} <= options)
        self.assertIn('GearDesignPlanT5', {item['name'] for item in summary['items']})

    def test_unknown_month_boss_zone_uses_known_task_type(self):
        self.insert('opsi_month_boss', {'GearDesignPlanT5': 1}, self.now - timedelta(hours=1), 'boss')
        with closing(sqlite3.connect(AzurStats._database().path)) as connection, opsi_secure.immediate_transaction(connection):
            connection.row_factory = sqlite3.Row
            connection.execute("UPDATE opsi_items SET zone='',zone_type='UNKNOWN',hazard_level=0 WHERE imgid='boss'")
        summary = self.collect()
        self.assertEqual(summary['records'][0][2], '月度Boss海域')
        self.assertEqual(summary['total'], 1)

    def test_task_label_falls_back_to_genre(self):
        self.assertEqual(opsi_drop_stats.task_label('opsi_month_boss'), '月度Boss')
        self.assertEqual(opsi_drop_stats.task_label('opsi_unknown_task'), 'opsi_unknown_task')


class TestSchema(unittest.TestCase):
    """明细库的查询直接由那套常量生成，不应在 SQL 里再抄一份任务范围。"""

    def test_load_query_excludes_corrosion_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            install_store(self, directory)
            self.enterContext(patch.object(AzurStats, 'LOCAL_DB', str(Path(directory) / 'config' / 'azurstats_local.db')))
            with patch.object(azurstats, 'get_device_id', return_value=DEVICE):
                AzurStats._ensure_local_db()
                AzurStats._insert_local_opsi_items([
                    {'imgid': 'x', 'server': 'cn', 'zone': None, 'zone_type': None,
                     'zone_id': None, 'hazard_level': 1, 'item': 'OperationCoin', 'amount': 1,
                     'tag': None, 'device_id': DEVICE, 'instance': INSTANCE,
                     'genre': genre, 'combat_count': 0, 'created_at': 1}
                    for genre in ('opsi_abyssal', 'opsi_hazard1_leveling', 'research')
                ])
                rows = AzurStats.load_opsi_drop_rows(INSTANCE, device_id=DEVICE)
            self.assertEqual([row['genre'] for row in rows], ['opsi_abyssal'])

    def test_database_rows_survive_a_reopen(self):
        """明细写入后能被独立连接读到（提交不是靠连接关闭时的隐式提交）。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            install_store(self, directory)
            self.enterContext(patch.object(AzurStats, 'LOCAL_DB', str(Path(directory) / 'config' / 'azurstats_local.db')))
            AzurStats._ensure_local_db()
            AzurStats._insert_local_opsi_items([
                {'imgid': 'y', 'server': 'cn', 'zone': None, 'zone_type': None,
                 'zone_id': None, 'hazard_level': 0, 'item': 'PlateGunT4', 'amount': 2,
                 'tag': None, 'device_id': DEVICE, 'instance': INSTANCE,
                 'genre': 'opsi_abyssal', 'combat_count': 0, 'created_at': 1}
            ])
            with closing(sqlite3.connect(AzurStats._database().path)) as conn:
                count = conn.execute('SELECT COUNT(*) FROM opsi_items').fetchone()[0]
            self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
