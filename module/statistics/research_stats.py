"""科研掉落统计汇总。

把 cl1_record.db 里逐次记录的科研掉落，按「科研期数 × 物品」聚合，供 WebUI
的科研统计页展示。

展示口径（用户 2026-09-24 定，金装已下线）：
- **期数视图**（第 1~9 期）：只统计**彩装备、彩图纸、金图纸**；
- **心智/物资视图**（不分期）：只看**心智单元与物资**，所有期数合并。

不分期的口径是必要的：只有彩装备与舰船图纸绑定期数，心智单元与物资
都是各期混着出的（见 alas-research-stats 技能文档第六节第 16 条）。
**金装备不再统计**（用户 2026-09-24 定）：它各期混着出、不绑期数，
且图标与彩装备相近，容易被认成彩装，所以连原本的「金装统计」视图一并撤掉。
其余物品照常入库，只是不出现在这里，将来想扩展口径改 should_show 即可。
"""

import json
import typing as t
from collections import defaultdict
from datetime import date, datetime, timedelta

from module.logger import logger

NAME_TABLE_PATH = './assets/stats/research_item_names.json'
# 中文名与稀有度的静态表，由 dev_tools/research_template_extract.py 生成

# 展示的稀有度门槛：4 = 金，5 = 彩。金装备图纸与改造图纸不入期数视图。
SHOW_RARITY = (4, 5)
# 界面上的稀有度标签，与游戏内一致：彩 > 金 > 紫 > 蓝
RARITY_LABELS = {6: '彩', 5: '彩', 4: '金', 3: '紫', 2: '蓝'}

# 视图口径
SCOPE_SERIES = 'series'
SCOPE_CONSUMABLE = 'consumable'
# 心智/物资视图认的物品（模板名）。这两件不绑期数，各期混着出，所以单开一个不分期的视图。
CONSUMABLE_ITEMS = ('CognitiveChips', 'Coins')
# 少数物品的名字推导不出模板名（如心智单元没有 T 后缀），内置兜底
BUILTIN_NAMES = {
    'CognitiveChips': {'zh': '心智单元', 'en': 'Cognitive Chips', 'rarity': 4},
}

_name_table: t.Optional[dict] = None


def load_name_table() -> dict:
    """读取模板名 -> 中文名/稀有度的静态表（进程内缓存）。

    Returns:
        dict: {模板名: {'zh': ..., 'en': ..., 'rarity': ...}}；表缺失时返回空字典。
    """
    global _name_table
    if _name_table is None:
        try:
            with open(NAME_TABLE_PATH, encoding='utf-8') as f:
                _name_table = json.load(f)
        except (OSError, ValueError):
            logger.warning(f'[科研统计] 名称表不存在或损坏: {NAME_TABLE_PATH}')
            _name_table = {}
    return _name_table


def item_info(template_name: str) -> dict:
    """取物品的中文名与稀有度。

    Args:
        template_name (str): 模板文件名（不含扩展名），如 'BlueprintValparaiso'。

    Returns:
        dict: {'zh': 中文名, 'en': 英文名, 'rarity': 稀有度}；查不到时用模板名兜底。
    """
    table = load_name_table()
    info = BUILTIN_NAMES.get(template_name) or table.get(template_name)
    if info:
        return info
    # 变体（_2/_3）与库外模板走兜底，至少让界面不是空白
    base, _, suffix = template_name.rpartition('_')
    if base and suffix.isdigit():
        info = table.get(base)
        if info:
            return info
    return {'zh': template_name, 'en': template_name, 'rarity': None}


