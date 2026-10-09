"""岛屿走位规则（岛屿计划全局配置）的离线回归测试。

岛屿计划（`IslandPlan`）是岛屿的全局配置：季节 + 每条走位路线的规则字符串。
规则对所有控制方式生效，未填写或非法时回退代码默认路线。

这里验证：

1. 官方规则字符串的解析（毫秒 / 秒 / 单位后缀 / jump / 非法输入）；
2. 所有控制方式都按配置规则覆盖；
3. 路线执行顺序，jump 只点一次跳跃；
4. 校验开关（`<路线>Enable`）的读取；
5. 生成配置里的默认规则与代码里的默认路线完全一致（升级后行为不突变）。
"""
import unittest

from module.config.config_generated import GeneratedConfig
from module.island.island import Island
from module.island.island_plan import IslandPlan
from module.island.island_walk import (
    ISLAND_WALK_ROUTES,
    format_walk_rule,
    parse_walk_duration,
    parse_walk_rule,
)


class StubConfig:
    """只实现走位规则需要的接口，其它访问直接报错以便发现漏配。"""

    def __init__(self, method='azurpilot_android', values=None):
        self.Emulator_ControlMethod = method
        self.values = values or {}
        self.delays = []

    def cross_get(self, keys, default=None):
        return self.values.get(keys, default)

    def task_delay(self, **kwargs):
        self.delays.append(kwargs)


class StubDevice:
    """记录设备调用，验证走位顺序与时长。"""

    def __init__(self):
        self.calls = []

    def island_swipe_hold(self, p1, p2, hold_time):
        self.calls.append((p1, p2, hold_time))

    def click(self, button, *args, **kwargs):
        self.calls.append(('jump', button))

    def screenshot(self):
        return None

    def sleep(self, seconds):
        return None


def build_island(method='azurpilot_android', values=None):
    device = StubDevice()
    island = Island(config=StubConfig(method=method, values=values), device=device)
    return island, device


def rule(route, text):
    """构造一份只覆盖单条路线的全局配置。"""
    return {f'IslandPlan.IslandWalk.{route}': text}


class TestWalkRuleParsing(unittest.TestCase):
    def test_duration_units(self):
        self.assertEqual(parse_walk_duration('800'), 800)
        self.assertEqual(parse_walk_duration('1500ms'), 1500)
        self.assertEqual(parse_walk_duration('3.0'), 3000)
        self.assertEqual(parse_walk_duration('1.5s'), 1500)
        self.assertEqual(parse_walk_duration('0.001'), 100)  # 小于下限夹到 100
        self.assertEqual(parse_walk_duration('99'), 100)
        self.assertEqual(parse_walk_duration('99999'), 20000)  # 大于上限夹到 20000
        self.assertIsNone(parse_walk_duration('abc'))
        self.assertIsNone(parse_walk_duration(''))
        # nan / inf 不能进 round/int，必须当作非法值回退默认路线
        self.assertIsNone(parse_walk_duration('nan'))
        self.assertIsNone(parse_walk_duration('inf'))
        self.assertIsNone(parse_walk_duration('-inf'))
        self.assertIsNone(parse_walk_duration('nan s'))

    def test_parse_rule(self):
        steps = parse_walk_rule('up 3000, right 800, jump, left 1.5')
        self.assertEqual(steps, (('up', 3000), ('right', 800), ('jump', 0), ('left', 1500)))

    def test_parse_rule_with_switch_action(self):
        steps = parse_walk_rule('up 2600, switch, left 600')
        self.assertEqual(steps, (('up', 2600), ('switch', 0), ('left', 600)))

    def test_parse_rule_with_cn_punctuation_and_newlines(self):
        steps = parse_walk_rule('up 1000，down 2000；\nleft 500')
        self.assertEqual(steps, (('up', 1000), ('down', 2000), ('left', 500)))

    def test_parse_rule_invalid(self):
        self.assertIsNone(parse_walk_rule(''))
        self.assertIsNone(parse_walk_rule('up'))
        self.assertIsNone(parse_walk_rule('diag 100'))
        self.assertIsNone(parse_walk_rule('up abc'))
        self.assertIsNone(parse_walk_rule('up 100, diag 200'))

    def test_format_rule(self):
        self.assertEqual(format_walk_rule((('up', 3000), ('jump', 0))), 'up 3000, jump')
        self.assertEqual(
            format_walk_rule(ISLAND_WALK_ROUTES['DailyBulaimei']),
            'up 2600, switch, left 600',
        )


