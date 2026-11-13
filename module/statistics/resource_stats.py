"""资源快照统计模块，实现游戏资源的本地记录与历史查询。
通过 SQLite 数据库存储资源变动快照，
支持按实例和时间范围查询，用于绘制资源趋势图。"""

# 此文件实现了通用资源快照的记录与查询功能。
# 当各项资源数值（如石油、物资、钻石等）发生变化时，记录快照以便后续绘制历史趋势图。
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List

from module.logger import logger


_local_lock = threading.Lock()
_LOCAL_DB = './config/azurstats_local.db'
_table_ensured = False


def _database():
    from module.persistence.database import for_legacy_path
    return for_legacy_path(_LOCAL_DB, 'statistics')


# Dashboard 使用的资源名称与数据库列名保持在同一处，供区间聚合复用。
RESOURCE_COLUMNS = {
    'Oil': 'oil',
    'Coin': 'coin',
    'Gem': 'gem',
    'Pt': 'pt',
    'Cube': 'cube',
    'Core': 'core',
    'Medal': 'medal',
    'Merit': 'merit',
    'GuildCoin': 'guild_coin',
    'ActionPoint': 'action_point',
    'YellowCoin': 'yellow_coin',
    'PurpleCoin': 'purple_coin',
}

# 快照写入语句写成完整字面量，数值全部走命名参数绑定；
# 列顺序须与 RESOURCE_COLUMNS 一致，由 tests/test_resource_snapshot_sql.py 校验
_SNAPSHOT_INSERT_SQL = (
    'INSERT INTO resource_snapshots '
    '(instance,ts,oil,coin,gem,pt,cube,core,medal,merit,guild_coin,action_point,yellow_coin,purple_coin) '
    'VALUES (:instance,:ts,:oil,:coin,:gem,:pt,:cube,:core,:medal,:merit,:guild_coin,:action_point,'
    ':yellow_coin,:purple_coin)'
)


def _ensure_table():
    """建表和旧数据转换统一由安装级迁移入口完成。"""
    _database().ensure_ready()


def _overlay_opsi_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
    """保留业务适配入口；资源值直接读取原生列。"""
    return row


def _snapshot_row(instance: str, resources: Dict[str, Any], observed_at: datetime = None) -> Dict[str, Any]:
    """把资源读数整理成一行快照，未读到的资源留空。"""
    row = {'instance': instance, 'ts': (observed_at or datetime.now()).isoformat()}
    row.update({column: resources.get(name) for name, column in RESOURCE_COLUMNS.items()})
    return row


def _apply_snapshot(connection, instance, row, provided, carry_forward):
    """在给定事务内写入一行快照；同一批次的顺序写入与逐条写入语义一致。"""
    from module.persistence.database import register_instance
    register_instance(connection, instance)
    if carry_forward:
        latest = connection.execute('SELECT * FROM resource_snapshots WHERE instance = ? ORDER BY id DESC LIMIT 1',
                                    (instance,)).fetchone()
        if latest is not None:
            for name, column in RESOURCE_COLUMNS.items():
                if name not in provided:
                    row[column] = latest[column]
    connection.execute(_SNAPSHOT_INSERT_SQL, row)


def record_resource_snapshot(instance: str, resources: Dict[str, Any], *, observed_at: datetime = None,
                             carry_forward: bool = False) -> bool:
    """以同一事务保存各项资源的当前读数。

    Args:
        instance: 实例名称。
        resources: 资源名到读数的映射。
        observed_at: 采样时间，缺省为当前时间。
        carry_forward: 为 True 时只写入 ``resources`` 中给出的资源，其余列沿用该实例最近一行快照；
            首行没有可沿用的值时留空，不把从未读取的资源记成 0。
            运行中各个配置对象（例如战役使用的配置副本）的 Dashboard 值可能已过期，
            用它们补全整行会让曲线出现一个点的旧值尖刺。
    """
    try:
        row = _snapshot_row(instance, resources, observed_at)
        with _local_lock, _database().transaction() as conn:
            _apply_snapshot(conn, instance, row, frozenset(resources), carry_forward)
        return True
    except Exception as error:
        logger.warning(f'[统计-资源] 记录资源快照失败: {type(error).__name__}')
        return False


def queue_resource_snapshot(instance: str, resources: Dict[str, Any], *, observed_at: datetime = None,
                            carry_forward: bool = False) -> bool:
    """把资源快照排队，由后台窗口合并成一次事务落库；调用方立即返回。"""
    from module.persistence.write_queue import write_queue
    row = _snapshot_row(instance, resources, observed_at)
    provided = frozenset(resources)
    write_queue.enqueue(
        'append', None,
        lambda connection: _apply_snapshot(connection, instance, row, provided, carry_forward),
        directory=_database().directory)
    return True


def async_record_resource_snapshot(instance: str, resources: Dict[str, Any], *, observed_at: datetime = None,
                                   carry_forward: bool = False):
    """固定主线程采样值与时间后排队，不向后台传递可变配置对象。"""
    from module.base.async_executor import async_executor
    future = async_executor.submit(record_resource_snapshot, instance, dict(resources),
                                   observed_at=observed_at or datetime.now(), carry_forward=carry_forward)

    def finished(result):
        if result.cancelled() or result.exception() is not None:
            logger.warning('[统计-资源] 后台快照写入失败')

    future.add_done_callback(finished)
    return future


