"""制造业：始终找不到的产品（科技未解锁）记入本批不可用，改试下一个候选；铁钉线餐具不可用时回退铁钉。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.island import island_manufacture as manufacture_module
from module.island.island_manufacture import IslandManufacture


def make_factory(found):
    """found: 可以在产品列表中找到的产品名集合。"""
    with patch.object(IslandManufacture, '__init__', lambda self: None):
        factory = IslandManufacture()
    factory.device = Mock()
    factory.device.screenshot = Mock(return_value=None)
    factory.posts = {'POST1': {'button': 'POST1_BUTTON'}, 'POST2': {'button': 'POST2_BUTTON'}}
    factory.unavailable_products = set()
    factory.post_manage_swipe_count = 2
    factory._item_cn = lambda name: name
    for name in ('post_close', 'post_open', 'wait_until_appear', 'post_manage_up_swipe'):
        setattr(factory, name, Mock())
    factory.appear_then_click = Mock(return_value=False)
    factory.appear = Mock(side_effect=lambda button, **kwargs: button is manufacture_module.ISLAND_SELECT_PRODUCT_CHECK)
    attempts = []

    def select_product(selection, selection_check):
        attempts.append(selection)
        return selection in found

    factory.select_product = Mock(side_effect=select_product)
    return factory, attempts


def item(name):
    return {'name': name, 'selection': name, 'selection_check': f'{name}_CHECK'}


class MissingProductTest(unittest.TestCase):
    def test_missing_product_is_remembered_and_next_tried(self):
        factory, attempts = make_factory(found={'iron_nail'})
        # 找到铁钉后进入派遣流程：截图取色判断材料，返回非灰色；后续流程打桩
        with patch.object(manufacture_module, 'get_color', Mock(return_value=(255, 255, 255))), \
                patch.object(manufacture_module, 'Digit') as digit, \
                patch.object(manufacture_module, 'Duration') as duration, \
                patch.object(manufacture_module, 'current_time', Mock(return_value=0)):
            digit.return_value.ocr.return_value = 7
            duration.return_value.ocr.return_value = 0
            factory.time_prefix = 'time_manufacture'
            result = factory.select_product_with_material_check('POST1', [item('cutlery'), item('iron_nail')])
            self.assertEqual(result['name'], 'iron_nail')
            limit = IslandManufacture.PRODUCT_SELECT_RETRY_LIMIT
            self.assertEqual(attempts, ['cutlery'] * limit + ['iron_nail'])
            self.assertIn('cutlery', factory.unavailable_products)

            # 第二个岗位直接跳过餐具
            attempts.clear()
            factory.select_product_with_material_check('POST2', [item('cutlery'), item('iron_nail')])
            self.assertEqual(attempts, ['iron_nail'])

    def test_industrial_falls_back_to_nails(self):
        with patch.object(IslandManufacture, '__init__', lambda self: None):
            factory = IslandManufacture()
        factory.manufacture = {'industrial_production': {'items': [item('iron_nail'), item('cutlery')]}}
        factory.config = SimpleNamespace(Industrial_Products='')
        factory.warehouse_counts = {'iron_nail': 30}
        factory.get_idle_posts_by_category = Mock(return_value=['POST1'])
        factory.select_product_with_material_check = Mock()
        factory.schedule_industrial_production()
        product_list = factory.select_product_with_material_check.call_args.args[1]
        self.assertEqual([p['name'] for p in product_list], ['cutlery', 'iron_nail'])


class ProductOrderTest(unittest.TestCase):
    """产线按 <产线>.Products 的顺序选品，未配置时沿用固定规则。"""

    def make(self, products, line='WoodProcessing', category='wood_processing', names=()):
        with patch.object(IslandManufacture, '__init__', lambda self: None):
            factory = IslandManufacture()
        factory.manufacture = {category: {'items': [item(name) for name in names]}}
        factory.config = SimpleNamespace(**{f'{line}_Products': products})
        factory.warehouse_counts = {}
        factory.get_idle_posts_by_category = Mock(return_value=['POST1', 'POST2'])
        factory.select_product_with_material_check = Mock()
        return factory

    def test_parse_product_order(self):
        self.assertEqual(manufacture_module.parse_product_order(' Paper > notebook,paper\nchair_desk '),
                         ['paper', 'notebook', 'chair_desk'])
        self.assertEqual(manufacture_module.parse_product_order(None), [])

    def test_configured_order_is_used_for_every_idle_post(self):
        factory = self.make('notebook > paper > unknown', names=('file_cabinet', 'paper', 'notebook'))
        factory.schedule_wood_processing()
        calls = factory.select_product_with_material_check.call_args_list
        self.assertEqual([call.args[0] for call in calls], ['POST1', 'POST2'])
        self.assertEqual([p['name'] for p in calls[0].args[1]], ['notebook', 'paper'])

    def test_empty_order_keeps_fixed_rule(self):
        factory = self.make('', names=('file_cabinet', 'paper', 'notebook'))
        factory.schedule_wood_processing()
        product_list = factory.select_product_with_material_check.call_args.args[1]
        self.assertEqual([p['name'] for p in product_list], ['file_cabinet'])

    def test_handmade_order_overrides_seasonal_rule(self):
        factory = self.make('rope > cloth', line='Handmade', category='handmade',
                            names=('leather', 'boot', 'cloth', 'rope'))
        factory.schedule_handmade()
        product_list = factory.select_product_with_material_check.call_args.args[1]
        self.assertEqual([p['name'] for p in product_list], ['rope', 'cloth'])

    def test_new_products_have_pictures(self):
        names = {'paper', 'notebook', 'chair_desk', 'ink_cartridge', 'charcoal_brush', 'cable', 'cloth', 'rope'}
        assets = vars(manufacture_module)
        for name in names:
            for suffix in ('', '_CHECK'):
                self.assertIn(f'SELECT_{name.upper()}{suffix}', assets)


if __name__ == '__main__':
    unittest.main()