def should_show(template_name: str, scope: str = SCOPE_SERIES) -> bool:
    """判断某件掉落是否进入当前视图。

    期数视图只展示彩装备、彩图纸与金图纸（心智单元另有「心智/物资」视图，
    不在这里出现；金装备各期混着出、已不再统计）；
    心智/物资视图只展示心智单元与物资。
    稀有度来自静态名称表，查不到时（模板没收录进表）一律不展示，避免用乱码占屏。

    Args:
        template_name (str): 模板文件名（不含扩展名）。
        scope (str): 视图口径，SCOPE_SERIES / SCOPE_CONSUMABLE。

    Returns:
        bool: 是否展示。
    """
    if scope == SCOPE_CONSUMABLE:
        return template_name in CONSUMABLE_ITEMS
    info = item_info(template_name)
    rarity = info.get('rarity')
    if rarity not in SHOW_RARITY:
        return False
    if template_name.startswith('Blueprint'):
        return True
    return rarity == 5


def _iter_entries(instance: str, start: datetime, end: datetime) -> t.Iterator[dict]:
    """跨月读取掉落条目。

    Args:
        instance (str): ALAS 实例名。
        start (datetime): 起始时间（含）。
        end (datetime): 结束时间（不含）。

    Yields:
        dict: 单条掉落记录。
    """
    from module.statistics.cl1_database import db

    cursor = start.replace(day=1)
    while cursor < end:
        for entry in db.get_research_drop(instance, cursor.year, cursor.month):
            yield entry
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)


def _entry_datetime(entry: dict) -> t.Optional[datetime]:
    """取一条掉落记录的时间。

    记录里 `ts` 与 `completed_at` 都是 ISO 时间串；缺失或损坏时返回 None。

    Args:
        entry (dict): 单条掉落记录。

    Returns:
        datetime: 记录时间；解析不出来时 None。
    """
    for key in ('ts', 'completed_at'):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            continue
    return None


def _entry_date(entry: dict) -> t.Optional[date]:
    """取一条掉落记录的日期。

    调用方据此跳过「今日/本月」计数，而不是把缺失值当成今天。

    Args:
        entry (dict): 单条掉落记录。

    Returns:
        date: 记录日期；解析不出来时 None。
    """
    stamp = _entry_datetime(entry)
    return stamp.date() if stamp else None


def in_window(entry: dict, start: datetime, end: datetime) -> bool:
    """判断记录是否落在统计窗口内。

    `_iter_entries` 是按月份分区取记录的，只能保证落在窗口覆盖的那几个月里；
    日/周视图还要按时间精确筛一遍。时间戳缺失的记录不放进任何窗口
    （与「今日/本月」计数同样的口径：不把缺失当今天）。

    Args:
        entry (dict): 单条掉落记录。
        start (datetime): 窗口起点（含）。
        end (datetime): 窗口终点（不含）。

    Returns:
        bool: 是否在窗口内。
    """
    stamp = _entry_datetime(entry)
    return stamp is not None and start <= stamp < end


def series_item_names(series: int) -> t.List[str]:
    """某一期的固定物品清单：该期各艘船的图纸 + 该期的彩装图纸（模板名）。

    清单来自名称表的 `series` 字段（由 dev_tools/research_template_extract.py 按游戏
    数据生成）。同一件道具可能有多个底色变体（`_2`/`_3`），按基名去重只留一个；
    船图纸排在彩装前面，与界面上「每期舰船的模板和彩图」的顺序一致。

    Args:
        series (int): 科研期数。

    Returns:
        list[str]: 模板名列表；该期没有收录任何物品时为空。
    """
    table = load_name_table()
    picked: t.Dict[str, str] = {}
    for name, info in table.items():
        if info.get('series') != series:
            continue
        base, _, suffix = name.rpartition('_')
        key = base if base and suffix.isdigit() else name
        # 变体与基名只留一个；名字小的（不带后缀的基名）优先
        if key not in picked or name < picked[key]:
            picked[key] = name
    return sorted(picked.values(), key=lambda name: (not name.startswith('Blueprint'), name))


