"""大世界开荒模式与共用进度的配置迁移。"""
from copy import deepcopy

from module.config.deep import deep_get, deep_set


def migrate_opsi_explore(old, new):
    """保留当前有效模式及其进度；已有新配置优先，读取时不写盘。"""
    if 'OpsiExplore' not in new:
        return new
    fields = deep_get(old, 'OpsiExplore.OpsiExplore', {})
    legacy = deep_get(old, 'OpsiScheduling.OpsiSmartExplore', {})
    target = new['OpsiExplore'].setdefault('OpsiExplore', {})
    migrated_smart = ('SmartEnable' not in fields and 'TraditionalEnable' not in fields
                      and legacy.get('Enable') is True
                      and deep_get(old, 'OpsiExplore.Scheduler.Enable') is not True)
    if 'SmartEnable' in fields:
        smart = fields['SmartEnable'] is True
    elif 'TraditionalEnable' in fields:
        smart = fields['TraditionalEnable'] is False
    else:
        smart = migrated_smart
    target.update(TraditionalEnable=not smart, SmartEnable=smart)
    if migrated_smart:
        # 旧智能开荒无需开启每月开荒；迁移后由同一个任务开关控制。
        new['OpsiExplore'].setdefault('Scheduler', {})['Enable'] = True
        if 'ForceRun' in legacy:
            target['ForceRun'] = legacy['ForceRun']
    target['Progress'] = fields.get('Progress', legacy.get('Progress', '') if smart
                                    else fields.get('ExploreProgress', ''))
    target.pop('ExploreProgress', None)
    scheduling = new.get('OpsiScheduling', {})
    if 'BuyActionPoint' in legacy and deep_get(old, 'OpsiScheduling.OpsiScheduling.BuyActionPoint') is None:
        scheduling.setdefault('OpsiScheduling', {})['BuyActionPoint'] = legacy['BuyActionPoint']
    scheduling.pop('OpsiSmartExplore', None)
    return new


def reset_opsi_explore_progress(data):
    """同时清除两种开荒的进度及断点，保留购买记录和独立补扫状态。"""
    deep_set(data, 'OpsiExplore.OpsiExplore.Progress', '')
    deep_set(data, 'OpsiExplore.OpsiExplore.LastZone', 0)
    deep_set(data, 'OpsiExplore.OpsiExplore.MeowfficerCleanupState', None)
    storage = deep_get(data, 'OpsiScheduling.Storage.Storage')
    if isinstance(storage, dict):
        # 不修改传入存储对象的其他持有者。
        storage = deepcopy(storage)
        storage.pop('SmartExplore', None)
        deep_set(data, 'OpsiScheduling.Storage.Storage', storage)
