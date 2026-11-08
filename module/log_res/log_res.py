"""资源变动记录与同步模块。

当各项游戏资源数值（如石油、物资、钻石、魔方等）发生变化时，
负责更新配置文件中对应的 Dashboard 项及记录时间戳。

使用示例：
    >>> log_res = LogRes(config)
    >>> log_res.Oil = 12345  # 自动更新 Dashboard.Oil.Value 和记录时间
    >>> log_res.Coin = {'Value': 50000, 'Limit': 99999}  # 同时记录值和上限

Dashboard 数据结构：
    Dashboard.<资源名> = {
        'Value': int,      # 当前值
        'Record': datetime, # 最后更新时间
        'Limit': int,      # 上限（可选）
    }
"""

# 此文件实现了资源变动的记录与同步功能。
# 当各项资源数值（如石油、魔方等）发生变化时，负责更新配置文件中对应的 Dashboard 项及记录时间戳。
from cached_property import cached_property
from module.logger import logger
from module.config.deep import deep_get
from datetime import datetime


class LogRes:
    """资源变动记录器。

    通过属性赋值语法动态更新 Dashboard 配置中的资源值和更新时间戳，
    并同步写入统计数据库快照。

    示例:
        LogRes(config).Oil = 12000
        LogRes(config).ActionPoint = {'Total': 200, 'Value': 150}
    """
    YellowCoin: list

    def __init__(self, config):
        """初始化资源记录器。

        Args:
            config: AzurLaneConfig 配置实例。
        """
        self.__dict__['config'] = config

    def __setattr__(self, key, value):
        self._set_value(key, value)

    def _set_value(self, key, value):
        """设置资源属性值，并自动同步更新 Dashboard 及历史快照。

        Args:
            key (str): 资源名称。
            value (int | dict): 资源数值，或包含 Value/Total/Limit 的字典。
        """
        if key in self.groups:
            observation = self._observe(key, value) if self.__dict__.get('_observation_enabled', True) else None
            _key_group = f'Dashboard.{key}'
            _mod = False
            original = deep_get(self.config.data, keys=_key_group)
            if isinstance(value, int):
                if original['Value'] != value:
                    _key = _key_group + '.Value'
                    self.config.modified[_key] = value
                    _time = self.__dict__.get('_recorded_at') or datetime.now().replace(microsecond=0)
                    _key_time = _key_group + f'.Record'
                    self.config.modified[_key_time] = _time
                    if key == 'YellowCoin':
                        try:
                            from module.statistics.cl1_database import db as cl1_db
                            instance_name = getattr(self.config, 'config_name', 'default')
                            cl1_db.async_add_yellow_coin_snapshot(
                                instance_name, int(value), source='dashboard',
                                observed_at=self.__dict__.get('_recorded_at'),
                            )
                        except Exception:
                            logger.exception('[日志资源] 保存金币快照失败')
                    if observation is not False:
                        self._record_all_resource_snapshot({key: value})
            elif isinstance(value, dict):
                _mod = False
                for value_name, _value in value.items():
                    if _value == original[value_name]:
                        continue
                    _key = _key_group + f'.{value_name}'
                    self.config.modified[_key] = _value
                    _key_time = _key_group + f'.Record'
                    _time = self.__dict__.get('_recorded_at') or datetime.now().replace(microsecond=0)
                    self.config.modified[_key_time] = _time
                    _mod = True
                if _mod:
                    if (key == 'ActionPoint' and value.get('Total') is not None
                            and self.__dict__.get('_observation_enabled', True)):
                        try:
                            from module.statistics.opsi_runtime import record_ap_snapshot
                            source = 'dashboard'
                            task = getattr(self.config, '_bind_task_override', None) or getattr(
                                getattr(self.config, 'task', None), 'command', None
                            )
                            if task:
                                source = task
                            # Total 必须来自本次完整面板读取，不能用旧配置或缓存箱子补齐。
                            record_ap_snapshot(
                                self.config,
                                ap_current=value.get('Value'),
                                ap_total=value['Total'],
                                source=source,
                                observed_at=self.__dict__.get('_recorded_at'),
                            )
                        except Exception:
                            logger.exception('保存行动力快照失败')
                    if observation is not False:
                        value_to_record = value.get('Value')
                        if value_to_record is not None:
                            self._record_all_resource_snapshot({key: value_to_record})
                        else:
                            self._record_all_resource_snapshot()
            return observation is True
        else:
            logger.info('[日志资源] 仪表盘中无此资源')
            super().__setattr__(name=key, value=value)
            return False

    def record(self, name, value, *, observed=True, source=None, defer_history=False, observed_at=None):
        """更新仪表盘，并返回是否成功写入调度观测。"""
        self.__dict__['_observation_enabled'] = observed
        self.__dict__['_observation_source'] = source
        self.__dict__['_defer_history'] = defer_history
        self.__dict__['_recorded_at'] = observed_at or datetime.now()
        try:
            return self._set_value(name, value)
        finally:
            self.__dict__.pop('_observation_enabled', None)
            self.__dict__.pop('_observation_source', None)
            self.__dict__.pop('_defer_history', None)
            self.__dict__.pop('_recorded_at', None)

    def _observe(self, name, value):
        """返回观测写入结果，未尝试写入时返回 None。"""
        from pathlib import Path
        from module.config.utils import filepath_config
        instance = getattr(self.config, 'config_name', None)
        if not isinstance(instance, str) or not Path(filepath_config(instance)).exists():
            return
        current = value.get('Value') if isinstance(value, dict) else value
        if type(current) not in (int, float) or current < 0 or (current == 0 and '_observation_enabled' not in self.__dict__):
            return
        from module.scheduler.store import ProgramStore
        from module.config.time_source import now
        task = getattr(getattr(self.config, 'task', None), 'command', None)
        source = self.__dict__.get('_observation_source') or task or 'task_observation'
        stamp = self.__dict__.get('_recorded_at') or now()
        store = ProgramStore(Path(filepath_config(instance)).parent)
        if not store.observe(instance, name, value, stamp.isoformat(sep=' '), source):
            # 账本和资源快照共用总库，争用时跳过本次同步写入。
            return False
        from module.statistics.resource_flow import observe
        observe(self.config, name, current, source, observed_at=stamp)
        return True

    def _record_all_resource_snapshot(self, overrides=None):
        """记录本次读到的资源，其余资源沿用数据库里最近一行快照。

        不从当前配置对象补全其他资源：战役等模块持有配置副本，副本里的 Dashboard 值可能已过期，
        用它补全会写入一行旧石油、旧物资，使趋势图出现单点尖刺；从未读取的资源也会被记成 0。

        Args:
            overrides (dict, optional): 本次读到的资源键值对。
        """
        try:
            from module.statistics.resource_stats import async_record_resource_snapshot, record_resource_snapshot
            instance_name = getattr(self.config, 'config_name', 'default')
            resources = {}
            for group_name, value in (overrides or {}).items():
                if group_name in self.groups and value is not None:
                    try:
                        resources[group_name] = int(value)
                    except (TypeError, ValueError):
                        pass
            if not resources:
                # 只改了上限等附属字段时没有新的资源读数，不必重复写一行。
                return
            if self.__dict__.get('_defer_history', False):
                async_record_resource_snapshot(instance_name, resources, observed_at=self.__dict__.get('_recorded_at'),
                                               carry_forward=True)
            else:
                record_resource_snapshot(instance_name, resources, carry_forward=True)
        except Exception:
            logger.exception('[日志资源] 记录资源快照失败')

    def group(self, name):
        """获取指定资源的 Dashboard 数据。

        Args:
            name (str): 资源名称。

        Returns:
            dict: 包含 Value、Record 等字段的数据字典。
        """
        return deep_get(self.config.data, f'Dashboard.{name}')

    @cached_property
    def groups(self) -> dict:
        """获取仪表盘中定义的所有资源组字典。

        Returns:
            dict: 仪表盘资源配置字典。
        """
        from module.config.utils import read_file, filepath_argument
        return deep_get(d=read_file(filepath_argument("dashboard")), keys='Dashboard')

    """
    def log_res(self, name, modified: dict, update=True):
        if name in self.groups:
            key = f'Dashboard.{name}'
            original = deep_get(self.config.data, keys=key)
            _mod = False
            for value_name, value in modified.items():
                if value == original[value_name]:
                    continue
                _key = key + f'.{value_name}'
                self.config.modified[_key] = value
                _mod = True
            if _mod:
                _key_time = key + f'.Record'
                _time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.config.modified[_key_time] = _time
                if update:
                    self.config.update()
        else:
            logger.warning('[日志资源] 没有此资源！')
        return True
        """
if __name__ == '__main__':
    from module.config.config import AzurLaneConfig
    config = AzurLaneConfig('alas2')
    LogRes(config=config).ActionPoint = {'Total': 99999, 'Value': 99999}
    config.update()
    exit(0)
