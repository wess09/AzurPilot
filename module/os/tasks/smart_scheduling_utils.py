from module.logger import logger


def _parse_bool_flag(value):
    """
    将配置值解析为布尔值。

    支持:
        - 直接的 bool
        - 常见字符串形式: "true/false", "1/0", "yes/no", "y/n", "on/off"
    解析失败时返回 None，由调用方决定默认行为。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('true', '1', 'yes', 'y', 'on'):
            return True
        if v in ('false', '0', 'no', 'n', 'off'):
            return False
    return None


def is_smart_scheduling_enabled(config) -> bool:
    """
    统一判断是否启用了智能调度（侵蚀1与补黄币任务共享的开关逻辑）。

    智能调度功能由 OpsiScheduling 任务是否运行来控制。
    如果 OpsiScheduling 任务启用，则智能调度功能自动启用。
    """
    # 1) 检查 OpsiScheduling 任务是否启用
    # 使用 cross_get 而不是 getattr，因为 OpsiScheduling_Scheduler_Enable 属性可能未在 GeneratedConfig 中生成
    try:
        scheduling_enabled = config.cross_get(
            keys='OpsiScheduling.Scheduler.Enable',
            default=False
        )
    except (AttributeError, KeyError):
        scheduling_enabled = False

    if scheduling_enabled:
        return True

    # 2) 兼容旧配置：检查 OpsiScheduling_SmartScheduling_EnableSmartScheduling
    smart_raw = getattr(config, 'OpsiScheduling_SmartScheduling_EnableSmartScheduling', None)
    smart = _parse_bool_flag(smart_raw)
    if smart is True:
        return True

    # 3) 回退到侵蚀1下的配置字段（老配置）
    try:
        fallback_raw = config.cross_get(
            keys='OpsiHazard1Leveling.OpsiScheduling.EnableSmartScheduling',
            default=None,
        )
    except (AttributeError, KeyError) as e:
        fallback_raw = None
    except Exception as e:
        logger.warning(
            '读取侵蚀1智能调度配置时出现异常: %s',
            e,
            exc_info=True,
        )
        fallback_raw = None

    fallback = _parse_bool_flag(fallback_raw)
    if fallback is True:
        return True

    # 默认视为未开启
    return False

