from module.logger import logger


def is_smart_scheduling_enabled(config) -> bool:
    """
    统一判断是否启用了智能调度（侵蚀1与补黄币任务共享的开关逻辑）。

    智能调度功能由 OpsiScheduling 任务是否运行来控制。
    如果 OpsiScheduling 任务启用，则智能调度功能自动启用。
    """
    # 检查 OpsiScheduling 任务是否启用
    # 使用 cross_get 而不是 getattr，因为 OpsiScheduling_Scheduler_Enable 属性可能未在 GeneratedConfig 中生成
    try:
        scheduling_enabled = config.cross_get(
            keys='OpsiScheduling.Scheduler.Enable',
            default=False
        )
    except (AttributeError, KeyError):
        scheduling_enabled = False

    return scheduling_enabled

