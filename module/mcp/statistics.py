"""把 WebUI 统计页的报表适配成 MCP 的结构化结果。

本模块只做三件事：复用统计服务生成数据、把界面字段翻译成稳定的机器可读结构、
把「空数据 / 任务运行中 / 数据库不可读」翻译成明确的状态或错误码。所有统计口径
都来自 ``module.api.statistics_service`` 与 ``module.statistics``，不在这里重算。
"""
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

from module.api.protocol import ApiError
from module.api.statistics_service import report
from module.statistics.metric_catalog import (
    CATEGORY_FILTERS, CATEGORY_INFO, CATEGORY_ORDER, CATEGORY_TABLES, DYNAMIC_METRICS,
    ERROR_INFO, FILTER_INFO, METRIC_MEANINGS, RESOURCE_FIELDS, RESOURCE_MEANINGS,
    SERIES_INFO, STATE_INFO, TABLE_INFO, metric_meaning, series_info, table_header,
)

#: 与 WebUI 统计页固定的八类报表（overview / flows 另行实现）。
REPORT_CATEGORIES = ('resources', 'action', 'opsi', 'commission', 'ships', 'loot', 'research', 'storage')
ALL_CATEGORIES = CATEGORY_ORDER
#: 会触发仓库扫描的任务名；扫描期间仓库报表返回上一次完整快照。
LOADING_TASKS = {'storage': {'StorageStatistics'}}

#: 1970-01-01 的日期序数，与统计服务的 wallclock_micros 保持一致。
EPOCH = datetime(1970, 1, 1)


def format_micros(value) -> str:
    """把统计服务下发的「协调世界时字段微秒」还原成本地墙上时间文本。"""
    try:
        seconds, micro = divmod(int(value), 1_000_000)
        moment = EPOCH + timedelta(seconds=seconds)
    except (TypeError, ValueError, OverflowError):
        return ''
    text = moment.isoformat(sep=' ')
    return f'{text}.{micro:06d}' if micro else text


def downsample(points: list, limit: int) -> tuple:
    """等距抽取真实点位（不聚合），保留首尾；返回 (采样后点位, 是否截断)。"""
    if limit <= 0 or len(points) <= limit:
        return points, False
    if limit == 1:
        return points[-1:], True
    step = (len(points) - 1) / (limit - 1)
    indices = sorted({round(index * step) for index in range(limit)})
    return [points[index] for index in indices], True


def running_task(instance: str):
    """返回实例当前正在执行的统计任务名；未运行或已停止时返回 None。"""
    from module.runtime.process_manager import ProcessManager
    manager = ProcessManager._processes.get(instance)
    if manager is None or getattr(manager, 'state', None) != 1:
        return None
    return getattr(manager, 'current_task', None)


def category_label(category: str) -> str:
    return (CATEGORY_INFO.get(category) or {}).get('label', category)


def validate_arguments(arguments: dict):
    """拒绝明确不属于该分类的筛选参数，避免静默忽略造成误读。

    month/period/days 对报表分类是通用窗口，不在此校验；带默认值的 series/scope
    只在取值不同于默认值时才算显式指定，兼容会填充默认值的客户端。
    """
    category = arguments['category']
    if category != 'flows':
        for field in ('start', 'end', 'resource', 'through_id'):
            if field in arguments:
                raise ApiError('INVALID_PARAMS', f'{field} 仅适用于 category=flows',
                               {'field': field, 'allowed_categories': ['flows']})
    if category != 'research':
        if arguments.get('series') not in (None, 0) or arguments.get('scope') not in (None, 'series'):
            raise ApiError('INVALID_PARAMS', 'series 与 scope 仅适用于 category=research',
                           {'field': 'series/scope', 'allowed_categories': ['research']})
    if 'task' in arguments and category not in ('loot', 'flows'):
        raise ApiError('INVALID_PARAMS', 'task 仅适用于 category=loot 或 flows',
                       {'field': 'task', 'allowed_categories': ['loot', 'flows']})
    if category == 'loot' and arguments.get('task'):
        import re
        if not re.match(r'^[a-z][a-z0-9_]{0,40}$', arguments['task']):
            raise ApiError('INVALID_PARAMS', '大世界任务标识应为小写字母开头，仅含小写字母、数字与下划线',
                           {'field': 'task', 'rule': 'pattern', 'value': arguments['task']})


