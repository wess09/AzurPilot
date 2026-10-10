"""复用既有统计源，为分类页面提供指标、时间线和可导出的明细。"""
import math
import threading
from datetime import datetime, timedelta

from module.api.protocol import ApiError
from module.persistence.database import configured_database, get_database

_loot_lock = threading.Lock()


def get_statistics_fingerprint(instance: str, directory=None) -> str:
    """检测总库、已提交 WAL 和实例配置的修改时间与大小。"""
    database = get_database(directory)
    parts = []
    for label, path in (('business', database.path), ('wal', database.path.with_name(database.path.name + '-wal')),
                        ('config', database.directory / (instance + '.json'))):
        try:
            stat = path.stat()
            parts.append(f'{label}:{stat.st_mtime_ns}:{stat.st_size}')
        except OSError:
            parts.append(label + ':none')
    return ';'.join(parts)


@configured_database
def refresh_loot(configs, instance: str) -> dict:
    """重新计算已有本地掉落记录，复用旧界面刷新操作。

    Args:
        configs: 配置管理服务实例。
        instance: 实例名称。

    Returns:
        dict: 包含刷新成功标识的字典。
    """
    configs.path(instance)
    from module.statistics.azurstats import AzurStats
    with _loot_lock:
        AzurStats.get_meowofficer_farming(instance=instance)
    return {'refreshed': True}


RESOURCE_LABELS = {
    'Oil': '石油', 'Coin': '物资', 'Gem': '钻石', 'Cube': '心智魔方', 'Pt': '活动 PT',
    'Core': '核心数据', 'Medal': '荣誉勋章', 'Merit': '功勋', 'GuildCoin': '舰队币',
    'ActionPoint': '行动力', 'YellowCoin': '作战补给凭证', 'PurpleCoin': '特别兑换凭证',
}


def table(title: str, columns: list[str], rows: list[list], note: str = '', default_sort: dict = None) -> dict:
    """构造前端通用的数据表格结构字典。

    Args:
        title: 表格标题。
        columns: 列名称列表。
        rows: 数据行列表。
        note: 表格备注或提示说明。
        default_sort: 默认排序规则字典，如 ``{'index': 0, 'descending': True}``。

    Returns:
        dict: 格式化后的表格结构字典。
    """
    result = {'title': title, 'columns': columns, 'rows': rows, 'note': note}
    if default_sort is not None:
        result['defaultSort'] = default_sort
    return result


# 1970-01-01 的日期序数：与日期序数相减即可得到协调世界时秒数。
EPOCH_ORDINAL = 719163


def wallclock_micros(timestamp: datetime) -> int:
    """把墙上时钟编码为微秒整数：按协调世界时解释，客户端同样按协调世界时取回，换时区访问也不偏移。"""
    seconds = (timestamp.toordinal() - EPOCH_ORDINAL) * 86400         + timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
    return seconds * 1000000 + timestamp.microsecond


def compact_axis(series_list: list) -> dict:
    """时间轴完全一致时改列式下发：共用一份时间轴，数值按序列成数组。

    九条资源序列取自同一批快照，时刻逐点相同；逐点各带一份时间戳会造成九倍重复。
    轴不一致（其它分类可能不同源）或没有点时按逐点形式返回，避免前端对不齐。

    Args:
        series_list: 报表里的序列列表。

    Returns:
        dict: 含 axis 与列式 series，或原样的 series。
    """
    if not series_list or not series_list[0]['points']:
        return {'series': series_list}
    times = [point['t'] for point in series_list[0]['points']]
    if any([point['t'] for point in item['points']] != times for item in series_list):
        return {'series': series_list}
    columns = []
    for item in series_list:
        column = {'key': item['key'], 'label': item['label'],
                  'values': [point['v'] for point in item['points']]}
        if item.get('icon'):
            column['icon'] = item['icon']
        sources = [point.get('s', '') for point in item['points']]
        if any(sources):
            column['sources'] = sources
        columns.append(column)
    return {'axis': times, 'series': columns}


