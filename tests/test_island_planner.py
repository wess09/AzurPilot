"""岛屿生产规划器（移植自 ALAS）：离线求解与写回 AzurPilot 配置的换算。"""

import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml
from unittest.mock import patch

import module.config.server as server
from module.island.farm_targets import parse_crop_targets
from module.island_planner import settings_map as sm
from module.island_planner.calculator import ProductionPlanCalculator
from module.island_planner.data import DIC_ISLAND_ITEM, DIC_ISLAND_RECIPE, DIC_ISLAND_TECHNOLOGY
from module.island_planner.utils import get_current_activity_list

ROOT = Path(__file__).resolve().parents[1]
ARGUMENT = yaml.safe_load((ROOT / 'module/config/argument/argument.yaml').read_text(encoding='utf-8'))
ARGS = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))
NOW = datetime(2026, 10, 27, 12)


def options(group, key):
    return [name for name in ARGUMENT[group][key]['option'] if name != 'None']


MEAL_OPTIONS = {rid: options(k['task'], 'Meal1') for rid, k in sm.KITCHENS.items()}
PRODUCT_OPTIONS = {rid: options(k['business'], 'Product1') for rid, k in sm.KITCHENS.items()}


def solve(technology, grades='gold', chars=('WorkerJuu', 'WorkerJuu'), profit=50000, open_ids=None):
    calculator = ProductionPlanCalculator(
        technology,
        activity_list=get_current_activity_list(NOW),
        restaurant_settings=sm.restaurant_settings(
            {rid: grades for rid in sm.KITCHENS}, {rid: chars for rid in sm.KITCHENS}, open_ids),
        daily_profit_lower_limit=profit,
    )
    excluded = sm.restrict_calculator(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS)
    calculator.solve_production_plan(current_time=NOW)
    return calculator, excluded


class NameMappingTest(unittest.TestCase):
    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_english_names_on_cn_server_keep_producible_identity(self):
        from module.island_planner.planner import parse_targets, resolve_item
        from module.island_planner.utils import normalize_item_id

        server.server = 'cn'
        matches = [item_id for item_id, item in DIC_ISLAND_ITEM.items()
                   if item['name']['en'] == 'Corn']
        expected = next((item_id for item_id in matches
                         if item_id in ProductionPlanCalculator.RECIPE_PRODUCT_IDS), matches[0])
        self.assertEqual(resolve_item('Corn'), expected)
        self.assertIn(normalize_item_id('Corn'), matches)
        self.assertEqual(parse_targets('Corn: 200', 'ExtraTargets'), {expected: [200]})

    def test_every_azurpilot_dish_option_has_an_item(self):
        for rid, kitchen in sm.KITCHENS.items():
            for name in MEAL_OPTIONS[rid] + PRODUCT_OPTIONS[rid]:
                self.assertIn(name, sm.DISH_ITEM_IDS, f'{kitchen["task"]}: {name}')
        for item_id in sm.DISH_ITEM_IDS.values():
            self.assertIn(item_id, DIC_ISLAND_ITEM)

    def test_every_crop_is_produced_by_a_recipe(self):
        products = {next(iter(r['commission_product'])) for r in DIC_ISLAND_RECIPE.values()}
        for area, crops in sm.CROP_ITEM_IDS.items():
            for crop, item_id in crops.items():
                self.assertIn(item_id, products, f'{area}: {crop}')

    def test_waitress_slots(self):
        # 有鱼餐馆：肇和有加成，柴郡对本店无加成视为 any；None 由工作啾代班，也视为 any
        self.assertEqual(sm.waitress_slots(601, ('ChaoHo', 'Cheshire')), ('Chao_Ho', 'any'))
        self.assertEqual(sm.waitress_slots(602, ('Cheshire', 'None')), ('Cheshire', 'any'))
        self.assertEqual(sm.waitress_slots(603, ('Eugen', 'Eugen')), ('Prinz_Eugen', 'any'))
        with self.assertRaises(ValueError):
            sm.restaurant_settings({601: 'platinum'}, {})

    def test_open_restaurants(self):
        self.assertEqual(sm.open_restaurants(False, [], []), set(sm.KITCHENS))
        # 默认分批 [3, 1, 5] + [2, 4] 覆盖全部五家
        self.assertEqual(sm.open_restaurants(True, [3, 1, 5], [2, 4]), set(sm.KITCHENS))
        self.assertEqual(sm.open_restaurants(True, [1], ['5']), {601, 901})
        settings = sm.restaurant_settings({}, {}, open_ids={601})
        self.assertEqual(settings[602]['waitress_slots'], ('none', 'none'))
        self.assertEqual(settings[601]['waitress_slots'], ('any', 'any'))


