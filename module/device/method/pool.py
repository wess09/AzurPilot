"""工作线程池模块。

基于生产者-消费者模型的轻量任务池，用于并发执行截图、控制等设备操作，
提供 Outcome 包装、异常栈帧清理、优雅关闭与异常传播支持。
"""

import abc
import ctypes
import subprocess
from collections import deque
from functools import wraps
from itertools import count
from threading import Lock, Thread
from typing import Generic, NoReturn, TypeVar

from module.logger import logger

ValueT = TypeVar("ValueT", covariant=True)
ResultT = TypeVar("ResultT")


def remove_tb_frames(exc, n: int):
    """移除异常回溯信息中最顶层的 n 个栈帧。

    Args:
        exc (BaseException): 原始异常对象。
        n (int): 要剥离的栈帧层数。

    Returns:
        BaseException: 附加修剪后回溯栈帧的异常对象。
    """
    tb = exc.__traceback__
    for _ in range(n):
        assert tb is not None
        tb = tb.tb_next
    return exc.with_traceback(tb)


class Outcome(abc.ABC, Generic[ValueT]):
    """封装同步计算结果（值或异常）的抽象基类。"""

    @abc.abstractmethod
    def unwrap(self) -> ValueT:
        """返回包含的值或重新抛出捕获的异常。

        Returns:
            ValueT: 成功计算得到的值。

        Raises:
            BaseException: 如果捕获的是异常则将其重新抛出。
        """
        pass


class Value(Outcome[ValueT], Generic[ValueT]):
    """表示成功执行并包含返回值的 Outcome 实现类。"""
    __slots__ = ('value',)

    def __init__(self, value: ValueT):
        """初始化成功值对象。

        Args:
            value: 计算结果值。
        """
        self.value: ValueT = value

    def __repr__(self) -> str:
        return f'Value({self.value!r})'

    def unwrap(self) -> ValueT:
        """获取并返回包含的计算结果值。

        Returns:
            ValueT: 计算结果。
        """
        return self.value


class Error(Outcome[NoReturn]):
    """表示执行失败并捕获了异常的 Outcome 实现类。"""
    __slots__ = ('error',)

    def __init__(self, error: BaseException):
        """初始化异常结果对象。

        Args:
            error: 捕获的异常对象。
        """
        self.error: BaseException = error

    def __repr__(self) -> str:
        return f'Error({self.error!r})'

    def unwrap(self):
        """重新抛出捕获的异常并清理局部变量避免引用循环。

        Raises:
            BaseException: 包含的原始异常。
        """
        captured_error = self.error
        try:
            raise captured_error
        finally:
            # 清理局部变量，防止 captured_error 的 __traceback__ 形成循环引用
            del captured_error, self


def capture(sync_fn, *args, **kwargs):
    """执行同步函数并将其返回值或抛出的异常包装为 Outcome 对象。

    Args:
        sync_fn: 待执行的目标函数。
        *args: 传递给目标函数的位置参数。
        **kwargs: 传递给目标函数的关键字参数。

    Returns:
        Value | Error: 成功时返回 Value，抛出异常时返回 Error。
    """
    try:
        return Value(sync_fn(*args, **kwargs))
    except BaseException as exc:
        exc = remove_tb_frames(exc, 1)
        return Error(exc)


class JobError(Exception):
    """任务执行失败异常。"""
    pass


class JobTimeout(Exception):
    """任务等待超时异常。"""
    pass


class _JobKill(Exception):
    """用于强制终止工作线程的内部异常。"""
    pass


class Job(Generic[ResultT]):
    """轻量单次任务结果队列。

    从 queue.Queue 简化而来，针对一次 put() 和一次 get() 进行极致性能优化。
    """

    def __init__(self, worker, func_args_kwargs):
        """初始化任务对象。

        Args:
            worker: 执行本任务的工作线程实例。
            func_args_kwargs: 函数与入参元组 (func, args, kwargs)。
        """
        self.worker = worker
        self.func_args_kwargs = func_args_kwargs

        self.queue: "deque[Outcome[ResultT]]" = deque()
        self.put_lock = Lock()
        self.notify_get = Lock()
        self.notify_get.acquire()

    def __repr__(self):
        return f'Job({self.func_args_kwargs})'

    def get(self) -> ResultT:
        """阻塞等待并获取任务的执行结果。

        Returns:
            ResultT: 任务执行成功时的返回值。

        Raises:
            BaseException: 任务内部抛出的任何异常。
        """
        self.notify_get.acquire()
        item = self.queue.popleft()
        return item.unwrap()

    def get_or_kill(self, timeout) -> ResultT:
        """在指定超时时间内获取任务结果，超时则强行终止任务。

        Args:
            timeout (float): 最长等待超时时间（秒）。

        Returns:
            ResultT: 任务执行返回值。

        Raises:
            JobTimeout: 超时未获取到结果。
        """
        if self.notify_get.acquire(timeout=timeout):
            item = self.queue.popleft()
            return item.unwrap()
        else:
            self._kill()
            raise JobTimeout

    def _kill(self):
        """终止当前正在执行该任务的工作线程。"""
        with self.put_lock:
            try:
                worker = self.worker
            except AttributeError:
                return
            worker.kill()
            del self.worker