def series(rows: list[dict], key: str, label: str) -> dict:
    """提取时间线序列数据，保留真实采集时间与来源，跳过无效值。

    绝不把缺失值补充为零。

    Args:
        rows: 包含时间戳与属性值的数据字典列表。
        key: 数据字段键名。
        label: 展现标签名称。

    Returns:
        dict: 包含字段键、标签及按时间排序的数据点列表字典。
    """
    points = []
    for row in rows:
        value = row.get(key)
        try:
            timestamp = datetime.fromisoformat(str(row['ts']))
            if value is None or not math.isfinite(float(value)):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        point = {'t': wallclock_micros(timestamp), 'v': float(value)}
        if row.get('source'):
            point['s'] = row['source']
        points.append(point)
    points.sort(key=lambda item: item['t'])
    return {'key': key, 'label': label, 'points': points}


def _research_record_rows(instance: str, start: datetime, end: datetime, scope: str) -> list[list]:
    """获取指定区间内的科研掉落记录，供「掉落记录」表使用。

    只列当前视图认定的物品：那一次只掉了本视图不看的物品时，不算作一次有效掉落。

    Args:
        instance: 实例名称。
        start: 区间起点（含）。
        end: 区间终点（不含）。
        scope: 视图口径。

    Returns:
        list[list]: 表格数据行列表，每行为 [时间, 项目, 期数, 掉落物]。
    """
    from module.statistics.cl1_database import db as cl1_db
    from module.statistics.research_stats import item_info, should_show

    entries = []
    cursor = start.replace(day=1)
    while cursor < end:
        entries.extend(cl1_db.get_research_drop(instance, cursor.year, cursor.month))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    entries = [entry for entry in entries
               if start.isoformat(sep=' ') <= str(entry.get('ts', '')).replace('T', ' ') < end.isoformat(sep=' ')]
    entries.sort(key=lambda entry: entry['ts'])
    rows = []
    for entry in entries:
        shown = [(item_info(name)['zh'], amount) for name, amount in (entry.get('items') or {}).items()
                 if should_show(name, scope=scope)]
        if not shown:
            continue
        rows.append([
            entry['ts'], entry.get('project') or '—', entry.get('series') or '—',
            '、'.join(f'{zh} x{amount}' for zh, amount in shown),
        ])
    return rows


def _month_end(moment: datetime) -> datetime:
    """计算指定时刻所在月份的下月 1 号（0 点）。

    Args:
        moment: 基准时间对象。

    Returns:
        datetime: 下月首日零点的时间对象。
    """
    return (moment.replace(day=28) + timedelta(days=4)).replace(day=1)


def _trend_window(selected: datetime, now: datetime, period: str, days: int) -> tuple:
    """给出资源类趋势窗口的起止时间：日取最近 N 天，周取本周，月取选定月份。"""
    if period == 'month':
        start = selected.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 窗口两端都含，上界取本月最后一刻。
        return start, _month_end(start) - timedelta(microseconds=1)
    if period == 'week':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        return start, now
    return now - timedelta(days=days), now


@configured_database
def report(configs, instance: str, category: str, month: str, days: int, period: str,
           research_series: int = 0, research_scope: str = 'series', loot_task: str = None,
           include_series: bool = True) -> dict:
    """生成并获取指定维度的统计报表。"""
    configs.path(instance)
    return _report(configs, instance, category, month, days, period,
                   research_series, research_scope, loot_task, include_series)


