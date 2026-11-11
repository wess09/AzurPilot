"""进程内排队写入：把可合并的观测类写入攒批后一次事务落库。

设计要点：
- 只用于「可丢、可重采样」的观测、快照与流水；认证历史、调度文档等仍同步写。
- `latest` 类按 key 保留最新值，`append` 类保序批量提交（依赖业务幂等键）。
- 调度复用 `async_executor` 的单线程事件循环，不新开线程。
- 刷新失败时保留未落库项并在下个窗口重试，连续失败超上限才丢弃最旧项。
"""
import sqlite3
import threading
from pathlib import Path

from module.logger import logger
from module.persistence.database import current_directory, get_database, is_busy, use_database

# 攒批窗口：主循环高频写入合并成每窗口一次事务。
FLUSH_INTERVAL = 0.5
# 攒够该条数立即刷新，避免长时间只写不落库。
FLUSH_THRESHOLD = 200
# 连续刷新失败多少次后丢弃最旧项，防止内存无界增长。
MAX_FAILURES = 5
# 单次刷新的事务预算（秒），复用存储层的分段取锁。
FLUSH_TIMEOUT = 10.0
# 刷新失败后的重试间隔。
RETRY_INTERVAL = 1.0


class WriteQueue:
    """按窗口合并观测类写入的进程内队列。"""

    def __init__(self):
        """初始化待写表与调度状态。"""
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._latest = {}
        self._append = []
        self._scheduled = False
        self._failures = 0

    def enqueue(self, kind, key, apply, *, directory=None):
        """登记一条待写入；`latest` 需要 key，`append` 忽略 key。

        Args:
            kind: `latest` 表示同 key 只保留最新值，`append` 表示保序全部提交。
            key: `latest` 的合并键，通常为 (表名, 实例, 资源)。
            apply: 接收 sqlite3.Connection 的写入函数，必须只依赖该连接。
            directory: 目标配置目录；缺省取当前业务调用绑定的目录。
        """
        directory = Path(directory).absolute() if directory is not None else current_directory()
        with self._lock:
            if kind == 'latest':
                if key is None:
                    raise ValueError('latest 队列项必须提供合并键')
                self._latest[key] = (directory, apply)
            elif kind == 'append':
                self._append.append((directory, apply))
            else:
                raise ValueError(f'未知的队列类型：{kind}')
            size = len(self._latest) + len(self._append)
        if size >= FLUSH_THRESHOLD:
            self.flush(timeout=FLUSH_TIMEOUT)
        else:
            self._schedule()

    def _schedule(self, delay=FLUSH_INTERVAL):
        """安排一次延迟刷新；已在排队时跳过。"""
        with self._lock:
            if self._scheduled:
                return
            self._scheduled = True
        try:
            from module.base.async_executor import async_executor
            future = async_executor.submit(self._deferred_flush, delay)
            future.add_done_callback(self._schedule_finished)
        except Exception as error:
            with self._lock:
                self._scheduled = False
            logger.warning('[存储队列] 无法安排后台刷新：%s', type(error).__name__)

    @staticmethod
    def _schedule_finished(future):
        """后台刷新协程异常时只记类型名，避免 asyncio 打出零散栈。"""
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            logger.warning('[存储队列] 后台刷新异常：%s', type(error).__name__)

    async def _deferred_flush(self, delay):
        """等待窗口结束后刷新队列。"""
        import asyncio
        await asyncio.sleep(delay)
        with self._lock:
            self._scheduled = False
        self.flush(timeout=FLUSH_TIMEOUT)

    def _take(self):
        """取出当前批次：先合并项，再按入队顺序的追加项。"""
        with self._lock:
            latest = [('latest', key, directory, apply) for key, (directory, apply) in self._latest.items()]
            append = [('append', None, directory, apply) for directory, apply in self._append]
            self._latest = {}
            self._append = []
        return latest + append

    def _requeue(self, items):
        """把未落库的批次合并回待写表，已有更新值时保留新值。"""
        with self._lock:
            for kind, key, directory, apply in reversed(items):
                if kind == 'latest':
                    self._latest.setdefault(key, (directory, apply))
                else:
                    self._append.insert(0, (directory, apply))

    def flush(self, timeout=None):
        """把待写项按配置目录分组写入数据库。

        Args:
            timeout: 等待其他刷新完成的最长时间（秒）；None 表示一直等待。

        Returns:
            bool: 队列是否已排空。
        """
        acquired = self._flush_lock.acquire(True, -1 if timeout is None else timeout)
        if not acquired:
            return False
        try:
            items = self._take()
            if not items:
                self._failures = 0
                return True
            batches = {}
            for item in items:
                batches.setdefault(item[2], []).append(item)
            failure = None
            for directory, batch in batches.items():
                database = get_database(directory)
                applied = 0
                try:
                    with use_database(database), database.session(label='write_queue') as connection:
                        for _, _, _, apply in batch:
                            apply(connection)
                            applied += 1
                except sqlite3.Error as error:
                    if is_busy(error):
                        failure = error
                        self._requeue(batch[applied:])
                    else:
                        # 非锁冲突的错误重试也不会成功，丢弃该批避免阻塞后续窗口。
                        logger.warning('[存储队列] 写入失败并丢弃该批：%s', type(error).__name__)
                    break
            if failure is None:
                self._failures = 0
                return True
            self._failures += 1
            if self._failures >= MAX_FAILURES:
                self._failures = 0
                logger.warning('[存储队列] 连续写入失败 %s 次，丢弃积压的观测数据', MAX_FAILURES)
                self.clear()
                return True
            self._schedule(RETRY_INTERVAL)
            return False
        finally:
            self._flush_lock.release()

    def pending(self):
        """返回待写入条数，供测试与诊断使用。"""
        with self._lock:
            return len(self._latest) + len(self._append)

    def clear(self):
        """丢弃所有待写入项，用于测试清理。"""
        with self._lock:
            self._latest.clear()
            self._append.clear()
            self._scheduled = False
            self._failures = 0


write_queue = WriteQueue()