name_counter = count()


class WorkerThread:
    def __init__(self, thread_pool):
        """
        Args:
            thread_pool (WorkerPool):
        """
        self.job: "Job | None" = None
        self.thread_pool = thread_pool
        # 此 Lock 的使用方式非常规。
        #
        # "未锁定" 表示有待处理的任务已分配给我们；
        # "已锁定" 表示没有待处理的任务。
        #
        # 初始时没有任务，因此以锁定状态开始。
        self.worker_lock = Lock()
        self.worker_lock.acquire()
        self.default_name = f"Alasio thread {next(name_counter)}"

        self.thread = Thread(target=self._work, name=self.default_name, daemon=True)
        self.thread.start()

    def __repr__(self):
        return f'{self.__class__.__name__}({self.default_name})'

    def _handle_job(self) -> None:
        # 转换为局部变量，如果分配了新任务，`self.job` 会是另一个值
        job = self.job
        del self.job
        func, args, kwargs = job.func_args_kwargs

        result = capture(func, *args, **kwargs)

        # 通知线程池我们已空闲，可以接受新任务。
        # 在调用 'deliver' 之前执行，这样如果 'deliver' 触发了新任务，
        # 可以分配给我们而不是创建新线程。
        self.thread_pool.idle_workers[self] = None
        self.thread_pool.release_full_lock()

        # 传递结果
        if isinstance(result, Error) and isinstance(result.error, _JobKill):
            # 任务被终止
            pass
        else:
            # 任务完成，放入结果并通知
            with job.put_lock:
                job.queue.append(result)
                del job.worker
                job.notify_get.release()

    def _work(self) -> None:
        while True:
            if self.worker_lock.acquire(timeout=WorkerPool.IDLE_TIMEOUT):
                # 获取到任务
                self._handle_job()
            else:
                # 获取锁超时，可以退出。但存在竞态条件：
                # 可能在即将退出时被分配了任务，因此需要检查。
                try:
                    del self.thread_pool.idle_workers[self]
                except KeyError:
                    # 其他线程已将我们从空闲队列中移除，
                    # 说明正在给我们分配任务 - 继续循环等待。
                    self.thread_pool.release_full_lock()
                    continue
                else:
                    # 成功从空闲队列中移除自己，不会再有新任务，可以安全退出。
                    del self.thread_pool.all_workers[self]
                    self.thread_pool.release_full_lock()
                    return

    def kill(self):
        """强制终止当前工作线程。

        通过向目标线程发送异步异常 `_JobKill` 来中断执行。

        Returns:
            bool: 成功终止返回 True，失败返回 False。
        """
        # 向线程发送 SystemExit
        thread_id = ctypes.c_long(self.thread.ident)
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            thread_id, ctypes.py_object(_JobKill))
        if res <= 1:
            self.thread_pool.all_workers.pop(self, None)
            self.thread_pool.release_full_lock()
            return True
        else:
            try:
                job = self.job
            except AttributeError:
                job = None
            logger.error(f'[设备-线程] 终止线程 {self.thread.ident} 失败，来自任务 {job}')
            # 发送 SystemExit 失败，重置它
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            return False


