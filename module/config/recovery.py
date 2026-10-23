"""异常恢复的只读设置和停机信号，不重载或改写正在绑定任务的配置。"""

import json
from dataclasses import dataclass
from contextlib import contextmanager

from module.config.config_generated import GeneratedConfig
from module.config.deep import deep_get
from module.config.utils import filepath_config
from module.logger import logger


class RecoveryStopped(SystemExit):
    """禁止恢复时越过底层的普通异常捕获，交由工作进程边界退出。"""

    def __init__(self, error, reason):
        super().__init__(1)
        self.error = error
        self.reason = reason


@dataclass
class RecoverySettings:
    config: object
    data: dict
    unreadable: bool = False

    def value(self, name):
        """优先读取已保存设置；测试或无文件的调用方使用已有配置。"""
        group, key = name.split('_', 1)
        default = getattr(GeneratedConfig, name)
        fallback = getattr(self.config, name, default)
        if not isinstance(fallback, (bool, int, float, str)):
            fallback = default
        task = 'RunParams' if group in ('Reboot', 'Watchdog') else 'Alas'
        value = deep_get(self.data, f'{task}.{group}.{key}', default=fallback)
        if isinstance(default, bool):
            if self.unreadable and name == 'Error_HandleError':
                return False
            return value is True
        if isinstance(default, int):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return default
        return value

    def sensitive(self, task):
        """敏感任务设置也取同一份快照，后台线程不访问绑定写操作。"""
        if not self.value('Error_StrictRestart') or not task:
            return False
        import inflection
        path = f'{inflection.camelize(task)}.Scheduler.Sensitive'
        if self.data:
            return deep_get(self.data, path, default=False) is True
        return self.config.cross_get(keys=path, default=False) is True


def read_recovery_settings(config):
    """读取最新设置，文件损坏时禁止异常恢复，保留人工处理现场。"""
    data = getattr(config, 'data', {})
    if not isinstance(data, dict):
        data = {}
    name = getattr(config, 'config_name', None)
    if isinstance(name, str):
        try:
            with open(filepath_config(name), encoding='utf-8') as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise ValueError('配置根节点必须是对象')
        except FileNotFoundError:
            # 无文件的隔离调用仍允许使用传入配置；真实配置丢失时安全停机。
            return RecoverySettings(config, data, unreadable=bool(data))
        except (OSError, ValueError):
            logger.error('[异常恢复] 无法读取最新配置，禁止自动恢复')
            return RecoverySettings(config, data, unreadable=True)
    return RecoverySettings(config, data)


def check_error_recovery(config, error, task=None):
    """每次恢复前检查最新总开关与敏感保护；正常主动启停不调用此入口。"""
    settings = read_recovery_settings(config)
    if not settings.value('Error_HandleError'):
        reason = '异常处理已关闭，停止当前自动化工作进程，保留游戏现场'
    elif settings.sensitive(task or getattr(getattr(config, 'task', None), 'command', None)):
        reason = '敏感任务发生异常，禁止自动恢复'
    else:
        return settings
    logger.error_context(
        title='禁止异常恢复', reason=reason, exc=error,
        impact='仅当前自动化工作进程退出，等待人工处理。',
        action='检查日志和游戏现场，处理问题后手动启动。', level=50,
    )
    raise RecoveryStopped(error, reason)


@contextmanager
def recovery_scope(config, device, error):
    """标记已授权的恢复步骤，让后续截图和启停仍能响应设置关闭。"""
    check_error_recovery(config, error)
    previous = device.__dict__.get('_recovery_error')
    device.__dict__['_recovery_error'] = error
    try:
        yield
    finally:
        if previous is None:
            device.__dict__.pop('_recovery_error', None)
        else:
            device.__dict__['_recovery_error'] = previous


def check_pending_recovery(device):
    """正常主动操作不受影响；恢复过程中每次操作先重新校验授权。"""
    error = device.__dict__.get('_recovery_error')
    if error is not None:
        check_error_recovery(device.config, error)
