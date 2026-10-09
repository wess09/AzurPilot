"""岛屿走位路线的集中定义与规则解析。

每条路线是一串 `(方向或动作, 时长毫秒)`；方向取值为 `up` / `down` / `left` / `right`，
固定动作为 `jump`（点一次跳跃按钮）与 `switch`（切换到啾咖啡餐厅），它们不占用时长。

代码里的默认值在这里集中维护；运行时可以用岛屿计划的全局配置
`IslandPlan.IslandWalk.<路线名>` 覆盖整条规则（对所有控制方式生效），例如：

    up 3000, right 800, jump, up 1200

规则字符串写法：

- 逗号、分号或换行分隔，方向大小写不敏感；
- `up 3000` / `right 800`：方向 + 时长，**纯整数按毫秒**；
- `up 3.0` / `left 1.5s`：带小数点或 `s` 后缀时按**秒**换算（1.5s = 1500 毫秒）；
- `jump` / `switch` 单独成项即可，后面写数值会被忽略；
- 解析失败、方向非法或个数为 0 时返回 `None`，调用方回退代码默认值。
"""
import math
from typing import Dict, Optional, Tuple

WalkStep = Tuple[str, int]
WalkRoute = Tuple[WalkStep, ...]

# 不需要时长的固定动作：jump=点跳跃按钮，switch=切换到啾咖啡餐厅
ISLAND_WALK_ACTIONS = ('jump', 'switch')
ISLAND_WALK_DIRECTIONS = ('up', 'down', 'left', 'right') + ISLAND_WALK_ACTIONS

# 与 WebUI「岛屿计划 - 岛屿走位规则」一一对应；键名即配置项后缀。
ISLAND_WALK_ROUTES: Dict[str, WalkRoute] = {
    # 好友岛每日补给（J 为点击跳跃按钮）
    'AirDrop': (
        ('up', 3000), ('right', 800), ('up', 2000),
        ('jump', 0),
        ('up', 1200), ('right', 2000), ('up', 6500), ('right', 1000),
        ('up', 2300), ('right', 2000), ('up', 4000), ('right', 2600), ('up', 500),
        ('jump', 0),
        ('up', 1300),
    ),
    # 拿不到补给时的补滑
    'AirDropRetry': (('up', 500), ('right', 500), ('down', 500)),
    # 自己岛屿领取补给后的下移
    'AirDropSelf': (('down', 1000),),
    'DailyLakeniya': (('up', 2000), ('right', 1800), ('up', 500)),
    'DailyLuxi': (('left', 800), ('up', 5500), ('left', 1000), ('up', 3700)),
    'DailyAobulaien': (('right', 4600), ('up', 5100), ('right', 1100)),
    'DailyQiaoan': (('right', 6000), ('down', 3000), ('right', 2300)),
    'DailyMorningdewFarm': (('left', 500), ('down', 200)),
    'DailyHemo': (('left', 600), ('up', 2000), ('left', 800)),
    'DailyMeili': (('right', 1800), ('down', 600)),
    'DailyAolipike': (('left', 500), ('down', 1500), ('left', 1700), ('down', 1900)),
    'DailyAmoma': (('up', 1500), ('left', 400)),
    'DailyPateli': (('left', 2200), ('jump', 0), ('left', 1200), ('up', 500)),
    # 中间要切到啾咖啡餐厅，因此用 switch 占一步
    'DailyBulaimei': (('up', 2600), ('switch', 0), ('left', 600)),
    'DailyLisha': (
        ('up', 3000), ('left', 2000), ('up', 5500),
        ('right', 300), ('up', 2200), ('left', 1100),
    ),
    'PearlAssembly': (('up', 2500), ('right', 1700), ('down', 1700), ('right', 500)),
    'PearlPort': (('left', 2500), ('jump', 0), ('left', 3000), ('down', 1000)),
}

# 走位时长的合法区间（毫秒）：过小滑不动，过大通常是写错了单位。
ISLAND_WALK_MIN_HOLD = 100
ISLAND_WALK_MAX_HOLD = 20000


def format_walk_rule(steps: WalkRoute) -> str:
    """把路线格式化成配置里显示的规则字符串。"""
    return ', '.join(
        direction if direction in ISLAND_WALK_ACTIONS else f'{direction} {hold}'
        for direction, hold in steps
    )


def parse_walk_duration(value: str) -> Optional[int]:
    """解析单个时长：纯整数按毫秒，带小数点或 s 后缀按秒。

    Args:
        value: 形如 `3000` / `0.8` / `1.5s` / `1500ms` 的文本。

    Returns:
        Optional[int]: 毫秒时长；无法解析时返回 None。
    """
    text = value.strip().lower()
    if not text:
        return None
    unit = None
    if text.endswith('ms'):
        unit, text = 'ms', text[:-2]
    elif text.endswith('s'):
        unit, text = 's', text[:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    # nan / inf 这类非有限值不能进 round/int，直接判非法并回退默认值
    if not math.isfinite(number):
        return None
    if unit == 's' or (unit is None and '.' in text):
        number *= 1000
        if not math.isfinite(number):
            return None
    hold = int(round(number))
    return max(ISLAND_WALK_MIN_HOLD, min(ISLAND_WALK_MAX_HOLD, hold))


def parse_walk_rule(text: str) -> Optional[WalkRoute]:
    """把规则字符串解析成走位步骤。

    Args:
        text: 形如 `up 3000, right 800, jump, up 1200` 的规则字符串。

    Returns:
        Optional[WalkRoute]: 解析结果；文本为空、方向非法或时长缺失时返回 None。
    """
    if text is None:
        return None
    steps = []
    normalized = str(text).replace('，', ',').replace('；', ';')
    for raw in normalized.replace(';', ',').replace('\n', ',').split(','):
        token = raw.strip()
        if not token:
            continue
        parts = token.split()
        direction = parts[0].lower()
        if direction not in ISLAND_WALK_DIRECTIONS:
            return None
        if direction in ISLAND_WALK_ACTIONS:
            steps.append((direction, 0))
            continue
        if len(parts) != 2:
            return None
        hold = parse_walk_duration(parts[1])
        if hold is None:
            return None
        steps.append((direction, hold))
    return tuple(steps) if steps else None