class SeasonScannerRetryTest(unittest.TestCase):
    def test_retry_when_no_task_rows_found(self):
        from unittest.mock import Mock

        import numpy as np

        from module.island_planner.season_tasks import IslandSeasonTaskScanner

        scanner = IslandSeasonTaskScanner.__new__(IslandSeasonTaskScanner)
        scanner.loop = Mock(return_value=range(2))
        scanner._task_rows = Mock(side_effect=[np.empty((0, 2)), np.array([[0., 40.]])])
        self.assertEqual(len(scanner.season_task_grid.buttons), 3)
        self.assertEqual(scanner._task_rows.call_count, 2)


class FakeCalculatorTest(unittest.TestCase):
    """用假结果检查后厨/商区/作物的换算规则。"""

    def make(self):
        return SimpleNamespace(
            restaurant_capacity={rid: 6 for rid in sm.KITCHENS},
            # 豆腐 40/天（中间品），肉末烧豆腐卖 6、日缓冲 6，套餐卖 3
            production_plan={601001: 40 / 1, 601002: 6, 601101: 3, 101005: 1},
            recipe_group={601001: 'koi', 601002: 'koi', 601101: 'koi', 101005: 'field'},
            sell_plan={(601, 3012): 6, (601, 3101): 3},
            product_daily_buffer_items={3011: 12, 3012: 9, 3101: 3, 2002: 20},
            idle_accumulating_items_per_day={3011: 2.5, 2002: 4.2},
        )

    def test_kitchen_settings(self):
        values, notes = sm.kitchen_settings(self.make(), 601, MEAL_OPTIONS[601], PRODUCT_OPTIONS[601])
        self.assertEqual(notes, [])
        meals = [(values[f'IslandRestaurant.IslandRestaurant.Meal{i}'],
                  values[f'IslandRestaurant.IslandRestaurant.MealNumber{i}']) for i in range(1, 9)]
        # 出售菜品在前（容量 6 + 日缓冲），中间品在后，空槽为 None/0
        self.assertEqual(meals[:3], [('tofu_meat', 15), ('tofu_combo', 9), ('tofu', 12)])
        self.assertEqual(meals[3:], [('None', 0)] * 5)
        self.assertEqual(values['IslandRestaurant.IslandRestaurantNextTask.AwayCook'], 'tofu')
        self.assertEqual(
            [values[f'IslandBusiness.IslandBusinessShop1.Product{i}'] for i in range(1, 6)],
            ['tofu_meat', 'tofu_combo', 'None', 'None', 'None'])

    def test_crop_settings(self):
        values, notes = sm.crop_settings(self.make())
        farm = parse_crop_targets(values['IslandFarm.IslandFarm.CropTargets'])
        # 目标只含一天消耗，闲时累积量只作提示，避免攒 PT 的作物挤占真正需要的作物
        self.assertEqual(farm['rice'], 20)
        self.assertEqual(farm['wheat'], 0)
        self.assertEqual(set(farm), set(sm.CROP_ITEM_IDS['farm']))
        self.assertEqual(len(notes), 1)
        self.assertIn('rice 4/day', notes[0])