def normalize_window(arguments: dict, now: datetime) -> dict:
    """回显本次统计使用的窗口；区间类分类用 start/end，报表分类用月份与周期。"""
    month = arguments.get('month')
    return {
        'month': month or (now.strftime('%Y-%m') if arguments['category'] != 'flows' else None),
        'period': arguments.get('period', 'month'),
        'days': arguments.get('days', 7),
        'start': arguments.get('start') if arguments['category'] == 'flows' else None,
        'end': arguments.get('end') if arguments['category'] == 'flows' else None,
    }


def normalize_metrics(category: str, metrics: list) -> list:
    result = []
    for item in metrics or []:
        key = item.get('key') or item.get('label') or 'metric'
        result.append({
            'key': str(key),
            'label': str(item.get('label') or key),
            'value': item.get('value'),
            'unit': str(item.get('unit') or ''),
            'meaning': item.get('meaning') or metric_meaning(category, str(key), str(item.get('label') or '')),
            'icon': item.get('icon'),
        })
    return result


def normalize_series(category: str, series_list: list, max_points: int) -> tuple:
    result, truncated = [], False
    for item in series_list or []:
        key = str(item.get('key') or item.get('label') or 'series')
        unit, meaning = series_info(category, key)
        raw_points = item.get('points') or []
        points, clipped = downsample(raw_points, max_points)
        truncated = truncated or clipped
        result.append({
            'key': key,
            'label': str(item.get('label') or key),
            'unit': unit,
            'meaning': meaning,
            'point_count': len(raw_points),
            'truncated': clipped,
            'points': [{
                'time': format_micros(point.get('t')),
                'value': point.get('v'),
                'source': point.get('s'),
            } for point in points],
        })
    return result, truncated


def normalize_tables(tables: list) -> list:
    result = []
    for item in tables or []:
        key = str(item.get('key') or item.get('title') or 'table')
        columns = [str(column) for column in item.get('columns') or []]
        column_keys = [str(column) for column in item.get('column_keys') or []]
        if len(column_keys) != len(columns):
            column_keys = [f'column_{index + 1}' for index in range(len(columns))]
        result.append({
            'key': key,
            'title': str(item.get('title') or key),
            'meaning': str(item.get('meaning') or (TABLE_INFO.get(key) or {}).get('meaning', '')),
            'columns': columns,
            'column_keys': column_keys,
            'rows': item.get('rows') or [],
            'note': str(item.get('note') or ''),
            'truncated': bool(item.get('truncated')),
        })
    return result


def normalize_task_options(items) -> list:
    result = []
    for item in items or []:
        if isinstance(item, str):
            result.append({'key': item, 'label': item, 'count': None})
            continue
        key = str(item.get('key') or '')
        result.append({'key': key, 'label': str(item.get('label') or key), 'count': item.get('count')})
    return result


def empty_hint(category: str) -> str:
    return {
        'overview': '实例尚未同步资源；运行调度器并完成一次资源识别后，概览卡片才会更新。',
        'resources': '所选区间没有资源快照；任务运行并采集后才有数据，可调整月份或周期再试。',
        'action': '所选月份没有行动力记录；先运行大世界任务再查询。',
        'opsi': '所选月份没有大世界运行记录；可切换月份或先运行大世界任务。',
        'commission': '所选周期没有委托结算记录；可切换为选定月份扩大范围。',
        'ships': '尚未检测舰船经验；运行舰船经验相关任务后再查询。',
        'loot': '所选区间没有大世界掉落记录；可切换汇总周期或月份扩大范围。',
        'research': '所选区间没有科研掉落记录；科研领奖时会自动统计。',
        'storage': '尚未运行仓库统计任务；完成一次完整扫描后才会更新物品数量。',
        'flows': '所选区间没有资源流水；资源管理在任务结算时记录收支，可扩大区间或先运行任务。',
    }.get(category, '所选范围没有统计数据。')


def is_empty(category: str, metrics: list, series_list: list, tables: list, resources: list) -> bool:
    """按分类判断「真的没有数据」，避免把固定指标行或固定物品清单当成有数据。"""
    by_key = {item['key']: item.get('value') for item in metrics}
    if category == 'overview':
        return not any(item.get('observed') for item in resources)
    if category == 'flows':
        return not any(item.get('value') is not None for item in resources) \
            and not any((item.get('income') or 0) + (item.get('expense') or 0)
                        + abs(item.get('adjustment') or 0) for item in resources) \
            and not any(table.get('rows') for table in tables if table['key'] == 'flows_entries')
    if category == 'resources':
        return not any(item.get('points') for item in series_list)
    if category == 'action':
        return not any(item.get('points') for item in series_list)
    if category == 'storage':
        table = next((item for item in tables if item['key'] == 'storage_items'), None)
        return not table or not any(row[3] is not None for row in table['rows'] if len(row) > 3)
    if category in ('opsi', 'commission', 'loot', 'research'):
        counter = {'opsi': 'battles', 'commission': 'commissions',
                   'loot': 'drops', 'research': 'drops'}[category]
        return not by_key.get(counter)
    if category == 'ships':
        return not any(by_key.get(key) for key in ('today_battles', 'today_exp'))
    return not metrics and not series_list and not tables