def get_resource_timeline(
    instance: str = 'default',
    limit: int = 500,
    since: str = None,
    until: str = None,
    include_opsi: bool = True,
) -> List[Dict[str, Any]]:
    """获取资源快照时间序列数据，用于绘制资源变化曲线。

    Args:
        instance: 实例名称
        limit: 最大返回条数
        since: 起始时间（ISO 文本，含）。为空表示不限
        until: 结束时间（ISO 文本，含）。为空表示不限
        include_opsi: 是否返回大世界三列（行动力/黄币/紫币）。

    Returns:
        list[dict]: 按时间排序的快照列表，每个包含:
            - ts: ISO 格式时间戳
            - oil, coin, gem, pt, cube, core, medal, merit, guild_coin,
              action_point, yellow_coin, purple_coin: 资源数值（可能为 None）
    """
    try:
        _ensure_table()
        with _database().transaction(write=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''
                SELECT * FROM resource_snapshots
                WHERE instance = ? AND (? IS NULL OR ts >= ?) AND (? IS NULL OR ts <= ?)
                ORDER BY id DESC
                LIMIT ?
                ''',
                (instance, since, since, until, until, limit),
            ).fetchall()
            if include_opsi:
                result = [_overlay_opsi_snapshot(dict(row)) for row in rows]
            else:
                result = [dict(row) for row in rows]
                for item in result:
                    item.update(action_point=None, yellow_coin=None, purple_coin=None)
            result.reverse()
            return result
    except Exception as e:
        logger.warning(f'[统计-资源] 获取资源时间线失败: {type(e).__name__}')
        return []


def _validate_interval(start: datetime, end: datetime) -> None:
    """校验日报区间使用的本地 naive datetime 参数。

    Args:
        start (datetime): 区间起始时间。
        end (datetime): 区间结束时间。

    Raises:
        TypeError: 若参数不是 datetime 对象时抛出。
        ValueError: 若时间带时区或 start > end 时抛出。
    """
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise TypeError('start 和 end 必须是 datetime')
    if start.tzinfo is not None or end.tzinfo is not None:
        raise ValueError('start 和 end 必须是不带时区的本地时间')
    if start > end:
        raise ValueError('start 不能晚于 end')


def _parse_snapshot_timestamp(value: Any) -> datetime | None:
    """解析历史快照时间，遇到旧数据或损坏数据时跳过。

    Args:
        value (Any): 快照时间字符串。

    Returns:
        datetime | None: 解析出的 naive datetime 对象，失败返回 None。
    """
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is not None:
        return None
    return timestamp


def get_resource_interval_summary(
    instance: str,
    start: datetime,
    end: datetime,
) -> Dict[str, Any]:
    """获取指定日报区间内 Dashboard 资源的首末值与变化。

    起始值取 ``start`` 时刻及之前最后一次有效快照，终止值取半开区间
    ``[start, end)`` 内最后一次有效快照。这样相邻日报不会重复使用
    恰好发生在结束边界的快照，也不会将窗口中首次
    采集到的值错误地当作窗口开始基线；任一端缺失时 ``delta`` 为
    ``None``，并通过对应的 ``*_known`` 字段明确标识。

    Args:
        instance: 实例名称。
        start: 本地 naive datetime 的统计起点（包含）。
        end: 本地 naive datetime 的统计终点（不包含）。

    Returns:
        可直接 JSON 序列化的字典，``resources`` 按 Dashboard 资源名
        返回 ``start``、``end``、``delta``、观测时间和可用状态。
    """
    _validate_interval(start, end)

    # 每种资源独立寻找有效快照，避免同一行中某个资源缺失影响其他资源。
    summary = {
        resource_name: {
            'start': None,
            'end': None,
            'delta': None,
            'baseline_known': False,
            'end_known': False,
            'start_observed_at': None,
            'end_observed_at': None,
        }
        for resource_name in RESOURCE_COLUMNS
    }

    try:
        _ensure_table()
        with _local_lock:
            with _database().transaction(write=False) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    '''
                    SELECT * FROM resource_snapshots
                    WHERE instance = ?
                    ORDER BY id ASC
                    ''',
                    (instance,),
                ).fetchall()

        for row in rows:
            row_data = _overlay_opsi_snapshot(dict(row))
            timestamp = _parse_snapshot_timestamp(row_data.get('ts'))
            if timestamp is None or timestamp >= end:
                continue

            for resource_name, column_name in RESOURCE_COLUMNS.items():
                value = row_data.get(column_name)
                if value is None:
                    continue
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue

                item = summary[resource_name]
                if timestamp <= start:
                    previous_timestamp = _parse_snapshot_timestamp(
                        item['start_observed_at']
                    )
                    if previous_timestamp is None or timestamp >= previous_timestamp:
                        item['start'] = value
                        item['baseline_known'] = True
                        item['start_observed_at'] = timestamp.isoformat()
                if start <= timestamp < end:
                    previous_timestamp = _parse_snapshot_timestamp(
                        item['end_observed_at']
                    )
                    if previous_timestamp is None or timestamp >= previous_timestamp:
                        item['end'] = value
                        item['end_known'] = True
                        item['end_observed_at'] = timestamp.isoformat()

        for item in summary.values():
            if item['baseline_known'] and item['end_known']:
                item['delta'] = item['end'] - item['start']

        return {
            'instance': instance,
            'start': start.isoformat(),
            'end': end.isoformat(),
            'resources': summary,
        }
    except Exception as e:
        logger.warning(f'[统计-资源] 获取资源区间摘要失败: {type(e).__name__}')
        return {
            'instance': instance,
            'start': start.isoformat(),
            'end': end.isoformat(),
            'resources': summary,
        }


__all__ = [
    'RESOURCE_COLUMNS',
    'record_resource_snapshot',
    'get_resource_timeline',
    'get_resource_interval_summary',
]
