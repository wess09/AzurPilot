"""科研掉落解析：期数只能看卡片角标。

项目代号在每一期都存在（G-531-MI、Q-051-MI…），代号里没有期数信息；金装备也不绑
期数。所以这里用合成图锁住「角标区域能盖住罗马数字、缩放是 1.0」这条契约——
区域改错时这个测试会失败。

真实截图的端到端验证不在单测里（截图不入库），实测见 alas-research-stats 技能文档。
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock

import numpy as np


def module_stub(name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def load_research_drop():
    """仅导入待测实现，日志模块用替身，避免初始化用户配置与日志目录。

    手工换掉 `sys.modules` 里的一项再还原，而不是用 ``patch.dict(sys.modules, ...)``：
    后者退出时会清空并还原整个 sys.modules 快照，把本次导入期间新进来的模块（numpy 的
    C 扩展等）一起抹掉，同一进程里再 ``import numpy`` 就会报
    ``cannot load module more than once per process``，把后面的测试模块连带弄挂。
    """
    path = Path(__file__).resolve().parents[1] / 'module/statistics/research_drop.py'
    spec = importlib.util.spec_from_file_location('_research_drop_test', path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get('module.logger')
    sys.modules['module.logger'] = module_stub('module.logger', logger=Mock())
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop('module.logger', None)
        else:
            sys.modules['module.logger'] = previous
    return module


RESEARCH_DROP = load_research_drop()


class SeriesBadgeGeometryTest(unittest.TestCase):
    """角标区域与缩放：把某个罗马数字模板贴进区域，读出来必须是它。"""

    @classmethod
    def setUpClass(cls):
        from module.config import server as server_config
        server_config.server = 'cn'
        from module.base.utils import load_image

        cls.badge_area = RESEARCH_DROP.SERIES_BADGE_AREA
        cls.badges = {
            value: load_image(f'./assets/cn/research/TEMPLATE_S{value}.png')
            for value in (1, 4, 6, 7, 8, 9)
        }

    def page_with_badge(self, value):
        """造一张只有角标区域有内容的 1280x720 图。"""
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        badge = self.badges[value]
        if badge.ndim == 2:  # 模板 png 是灰度图，贴进彩色画布要补通道
            badge = np.repeat(badge[:, :, None], 3, axis=2)
        left, top, _, _ = self.badge_area
        # 角标贴在区域左上角内留 5px 边距的位置：真实截图里罗马数字就在这附近，
        # 区域太贴边时模板匹配会失败（实测裁到 40x36 就全读不出）。
        x, y = left + 5, top + 5
        image[y:y + badge.shape[0], x:x + badge.shape[1]] = badge
        return image

    def test_badge_area_is_large_enough(self):
        for value, badge in self.badges.items():
            left, top, right, bottom = self.badge_area
            with self.subTest(series=value):
                self.assertGreaterEqual(right - left, badge.shape[1] + 10)
                self.assertGreaterEqual(bottom - top, badge.shape[0] + 10)

    def test_reads_series_from_badge(self):
        for value in self.badges:
            with self.subTest(series=value):
                self.assertEqual(
                    RESEARCH_DROP.ResearchDropParser._read_series(None, self.page_with_badge(value)),
                    value)

    def test_blank_page_reads_zero(self):
        """读不出期数时返回 0，不猜一个期数出来。"""
        blank = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertEqual(RESEARCH_DROP.ResearchDropParser._read_series(None, blank), 0)


if __name__ == '__main__':
    unittest.main()