class ProductionLineTest(unittest.TestCase):
    """矿山/林场/渔场/牧场/制造业的换算。"""

    def make(self):
        tech = {tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY}
        calculator = ProductionPlanCalculator(tech)
        calculator.production_plan = {
            101013: 3,      # 鸡舍 3 批
            701010: 10,     # 铁钉 10 批，工作量 10 * workload
            401005: 2,      # 铁矿
        }
        calculator.product_daily_buffer_items = {2703: 12, 5107: 3}
        calculator.idle_accumulating_items_per_day = {2705: 40}
        return calculator

    def test_thresholds(self):
        values, notes = sm.threshold_settings(self.make())
        self.assertEqual(values['IslandMineForest.IslandMine.MinIron'], 12)
        self.assertEqual(values['IslandMineForest.IslandMine.MinSilver'], 0)
        self.assertEqual(values['IslandRancher.IslandFishery.MinYellowfinTuna'], 3)
        self.assertEqual(values['IslandMineForest.IslandForest.MinElegant'], 0)
        self.assertEqual(len(notes), 1)
        self.assertIn('Silver Ore 40/day', notes[0])

    def test_ranch(self):
        calculator = self.make()
        values = sm.ranch_settings(calculator)
        level = calculator.ranch_level[9031]
        # 禽肉为副产物：每批 4 * (1 + 等级)，每 3 批摊一次
        expected = 4 * (1 + level) / 3 * 3
        self.assertEqual(values['IslandRancher.IslandRancher.MinChicken'], max(int(-(-expected // 1)), 1))
        self.assertEqual(values['IslandRancher.IslandRancher.MinPork'], 0)
        self.assertFalse(values['IslandRancher.IslandRancher.Milk'])
        self.assertFalse(values['IslandRancher.IslandRancher.Wool'])

    def test_manufacture_positions(self):
        values = sm.manufacture_settings(self.make())
        workload = DIC_ISLAND_RECIPE[701010]['workload'] * 10
        self.assertEqual(values['IslandManufacture.Industrial.Positions'],
                         min(-(-workload // sm.DAILY_WORKLOAD), 2))
        self.assertEqual(values['IslandManufacture.WoodProcessing.Positions'], 0)


class SolveTest(unittest.TestCase):
    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_full_technology_plan_writes_valid_settings(self):
        calculator, excluded = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY})
        self.assertTrue(calculator.lp_success, calculator.lp_message)
        self.assertGreaterEqual(calculator.daily_profit, 50000 - 1e-6)
        # 烧烤店后厨没有柠檬虾选项，求解前排除
        self.assertIn('Lemon Shrimp', excluded)

        values, _ = sm.build_settings(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS)
        for path, value in values.items():
            task, group, key = path.split('.')
            self.assertIn(key, ARGS[task][group], path)
            definition = ARGUMENT[group][key]
            if isinstance(definition, dict) and 'option' in definition:
                self.assertIn(value, definition['option'], path)
            elif key.startswith(('MealNumber', 'Min')):
                self.assertIsInstance(value, int, path)
                self.assertGreaterEqual(value, 0, path)
        for rid, kitchen in sm.KITCHENS.items():
            products = [values[f'IslandBusiness.{kitchen["business"]}.Product{i}'] for i in range(1, 6)]
            sold = [name for name in products if name != 'None']
            self.assertEqual(len(sold), len(set(sold)))
            # 只卖规划出售的菜品，且都在 AzurPilot 商区选项里
            for name in sold:
                self.assertIn(name, PRODUCT_OPTIONS[rid])

    def test_starting_island_still_solves(self):
        calculator, _ = solve({tech_id: False for tech_id in DIC_ISLAND_TECHNOLOGY}, grades='bronze', profit=0)
        self.assertTrue(calculator.lp_success, calculator.lp_message)
        values, _ = sm.build_settings(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS)
        self.assertEqual(len([path for path in values if path.endswith('CropTargets')]), 3)

    def test_closed_restaurant_sells_nothing(self):
        calculator, _ = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY}, open_ids=set(), profit=-1e9)
        self.assertTrue(calculator.lp_success, calculator.lp_message)
        self.assertEqual(calculator.sell_plan, {})


class FakeConfig:
    """只实现规划器用到的配置接口：属性读取、cross_get、批量写入。"""

    def __init__(self, technology_status, **overrides):
        self.data = {}
        for task, groups in ARGS.items():
            for group, args in groups.items():
                for key, arg in args.items():
                    if isinstance(arg, dict) and 'value' in arg:
                        self.data.setdefault(task, {}).setdefault(group, {})[key] = arg['value']
                        setattr(self, f'{group}_{key}', arg['value'])
        self.data['IslandProductionPlanner']['Storage']['Storage'] = {'IslandTechnologyStatus': technology_status}
        for key, value in overrides.items():
            setattr(self, key, value)
        self.written = {}

    def cross_get(self, keys, default=None):
        node = self.data
        for key in keys.split('.'):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def cross_set(self, keys, value):
        self.written[keys] = value

    def cross_set_many(self, values):
        self.written.update(values)

    def multi_set(self):
        from contextlib import nullcontext
        return nullcontext()


class PlannerTaskTest(unittest.TestCase):
    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def run_planner(self, **overrides):
        from unittest.mock import patch
        from module.island_planner.planner import IslandProductionPlanner
        technology = {str(tech_id): True for tech_id in DIC_ISLAND_TECHNOLOGY}
        with patch.object(IslandProductionPlanner, '__init__', lambda self: None):
            planner = IslandProductionPlanner()
        overrides.setdefault('IslandProductionPlanner_ScanSeasonTasks', False)
        planner.config = FakeConfig(technology, IslandProductionPlanner_RescanTechnology=False, **overrides)
        planner.get_technology_status = lambda: self.fail('saved technology must not trigger a scan')
        planner.scan_season_task_targets = lambda: {3009: 30}
        return planner, planner.run()

    def test_preview_does_not_write(self):
        planner, result = self.run_planner()
        self.assertTrue(result)
        self.assertEqual(planner.config.written, {})

    def test_apply_writes_settings(self):
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           IslandProductionPlanner_RestaurantGrade='gold')
        self.assertTrue(result)
        written = planner.config.written
        self.assertIn('IslandFarm.IslandFarm.CropTargets', written)
        self.assertIn('IslandBusiness.IslandBusinessShop1.Product1', written)
        self.assertTrue(all(path.split('.')[2] in ARGS[path.split('.')[0]][path.split('.')[1]] for path in written))

    def test_infeasible_plan_keeps_settings(self):
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           IslandProductionPlanner_DailyProfitLowerLimit=10 ** 9)
        self.assertFalse(result)
        self.assertEqual(planner.config.written, {})


    def test_targets_reach_kitchen_settings(self):
        # 苹果派不在默认方案里；加入目标后啾啾简餐后厨应为其开工
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           IslandProductionPlanner_ExtraTargets='Apple Pie: 84')
        self.assertTrue(result)
        meals = [planner.config.written.get(f'IslandJuuEatery.IslandJuuEatery.Meal{i}') for i in range(1, 9)]
        self.assertIn('apple_pie', meals)

    def test_scan_writes_season_targets(self):
        planner, result = self.run_planner(IslandProductionPlanner_ScanSeasonTasks=True)
        self.assertTrue(result)
        self.assertEqual(
            planner.config.written['IslandProductionPlanner.IslandProductionPlanner.SeasonTaskTargets'].strip(),
            'Apple Pie (3009): 30')


