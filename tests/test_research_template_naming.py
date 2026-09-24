"""科研模板名与 Lua 名的词元归一。

仓库里的一批老模板名与游戏 Lua 的英文名只差词序、大小写或多一个 `Mount`，按字符串
永远对不上，于是这些物品在名称表里没有中文名、也拿不到稀有度——金装图纸在「金装统计」
里就是隐形的（实测 2026-09-24：海兹梅耶 T0 一次导入掉 19 个，视图里一个都看不见）。

`name_tokens(loose=True)` 负责把这类差异吃掉。它放宽的只有三类：词序、大小写、
通用词 `Mount` 与 Reppuu/Reppu 这处拼写差异——放松过头会把 40mm Bofors Type 5
认成 Hazemeyer，所以这里既锁「该对上的对上」，也锁「不该对上的别对上」。
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import Mock


def load_tool():
    """仅导入待测实现，日志模块用替身，避免初始化用户配置与日志目录。

    这里手工换掉 `sys.modules` 里的一项再还原，而不是用 ``patch.dict(sys.modules, ...)``：
    后者退出时会清空并还原整个 sys.modules 快照，把本次导入期间新进来的模块（numpy 的
    C 扩展等）一起抹掉，同一进程里再 ``import numpy`` 就会报
    ``cannot load module more than once per process``，把后面的测试模块连带弄挂。
    """
    path = Path(__file__).resolve().parents[1] / 'dev_tools/research_template_extract.py'
    spec = importlib.util.spec_from_file_location('_research_extract_test', path)
    module = importlib.util.module_from_spec(spec)
    stub = ModuleType('module.logger')
    for name in ('logger', 'rule', 'hr', 'attr', 'attr_align'):
        setattr(stub, name, Mock())
    previous = sys.modules.get('module.logger')
    sys.modules['module.logger'] = stub
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop('module.logger', None)
        else:
            sys.modules['module.logger'] = previous
    return module


TOOL = load_tool()


class LooseTokenMatchTest(unittest.TestCase):
    def tokens(self, text, loose=True):
        return TOOL.name_tokens(text, loose=loose)

    def test_generic_word_and_word_order_are_ignored_when_loose(self):
        """库内名多一个 Mount、词序不同，都要能和 Lua 名对齐。"""
        pairs = [
            # 多一个 Mount
            ('Twin_40mm_Bofors_Hazemeyer_AA_Gun_Mount_T0',
             'Twin_40mm_Bofors_Hazemeyer_AA_Gun_T0'),
            ('Prototype_Triple_406mm_50_Main_Gun_Mount_T0',
             'Prototype_Triple_406mm_50_Main_Gun_T0'),
            # 词序不同
            ('610mm_Quadruple_Torpedo_Mount_T3', 'Quadruple_610mm_Torpedo_T3'),
            ('533mm_Quintuple_Torpedo_Mount_T3', 'Quintuple_533mm_Torpedo_T3'),
            ('Prototype_Triple_310mm_Type_0_Main_Gun_Mount_T0',
             'Prototype_Triple_310mm_Main_Gun_Type_0_T0'),
            # 拼写差异
            ('A7M_Reppuu_T3', 'A7M_Reppu_T3'),
        ]
        for library_name, lua_name in pairs:
            with self.subTest(name=library_name):
                self.assertNotEqual(self.tokens(library_name, loose=False),
                                    self.tokens(lua_name, loose=False))
                self.assertEqual(self.tokens(library_name), self.tokens(lua_name))

    def test_case_difference_needs_no_loosening(self):
        """大小写差异在基础实现里就已经吃掉（整串先转小写）。"""
        self.assertEqual(self.tokens('BlueprintMarcopolo', loose=False),
                         self.tokens('BlueprintMarcoPolo', loose=False))

    def test_strict_tokens_still_match_by_word_set(self):
        """不放宽时也要吃下词序差异（原有行为，别被本次修改带坏）。"""
        self.assertEqual(self.tokens('610mm_Quadruple_Torpedo_Mount_T3', loose=False),
                         self.tokens('Quadruple_610mm_Torpedo_Mount_T3', loose=False))

    def test_neighbours_are_not_folded_together(self):
        """同类近邻不能归一——认错就等于给错稀有度。"""
        pairs = [
            # 单装 vs 双联装（口径相同）
            ('Single_20mm_Oerlikon_AA_Gun_Mount_T3', 'Twin_20mm_AA_Oerlikon_T3'),
            # 同一门口径的不同型号
            ('Twin_40mm_Bofors_Type_5_AA_Gun_Mount_T0',
             'Twin_40mm_Bofors_Hazemeyer_AA_Gun_T0'),
            ('Twin_203mm_SK_C_34_T3', 'Twin_203mm_Main_Gun_SK_C_28_T3'),
            # 品阶后缀必须保留，否则 T2/T3 会撞在一起
            ('Twin_113mm_AA_Gun_Mount_T2', 'Twin_113mm_AA_Gun_T3'),
        ]
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(self.tokens(left), self.tokens(right))


if __name__ == '__main__':
    unittest.main()
