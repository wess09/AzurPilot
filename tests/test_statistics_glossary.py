"""统计页物品名、任务名对照表的单元测试。"""
import unittest

from module.statistics.glossary import build_glossary, report_texts


class StatisticsGlossaryTest(unittest.TestCase):
    def test_item_names_from_tables_and_storage_catalog(self):
        glossary = build_glossary(['钛合金', '通用部件T4', '特装型突破部件', '未扫描', None, 3])
        self.assertEqual(glossary['钛合金']['en-US'], 'Corrosion-Resistant Alloys')
        self.assertIn('en-US', glossary['通用部件T4'])
        self.assertIn('en-US', glossary['特装型突破部件'])
        # 固定文案由前端翻译，不进对照表；非字符串忽略。
        self.assertNotIn('未扫描', glossary)

    def test_joined_drop_list_is_split(self):
        glossary = build_glossary(['钛合金 x2、HBX炸药 x1'])
        self.assertEqual(set(glossary), {'钛合金', 'HBX炸药'})

    def test_task_names_follow_config_i18n(self):
        glossary = build_glossary(['深渊坐标'])
        self.assertEqual(set(glossary['深渊坐标']), {'en-US', 'ja-JP', 'zh-TW', 'zh-CN-neko'})

    def test_report_texts_cover_labels_tables_and_task_options(self):
        result = {
            'metrics': [{'label': 'a'}], 'series': [{'label': 'b'}],
            'tables': [{'columns': ['c'], 'rows': [['d', 1]]}], 'taskOptions': [{'label': 'e'}],
        }
        self.assertEqual(list(report_texts(result)), ['a', 'b', 'c', 'd', 1, 'e'])


if __name__ == '__main__':
    unittest.main()