def summarize(category: str, state: str, metrics: list, series_list: list, tables: list,
              resources: list, hint: str) -> str:
    label = category_label(category)
    if state == 'empty':
        return f'{label}（{category}）：{hint or empty_hint(category)}'
    if state == 'loading':
        return f'{label}（{category}）：统计任务正在运行，当前返回已有快照。{hint or ""}'.strip()
    if category == 'overview':
        cards = [f"{item['label']}={item['value']}" for item in resources
                 if item.get('value') is not None][:8]
        return f'概览资源（overview）：' + ('，'.join(cards) if cards else '暂无已同步资源')
    parts = [f"{item['label']}={item['value']}{item['unit']}"
             for item in metrics if item.get('value') is not None][:8]
    if series_list:
        parts.append(f'{len(series_list)} 条时间线')
    if tables:
        parts.append('表格：' + '、'.join(item['title'] for item in tables[:3]))
    detail = '，'.join(parts) if parts else '无可展示指标'
    return f'{label}（{category}）：{detail}'


def build_report(configs, runtime, arguments: dict) -> tuple:
    """生成报表类统计的结构化结果，返回 (payload, 摘要)。"""
    instance = arguments['instance']
    category = arguments['category']
    configs.path(instance)
    now = datetime.now()
    month = arguments.get('month')
    period = arguments.get('period', 'month')
    days = arguments.get('days', 7)
    max_points = arguments.get('max_points', 500)
    include_series = arguments.get('include_series', True)

    try:
        raw = report(configs, instance, category, month, days, period,
                     research_series=arguments.get('series', 0),
                     research_scope=arguments.get('scope', 'series'),
                     loot_task=arguments.get('task'),
                     include_series=include_series)
    except ApiError:
        raise
    except PermissionError as exc:
        raise ApiError('PERMISSION_DENIED', f'无权读取统计库：{exc.strerror or exc}',
                       {'filename': exc.filename}) from exc
    except sqlite3.OperationalError as exc:
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():
            raise ApiError('STATISTICS_LOADING', '统计库正在写入或初始化，请稍后重试',
                           {'reason': str(exc)}) from exc
        raise ApiError('STATISTICS_UNAVAILABLE', f'统计库不可用：{exc}') from exc
    except OSError as exc:
        raise ApiError('STATISTICS_UNAVAILABLE', f'读取统计库失败：{exc}') from exc

    metrics = normalize_metrics(category, raw.get('metrics'))
    series_list, series_truncated = normalize_series(category, raw.get('series'), max_points) \
        if include_series else ([], False)
    tables = normalize_tables(raw.get('tables'))
    notes = [str(note) for note in raw.get('notes') or []]
    task_options = normalize_task_options(raw.get('taskOptions'))

    state = 'empty' if is_empty(category, metrics, series_list, tables, []) else 'ready'
    active = running_task(instance)
    loading_task = next((name for name in LOADING_TASKS.get(category, set()) if name == active), None)
    hint = None
    if loading_task:
        state = 'loading'
        hint = f'{loading_task} 正在运行；当前展示上一次完整快照，任务结束后重试可获取最新数量。'
    elif state == 'empty':
        hint = empty_hint(category)

    payload = {
        'status': 'success',
        'instance': instance,
        'category': category,
        'category_label': category_label(category),
        'generated_at': now.astimezone().isoformat(timespec='seconds'),
        'window': normalize_window(arguments, now),
        'state': state,
        'metrics': metrics,
        'series': series_list,
        'tables': tables,
        'resources': [],
        'notes': notes,
        'hint': hint,
        'task_options': task_options,
        'page': {'offset': None, 'limit': None, 'total': None, 'has_more': False},
        'truncated': series_truncated,
        'data_source': 'statistics_service.report',
    }
    return payload, summarize(category, state, metrics, series_list, tables, [], hint)


def overview_meaning(key: str) -> str:
    return RESOURCE_MEANINGS.get(key, '概览页资源卡片的当前值、上限、总量与最近同步时间。')


