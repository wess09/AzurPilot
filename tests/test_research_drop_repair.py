"""科研掉落的数据订正：模板改名后按 imgid 重放原截图。

库里存的是**模板文件名**，显示时再拿名称表翻译，模板一改名老记录就会张冠李戴。
名字级的历史映射修不了这种错（旧名 `Prototype_Triple_381mm_AA_Gun_T0` 一条就同时
盖住了两件不同的装备），只能按 imgid 覆盖 items。这里锁住这条契约：只动 items、
不动期数与项目代号（期数来自角标识别，重解析读不出角标时是 0，覆盖会毁掉数据）、
记录在哪个分区都能找到。
"""

import sqlite3
import tempfile
import unittest
from contextlib import nullcontext
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from module.statistics import cl1_database as database
from tests.opsi_test_support import install_store
from dev_tools.research_drop_repair import load_instance_entries


class TestResearchDropRepair(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        install_store(self, directory.name)
        self.path = Path(directory.name) / 'config' / 'cl1_data.db'
        with nullcontext():
            self.db = database.Cl1Database(self.path)

    def add(self, imgid, items, stamp=datetime(2026, 9, 24, 16, 22), instance='alas',
            series=9, project='Q-268-MI'):
        return self.db.add_research_drop(instance, project, series, items, imgid=imgid, ts=stamp)

    def entry(self, imgid, year=2026, month=9, instance='alas'):
        for entry in self.db.get_research_drop(instance, year, month):
            if entry.get('imgid') == imgid:
                return entry
        return None

    def test_replaces_items_but_keeps_series_and_project(self):
        self.add('a.png', {'Prototype_Tenrai_T0': 1, 'Coins': 243})
        updated = self.db.update_research_drop_items(
            'alas', 'a.png', {'Prototype_Carrier_Based_Ta_152_C_1_R14_T0': 1, 'Coins': 243})

        self.assertEqual(updated['items'], {'Prototype_Carrier_Based_Ta_152_C_1_R14_T0': 1, 'Coins': 243})
        entry = self.entry('a.png')
        self.assertEqual(entry['items'], updated['items'])
        # 期数与项目代号来自角标识别，与模板名无关，不能被重解析结果带着走
        self.assertEqual(entry['series'], 9)
        self.assertEqual(entry['project'], 'Q-268-MI')
        self.assertEqual(entry['ts'], '2026-09-24T16:22:00')

    def test_finds_entry_in_another_month_partition(self):
        self.add('b.png', {'Prototype_Triple_381mm_AA_Gun_T0': 2},
                 stamp=datetime(2026, 7, 5, 8, 0))
        updated = self.db.update_research_drop_items(
            'alas', 'b.png', {'Prototype_Triple_419mm_Mk_I_Main_Gun_Mount_T0': 1})

        self.assertIsNotNone(updated)
        self.assertEqual(self.entry('b.png', month=7)['items'],
                         {'Prototype_Triple_419mm_Mk_I_Main_Gun_Mount_T0': 1})

    def test_unknown_imgid_is_left_alone(self):
        self.add('c.png', {'Coins': 10})
        self.assertIsNone(self.db.update_research_drop_items('alas', 'nope.png', {'Coins': 1}))
        self.assertEqual(self.entry('c.png')['items'], {'Coins': 10})

    def test_empty_items_do_not_wipe_a_record(self):
        """解析不出掉落物时不能把已有记录清空——宁可留着旧名字。"""
        self.add('d.png', {'Coins': 10})
        self.assertIsNone(self.db.update_research_drop_items('alas', 'd.png', {}))
        self.assertIsNone(self.db.update_research_drop_items('alas', 'd.png', {'Coins': 0}))
        self.assertEqual(self.entry('d.png')['items'], {'Coins': 10})

    def test_other_instances_untouched(self):
        self.add('e.png', {'Coins': 10}, instance='alas')
        self.add('e.png', {'Coins': 20}, instance='代肝')
        self.db.update_research_drop_items('alas', 'e.png', {'Coins': 99})

        self.assertEqual(self.entry('e.png')['items'], {'Coins': 99})
        self.assertEqual(self.entry('e.png', instance='代肝')['items'], {'Coins': 20})

    def test_load_instance_entries_indexes_by_imgid(self):
        self.add('f.png', {'Coins': 10}, stamp=datetime(2026, 7, 5, 8, 0))
        self.add('g.png', {'Coins': 20})
        self.add('h.png', {'Coins': 30}, instance='代肝')

        entries = load_instance_entries(self.db, 'alas')
        self.assertEqual(sorted(entries), ['f.png', 'g.png'])
        self.assertEqual(entries['f.png'][0], '2026-07')


if __name__ == '__main__':
    unittest.main()
