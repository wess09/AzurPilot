"""原料不够整批时，饲料只补到派遣门槛的离线测试。

库存取自国际服实例 2026-11-08 02:31 的牧场日志：小麦 218、牧草 146，
鸡饲料 14、牛饲料 46、羊饲料 44。原逻辑固定加工 11 组（需 330 原料），
三种饲料全部放弃，鸡饲料停在 14 < 50，养鸡岗位一直空闲。
"""
import unittest

from module.island.island_rancher import IslandRancher


class StubRancher:
    feed_groups_to_target = IslandRancher.feed_groups_to_target
    process_mill_item_with_inventory = IslandRancher.process_mill_item_with_inventory
    mill_material_needed = staticmethod(IslandRancher.mill_material_needed)
    mill_output_quantity = staticmethod(IslandRancher.mill_output_quantity)

    def __init__(self, farm, mill):
        self.inventory_counts = {'farm': dict(farm), 'mill': dict(mill), 'ranch': {}}
        self.ranch_feed_map = {
            'ISLAND_RANCH_POST1': 'chicken_feed',
            'ISLAND_RANCH_POST2': 'pig_feed',
            'ISLAND_RANCH_POST3': 'cattle_feed',
            'ISLAND_RANCH_POST4': 'sheep_feed',
        }
        self.name_to_config = {
            'chicken_feed': {'required_material': 'wheat'},
            'pig_feed': {'required_material': 'corn'},
            'cattle_feed': {'required_material': 'pasture'},
            'sheep_feed': {'required_material': 'pasture'},
            'wheat_flour': {'required_material': 'wheat'},
        }
        self.processed = []

    def process_mill_item(self, mill_item, quantity=None):
        self.processed.append((mill_item, quantity))
        return True

    @staticmethod
    def _item_cn(name):
        return name

    def supplement(self, needs, target=50):
        """与 process_mill_supplements 的加工循环相同（省去页面导航）。"""
        for mill_item, quantity in needs:
            fallback = self.feed_groups_to_target(mill_item, quantity, target)
            self.process_mill_item_with_inventory(mill_item, quantity, fallback_quantity=fallback)


class PartialFeedTest(unittest.TestCase):
    def test_short_materials_make_feed_up_to_dispatch_threshold(self):
        stub = StubRancher(
            farm={'wheat': 218, 'pasture': 146, 'corn': 1070},
            mill={'chicken_feed': 14, 'cattle_feed': 46, 'sheep_feed': 44},
        )
        stub.supplement([('chicken_feed', 11), ('cattle_feed', 11), ('sheep_feed', 11)])

        self.assertEqual(stub.processed, [('chicken_feed', 4), ('cattle_feed', 1), ('sheep_feed', 1)])
        self.assertEqual(stub.inventory_counts['mill'], {'chicken_feed': 54, 'cattle_feed': 56, 'sheep_feed': 54})
        self.assertEqual(stub.inventory_counts['farm']['wheat'], 218 - 120)
        self.assertEqual(stub.inventory_counts['farm']['pasture'], 146 - 60)

    def test_enough_materials_keep_full_batch(self):
        stub = StubRancher(farm={'wheat': 1000}, mill={'chicken_feed': 14})
        stub.supplement([('chicken_feed', 11)])
        self.assertEqual(stub.processed, [('chicken_feed', 11)])

    def test_too_little_even_for_threshold_skips(self):
        stub = StubRancher(farm={'wheat': 100}, mill={'chicken_feed': 0})
        stub.supplement([('chicken_feed', 11)])
        self.assertEqual(stub.processed, [])

    def test_flour_never_partial(self):
        stub = StubRancher(farm={'wheat': 218}, mill={'wheat_flour': 0})
        stub.supplement([('wheat_flour', 200)])
        self.assertEqual(stub.processed, [])
        self.assertEqual(stub.inventory_counts['farm']['wheat'], 218)


if __name__ == "__main__":
    unittest.main()