def build_overview(runtime, arguments: dict) -> tuple:
    """生成概览页资源卡片的结构化结果。"""
    instance = arguments['instance']
    overview = runtime.overview(instance)
    resources = []
    for item in overview.get('resources') or []:
        record = item.get('record')
        record = str(record) if record else None
        observed = bool(record) and record > '2020-01-01' and item.get('value') is not None
        key = str(item.get('name') or '')
        label = str(item.get('label') or '')
        if not label or label == 'name':
            # 配置缺少对应语言的译名时 translate 会回退到路径末段，这里改用资源键。
            label = key
        resources.append({
            'key': key,
            'label': label,
            'value': item.get('value'),
            'limit': item.get('limit'),
            'total': item.get('total'),
            'record': record,
            'observed': observed,
            'group': None,
            'income': None,
            'expense': None,
            'adjustment': None,
            'records': None,
            'observed_at': None,
            'meaning': overview_meaning(str(item.get('name') or '')),
        })
    state = 'ready' if any(item['observed'] for item in resources) else 'empty'
    hint = None if state == 'ready' else empty_hint('overview')
    now = datetime.now()
    payload = {
        'status': 'success',
        'instance': instance,
        'category': 'overview',
        'category_label': category_label('overview'),
        'generated_at': now.astimezone().isoformat(timespec='seconds'),
        'window': {'month': now.strftime('%Y-%m'), 'period': 'month', 'days': 0,
                   'start': None, 'end': None},
        'state': state,
        'metrics': [],
        'series': [],
        'tables': [],
        'resources': resources,
        'notes': ['资源卡片与 WebUI 概览页同源：Dashboard 配置中的当前值、上限与总量，'
                  '加上本月大世界海里数与行动力资产。'],
        'hint': hint,
        'task_options': [],
        'page': {'offset': None, 'limit': None, 'total': None, 'has_more': False},
        'truncated': False,
        'data_source': 'runtime.overview',
    }
    return payload, summarize('overview', state, [], [], [], resources, hint)


def build_flows(configs, arguments: dict) -> tuple:
    """生成资源管理页的库存与区间收支。"""
    from module.api.resource_service import resource_flows

    instance = arguments['instance']
    params = SimpleNamespace(
        instance=instance,
        days=arguments.get('days', 7),
        start=arguments.get('start'),
        end=arguments.get('end'),
        resource=arguments.get('resource'),
        task=arguments.get('task'),
        offset=arguments.get('offset', 0),
        limit=arguments.get('limit', 100),
        through_id=arguments.get('through_id'),
    )
    try:
        raw = resource_flows(configs, params)
    except ApiError:
        raise
    except PermissionError as exc:
        raise ApiError('PERMISSION_DENIED', f'无权读取资源流水库：{exc.strerror or exc}',
                       {'filename': exc.filename}) from exc
    except sqlite3.OperationalError as exc:
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():
            raise ApiError('STATISTICS_LOADING', '资源流水库正在写入，请稍后重试',
                           {'reason': str(exc)}) from exc
        raise ApiError('STATISTICS_UNAVAILABLE', f'资源流水库不可用：{exc}') from exc
    except OSError as exc:
        raise ApiError('STATISTICS_UNAVAILABLE', f'读取资源流水库失败：{exc}') from exc

    resources = [{
        'key': str(item.get('key') or ''),
        'label': str(item.get('label') or item.get('key') or ''),
        'value': item.get('current'),
        'limit': None,
        'total': None,
        'record': item.get('observedAt'),
        'observed': item.get('current') is not None and bool(item.get('observedAt')),
        'group': item.get('group'),
        'income': item.get('income'),
        'expense': item.get('expense'),
        'adjustment': item.get('adjustment'),
        'records': item.get('count'),
        'observed_at': item.get('observedAt'),
        'meaning': RESOURCE_MEANINGS.get(str(item.get('key') or ''),
                                         '库存、区间收入、支出与调整的汇总。'),
    } for item in raw.get('resources') or []]

    def table(key, title, rows):
        header = table_header(key)
        return {
            'key': key,
            'title': title,
            'meaning': (TABLE_INFO.get(key) or {}).get('meaning', ''),
            'columns': header['labels'],
            'column_keys': header['keys'],
            'rows': rows,
            'note': '',
            'truncated': False,
        }

    tables = [
        table('flows_resources', '资源库存与区间收支', [[
            item['key'], item.get('group'), item.get('current'), item.get('income'),
            item.get('expense'), item.get('adjustment'), item.get('count'),
            item.get('observedAt'),
        ] for item in raw.get('resources') or []]),
        table('flows_detail', '资源流向汇总', [[
            item.get('resource'), item.get('task'), item.get('operation'), item.get('evidence'),
            item.get('income'), item.get('expense'), item.get('count'),
        ] for item in raw.get('flows') or []]),
        table('flows_entries', '资源流水明细', [[
            item.get('ts'), item.get('resource'), item.get('amount'), item.get('task'),
            item.get('operation'), item.get('evidence'), item.get('run_id'),
        ] for item in raw.get('entries') or []]),
    ]
    total = int(raw.get('total') or 0)
    page = {
        'offset': int(raw.get('offset') or 0),
        'limit': int(raw.get('limit') or 0),
        'total': total,
        'has_more': int(raw.get('offset') or 0) + len(raw.get('entries') or []) < total,
    }
    state = 'empty' if is_empty('flows', [], [], tables, resources) else 'ready'
    hint = None if state == 'ready' else empty_hint('flows')
    now = datetime.now()
    payload = {
        'status': 'success',
        'instance': instance,
        'category': 'flows',
        'category_label': category_label('flows'),
        'generated_at': now.astimezone().isoformat(timespec='seconds'),
        'window': {
            'month': None,
            'period': 'custom',
            'days': int(arguments.get('days', 7)),
            'start': raw.get('start'),
            'end': raw.get('end'),
        },
        'state': state,
        'metrics': [],
        'series': [],
        'tables': tables,
        'resources': resources,
        'notes': ['资源流向来自任务结算时写入的流水；手工调整单独计入 adjustment，不计入收入或支出。'],
        'hint': hint,
        'task_options': normalize_task_options(raw.get('tasks')),
        'page': page,
        'truncated': bool(page['has_more']),
        'data_source': 'resource_service.resource_flows',
    }
    if state == 'ready':
        income = sum(item.get('income') or 0 for item in resources)
        expense = sum(item.get('expense') or 0 for item in resources)
        summary = (f"资源流向（flows）：{len(resources)} 项资源，"
                   f"{page['total']} 条流水；区间总收入 {income}、总支出 {expense}"
                   f"{'（仅显示当前页）' if page['has_more'] else ''}")
    else:
        summary = summarize('flows', state, [], [], tables, resources, hint)
    return payload, summary


