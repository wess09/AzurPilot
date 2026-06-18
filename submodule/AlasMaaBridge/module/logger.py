import typing as t

from module.base.decorator import cached_property
from module.config.deep import deep_get
from module.logger import logger


def _log_callback(msg, details):
    logger.info(f'[{msg}] {details}')


class CallbackDetails:
    task_nested = 0

    @classmethod
    def show_nested(cls, msg, task):
        """记录嵌套任务链的层级关系。

        通过缩进展示任务的父子层级，便于调试和追踪任务执行流程。

        Args:
            msg: MAA 回调消息类型，包含 SubTaskStart 或 SubTaskCompleted。
            task: 当前任务名称。
        """
        if 'SubTaskStart' in msg:
            suffix = '=>'
        elif 'SubTaskCompleted' in msg:
            cls.task_nested -= 1
            suffix = '<='
        else:
            suffix = '??'

        logger.info(f'{"--" * cls.task_nested} {suffix} {task}')

        if 'SubTaskStart' in msg:
            cls.task_nested += 1

    @classmethod
    def clear_nested(cls):
        cls.task_nested = 0

    def __init__(self, details):
        self.details = details

    def __str__(self):
        return str(self.details)

    __repr__ = __str__

    def get(self, keys, default=None):
        return deep_get(self.details, keys=keys, default=default)

    def multi_get(self, list_keys: t.List, default=None):
        for keys in list_keys:
            res = self.get(keys, default=None)
            if res is not None:
                return res
        return default

    @cached_property
    def serial(self):
        return self.get('details.address')

    @cached_property
    def task(self):
        return self.multi_get([
            'details.task',
            'subtask',
        ])

    @cached_property
    def taskchain(self):
        return self.multi_get([
            'details.taskchain',
            'taskchain',
        ])

    @cached_property
    def what(self):
        return self.get('what')

    @cached_property
    def stats(self):
        return self.get('details.stats')


def parse_callback(msg, details):
    """解析并美化 MAA 回调日志。

    根据消息类型格式化输出，区分错误、子任务、任务链等不同类型。

    Args:
        msg: MAA 回调消息类型。
        details: 回调消息的详细信息字典。

    Returns:
        bool: 是否成功解析了该回调消息。
    """
    msg = str(msg)
    details = CallbackDetails(details)

    if 'Error' in msg:
        logger.error(f'{msg} {details}')
        return True
    elif msg in [
        'Message.SubTaskStart',
        'Message.SubTaskCompleted',
    ]:
        if details.task:
            CallbackDetails.show_nested(msg, details.task)
            return True
    elif msg == 'Message.SubTaskExtraInfo':
        if details.task:
            if details.stats:
                _log_callback(msg, details.stats)
            else:
                _log_callback(msg, details.task)
            return True
    elif msg in [
        'Message.TaskChainCompleted',
        'Message.AllTasksCompleted',
    ]:
        CallbackDetails.clear_nested()
        if details.taskchain:
            _log_callback(msg, details.taskchain)
            return True
    elif msg in [
        'Message.TaskChainStart',
    ]:
        CallbackDetails.clear_nested()
        if details.taskchain:
            logger.hr(details.taskchain, level=2)
            _log_callback(msg, details.taskchain)
            return True
    elif msg in [
        'Message.ConnectionInfo',
    ]:
        if details.serial and details.what:
            _log_callback(msg, f'{details.serial} {details.what}')
            return True

    return False


def log_callback(msg, details):
    if parse_callback(msg, details):
        pass
    else:
        _log_callback(msg, details)