def _report(configs, instance: str, category: str, month: str, days: int, period: str,
            research_series: int = 0, research_scope: str = 'series', loot_task: str = None,
            include_series: bool = True) -> dict:
    """生成并获取指定维度的统计报表。

    支持资源变动趋势、大世界运营、委托收益、舰船经验以及科研和大世界掉落明细。

    Args:
        configs: 配置管理服务实例。
        instance: 实例名称。
        category: 统计分类（resources, opsi, action, commission, ships, research, loot, storage）。
        month: 目标月份，格式为 ``YYYY-MM``。
        days: 趋势查询天数。
        period: 汇总周期（day, week, month）。
        research_series: 科研期数过滤编号。
        research_scope: 科研口径范围（series, consumable 等）。
        loot_task: 掉落所属任务过滤名称。

    Returns:
        dict: 统计报表数据字典，包含 metrics 指标、series 时间序列、tables 表格及 notes 备注。

    Raises:
        ApiError: 月份格式错误或超出有效年份范围 (INVALID_PARAMS)。
    """
    now = datetime.now()
    try:
        selected = datetime.strptime(month, '%Y-%m') if month else now.replace(day=1)
    except ValueError as exc:
        raise ApiError('INVALID_PARAMS', '月份格式应为 YYYY-MM') from exc
    if not 2020 <= selected.year <= 9998:
        raise ApiError('INVALID_PARAMS', '统计月份应在 2020 至 9998 年之间')
    year, month_number = selected.year, selected.month
    result = {'instance': instance, 'category': category, 'month': f'{year:04d}-{month_number:02d}',
              'metrics': [], 'series': [], 'tables': [], 'notes': []}

    def metric(label, value, unit='', icon=None):
        entry = {'label': label, 'value': value, 'unit': unit}
        if icon:
            # 前端按 icon 找图标，找不到就用 label 查内置表；科研物品写 'research:<模板名>'
            entry['icon'] = icon
        result['metrics'].append(entry)

    if category == 'storage':
        from pathlib import Path
        from module.statistics.storage_snapshot import get_storage_timeline, latest_snapshot
        from module.storage.statistics_recognition import StorageCatalog
        catalog = StorageCatalog()
        database = getattr(configs, 'database', None) or get_database(Path(configs.path(instance)).parent)
        snapshot = latest_snapshot(instance, database=database)
        icons = {item['id']: 'storage:' + item['templates'][0].removeprefix('assets/stats/').removesuffix('.png')
                 for item in catalog.items}
        if snapshot is None:
            result['notes'].append('尚未运行仓库统计任务。运行并完成完整扫描后才会更新物品数量。')
            items = [dict(item, amount=None) for item in catalog.items]
        else:
            items = snapshot['items']
            result['notes'].append(f"最近完整扫描：{snapshot['finished_at']}；服务器：{snapshot['server']}；复核 {snapshot['pages']} 页。")
            if snapshot['catalog_version'] != catalog.version:
                result['notes'].append('模板目录已更新，当前显示上次扫描结果，请重新运行仓库统计任务。')
        result['notes'].append('刷新只读取已有快照；未发现的物品显示“未发现”，不把无法确认的数量当成 0。')
        result['tables'] = [table('仓库物品', ['图标', '物品', '分类', '数量', '状态'],
            [[icons.get(item['id'], ''), item['name'], item['group'], item['amount'],
              '未扫描' if snapshot is None else '已复核' if item['amount'] is not None else '未发现']
             for item in items])]
        result['tables'][0]['note'] = ' '.join(result['notes'])
        if include_series:
            start, end = _trend_window(selected, now, period, days)
            rows = (get_storage_timeline(instance, since=start.isoformat(sep=' '), until=end.isoformat(sep=' '),
                                         through_id=snapshot['id'], database=database) if snapshot else [])
            if len(rows) > 50000:
                rows = rows[-50000:]
                result['notes'].append('记录超过 50,000 条，当前展示最近 50,000 条，请缩短时间范围查看细节。')
            result['series'] = [dict(series(rows, item['id'], item['name']), icon=icons[item['id']])
                                for item in catalog.items]
            result['notes'].append('趋势与原始记录只包含成功扫描中已确认的数量；未发现的物品不补为零。')
        return result

    if category == 'resources':
        if include_series:
            from module.statistics.resource_stats import RESOURCE_COLUMNS, get_resource_timeline
            start, end = _trend_window(selected, now, period, days)
            # 窗口过滤下推到 SQL，只读窗口内的行。
            # 该分类展示的序列不含大世界货币，跳过密文解密（它们是资源快照里解密开销最大的一批）。
            rows = get_resource_timeline(instance, limit=50001, since=start.isoformat(sep='T'),
                                         until=end.isoformat(sep='T'), include_opsi=False)
            if len(rows) > 50000:
                result['notes'].append('记录超过 50,000 条，当前展示最近 50,000 条，请缩短时间范围查看细节。')
                rows = rows[-50000:]
            resource_items = [
                (name, key) for name, key in RESOURCE_COLUMNS.items()
                if name not in ('ActionPoint', 'YellowCoin', 'PurpleCoin')
            ]
            result['series'] = [series(rows, key, RESOURCE_LABELS[name]) for name, key in resource_items]
        return result

    from module.statistics.cl1_database import db
    if category == 'opsi':
        from module.statistics.opsi_month import get_opsi_stats, compute_monthly_cl1_akashi_ap
        summary = get_opsi_stats(instance).summary(year, month_number)
        battles = summary['total_battles']
        # 沿用旧界面口径：向上取整，每轮侵蚀1消耗 5 行动力。
        rounds = (battles + 1) // 2
        cost = rounds * 5
        purchased = compute_monthly_cl1_akashi_ap(year, month_number, instance_name=instance)
        encounters = summary['akashi_encounters']
        devices = summary['siren_research_devices']
        for label, value, unit in [
            ('战斗次数', battles, '场'), ('出击轮数', rounds, '轮'), ('出击消耗', cost, '行动力'),
            ('明石遭遇', encounters, '次'), ('明石遭遇率', round(encounters / rounds * 100, 2) if rounds else None, '%'),
            ('塞壬研究装置', devices, '个'), ('装置获取率', round(devices / rounds * 100, 2) if rounds else None, '%'),
            ('购买行动力', purchased, ''), ('平均每次购买', round(purchased / encounters, 2) if encounters else None, ''),
            ('净行动力', purchased - cost, ''), ('循环效率', round((purchased - cost) / cost * 100, 2) if cost else None, '%'),
        ]:
            metric(label, value, unit)
        # 收获卡片同时给出舰船经验侧的效率与今日进度，与「舰船经验」页同一批数据。
        from module.statistics.ship_exp_stats import ShipExpStats
        exp_stats = ShipExpStats(instance_name=instance)
        today_exp = exp_stats.get_today_stats() or {}
        metric('平均战斗时长', exp_stats.get_average_battle_time(), '秒')
        metric('预估经验效率', exp_stats.get_exp_per_hour(), '/小时')
        metric('今日战斗', today_exp.get('battle_count'), '场')
        metric('今日经验', today_exp.get('total_exp_gained'))
        metric('今日运行', round(today_exp['total_run_time'] / 60, 1) if 'total_run_time' in today_exp else None, '分钟')
        rows = []
        for hazard in (3, 5):
            data = db.get_meow_stats(instance, year, month_number, hazard_level=hazard)
            rows.append([hazard, data.get('battle_count'), data.get('effective_rounds'),
                         data.get('avg_battle_time'), data.get('avg_round_time'),
                         data.get('siren_research_devices'), round(data.get('siren_research_rate', 0) * 100, 2),
                         {'exact': '实测', 'estimated': '估算', 'none': '暂无记录'}.get(data.get('by_hazard', {}).get(str(hazard), {}).get('source', 'none'))])
        result['tables'].append(table('短猫运行统计', ['侵蚀等级', '战斗次数', '有效轮数', '平均战斗秒数', '平均每轮秒数', '研究装置', '获取率（%）', '统计来源'], rows))
        # 收获只作卡片渲染：卡片 / 表格两种呈现由前端布局按页切换，后端不另出表。
    elif category == 'action':
        from module.statistics.opsi_month import get_ap_timeline, get_coins_timeline
        ap = get_ap_timeline(year, month_number, instance)
        coins = get_coins_timeline(year, month_number, instance)
        ap_normalized = [
            {**row, 'ap': row['ap_total'] if row.get('ap_total') is not None else row.get('ap')}
            for row in ap
        ]
        if include_series:
            result['series'] = [series(ap_normalized, 'ap', '行动力'), series(ap, 'asset', '行动力资产'),
                                series(ap, 'distance', '海里数'), series(coins, 'yellow_coins', '作战补给凭证'),
                                series(coins, 'purple_coins', '特别兑换凭证')]
    elif category == 'commission':
        from module.statistics.commission_income_stats import get_commission_income_interval_summary
        start = selected.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if period != 'month':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if period == 'week':
                start -= timedelta(days=start.weekday())
            end = now
        summary = get_commission_income_interval_summary(instance, start, end)
        metric('完成委托', summary['total_commissions'], '项')
        labels = {**RESOURCE_LABELS, 'Chip': '心智单元'}
        for name, item in summary['items'].items():
            metric(labels[name], item['total'])
        result['tables'].append(table('委托收益明细', ['资源', '总收益', '掉落记录数', '平均每次掉落'],
            [[labels[item['name']], item['total'], item['count'], item['avg']] for item in summary['detail_rows']]))
        entries = []
        cursor = start.replace(day=1)
        while cursor < end:
            entries.extend(db.get_commission_income(instance, cursor.year, cursor.month))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        entries = [item for item in entries if start.isoformat(sep=' ') <= str(item.get('ts', '')).replace('T', ' ') < end.isoformat(sep=' ')]
        entries.sort(key=lambda item: item['ts'])
        from module.statistics.commission_income_stats import COMMISSION_ITEM_NAME_MAP
        normalized = [{**item, 'items': {COMMISSION_ITEM_NAME_MAP.get(k, k): v for k, v in item.get('items', {}).items()}} for item in entries]
        result['tables'].append(table('委托结算记录', ['时间', '委托数量', '钻石', '魔方', '心智单元', '石油', '物资'],
            [[item['ts'], item.get('commission_count', 1), *[item['items'].get(k) for k in ('Gem', 'Cube', 'Chip', 'Oil', 'Coin')]] for item in normalized],
            default_sort={'index': 0, 'descending': True}))
        if include_series:
            result['series'] = [series([{'ts': item['ts'], **item['items']} for item in normalized], k, labels[k]) for k in ('Gem', 'Cube', 'Chip', 'Oil', 'Coin')]
    elif category == 'ships':
        from module.statistics.ship_exp_stats import ShipExpStats
        from module.statistics.opsi_month import get_opsi_stats
        stats = ShipExpStats(instance_name=instance)
        data = stats.data
        metric('目标等级', data.get('target_level', 125))
        metric('预估经验效率', stats.get_exp_per_hour(), '/小时')
        metric('平均战斗时长', stats.get_average_battle_time(), '秒')
        metric('平均每轮时长', stats.get_average_round_time(), '秒')
        metric('短猫平均战斗时长', stats.get_average_meow_battle_time(), '秒')
        today = stats.get_today_stats() or {}
        metric('今日战斗', today.get('battle_count'), '场')
        metric('今日经验', today.get('total_exp_gained'))
        metric('今日运行', round(today['total_run_time'] / 60, 1) if 'total_run_time' in today else None, '分钟')
        battles = get_opsi_stats(instance).summary()['total_battles']
        progress = stats.get_all_progress(battles)
        result['tables'].append(table('舰船升级进度', ['位置', '等级', '当前经验', '累计经验', '目标经验', '检测后战斗数', '还需经验', '还需战斗', '预估用时'],
            [[p.get(k) for k in ('position', 'level', 'current_exp', 'total_exp', 'target_exp', 'battles_done', 'exp_needed', 'battles_needed', 'time_needed')] for p in progress],
            f"上次检测：{data.get('last_check_time', '尚未检测')}；舰队：{data.get('fleet_index', '—')}。"))
        daily = [{'ts': key, **value} for key, value in sorted(data.get('daily_stats', {}).items())]
        if include_series:
            result['series'] = [series(daily, 'total_exp_gained', '每日经验'), series(daily, 'battle_count', '每日战斗'), series(daily, 'total_run_time', '每日运行秒数')]
    elif category == 'research':
        from module.statistics.research_stats import (
            CONSUMABLE_ITEMS, collect, item_info, RARITY_LABELS, SCOPE_SERIES)
        # 走表格的 note 而不是 notes：前端只渲染 tables，notes 仅在导出 CSV 时用到，
        # 放在那里用户界面上什么都看不到（会以为功能坏了）。
        # 两个视图（期数 / 心智物资）共用同一套布局与列名：上面收益卡片、中间收获明细、
        # 下面原始掉落记录——前端按数据形状渲染，这里保持一致即得一致版式。
        detail_columns = ['图标', '物品', '稀有度', '总收益', '掉落记录数', '平均每次掉落']
        record_columns = ['时间', '项目', '期数', '掉落物']
        # 两个视图都照委托收益的样子按「汇总周期」框时间（period=month 看选定月份，
        # day/week 看今天/本周）；差别只在期数视图还按期过滤。
        start = selected.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = _month_end(start)
        if period != 'month':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if period == 'week':
                start -= timedelta(days=start.weekday())
            end = now

        if research_scope != SCOPE_SERIES:
            # 不分期：心智单元与物资各期混着出，只有时间范围跟着「汇总周期」走。
            summary = collect(instance, series=research_series, scope=research_scope, start=start, end=end)
            title = '心智/物资收获明细'
            note = ('心智单元与物资不绑期数、各期混着出，所以这里不分期统计'
                    '（时间范围跟着「汇总周期」走）；清单里没掉过的也留一行，便于对照。'
                    '图标暂用当前物品模板。')
            if not summary['records']:
                result['tables'].append(table(title, detail_columns, [], note=(
                    '这段时间里没有掉落记录。「汇总周期」选今天/本周时窗口很短，'
                    '改成「选定月份」能看得更多；统计在领奖时自动完成，把「科研截图」设为'
                    '「保存」或「上传」即可（两者都会统计，区别只是要不要把截图落盘）。')))
                return result
            record_rows = _research_record_rows(instance, start, end, research_scope)
            metric('掉落记录', len(record_rows), '次')
            by_name = {item['name']: item for item in summary['items']}
            rows = []
            for name in CONSUMABLE_ITEMS:
                # 两件物品都留一行（没掉过的显示「—」），与期数视图的固定清单一致
                info = item_info(name)
                entry = by_name.get(name)
                amount = entry['amount'] if entry else 0
                rows.append([f'research:{name}', info['zh'],
                             RARITY_LABELS.get(info.get('rarity'), '—'),
                             amount or None, (entry['count'] if entry else 0) or None,
                             (entry['avg'] if entry else 0) or None])
                metric(info['zh'], amount or None, icon=f'research:{name}')
            # 三档时间总计固定看今日 / 本月 / 选定月份，不受上面「汇总周期」影响；
            # 三者窗口常常重合（选的就是本月时是同一个），同窗口只查一次库。
            windows = (
                ('今日总计', now.replace(hour=0, minute=0, second=0, microsecond=0), now + timedelta(seconds=1)),
                ('本月总计', now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), None),
                ('选定月份总计', selected.replace(day=1, hour=0, minute=0, second=0, microsecond=0), None),
            )
            totals = {}
            for label, begin, finish in windows:
                finish = _month_end(begin) if finish is None else finish
                if (begin, finish) not in totals:
                    totals[(begin, finish)] = collect(
                        instance, series=research_series, scope=research_scope,
                        start=begin, end=finish)['total']
                metric(label, totals[(begin, finish)] or None)
            result['tables'].append(table(
                title, detail_columns, rows, note=note,
                default_sort={'index': 3, 'descending': True},
            ))
            result['tables'].append(table(
                '掉落记录', record_columns, record_rows[-200:],
                note='按时间倒序；只列掉了心智单元或物资的记录。'
                     + ('记录超过 200 条，只显示最近 200 条。' if len(record_rows) > 200 else ''),
                default_sort={'index': 0, 'descending': True},
            ))
            return result

        summary = collect(instance, series=research_series, scope=SCOPE_SERIES, start=start, end=end)
        title = f'第 {summary["series"]} 期收获明细'
        note = ('每期只统计该期各艘船的图纸与该期的彩装图纸；'
                '心智与物资在「心智/物资」里看。图标暂用当前物品模板。'
                '清单里本期没掉过的也留一行，便于对照。')
        if not summary['records']:
            if summary['available']:
                hint = (f'第 {summary["series"]} 期在统计区间内没有记录；有记录的期数：'
                        + '、'.join(f'第 {item} 期' for item in summary['available'])
                        + '（可把「汇总周期」改成选定月份再看）')
            else:
                hint = ('还没有科研掉落记录。统计在领奖时自动完成：'
                        '把「科研截图」设为「保存」或「上传」即可（两者都会统计，'
                        '区别只是要不要把截图落盘）。')
            result['tables'].append(table(title, detail_columns, [], note=hint))
            return result
        # 原始掉落记录：本视图认的物品才算「一次掉落」，只列这些
        record_rows = _research_record_rows(instance, start, end, SCOPE_SERIES)

        metric('掉落记录', len(record_rows), '次')
        for item in summary['items']:
            # 0 传 null：前端与委托收益一样显示「—」，区分「没有」和「真是 0」
            metric(item['zh'], item['amount'] or None, icon=f'research:{item["name"]}')
        rows = [
            [f'research:{item["name"]}', item['zh'], RARITY_LABELS.get(item.get('rarity'), '—'),
             item['amount'] or None, item['count'] or None, item['avg'] or None]
            for item in summary['items']
        ]
        result['tables'].append(table(
            title, detail_columns, rows, note=note,
            default_sort={'index': 3, 'descending': True},
        ))
        result['tables'].append(table(
            '掉落记录', record_columns, record_rows[-200:],
            note='按时间倒序；只列掉了本期图纸或彩装的记录，那一次只掉心智或物资的不算。'
                 + ('记录超过 200 条，只显示最近 200 条。' if len(record_rows) > 200 else ''),
            default_sort={'index': 0, 'descending': True},
        ))
    elif category == 'loot':
        from module.statistics.azurstats import AzurStats
        from module.statistics.opsi_drop_stats import collect as collect_opsi_drop
        from module.statistics.research_stats import RARITY_LABELS
        # 版式与科研掉落一致：上面收益卡片、中间收获明细、下面掉落记录。
        # 「汇总周期」框时间：month 看选定月份，day/week 看今天/本周。
        start = selected.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = _month_end(start)
        if period != 'month':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if period == 'week':
                start -= timedelta(days=start.weekday())
            end = now
        task = loot_task or None
        summary = collect_opsi_drop(instance, start, end, task=task)
        detail_columns = ['图标', '物品', '稀有度', '总收益', '掉落记录数', '平均每次掉落']
        record_columns = ['时间', '任务', '海域', '掉落物']
        title = '大世界掉落明细'
        note = ('统计金菜（部件T4）、装备研发图纸SSR/UR型、六种金色研发材料、'
                '机密/绝密实验计划及特装型突破部件；其他物品照常入库，只是不在这里展示。'
                '统计在任务跑完解析掉落时完成：把该任务的「掉落截图」设为保存或上传均可'
                '（两者都统计，区别只是要不要把截图落盘）。')
        # 独立或共用掉落开关的任务始终可选，次数不受当前任务筛选影响。
        result['taskOptions'] = summary['tasks']
        if not summary['record_count']:
            result['tables'].append(table(title, detail_columns, [], note=(
                note + ' 这段时间里没有掉落记录——「汇总周期」选今天/本周时窗口很短，'
                '改成「选定月份」能看得更多。')))
        else:
            metric('掉落记录', summary['record_count'], '次')
            for item in summary['items']:
                # 0 传 null：前端与委托收益一样显示「—」，区分「没有」和「真是 0」
                metric(item['zh'], item['amount'] or None, icon=f'opsi:{item["name"]}')
            for label, begin, finish in (
                ('今日总计', now.replace(hour=0, minute=0, second=0, microsecond=0), now + timedelta(seconds=1)),
                ('本月总计', now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), None),
                ('选定月份总计', selected.replace(day=1, hour=0, minute=0, second=0, microsecond=0), None),
            ):
                finish = _month_end(begin) if finish is None else finish
                metric(label, collect_opsi_drop(instance, begin, finish, task=task)['total'] or None)
            rows = [
                [f'opsi:{item["name"]}', item['zh'], RARITY_LABELS.get(item.get('rarity'), '—'),
                 item['amount'] or None, item['count'] or None, item['avg'] or None]
                for item in summary['items']
            ]
            result['tables'].append(table(
                title, detail_columns, rows, note=note,
                default_sort={'index': 3, 'descending': True},
            ))
            result['tables'].append(table(
                '掉落记录', record_columns, summary['records'][:200],
                note='按时间倒序；只列含上述统计物品的掉落记录，其余掉落不入这张表。'
                     + ('记录超过 200 条，只显示最近 200 条。' if len(summary['records']) > 200 else ''),
                default_sort={'index': 0, 'descending': True},
            ))

        # 短猫按侵蚀等级的收益汇总：沿用原「短猫掉落」页的数据源，放在最下面
        rows = []
        with _loot_lock:
            cached = AzurStats.load_meowofficer_farming(instance=instance)
        for row in cached:
            if row[2] > 0:
                rows.append([int(row[0]), datetime.fromtimestamp(row[1]).isoformat(sep=' '), float(row[2]), *[round(float(value), 4) for value in row[3:]]])
        result['tables'].append(table('短猫掉落收益', AzurStats.meowofficer_farming_labels, rows))
        result['notes'].append('仅统计当前实例的掉落；旧记录缺少实例信息，作为历史共享数据保留，不计入当前实例。')
    return result