def catalog_payload(category: str = None) -> dict:
    """返回统计分类、指标键、字段说明与错误码的目录。"""
    categories = [item for item in CATEGORY_ORDER if not category or item == category]
    items = []
    for name in categories:
        info = CATEGORY_INFO[name]
        metrics = [{'key': key, 'meaning': meaning}
                   for (owner, key), meaning in METRIC_MEANINGS.items() if owner == name]
        series_list = [{'key': key, 'unit': unit, 'meaning': meaning}
                       for key, (unit, meaning) in (SERIES_INFO.get(name) or {}).items()]
        tables = [{
            'key': key,
            'title': TABLE_INFO[key]['title'],
            'meaning': TABLE_INFO[key]['meaning'],
            'columns': [{'key': column[0], 'label': column[1], 'meaning': column[2]}
                        for column in TABLE_INFO[key]['columns']],
        } for key in CATEGORY_TABLES.get(name, ())]
        items.append({
            'category': name,
            'label': info['label'],
            'description': info['description'],
            'filters': [{'name': field, **FILTER_INFO[field]} for field in CATEGORY_FILTERS[name]],
            'metrics': metrics,
            'dynamic_metrics': DYNAMIC_METRICS.get(name, []),
            'series': series_list,
            'tables': tables,
        })
    return {
        'status': 'success',
        'catalog_version': 1,
        'categories': items,
        'resource_fields': RESOURCE_FIELDS,
        'states': [{'state': key, 'meaning': value} for key, value in STATE_INFO.items()],
        'error_codes': [{'code': code, 'meaning': meaning, 'retryable': retryable}
                        for code, (meaning, retryable) in ERROR_INFO.items()],
        'auth': {
            'scheme': 'Bearer / X-API-Key / ?key=',
            'note': '凭据复用 WebUI 密码；缺失或无效时 SSE 端点在工具执行前返回 HTTP 401。',
        },
    }


def catalog_summary(payload: dict) -> str:
    names = [f"{item['category']}({item['label']})" for item in payload['categories']]
    return (f"统计目录 v{payload['catalog_version']}：{len(names)} 个分类——"
            + '、'.join(names)
            + '。每类的指标键、时间线、表格列与筛选参数见结构化内容。')
