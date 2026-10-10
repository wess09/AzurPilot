"""每日总结的运行时事件与发送状态存储。"""

from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from module.logger import logger
from module.persistence.database import register_instance


DEFAULT_DAILY_SUMMARY_DB = Path('./config/daily_summary.db')
DAILY_SUMMARY_RETENTION_DAYS = 35


class DailySummaryStore:
    """以 SQLite 保存日报所需的最小运行时数据。"""

    def __init__(self, db_path: str | Path | None = None, *, store=None) -> None:
        from module.persistence.database import for_legacy_path
        self._store = store or (for_legacy_path(db_path, 'daily') if db_path is not None else None)
        self._lock = threading.RLock()
        self._pending_degradations: set[tuple[str, str, str]] = set()

    @property
    def store(self):
        from module.persistence.database import get_database
        return self._store or get_database()

    @property
    def db_path(self):
        return self.store.path

    def _connect(self) -> sqlite3.Connection:
        # 日报保留 50 毫秒锁等待，记录失败时标记采集缺口。
        return self.store.connect(timeout=0.05)

    def _ensure_tables(self) -> None:
        self.store.ensure_ready()

    @staticmethod
    def _serialize_time(value: datetime) -> str:
        return value.replace(microsecond=0).isoformat(sep=' ')

    def _mark_collection_degraded(
        self, instance: str, collection: str, occurred_at: datetime
    ) -> None:
        """缓存失败采集事件，待下次可写入时持久化为本周期数据不完整。"""
        with self._lock:
            self._pending_degradations.add(
                (instance, collection, self._serialize_time(occurred_at))
            )

    def _flush_pending_degradations(
        self, connection: sqlite3.Connection
    ) -> set[tuple[str, str, str]]:
        pending = set(self._pending_degradations)
        if pending:
            for instance, _, _ in pending:
                register_instance(connection, instance)
            connection.executemany(
                '''
                INSERT OR IGNORE INTO daily_summary_collection_gaps (
                    instance, collection, occurred_at
                ) VALUES (?, ?, ?)
                ''',
                pending,
            )
        return pending

    def _clear_pending_degradations(
        self, persisted: set[tuple[str, str, str]]
    ) -> None:
        with self._lock:
            self._pending_degradations.difference_update(persisted)

    def _get_collection_gap(
        self,
        connection: sqlite3.Connection,
        instance: str,
        collection: str,
        start: datetime,
        end: datetime,
    ) -> str | None:
        row = connection.execute(
            '''
            SELECT MIN(occurred_at) AS occurred_at
            FROM daily_summary_collection_gaps
            WHERE instance = ? AND collection = ?
              AND occurred_at >= ? AND occurred_at < ?
            ''',
            (
                instance,
                collection,
                self._serialize_time(start),
                self._serialize_time(end),
            ),
        ).fetchone()
        return row['occurred_at'] if row is not None else None

    def _mark_collection_started(
        self,
        connection: sqlite3.Connection,
        instance: str,
        column: str,
        started_at: datetime,
    ) -> None:
        """仅首次记录采集起点，后续日报据此判断统计是否完整。"""
        if column not in {'task_tracking_started_at', 'cl1_tracking_started_at'}:
            raise ValueError(f'未知日报采集列: {column}')
        register_instance(connection, instance)
        connection.execute(
            'INSERT OR IGNORE INTO daily_summary_collection_state (instance) VALUES (?)',
            (instance,),
        )
        connection.execute(
            f'''
            UPDATE daily_summary_collection_state
            SET {column} = ?
            WHERE instance = ? AND {column} IS NULL
            ''',
            (self._serialize_time(started_at), instance),
        )
    def record_task_start(self, instance: str, task: str, started_at: datetime) -> int | None:
        """记录任务开始，失败时返回 ``None`` 而不影响调度器。

        Args:
            instance (str): 实例名称。
            task (str): 任务名称。
            started_at (datetime): 任务启动时间。

        Returns:
            int | None: 数据库自增记录 ID，失败返回 None。
        """
        try:
            self._ensure_tables()
            with self._lock, self._connect() as connection:
                persisted = self._flush_pending_degradations(connection)
                self._mark_collection_started(
                    connection, instance, 'task_tracking_started_at', started_at
                )
                cursor = connection.execute(
                    '''
                    INSERT INTO daily_summary_task_runs (instance, task, started_at)
                    VALUES (?, ?, ?)
                    ''',
                    (instance, task, self._serialize_time(started_at)),
                )
            self._clear_pending_degradations(persisted)
            return int(cursor.lastrowid)
        except Exception as error:
            self._mark_collection_degraded(instance, 'task', started_at)
            logger.warning(f'[日报] 记录任务开始失败，已忽略: {type(error).__name__}')
            return None

    def record_task_finish(
        self,
        instance: str,
        run_id: int | None,
        finished_at: datetime,
        status: str,
        duration_seconds: float,
    ) -> None:
        """补全已记录任务的结果；不会向外抛出数据库错误。

        Args:
            instance (str): 实例名称。
            run_id (int | None): record_task_start 返回的记录 ID。
            finished_at (datetime): 任务结束时间。
            status (str): 任务结束状态（如 'success', 'failed', 'recoverable'）。
            duration_seconds (float): 任务耗时（秒）。
        """
        if run_id is None:
            return
        try:
            self._ensure_tables()
            with self._lock, self._connect() as connection:
                persisted = self._flush_pending_degradations(connection)
                connection.execute(
                    '''
                    UPDATE daily_summary_task_runs
                    SET finished_at = ?, status = ?, duration_seconds = ?
                    WHERE id = ? AND instance = ?
                    ''',
                    (
                        self._serialize_time(finished_at),
                        status,
                        max(0.0, float(duration_seconds)),
                        run_id,
                        instance,
                    ),
                )
            self._clear_pending_degradations(persisted)
        except Exception as error:
            self._mark_collection_degraded(instance, 'task', finished_at)
            logger.warning(f'[日报] 记录任务结果失败，已忽略: {type(error).__name__}')

    def get_task_summary(self, instance: str, start: datetime, end: datetime, limit: int = 15) -> dict[str, Any]:
        """聚合在统计窗口内结束的结构化任务结果。

        Args:
            instance (str): 实例名称。
            start (datetime): 窗口开始时间。
            end (datetime): 窗口结束时间。
            limit (int): 返回任务细分列表的条数上限。

        Returns:
            dict[str, Any]: 结构化任务统计结果字典。
        """
        self._ensure_tables()
        with self._lock, self._connect() as connection:
            persisted = self._flush_pending_degradations(connection)
            state = connection.execute(
                '''
                SELECT task_tracking_started_at
                FROM daily_summary_collection_state
                WHERE instance = ?
                ''',
                (instance,),
            ).fetchone()
            tracking_started_at = (
                state['task_tracking_started_at'] if state is not None else None
            )
            degraded_at = self._get_collection_gap(
                connection, instance, 'task', start, end
            )
            rows = []
            if (
                tracking_started_at is not None
                and tracking_started_at <= self._serialize_time(start)
                and degraded_at is None
            ):
                rows = connection.execute(
                    '''
                    SELECT task, status, duration_seconds
                    FROM daily_summary_task_runs
                    WHERE instance = ?
                      AND finished_at >= ?
                      AND finished_at < ?
                      AND status IS NOT NULL
                    ORDER BY finished_at ASC
                    ''',
                    (
                        instance,
                        self._serialize_time(start),
                        self._serialize_time(end),
                    ),
                ).fetchall()
        self._clear_pending_degradations(persisted)
        if tracking_started_at is None or tracking_started_at > self._serialize_time(start) or degraded_at:
            return {
                'available': False,
                'collection_started_at': tracking_started_at,
                'degraded_at': degraded_at,
                'run_count': None,
                'success_count': None,
                'recoverable_count': None,
                'failed_count': None,
                'duration_seconds': None,
                'task_breakdown': [],
            }
        totals = {'success': 0, 'recoverable': 0, 'failed': 0}
        task_totals: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                'runs': 0,
                'success': 0,
                'recoverable': 0,
                'failed': 0,
                'duration_seconds': 0,
            }
        )
        duration_seconds = 0
        for row in rows:
            status = row['status']
            if status not in totals:
                continue
            duration = max(0, round(float(row['duration_seconds'] or 0)))
            totals[status] += 1
            duration_seconds += duration
            task_data = task_totals[row['task']]
            task_data['runs'] += 1
            task_data[status] += 1
            task_data['duration_seconds'] += duration
        breakdown = []
        for task, task_data in task_totals.items():
            breakdown.append({'name': task, **task_data})
        breakdown.sort(
            key=lambda item: (item['duration_seconds'], item['runs'], item['name']),
            reverse=True,
        )
        return {
            'available': True,
            'collection_started_at': tracking_started_at,
            'degraded_at': None,
            'run_count': sum(totals.values()),
            'success_count': totals['success'],
            'recoverable_count': totals['recoverable'],
            'failed_count': totals['failed'],
            'duration_seconds': duration_seconds,
            'task_breakdown': breakdown[:max(0, int(limit))],
        }
    def record_cl1_battle_event(self, instance: str, timestamp: datetime, duration_seconds: float, estimated_exp: int) -> None:
        """记录可精确归属到日报窗口的侵蚀 1 战斗事件。

        Args:
            instance (str): 实例名称。
            timestamp (datetime): 战斗发生时间。
            duration_seconds (float): 战斗耗时（秒）。
            estimated_exp (int): 预估获得经验值。
        """
        try:
            self._ensure_tables()
            with self._lock, self._connect() as connection:
                persisted = self._flush_pending_degradations(connection)
                self._mark_collection_started(
                    connection, instance, 'cl1_tracking_started_at', timestamp
                )
                connection.execute(
                    'INSERT INTO daily_summary_cl1_events(instance,ts,duration_seconds,estimated_exp) VALUES(?,?,?,?)',
                    (instance, self._serialize_time(timestamp), max(0.0, float(duration_seconds)), max(0, int(estimated_exp))))
                cutoff = self._serialize_time(
                    timestamp - timedelta(days=DAILY_SUMMARY_RETENTION_DAYS)
                )
                connection.execute(
                    'DELETE FROM daily_summary_cl1_events WHERE ts < ?',
                    (cutoff,),
                )
            self._clear_pending_degradations(persisted)
        except Exception as error:
            self._mark_collection_degraded(instance, 'cl1', timestamp)
            logger.warning(f'[日报] 记录侵蚀1战斗事件失败，已忽略: {type(error).__name__}')

    def get_cl1_interval_summary(self, instance: str, start: datetime, end: datetime) -> dict[str, Any]:
        """读取指定窗口内的新式侵蚀 1 战斗事件。

        Args:
            instance (str): 实例名称。
            start (datetime): 窗口开始时间。
            end (datetime): 窗口结束时间。

        Returns:
            dict[str, Any]: 侵蚀 1 战斗聚合统计字典。
        """
        self._ensure_tables()
        with self._lock, self._connect() as connection:
            persisted = self._flush_pending_degradations(connection)
            state = connection.execute(
                '''
                SELECT cl1_tracking_started_at
                FROM daily_summary_collection_state
                WHERE instance = ?
                ''',
                (instance,),
            ).fetchone()
            tracking_started_at = (
                state['cl1_tracking_started_at'] if state is not None else None
            )
            degraded_at = self._get_collection_gap(
                connection, instance, 'cl1', start, end
            )
            row = None
            if (
                tracking_started_at is not None
                and tracking_started_at <= self._serialize_time(start)
                and degraded_at is None
            ):
                records = connection.execute(
                    'SELECT * FROM daily_summary_cl1_events WHERE instance=? AND ts>=? AND ts<? ORDER BY ts',
                    (instance, self._serialize_time(start), self._serialize_time(end))).fetchall()
                decoded = [dict(record) for record in records]
                row = {'battles': len(decoded), 'estimated_exp': sum(r['estimated_exp'] for r in decoded),
                       'duration_seconds': sum(r['duration_seconds'] for r in decoded),
                       'first_observed_at': decoded[0]['ts'] if decoded else None,
                       'last_observed_at': decoded[-1]['ts'] if decoded else None}
        self._clear_pending_degradations(persisted)
        if tracking_started_at is None or tracking_started_at > self._serialize_time(start) or degraded_at:
            return {
                'start': self._serialize_time(start),
                'end': self._serialize_time(end),
                'available': False,
                'collection_started_at': tracking_started_at,
                'degraded_at': degraded_at,
                'window_has_data': None,
                'battles': None,
                'estimated_exp': None,
                'duration_seconds': None,
                'first_observed_at': None,
                'last_observed_at': None,
            }
        battles = int(row['battles'] or 0) if row is not None else 0
        return {
            'start': self._serialize_time(start),
            'end': self._serialize_time(end),
            'available': True,
            'collection_started_at': tracking_started_at,
            'degraded_at': None,
            'window_has_data': battles > 0,
            'battles': battles,
            'estimated_exp': int(row['estimated_exp'] or 0) if row is not None else 0,
            'duration_seconds': round(
                float(row['duration_seconds'] or 0), 2
            ) if row is not None else 0.0,
            'first_observed_at': row['first_observed_at'] if row is not None else None,
            'last_observed_at': row['last_observed_at'] if row is not None else None,
        }

    def claim_period(
        self,
        instance: str,
        period_key: str,
        server: str,
        window_start: datetime,
        window_end: datetime,
    ) -> bool:
        """原子抢占一份日报，确保同一实例周期只会生成一次。

        Args:
            instance (str): 实例名称。
            period_key (str): 周期唯一标识。
            server (str): 服务器代码。
            window_start (datetime): 周期开始时间。
            window_end (datetime): 周期结束时间。

        Returns:
            bool: 成功抢占返回 True，已被抢占或已存在返回 False。
        """
        self._ensure_tables()
        now = self._serialize_time(datetime.now())
        with self._lock, self._connect() as connection:
            register_instance(connection, instance)
            cursor = connection.execute(
                '''
                INSERT OR IGNORE INTO daily_summary_periods (
                    instance, period_key, server, window_start, window_end,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'generating', ?, ?)
                ''',
                (
                    instance,
                    period_key,
                    server,
                    self._serialize_time(window_start),
                    self._serialize_time(window_end),
                    now,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def mark_period_skipped(
        self,
        instance: str,
        period_key: str,
        server: str,
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        """记录错过的周期，防止进程恢复后补发旧日报。

        Args:
            instance (str): 实例名称。
            period_key (str): 周期唯一标识。
            server (str): 服务器代码。
            window_start (datetime): 周期开始时间。
            window_end (datetime): 周期结束时间。
        """
        self._ensure_tables()
        now = self._serialize_time(datetime.now())
        with self._lock, self._connect() as connection:
            register_instance(connection, instance)
            connection.execute(
                '''
                INSERT OR IGNORE INTO daily_summary_periods (
                    instance, period_key, server, window_start, window_end,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'skipped', ?, ?)
                ''',
                (
                    instance,
                    period_key,
                    server,
                    self._serialize_time(window_start),
                    self._serialize_time(window_end),
                    now,
                    now,
                ),
            )

    def update_period(
        self,
        instance: str,
        period_key: str,
        status: str,
        *,
        report_text: str | None = None,
        llm_attempts: int | None = None,
        send_attempts: int | None = None,
        error_kind: str | None = None,
    ) -> None:
        """更新日报处理状态，不保存异常正文或敏感配置。

        Args:
            instance (str): 实例名称。
            period_key (str): 周期唯一标识。
            status (str): 目标状态 ('generating', 'sending', 'sent', 'failed', 'skipped')。
            report_text (str | None): 生成的日报正文。
            llm_attempts (int | None): LLM 调用次数。
            send_attempts (int | None): 推送发送次数。
            error_kind (str | None): 错误类别代码。
        """
        self._ensure_tables()
        values: dict[str, Any] = {
            'status': status,
            'updated_at': self._serialize_time(datetime.now()),
        }
        if report_text is not None:
            values['report_text'] = None
        if llm_attempts is not None:
            values['llm_attempts'] = int(llm_attempts)
        if send_attempts is not None:
            values['send_attempts'] = int(send_attempts)
        if error_kind is not None:
            values['error_kind'] = error_kind
        with self._lock, self._connect() as connection:
            if report_text is not None:
                values['report_text'] = str(report_text)
            assignments = ', '.join(f'{key} = ?' for key in values)
            parameters = [*values.values(), instance, period_key]
            connection.execute(
                f'''
                UPDATE daily_summary_periods
                SET {assignments}
                WHERE instance = ? AND period_key = ?
                ''',
                parameters,
            )

    def get_period(self, instance: str, period_key: str) -> dict[str, Any] | None:
        """读取单个周期状态，供测试和运行时去重检查使用。

        Args:
            instance (str): 实例名称。
            period_key (str): 周期唯一标识。

        Returns:
            dict[str, Any] | None: 周期记录字典，不存在返回 None。
        """
        self._ensure_tables()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                '''
                SELECT * FROM daily_summary_periods
                WHERE instance = ? AND period_key = ?
                ''',
                (instance, period_key),
            ).fetchone()
        result = dict(row) if row is not None else None
        return result

    def cleanup(self, now: datetime | None = None, keep_days: int = 35) -> None:
        """删除过期的任务事件和日报状态。

        Args:
            now (datetime | None): 当前参考时间。
            keep_days (int): 保留天数，默认 35 天。
        """
        self._ensure_tables()
        now = now or datetime.now()
        cutoff = self._serialize_time(now - timedelta(days=max(1, int(keep_days))))
        interrupted_cutoff = self._serialize_time(now - timedelta(days=1))
        with self._lock, self._connect() as connection:
            # 进程意外退出不会让周期永久停留在处理中，也不会触发补发。
            connection.execute(
                '''
                UPDATE daily_summary_periods
                SET status = 'failed', error_kind = COALESCE(error_kind, 'interrupted'),
                    updated_at = ?
                WHERE status IN ('generating', 'sending') AND window_end < ?
                ''',
                (self._serialize_time(now), interrupted_cutoff),
            )
            connection.execute(
                '''
                DELETE FROM daily_summary_task_runs
                WHERE COALESCE(finished_at, started_at) < ?
                ''',
                (cutoff,),
            )
            connection.execute(
                'DELETE FROM daily_summary_cl1_events WHERE ts < ?',
                (cutoff,),
            )
            connection.execute(
                'DELETE FROM daily_summary_collection_gaps WHERE occurred_at < ?',
                (cutoff,),
            )
            connection.execute(
                'DELETE FROM daily_summary_periods WHERE window_end < ?',
                (cutoff,),
            )


_default_store = DailySummaryStore()


def get_daily_summary_store() -> DailySummaryStore:
    """返回进程内共享的日报运行时存储。"""
    return _default_store
