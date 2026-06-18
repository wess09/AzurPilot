from time import time, sleep
from datetime import datetime, timedelta
from functools import wraps


def timer(function):
    """计时装饰器，仅用于调试。"""

    @wraps(function)
    def function_timer(*args, **kwargs):
        start = time()
        result = function(*args, **kwargs)
        cost = time() - start
        print(f'{function.__name__}: {cost:.10f} s')
        return result

    return function_timer


def future_time(string):
    """解析时间字符串，返回未来最近的对应时刻。

    Args:
        string (str): 时间字符串，如 "14:59"。

    Returns:
        datetime.datetime: 未来最近的对应时分时刻。
    """
    hour, minute = [int(x) for x in string.split(':')]
    future = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    future = future + timedelta(days=1) if future < datetime.now() else future
    return future


def past_time(string):
    """解析时间字符串，返回过去最近的对应时刻。

    Args:
        string (str): 时间字符串，如 "14:59"。

    Returns:
        datetime.datetime: 过去最近的对应时分时刻。
    """
    hour, minute = [int(x) for x in string.split(':')]
    past = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    past = past - timedelta(days=1) if past > datetime.now() else past
    return past


def future_time_range(string):
    """解析时间范围字符串，返回未来的起止时刻。

    Args:
        string (str): 时间范围字符串，如 "23:30-06:30"。

    Returns:
        tuple[datetime.datetime, datetime.datetime]: (起始时刻, 结束时刻)。
    """
    start, end = [future_time(s) for s in string.split('-')]
    if start > end:
        start = start - timedelta(days=1)
    return start, end


def time_range_active(time_range):
    """判断当前时间是否在给定时间范围内。

    Args:
        time_range (tuple[datetime.datetime, datetime.datetime]): (起始时刻, 结束时刻)。

    Returns:
        bool: 当前时间在范围内返回 True。
    """
    return time_range[0] < datetime.now() < time_range[1]


class Timer:
    """双重计时器，同时支持时间计数和访问计数。

    访问计数可以在慢速设备上提供鲁棒性——当截图耗时超过计时器限制时，
    仍能通过访问次数判断是否达到触发条件。
    """

    def __init__(self, limit, count=0):
        """初始化计时器。

        Args:
            limit (int | float): 时间限制（秒）。
            count (int): 访问次数限制，默认为 0。
        """
        self.limit = limit
        self.count = count
        self._start = 0.
        self._access = 0

    @classmethod
    def from_seconds(cls, limit, speed=0.5):
        """根据给定秒数创建计时器，自动计算访问次数。

        Args:
            limit (int | float): 时间限制（秒）。
            speed (int | float): 近似截图耗时（秒）。
                如果耗时超过 0.5 秒，设备被视为慢速设备。
        """
        count = int(limit / speed)
        return cls(limit, count=count)

    def start(self):
        """启动计时器。

        如果计时器未启动，reached() 始终返回 True，从而实现首次快速尝试：

        ```python
        interval = Timer(2)
        while 1:
            if interval.reached():
                pass
        ```

        Returns:
            Timer: 自身实例，支持链式调用。
        """
        if self._start <= 0:
            self._start = time()
            self._access = 0

        return self

    def started(self):
        """判断计时器是否已启动。

        Returns:
            bool: 已启动返回 True。
        """
        return self._start > 0

    def current_time(self):
        """获取计时器自启动以来经过的时间。

        Returns:
            float: 经过的秒数，未启动时返回 0.0。
        """
        if self._start > 0:
            diff = time() - self._start
            if diff < 0:
                diff = 0.
            return diff
        else:
            return 0.

    def current_count(self):
        """获取当前访问计数。

        Returns:
            int: 当前访问次数。
        """
        return self._access

    def add_count(self):
        """手动增加一次访问计数。

        Returns:
            Timer: 自身实例，支持链式调用。
        """
        self._access += 1
        return self

    def reached(self):
        """判断计时器是否已达到触发条件。

        每次调用 reached() 都会被计为一次访问。
        需要同时满足访问次数和时间限制才会返回 True。

        Returns:
            bool: 达到条件返回 True；计时器未启动时始终返回 True（用于首次快速尝试）。
        """
        # 每次 reached() 调用计为一次访问
        self._access += 1
        if self._start > 0:
            return self._access > self.count and time() - self._start > self.limit
        else:
            # 未启动时返回 True，实现首次快速尝试
            return True

    def reset(self):
        """重置计时器，如同刚刚启动。

        Returns:
            Timer: 自身实例，支持链式调用。
        """
        self._start = time()
        self._access = 0
        return self

    def clear(self):
        """清除计时器，如同从未启动。

        Returns:
            Timer: 自身实例，支持链式调用。
        """
        self._start = 0.
        self._access = self.count
        return self

    def reached_and_reset(self):
        """判断是否达到触发条件，达到则自动重置。

        Returns:
            bool: 达到条件并已重置返回 True，否则返回 False。
        """
        if self.reached():
            self.reset()
            return True
        else:
            return False

    def wait(self):
        """阻塞等待直到计时器达到时间限制。"""
        diff = self._start + self.limit - time()
        if diff > 0:
            sleep(diff)

    def show(self):
        """通过日志输出计时器当前状态。"""
        from module.logger import logger
        logger.info(str(self))

    def __str__(self):
        # Timer(limit=2.351/3, count=4/6)
        return f'Timer(limit={round(self.current_time(), 3)}/{self.limit}, count={self._access}/{self.count})'

    __repr__ = __str__