class TargetParsingTest(unittest.TestCase):
    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_parse_and_merge(self):
        from module.island_planner.planner import merge_targets, parse_targets
        season = parse_targets('Apple Pie: 30\nCorn: 100', 'SeasonTaskTargets')
        extra = parse_targets('Apple Pie: {count: 10, period: 2}\nNot An Item: 5\n3011: 4', 'ExtraTargets')
        self.assertEqual(season, {3009: [30], 2001: [100]})
        self.assertEqual(extra, {3009: [{'count': 10, 'period': 2}], 3011: [4]})
        merged = merge_targets(season, extra)
        from module.island_planner.utils import normalize_item_needs
        needs = normalize_item_needs(merged, default_period=8)
        # 30 个 8 天 + 10 个 2 天：前 2 天至少 10 个，8 天共 40 个
        self.assertEqual(needs[3009]['total_need_count'], 40)
        self.assertAlmostEqual(needs[3009]['rate_per_day'], 5.0)
        self.assertEqual(parse_targets('[1, 2', 'ExtraTargets'), {})

    def test_season_task_matching(self):
        from module.island_planner.data import DIC_ISLAND_TASK
        from module.island_planner.season_tasks import match_task_name, task_item_targets
        item_tasks = [tid for tid, task in DIC_ISLAND_TASK.items()
                      if task['target'] and next(iter(task['target'])) in DIC_ISLAND_ITEM]
        self.assertTrue(item_tasks)
        task_id = item_tasks[0]
        name = DIC_ISLAND_TASK[task_id]['name']['en']
        # OCR 少一个字母也能纠正到同一任务
        self.assertEqual(match_task_name(name[:-1], item_tasks[:20]), task_id)
        self.assertIsNone(match_task_name('', item_tasks))
        targets = task_item_targets([task_id, task_id, 10001000])
        item_id, count = next(iter(DIC_ISLAND_TASK[task_id]['target'].items()))
        self.assertEqual(targets, {item_id: count * 2})