class WorkerPool:
    """轻量级工作线程池。

    模仿 trio.to_thread.start_thread_soon() 设计，提供低延迟的任务分发与线程复用。
    """

    # 线程空闲 10 秒后退出。
    IDLE_TIMEOUT = 10

    def __init__(self, pool_size: int = 8):
        """初始化线程池。

        Args:
            pool_size (int): 线程池最大线程数量，默认为 8。
        """
        # 线程池最多 8 个线程。
        # Alasio 用于本地低频访问，默认线程池较小
        self.pool_size = pool_size

        self.idle_workers: "dict[WorkerThread, None]" = {}
        self.all_workers: "dict[WorkerThread, None]" = {}

        self.notify_worker = Lock()
        self.notify_worker.acquire()
        self.notify_pool = Lock()
        self.notify_pool.acquire()

    def release_full_lock(self):
        """当工作线程完成任务、退出或被终止时释放满池等待锁。"""
        if self.notify_worker.acquire(blocking=False):
            self.notify_pool.release()

    def _get_thread_worker(self) -> WorkerThread:
        try:
            worker, _ = self.idle_workers.popitem()
            return worker
        except KeyError:
            pass

        # 达到最大线程数时等待
        if len(self.all_workers) >= self.pool_size:
            # 参见 release_full_lock()
            self.notify_worker.release()
            self.notify_pool.acquire()
            # 某个工作线程刚好空闲
            try:
                worker, _ = self.idle_workers.popitem()
                return worker
            except KeyError:
                pass

        # 创建新工作线程
        worker = WorkerThread(self)
        self.all_workers[worker] = None
        return worker

    def start_thread_soon(self, func, *args, **kwargs):
        """在工作线程上调度执行函数，并返回用于获取结果的 Job 对象。

        Args:
            func: 目标可调用对象。
            *args: 位置参数。
            **kwargs: 关键字参数。

        Returns:
            Job[ResultT]: 用于获取执行结果的任务对象。
        """
        worker = self._get_thread_worker()
        job = Job(worker=worker, func_args_kwargs=(func, args, kwargs))

        worker.job = job
        worker.worker_lock.release()
        return job

    def run_on_thread(self, func):
        """将函数装饰为在后台工作线程上异步运行（返回 Job）。

        Args:
            func: 目标函数。

        Returns:
            Callable: 包装后的函数，调用时返回 Job。
        """
        @wraps(func)
        def thread_wrapper(*args, **kwargs) -> "Job[ResultT]":
            return self.start_thread_soon(func, *args, **kwargs)

        return thread_wrapper

    @staticmethod
    def _subprocess_execute(cmd, timeout=10):
        """在子进程中运行 Shell 命令并捕获其标准输出。

        Args:
            cmd (list[str]): 待执行的命令参数列表。
            timeout (float): 命令执行超时时间（秒）。

        Returns:
            bytes: 标准输出字节串。
        """
        logger.info(f'[设备-进程池] 执行: {cmd}')

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)

        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.warning(f'[设备-进程池] 调用超时: {cmd}，标准输出={stdout}，标准错误={stderr}')
        return stdout

    def start_cmd_soon(self, cmd, timeout=10):
        """在工作线程中异步执行子进程命令。

        Args:
            cmd (list[str]): 命令参数列表。
            timeout (float): 超时秒数。

        Returns:
            Job[bytes]: 封装命令输出的 Job 对象。
        """
        worker = self._get_thread_worker()
        job = Job(worker=worker, func_args_kwargs=(
            self._subprocess_execute, (cmd,), {'timeout': timeout}
        ))

        worker.job = job
        worker.worker_lock.release()
        return job

    def wait_jobs(self) -> "WaitJobsWrapper":
        """获取自动等待所有任务完成的上下文管理器。

        Returns:
            WaitJobsWrapper: 任务等待包装器。
        """
        return WaitJobsWrapper(self)

    def gather_jobs(self) -> "GatherJobsWrapper":
        """获取自动等待并收集所有任务结果的上下文管理器。

        Returns:
            GatherJobsWrapper: 结果聚合包装器。
        """
        return GatherJobsWrapper(self)

    def thread_map(self, func, iterables):
        """并发映射函数到参数序列并等待返回所有结果（类似 ThreadPoolExecutor.map）。

        Args:
            func: 目标执行函数。
            iterables: 参数可迭代对象。

        Returns:
            list[ResultT]: 所有任务的执行结果列表。
        """
        jobs = [self.start_thread_soon(func, arg) for arg in iterables]
        results = [job.get() for job in jobs]
        return results

    def thread_starmap(self, func, iterables):
        """并发星号映射函数到解包参数序列（类似 Pool.starmap）。

        Args:
            func: 目标执行函数。
            iterables: 包含参数元组的可迭代对象。

        Returns:
            list[ResultT]: 所有任务的执行结果列表。
        """
        jobs = [self.start_thread_soon(func, *arg) for arg in iterables]
        results = [job.get() for job in jobs]
        return results

    def thread_funcmap(self, func_iterables):
        """并发运行一组无参函数并返回结果。

        Args:
            func_iterables: 可调用对象序列。

        Returns:
            list[ResultT]: 执行结果列表。
        """
        jobs = [self.start_thread_soon(func) for func in func_iterables]
        results = [job.get() for job in jobs]
        return results


class WaitJobsWrapper:
    """等待所有已投递任务执行完毕的上下文管理器。"""

    def __init__(self, pool: "WorkerPool"):
        """初始化等待包装器。

        Args:
            pool (WorkerPool): 所属线程池。
        """
        self.pool: "WorkerPool" = pool
        self.jobs: "list[Job[ResultT]]" = []

    def get(self):
        """等待所有已分发任务完成。"""
        for job in self.jobs:
            job.get()
        self.jobs.clear()

    def __enter__(self):
        self.jobs.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.get()

    def start_thread_soon(self, func, *args, **kwargs):
        """分发新任务并登记到等待列表。

        Args:
            func: 目标函数。
            *args: 位置参数。
            **kwargs: 关键字参数。

        Returns:
            Job[ResultT]: 对应的 Job 实例。
        """
        job = self.pool.start_thread_soon(func, *args, **kwargs)
        self.jobs.append(job)
        return job


class GatherJobsWrapper(WaitJobsWrapper):
    """等待并收集所有已投递任务返回值的上下文管理器。"""

    def __init__(self, pool: "WorkerPool"):
        """初始化聚合包装器。

        Args:
            pool (WorkerPool): 所属线程池。
        """
        super().__init__(pool)
        self.results: "list[ResultT]" = []

    def get(self):
        """等待所有任务完成并收集其结果到 self.results。"""
        for job in self.jobs:
            result = job.get()
            self.results.append(result)
        self.jobs.clear()

    def __enter__(self):
        self.jobs.clear()
        self.results.clear()
        return self


WORKER_POOL = WorkerPool()

