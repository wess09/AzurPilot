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
    """
    Args:
        exc (BaseException):
        n:

    Returns:
        BaseException:
    """
    tb = exc.__traceback__
    for _ in range(n):
        assert tb is not None
        tb = tb.tb_next
    return exc.with_traceback(tb)


class Outcome(abc.ABC, Generic[ValueT]):
    @abc.abstractmethod
    def unwrap(self) -> ValueT:
        """返回或抛出包含的值或异常。

        以下两行代码是等价的::

           x = fn(*args)
           x = outcome.capture(fn, *args).unwrap()

        """
        pass


class Value(Outcome[ValueT], Generic[ValueT]):
    """表示常规值的 :class:`Outcome` 具体子类。

    """
    __slots__ = ('value',)

    def __init__(self, value: ValueT):
        self.value: ValueT = value

    def __repr__(self) -> str:
        return f'Value({self.value!r})'

    def unwrap(self) -> ValueT:
        return self.value


class Error(Outcome[NoReturn]):
    """表示已抛出异常的 :class:`Outcome` 具体子类。

    """
    __slots__ = ('error',)

    def __init__(self, error: BaseException):
        self.error: BaseException = error

    def __repr__(self) -> str:
        return f'Error({self.error!r})'

    def unwrap(self):
        # 回溯信息会脱离上下文显示下面的 'raise' 行，因此给这个变量
        # 取一个在脱离上下文时仍有意义的名字。
        captured_error = self.error
        try:
            raise captured_error
        finally:
            # 这里需要避免创建引用循环。Python 能正常回收循环引用，
            # 所以即使创建了循环也不是世界末日，但循环垃圾回收器会
            # 增加 Python 程序的延迟，创建的循环越多，回收器运行越频繁，
            # 所以最好从一开始就避免创建循环。更多详情请参阅:
            #
            #    https://github.com/python-trio/trio/issues/1770
            #
            # 具体来说，通过从 'unwrap' 方法的栈帧中删除这些局部变量，
            # 可以避免 'captured_error' 对象的 __traceback__ 间接引用
            # 'captured_error' 本身。
            del captured_error, self


def capture(sync_fn, *args, **kwargs):
    """
    运行 ``sync_fn(*args, **kwargs)`` 并捕获结果。

    Args:
        sync_fn (Callable[..., ResultT]):

    Returns:
        Value[ResultT] | Error:
    """
    try:
        return Value(sync_fn(*args, **kwargs))
    except BaseException as exc:
        exc = remove_tb_frames(exc, 1)
        return Error(exc)


class JobError(Exception):
    pass


class JobTimeout(Exception):
    pass


class _JobKill(Exception):
    pass