class TestIslandWalkConfig(unittest.TestCase):
    def test_default_steps_without_config(self):
        island, _ = build_island()
        self.assertEqual(island.island_walk_steps('DailyAobulaien'),
                         ISLAND_WALK_ROUTES['DailyAobulaien'])

    def test_config_applies_to_every_control_method(self):
        island, _ = build_island(method='minitouch', values=rule('DailyAobulaien', 'right 9000'))
        self.assertEqual(island.island_walk_steps('DailyAobulaien'),
                         (('right', 9000),))

    def test_android_uses_configured_rule(self):
        island, _ = build_island(values=rule('DailyAobulaien', 'right 5.2, up 5100, right 1.1'))
        self.assertEqual(island.island_walk_steps('DailyAobulaien'),
                         (('right', 5200), ('up', 5100), ('right', 1100)))
        self.assertEqual(island.island_walk_durations('DailyAobulaien'), [5200, 5100, 1100])

    def test_invalid_rule_falls_back(self):
        island, _ = build_island(values=rule('DailyAobulaien', 'chaos'))
        self.assertEqual(island.island_walk_steps('DailyAobulaien'),
                         ISLAND_WALK_ROUTES['DailyAobulaien'])

        island, _ = build_island(values=rule('DailyAobulaien', 'up nan, right 100'))
        self.assertEqual(island.island_walk_steps('DailyAobulaien'),
                         ISLAND_WALK_ROUTES['DailyAobulaien'])

    def test_route_execution_order_and_jump(self):
        island, device = build_island()
        island.island_walk_route('DailyPateli')
        kinds = [call[0] for call in device.calls]
        self.assertEqual(kinds, [(218, 507), 'jump', (218, 507), (218, 507)])
        self.assertEqual([call[2] for call in device.calls if call[0] != 'jump'],
                         [2200, 1200, 500])

    def test_route_execution_with_switch_action(self):
        """布莱梅路线：走一步 → 切餐厅 → 再走一步，方向和顺序都来自规则。"""
        island, device = build_island(values=rule('DailyBulaimei', 'left 700, switch, up 900'))
        switches = []
        island.island_walk_switch_restaurant = lambda: switches.append('switch')
        island.island_walk_route('DailyBulaimei')
        self.assertEqual(switches, ['switch'])
        self.assertEqual([call[2] for call in device.calls], [700, 900])
        # 第一步是左（x 变小），第二步是上（y 变小）
        self.assertLess(device.calls[0][1][0], device.calls[0][0][0])
        self.assertLess(device.calls[1][1][1], device.calls[1][0][1])

    def test_composite_durations_fallback(self):
        """复合路线（补滑）只改时长；个数对不上时回退默认值，不会越界。"""
        island, _ = build_island(values=rule('AirDropRetry', 'up 900, right 900, down 900'))
        self.assertEqual(island.island_walk_composite_durations('AirDropRetry', 3),
                         [900, 900, 900])

        island, _ = build_island(values=rule('AirDropRetry', 'up 900'))
        self.assertEqual(island.island_walk_composite_durations('AirDropRetry', 3),
                         [500, 500, 500])

    def test_verify_flag(self):
        island, _ = build_island(values={'IslandPlan.IslandWalk.DailyLishaEnable': True})
        self.assertTrue(island.island_walk_enabled('DailyLisha'))
        self.assertFalse(island.island_walk_enabled('DailyPateli'))

    def test_generated_defaults_match_registry(self):
        for route, steps in ISLAND_WALK_ROUTES.items():
            default = getattr(GeneratedConfig, f'IslandWalk_{route}', None)
            self.assertIsNotNone(default, msg=f'{route} 缺少生成配置默认值')
            self.assertEqual(parse_walk_rule(default), steps, msg=f'{route} 默认规则与代码路线不一致')


class TestIslandPlanTask(unittest.TestCase):
    """岛屿计划任务：跑勾选的走位校验，跑完（或没勾）推迟到第二天。"""

    def build_plan(self, values):
        config = StubConfig(values=values)
        plan = IslandPlan(config=config, device=StubDevice())
        visited = []
        plan.ui_goto = lambda *args, **kwargs: None
        plan.island_walk_route = lambda route: visited.append(route)
        return plan, config, visited

    def test_runs_ticked_routes_then_delays(self):
        values = {'IslandPlan.IslandWalk.DailyLishaEnable': True,
                  'IslandPlan.IslandWalk.PearlPortEnable': True}
        plan, config, visited = self.build_plan(values)
        plan.run()
        self.assertEqual(visited, ['DailyLisha', 'PearlPort'])
        self.assertEqual(len(config.delays), 1)
        self.assertEqual(config.delays[0]['task'], 'IslandPlan')

    def test_no_ticked_route_still_delays(self):
        plan, config, visited = self.build_plan({})
        plan.run()
        self.assertEqual(visited, [])
        self.assertEqual(len(config.delays), 1)
        self.assertEqual(config.delays[0]['task'], 'IslandPlan')


if __name__ == '__main__':
    unittest.main()
