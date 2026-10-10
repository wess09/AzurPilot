"""资源管理页面的只读汇总服务。"""
from datetime import datetime, timedelta
from pathlib import Path

from module.api.protocol import ApiError
from module.persistence.database import configured_database, get_database
from module.statistics import resource_flow


@configured_database
def resource_flows(configs, params):
    path = configs.path(params.instance)
    try:
        end = datetime.fromisoformat(params.end) if params.end else datetime.now()
        start = datetime.fromisoformat(params.start) if params.start else end - timedelta(days=params.days)
        if start.tzinfo or end.tzinfo or start >= end or end - start > timedelta(days=366):
            raise ValueError
    except (ValueError, TypeError, OverflowError) as error:
        raise ApiError('INVALID_PARAMS', '请选择不超过一年的有效本地时间区间') from error
    result = resource_flow.report(params.instance, start, end, params.resource, params.task,
                                  params.offset, params.limit, params.through_id)
    values = configs.get(params.instance)['values']
    dashboard = values.get('Dashboard', {})
    resources = {item['key']: item for item in result['resources']}
    for key, item in dashboard.items():
        if key not in resources or resources[key]['observedAt']:
            continue
        stamp = item.get('Record')
        if stamp and str(stamp) > '2020-01-01 00:00:00' and type(item.get('Value')) is int:
            resources[key].update(current=item['Value'], observedAt=str(stamp))
    from module.statistics.storage_snapshot import latest_snapshot
    database = getattr(configs, 'database', None) or get_database(Path(path).parent)
    storage = latest_snapshot(params.instance, database=database)
    if storage:
        for item in storage['items']:
            if item['id'] in resources and not resources[item['id']]['observedAt'] and item['amount'] is not None:
                resources[item['id']].update(current=item['amount'], observedAt=storage['finished_at'])
    dashboard_control = values.get('General', {}).get('OilControl', {})
    result['oilControl'] = {'enable': dashboard_control.get('Enable', True),
                            'target': dashboard_control.get('Target', 24000)}
    return result