def collect(
    instance: str,
    days: int = 90,
    series: int = 0,
    scope: str = SCOPE_SERIES,
    start: t.Optional[datetime] = None,
    end: t.Optional[datetime] = None,
) -> dict:
    """汇总一段时间内的科研掉落。

    Args:
        instance (str): ALAS 实例名。
        days (int): 回溯天数；给了 start/end 时忽略。
        series (int): 只看某一期（1~9）；0 表示最新有记录的一期。不分期的口径忽略此参数。
        scope (str): 视图口径，SCOPE_SERIES / SCOPE_CONSUMABLE。
        start (datetime): 统计起点（含）；缺省按 days 往前推。
        end (datetime): 统计终点（不含）；缺省取当前时间。

    Returns:
        dict: {
            'scope': 视图口径,
            'series': 实际展示的期数（不分期的口径为 0）,
            'available': 有记录的期数列表（降序）,
            'items': [{'name': 模板名, 'zh': 中文名, 'rarity': ..., 'amount': 总数量,
                       'count': 掉落次数, 'avg': 平均每次, 'today': 今日数量,
                       'month': 本月数量}, ...],
            'series_items': 期数视图的固定清单（各期船图纸 + 彩装，含本期没掉过的）,
            'total': 总掉落数量,
            'today': 今日掉落总数量,
            'month': 本月掉落总数量,
            'records': 纳入统计的记录条数,
        }
    """
    now = datetime.now()
    if start is None:
        start = now - timedelta(days=max(1, days))
    if end is None:
        end = now + timedelta(seconds=1)
    entries = [entry for entry in _iter_entries(instance, start, end)
               if in_window(entry, start, end)]

    available = sorted({int(e.get('series') or 0) for e in entries if e.get('series')}, reverse=True)
    if scope != SCOPE_SERIES:
        picked = entries
    else:
        if series <= 0:
            series = available[0] if available else 0
        picked = [e for e in entries if int(e.get('series') or 0) == series]

    today = now.date()
    this_month = (now.year, now.month)
    amount_by_item: t.Dict[str, int] = defaultdict(int)
    count_by_item: t.Dict[str, int] = defaultdict(int)
    today_by_item: t.Dict[str, int] = defaultdict(int)
    month_by_item: t.Dict[str, int] = defaultdict(int)
    for entry in picked:
        stamp = _entry_date(entry)
        for name, amount in (entry.get('items') or {}).items():
            if not should_show(name, scope=scope):
                continue
            amount = int(amount)
            amount_by_item[name] += amount
            count_by_item[name] += 1
            if stamp == today:
                today_by_item[name] += amount
            if stamp is not None and (stamp.year, stamp.month) == this_month:
                month_by_item[name] += amount

    def build(name: str) -> dict:
        info = item_info(name)
        amount = amount_by_item.get(name, 0)
        count = count_by_item.get(name, 0)
        return {
            'name': name,
            'zh': info.get('zh') or name,
            'en': info.get('en') or '',
            'rarity': info.get('rarity'),
            'amount': amount,
            'count': count,
            'avg': round(amount / count, 1) if count else 0,
            'today': today_by_item.get(name, 0),
            'month': month_by_item.get(name, 0),
        }

    # 期数视图按固定清单铺开：本期没掉过的也留一行（数量和次数为 0），
    # 与委托收益的「资源格子」一致。清单之外掉进来的（比如项目赠送的别期图纸）
    # 追加在后面，不丢数据。
    fixed = series_item_names(series) if scope == SCOPE_SERIES else []
    items = [build(name) for name in fixed]
    extra = [name for name in amount_by_item if name not in set(fixed)]
    # 彩在前、金在后，同稀有度按数量降序
    extra.sort(key=lambda name: (-(item_info(name).get('rarity') or 0), -amount_by_item[name], name))
    items.extend(build(name) for name in extra)

    return {
        'scope': scope,
        'series': 0 if scope != SCOPE_SERIES else series,
        'available': available,
        'items': items,
        'series_items': fixed,
        'total': sum(item['amount'] for item in items),
        'today': sum(today_by_item.values()),
        'month': sum(month_by_item.values()),
        'records': len(picked),
    }