class EfficiencyTest(unittest.TestCase):
    def test_efficiency_rate(self):
        from module.island_planner.planner import efficiency_rate
        # 配置为整数百分比；兼容早期的小数值与 WebUI 拆坏的字符串
        self.assertEqual(efficiency_rate(0), 0)
        self.assertAlmostEqual(efficiency_rate(4), 0.04)
        self.assertAlmostEqual(efficiency_rate(12), 0.12)
        self.assertAlmostEqual(efficiency_rate(0.04), 0.04)
        self.assertAlmostEqual(efficiency_rate('04'), 0.04)
        self.assertEqual(efficiency_rate('bad'), 0)


class SeasonScanGuardTest(unittest.TestCase):
    """季节任务扫描：读错的任务名不硬配，识别不到任务卡片时保留原目标。"""

    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_rejects_far_names(self):
        from module.island_planner.data import DIC_ISLAND_TASK
        from module.island_planner.season_tasks import match_task_name
        ids = [tid for tid, task in DIC_ISLAND_TASK.items() if task['name']['en'] == 'More Rice!']
        self.assertTrue(ids)
        # 11-02 日志：只读到「F」却被纠正为「More Rice!」
        self.assertIsNone(match_task_name('F', ids))
        self.assertIn(match_task_name('MoreRice!', ids), ids)

    def test_no_cards_keeps_targets(self):
        from unittest.mock import Mock
        from module.island_planner.season_tasks import IslandSeasonTaskScanner
        scanner = IslandSeasonTaskScanner.__new__(IslandSeasonTaskScanner)
        scanner.loop = Mock(side_effect=lambda **kwargs: iter(range(2)))
        scanner._task_rows = Mock(return_value=np.empty((0, 2)))
        with patch('module.island_planner.season_tasks.ISLAND_SEASON_TASK_SCROLL') as scroll:
            self.assertIsNone(scanner.scan_unfinished())
            scroll.next_page.assert_not_called()

    def test_planner_keeps_saved_targets_when_scan_fails(self):
        from module.island_planner.planner import IslandProductionPlanner
        with patch.object(IslandProductionPlanner, '__init__', lambda self: None):
            planner = IslandProductionPlanner()
        planner.config = FakeConfig({}, IslandProductionPlanner_ScanSeasonTasks=True,
                                    IslandProductionPlanner_ScanCargoOrders=False,
                                    IslandProductionPlanner_SeasonTaskTargets='Apple Pie: 30')
        planner.scan_season_task_targets = lambda: None
        targets = planner.load_targets()
        self.assertEqual(targets, {3009: [30]})
        self.assertNotIn('IslandProductionPlanner.IslandProductionPlanner.SeasonTaskTargets', planner.config.written)


class ScannerGeometryTest(unittest.TestCase):
    def test_node_positions_cover_scanned_tabs(self):
        from module.island_planner.scanner import SCANNED_TABS, get_technology_tab_and_position, node_in_view
        tabs = {get_technology_tab_and_position(tech_id)[0] for tech_id in DIC_ISLAND_TECHNOLOGY}
        self.assertTrue(set(SCANNED_TABS) <= tabs)
        # 视野左端时，第一列节点可见，很远的节点不可见
        self.assertTrue(node_in_view((ORIGIN_FIRST_COLUMN_X, 106), 0))
        self.assertFalse(node_in_view((5000, 106), 0))


ORIGIN_FIRST_COLUMN_X = 136 + 2 / 3 * 1 - 5 / 3 + 136


if __name__ == '__main__':
    unittest.main()
