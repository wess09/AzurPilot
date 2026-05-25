# 此文件实现了资源变动的记录与同步功能。
# 当各项资源数值（如石油、魔方等）发生变化时，负责更新配置文件中对应的 Dashboard 项及记录时间戳。
from cached_property import cached_property
from module.logger import logger
from module.config.deep import deep_get
from datetime import datetime


class LogRes:
    """
    set attr--->
    Logres(AzurLaneConfig).<res_name>=resource_value:int
    OR  ={'Value:int, 'Limit/Total':int}:dict
    """
    YellowCoin: list

    def __init__(self, config):
        self.__dict__['config'] = config

    def __setattr__(self, key, value):
        if key in self.groups:
            _key_group = f'Dashboard.{key}'
            original = deep_get(self.config.data, keys=_key_group)
            if isinstance(value, int):
                if original['Value'] != value:
                    _key = _key_group + '.Value'
                    self.config.modified[_key] = value
                    _time = datetime.now().replace(microsecond=0)
                    _key_time = _key_group + f'.Record'
                    self.config.modified[_key_time] = _time
                    if key == 'YellowCoin':
                        try:
                            from module.statistics.cl1_database import db as cl1_db
                            instance_name = getattr(self.config, 'config_name', 'default')
                            cl1_db.async_add_yellow_coin_snapshot(instance_name, int(value), source='dashboard')
                        except Exception:
                            logger.exception('Failed to save yellow coin snapshot')
            elif isinstance(value, dict):
                changed = False
                for value_name, _value in value.items():
                    original_value = original.get(value_name) if isinstance(original, dict) else None
                    if _value == original_value:
                        continue
                    _key = _key_group + f'.{value_name}'
                    self.config.modified[_key] = _value
                    changed = True
                if changed:
                    _key_time = _key_group + f'.Record'
                    _time = datetime.now().replace(microsecond=0)
                    self.config.modified[_key_time] = _time
        else:
            logger.info('No such resource on dashboard')
            super().__setattr__(name=key, value=value)

    def group(self, name):
        return deep_get(self.config.data, f'Dashboard.{name}')
    @cached_property
    def groups(self) -> dict:
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
            logger.warning('No such resource!')
        return True
        """
if __name__ == '__main__':
    from module.config.config import AzurLaneConfig
    config = AzurLaneConfig('alas2')
    LogRes(config=config).ActionPoint = {'Total': 99999, 'Value': 99999}
    config.update()
    exit(0)
