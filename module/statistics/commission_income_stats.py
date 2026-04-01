# -*- coding: utf-8 -*-
"""
委托收益聚合统计模块。

从 Cl1Database 读取原始委托收益条目，
按日/周/月维度聚合，供统计页面渲染使用。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from module.logger import logger
from module.statistics.cl1_database import db as cl1_db

COMMISSION_TRACKED_ITEMS = ['Gem', 'Cube', 'Chip', 'Oil', 'Coin']

COMMISSION_ITEM_META = {
    'Gem':  {'color': '#ff4757', 'order': 0},
    'Cube': {'color': '#3742fa', 'order': 1},
    'Chip': {'color': '#8854d0', 'order': 2},
    'Oil':  {'color': '#2d3436', 'order': 3},
    'Coin': {'color': '#ffa502', 'order': 4},
}

COMMISSION_ITEM_NAME_MAP = {
    'Gems': 'Gem',
    'Cubes': 'Cube',
    'CognitiveChips': 'Chip',
    'Coins': 'Coin',
}


def _parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _filter_entries_by_period(
    entries: List[Dict[str, Any]],
    period: str,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """按时间维度过滤条目。

    Args:
        entries: 原始条目列表
        period: 'day' | 'week' | 'month'
        now: 参考时间，默认当前时间

    Returns:
        过滤后的条目列表
    """
    if now is None:
        now = datetime.now()

    if period == 'month':
        return entries

    filtered = []
    for entry in entries:
        ts = _parse_ts(entry.get('ts', ''))
        if ts is None:
            continue
        if period == 'day':
            if ts.date() == now.date():
                filtered.append(entry)
        elif period == 'week':
            week_start = now - timedelta(days=now.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
            if ts >= week_start:
                filtered.append(entry)

    return filtered


def get_commission_income_summary(
    instance: str,
    period: str = 'month',
    year: int = None,
    month: int = None,
) -> Dict[str, Any]:
    """获取委托收益聚合摘要。

    Args:
        instance: 实例名称
        period: 'day' | 'week' | 'month'
        year: 年份
        month: 月份

    Returns:
        {
            'period': str,
            'total_commissions': int,
            'items': {
                'Gem': {'total': int, 'count': int, 'avg': float},
                ...
            },
            'detail_rows': [
                {'name': str, 'color': str, 'total': int, 'count': int, 'avg': float},
                ...
            ],
        }
    """
    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    entries = cl1_db.get_commission_income(instance, year, month)
    filtered = _filter_entries_by_period(entries, period, now)

    totals: Dict[str, int] = {}
    counts: Dict[str, int] = {}
    total_commissions = 0

    for entry in filtered:
        total_commissions += entry.get('commission_count', 1)
        items = entry.get('items', {})
        for item_name, amount in items.items():
            mapped_name = COMMISSION_ITEM_NAME_MAP.get(item_name, item_name)
            if mapped_name not in COMMISSION_TRACKED_ITEMS:
                continue
            totals[mapped_name] = totals.get(mapped_name, 0) + int(amount)
            counts[mapped_name] = counts.get(mapped_name, 0) + 1

    items_summary = {}
    detail_rows = []
    for item_name in COMMISSION_TRACKED_ITEMS:
        total = totals.get(item_name, 0)
        count = counts.get(item_name, 0)
        avg = round(total / count, 1) if count > 0 else 0
        meta = COMMISSION_ITEM_META.get(item_name, {'color': '#888', 'order': 99})

        items_summary[item_name] = {
            'total': total,
            'count': count,
            'avg': avg,
        }
        detail_rows.append({
            'name': item_name,
            'color': meta['color'],
            'total': total,
            'count': count,
            'avg': avg,
        })

    return {
        'period': period,
        'total_commissions': total_commissions,
        'items': items_summary,
        'detail_rows': detail_rows,
    }


def get_recent_commission_entries(
    instance: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """获取最近 N 条委托收益记录（按时间降序）。

    Args:
        instance: 实例名称
        limit: 返回条数上限，默认 10

    Returns:
        最近 N 条委托记录，每条包含 ts, items, commission_count
    """
    now = datetime.now()
    all_entries = []
    for offset in range(3):
        dt = now - timedelta(days=offset * 32)
        entries = cl1_db.get_commission_income(instance, dt.year, dt.month)
        for entry in entries:
            ts = _parse_ts(entry.get('ts', ''))
            if ts is not None:
                all_entries.append(entry)
        if len(all_entries) >= limit:
            break

    all_entries.sort(key=lambda e: e.get('ts', ''), reverse=True)
    return all_entries[:limit]
