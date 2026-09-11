"""图纸/报告等级按底色判定的单元测试。

覆盖 ``AutoSearchItemGrid.frame_color`` 的底色分类与
``AutoSearchItemGrid.template_tier`` 的模板等级提取，避免同种物品
不同稀有度（紫 T3 / 金 T4 / 彩 T5）互相误匹配。
"""

import unittest

import numpy as np

from module.azur_stats.image.auto_search_reward import AutoSearchItemGrid


def build_image(background, size=96):
    """构造一张中间是白纸、四周是给定底色的图标。

    Args:
        background (tuple): 底色 RGB。
        size (int): 图像边长。

    Returns:
        np.ndarray: RGB 图像。
    """
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:, :] = background
    image[size // 4:size * 3 // 4, size // 4:size * 3 // 4] = (250, 250, 250)
    return image


class TestFrameColor(unittest.TestCase):
    def test_gold_background(self):
        # 暖黄斜纹底色（金图纸 / 金报告）
        image = build_image((230, 190, 110))
        self.assertEqual(AutoSearchItemGrid.frame_color(image), 'gold')

    def test_purple_background(self):
        image = build_image((150, 120, 220))
        self.assertEqual(AutoSearchItemGrid.frame_color(image), 'purple')

    def test_rainbow_background(self):
        # 彩虹底同时含青、粉等多个色相
        image = np.zeros((96, 96, 3), dtype=np.uint8)
        image[:, :48] = (110, 220, 230)
        image[:, 48:] = (240, 150, 210)
        image[24:72, 24:72] = (250, 250, 250)
        self.assertEqual(AutoSearchItemGrid.frame_color(image), 'rainbow')

    def test_white_image_returns_none(self):
        image = np.full((96, 96, 3), 250, dtype=np.uint8)
        self.assertIsNone(AutoSearchItemGrid.frame_color(image))


class TestTemplateTier(unittest.TestCase):
    def test_design_plan_tiers(self):
        self.assertEqual(
            AutoSearchItemGrid.template_tier('GearDesignPlanGunT4'), 'T4')
        self.assertEqual(
            AutoSearchItemGrid.template_tier('GearDesignPlanAntiAirT5_2'), 'T5')
        self.assertEqual(
            AutoSearchItemGrid.template_tier('OrdnanceTestingReportT3_5'), 'T3')

    def test_other_items_are_unrestricted(self):
        # 非白纸类物品（强化板、猫箱等）不受等级限制
        self.assertIsNone(AutoSearchItemGrid.template_tier('PlateGunT4'))
        self.assertIsNone(AutoSearchItemGrid.template_tier('CatT2'))
        self.assertIsNone(AutoSearchItemGrid.template_tier('Natural_Rubber'))


class TestMatchCandidates(unittest.TestCase):
    def setUp(self):
        self.grid = AutoSearchItemGrid(None, {})

    def test_gold_image_only_keeps_t4_templates(self):
        image = build_image((230, 190, 110))
        names = ['GearDesignPlanGunT5', 'GearDesignPlanGunT4',
                 'OrdnanceTestingReportT3_2', 'Coins']
        filtered, similarity = self.grid.match_candidates(image, names, 0.85)
        self.assertEqual(filtered, ['GearDesignPlanGunT4', 'Coins'])
        self.assertLessEqual(similarity, AutoSearchItemGrid.TIER_SIMILARITY)

    def test_unknown_color_keeps_everything(self):
        image = np.full((96, 96, 3), 250, dtype=np.uint8)
        names = ['GearDesignPlanGunT5', 'GearDesignPlanGunT4']
        filtered, similarity = self.grid.match_candidates(image, names, 0.85)
        self.assertEqual(filtered, names)
        self.assertEqual(similarity, 0.85)

    def test_missing_tier_falls_back_to_all_candidates(self):
        # 该等级尚无模板时不限制候选，仍按原阈值识别
        image = build_image((150, 120, 220))
        names = ['GearDesignPlanGunT4', 'GearDesignPlanGunT5']
        filtered, similarity = self.grid.match_candidates(image, names, 0.85)
        self.assertEqual(filtered, names)
        self.assertEqual(similarity, 0.85)


if __name__ == '__main__':
    unittest.main()
