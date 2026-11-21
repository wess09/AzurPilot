"""作战委托为已安排的出击保留时间窗口。"""

from datetime import datetime, timedelta


SORTIE_TASKS = frozenset({
    'Main', 'Main2', 'Main3', 'Event', 'Event2', 'Event3', 'EventSp',
    'EventA', 'EventB', 'EventC', 'EventD', 'WarArchives', 'Hard', 'Sos',
    'GemsFarming', 'ThreeOilLowCost', 'Ambush11', 'Raid', 'RaidDaily',
    'RaidScuttle', 'Coalition', 'CoalitionSp', 'CoalitionScuttle',
    'Hospital', 'HospitalEvent', 'MaritimeEscort',
})


def next_sortie(config):
    """返回最近一次已启用的出击任务及时间，忽略禁用与无效计划。"""
    data = getattr(config, 'data', {})
    candidates = []
    for name in SORTIE_TASKS:
        schedule = data.get(name, {}).get('Scheduler', {})
        target = schedule.get('NextRun')
        if schedule.get('Enable') and isinstance(target, datetime):
            candidates.append((name, target))
    return min(candidates, key=lambda item: (item[1], item[0])) if candidates else None


def fit_sortie_window(count, needed, deadline, now):
    """按单次耗时限制委托次数，给下次出击预留 30 秒切换界面。"""
    if count <= 0 or needed <= timedelta():
        return 0
    available = deadline - now - timedelta(seconds=30)
    return max(0, min(count, int(available // (needed / count))))


def daily_runs(config, reset, now):
    """只统计本次服务器刷新后、已确认启动的普通委托批次。"""
    record = getattr(config, 'OperationHandover_DailyRunCountRecord', None)
    if not isinstance(record, datetime) or not reset <= record <= now:
        return 0
    return max(0, int(getattr(config, 'OperationHandover_DailyRunCountUsed', 0)))
