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

    优先读取全局配置项 OpsiScheduling_EnableSmartScheduling；
    若全局未设置，则回退读取
    OpsiHazard1Leveling.OpsiScheduling.EnableSmartScheduling。
    """
    # 1) 全局配置字段（GUI 新配置直接挂在这里）
    smart_raw = getattr(config, 'OpsiScheduling_EnableSmartScheduling', None)
    smart = _parse_bool_flag(smart_raw)
    if smart is not None:
        return smart

    # 2) 回退到侵蚀1下的配置字段（老配置或部分实例只写在这里）
    try:
        fallback_raw = config.cross_get(
            keys='OpsiHazard1Leveling.OpsiScheduling.EnableSmartScheduling',
            default=None,
        )
    except (AttributeError, KeyError) as e:
        # 常见于旧配置或部分实例未包含该字段的情况，记录 debug 便于排查
        logger.debug(
            '读取 OpsiHazard1Leveling.OpsiScheduling.EnableSmartScheduling 失败: %s',
            e,
            exc_info=True,
        )
        fallback_raw = None
    except Exception as e:
        # 理论上 cross_get 不应抛出其他异常，记录 warning 便于定位配置/实现问题
        logger.warning(
            '读取侵蚀1智能调度配置时出现异常: %s',
            e,
            exc_info=True,
        )
        fallback_raw = None

    fallback = _parse_bool_flag(fallback_raw)
    if fallback is not None:
        return fallback

    # 默认视为未开启
    return False