class Job(Generic[ResultT]):
    """
    简单队列，从 queue.Queue() 复制而来。
    更快但只能 put() 一次和 get() 一次。
    """

    # __slots__ = ('worker', 'func_args_kwargs', 'queue', 'mutex', 'finished')

    def __init__(self, worker, func_args_kwargs):
        # 有 "worker" 属性表示任务正在进行中
        # 没有 "worker" 属性表示任务已完成或被终止
        self.worker = worker
        self.func_args_kwargs = func_args_kwargs

        self.queue: "deque[Outcome[ResultT]]" = deque()
        self.put_lock = Lock()
        self.notify_get = Lock()
        self.notify_get.acquire()

    def __repr__(self):
        return f'Job({self.func_args_kwargs})'

    def get(self) -> ResultT:
        """
        获取任务结果或任务错误。
        """
        self.notify_get.acquire()

        # 返回任务结果或抛出任务错误
        item = self.queue.popleft()
        return item.unwrap()

    def get_or_kill(self, timeout) -> ResultT:
        """
        尝试在给定秒数内获取结果。
        成功则返回任务结果或任务错误，失败则终止任务并抛出 JobTimeout。

        注意当线程池已满时，JobTimeout 可能不会立即抛出。
        """
        if self.notify_get.acquire(timeout=timeout):
            # 返回任务结果或抛出任务错误
            item = self.queue.popleft()
            return item.unwrap()
        else:
            self._kill()
            raise JobTimeout

    def _kill(self):
        with self.put_lock:
            try:
                worker = self.worker
            except AttributeError:
                # 尝试终止已完成的任务，不做任何操作
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
        """
        终止线程确实不安全，但当单个任务函数阻塞时别无选择。
        此方法应受 `job.put_lock` 保护，以防止与 `_handle_job()` 的竞态条件。

        Returns:
            bool: 是否成功终止线程
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
            logger.error(f'终止线程 {self.thread.ident} 失败，来自任务 {job}')
            # 发送 SystemExit 失败，重置它
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            return False


class WorkerPool:
    """
    模仿 trio.to_thread.start_thread_soon() 的线程池。
    参考: https://github.com/python-trio/trio/issues/6
    """

    # 线程空闲 10 秒后退出。
    IDLE_TIMEOUT = 10

    def __init__(self, pool_size: int = 8):
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
        """
        当工作线程完成任务、退出或被终止时调用此方法。

        当线程池已满时，
        线程池通知所有工作线程：任何完成任务的线程请通知我。
        `self.notify_worker.release()`
        然后线程池阻塞自己。
        `self.notify_pool.acquire()`
        最快的工作线程（也是唯一一个）接收到消息。
        `if self.notify_worker.acquire(blocking=False):`
        工作线程通知线程池，新槽位已就绪，可以继续。
        `self.notify_pool.release()`
        """
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
            # 某个工作线程刚好退出
            # if len(self.all_workers) < WorkerPool.MAX_WORKER:
            #     break

        # 创建新工作线程
        worker = WorkerThread(self)
        # logger.info(f'New worker thread: {worker.default_name}')
        self.all_workers[worker] = None
        return worker

    def start_thread_soon(self, func, *args, **kwargs):
        """
        在线程上运行函数，结果可从 `job` 对象获取。

        Args:
            func (Callable[..., ResultT]):
            *args:
            **kwargs:

        Returns:
            Job[ResultT]:

        Examples:
            job = WORKER_POOL.start_thread_soon(func, *args)
            result = job.get()
        """
        worker = self._get_thread_worker()
        job = Job(worker=worker, func_args_kwargs=(func, args, kwargs))

        worker.job = job
        worker.worker_lock.release()
        return job

    def run_on_thread(self, func):
        """
        装饰器，使函数在线程上运行，结果可从 `job` 对象获取。

        Args:
            func (Callable[..., ResultT]):

        Returns:
            Job[ResultT]:

        Examples:
            @run_on_thread
            def function(...):
                pass
            job = function(...)
            result = job.get()
        """
        @wraps(func)
        def thread_wrapper(*args, **kwargs) -> "Job[ResultT]":
            return self.start_thread_soon(func, *args, **kwargs)

        return thread_wrapper

    @staticmethod
    def _subprocess_execute(cmd, timeout=10):
        """
        在子进程中运行命令的辅助函数。

        Args:
            cmd (list[str]):
            timeout:

        Returns:
            bytes:
        """
        logger.info(f'Execute: {cmd}')

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)

        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.warning(f'TimeoutExpired when calling {cmd}, stdout={stdout}, stderr={stderr}')
        return stdout

    def start_cmd_soon(self, cmd, timeout=10):
        """
        在子进程中运行命令并在另一个线程上通信，结果可从 `job` 对象获取。

        Args:
            cmd (list[str]):
            timeout:

        Returns:
            Job[bytes]:
        """
        worker = self._get_thread_worker()
        job = Job(worker=worker, func_args_kwargs=(
            self._subprocess_execute, (cmd,), {'timeout': timeout}
        ))

        worker.job = job
        worker.worker_lock.release()
        return job

    def wait_jobs(self) -> "WaitJobsWrapper":
        """
        自动等待所有任务完成。

        Examples:
            with WORKER_POOL.wait_jobs() as pool:
                pool.start_thread_soon(...)
        """
        return WaitJobsWrapper(self)

    def gather_jobs(self) -> "GatherJobsWrapper":
        """
        自动等待所有任务完成并收集结果。

        Examples:
            pool = WORKER_POOL.gather_jobs()
            with pool:
                pool.start_thread_soon(...)
            # 获取结果
            print(pool.results)
        """
        return GatherJobsWrapper(self)

    def thread_map(self, func, iterables):
        """
        ThreadPoolExecutor.map(func, iterables) 的替代方案。

        Args:
            func (Callable[..., ResultT]):
            iterables:

        Returns:
            list[ResultT]:
        """
        jobs = [self.start_thread_soon(func, arg) for arg in iterables]
        results = [job.get() for job in jobs]
        return results

    def thread_starmap(self, func, iterables):
        """
        multiprocessing.pool.Pool().starmap(func, iterables) 的线程版本替代方案。

        Args:
            func (Callable[..., ResultT]):
            iterables:

        Returns:
            list[ResultT]:
        """
        jobs = [self.start_thread_soon(func, *arg) for arg in iterables]
        results = [job.get() for job in jobs]
        return results

    def thread_funcmap(self, func_iterables):
        """
        在线程上运行一组函数。

        Args:
            func_iterables (Iterable[Callable[..., ResultT]]):

        Returns:
            list[ResultT]:
        """
        jobs = [self.start_thread_soon(func) for func in func_iterables]
        results = [job.get() for job in jobs]
        return results


class WaitJobsWrapper:
    """
    等待所有任务完成的包装类。
    """

    def __init__(self, pool: "WorkerPool"):
        self.pool: "WorkerPool" = pool
        self.jobs: "list[Job[ResultT]]" = []

    def get(self):
        for job in self.jobs:
            job.get()
        self.jobs.clear()

    def __enter__(self):
        self.jobs.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.get()

    def start_thread_soon(self, func, *args, **kwargs):
        """
        在线程上运行函数，结果可从 `job` 对象获取。

        Args:
            func (Callable[..., ResultT]):
            *args:
            **kwargs:

        Returns:
            Job[ResultT]:
        """
        job = self.pool.start_thread_soon(func, *args, **kwargs)
        self.jobs.append(job)
        return job


class GatherJobsWrapper(WaitJobsWrapper):
    """
    收集所有任务结果的包装类。
    """

    def __init__(self, pool: "WorkerPool"):
        super().__init__(pool)
        self.results: "list[ResultT]" = []

    def get(self):
        for job in self.jobs:
            result = job.get()
            self.results.append(result)
        self.jobs.clear()

    def __enter__(self):
        self.jobs.clear()
        self.results.clear()
        return self


WORKER_POOL = WorkerPool()
