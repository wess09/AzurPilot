"""配置重定向工具函数集。

提供配置版本升级时的值转换函数。
当配置 schema 发生变更时（如选项名称修改、值格式调整），
这些函数负责将旧格式的配置值转换为新格式。

重定向函数在 ConfigUpdater.config_redirect() 中被调用，
确保用户升级后无需手动修改配置文件。

常见的重定向场景：
- 选项名称变更（如 'auto' → 'default'）
- 值格式调整（如布尔值 → 枚举值）
- 服务器名称规范化
"""

from module.config.server import to_server


def upload_redirect(value):
    """重定向上传配置属性（Upload）。

    Args:
        value (list[bool] | bool): 旧版上传选项配置。

    Returns:
        str: 新版的上传模式字符串 ('do_not', 'save', 'upload', 'save_and_upload')。
    """
    if isinstance(value, list):
        if not value[0] and not value[1]:
            return 'do_not'
        elif value[0] and not value[1]:
            return 'save'
        elif not value[0] and value[1]:
            return 'upload'
        else:
            return 'save_and_upload'
    else:
        if not value:
            return 'do_not'
        else:
            return 'save'


def api_redirect(value):
    """重定向 API 服务器配置（API）。

    Args:
        value (str): 旧版 API 服务器标识。

    Returns:
        str: 新版 API 路由模式。
    """
    if value == 'auto':
        return 'default'
    elif to_server(value) == 'cn':
        return 'cn_gz_reverse_proxy'
    else:
        return 'default'


def dossier_redirect(value):
    """重定向大型作战档案信标攻击模式（OpsiDossierBeacon -> AttackMode）。

    Args:
        value (bool): 旧版信标开关。

    Returns:
        str: 新版攻击模式字符串 ('current_dossier' 或 'current')。
    """
    if value:
        return 'current_dossier'
    else:
        return 'current'


def meta_assist_limit_redirect(value):
    """将一击即走开关迁移为求援次数上限，保持原有作战策略。"""
    # 核心重定向会跳过 null，WebUI 的只读迁移也应保留默认的无限求援。
    if value is None:
        return 0
    return 0 if value else -1


def sea_miles_interval_redirect(value):
    """海里记录旧开关迁移为天数间隔，保留已有的数字设置。"""
    if value is None:
        return -1
    if isinstance(value, list):
        # 兼容旧版复选框保存的 [] / [True]，沿用原复选框解析规则。
        return 0 if any(bool(item) for item in value) else -1
    if isinstance(value, bool):
        return 0 if value else -1
    return value


def enhance_favourite_redirect(value):
    """重定向强化目标舰船选择（EnhanceFavourite -> ShipToEnhance）。

    Args:
        value (bool): 旧版仅强化喜爱舰船开关。

    Returns:
        str: 新版目标舰船范围 ('all' 或 'favourite')。
    """
    if value:
        return 'all'
    else:
        return 'favourite'


def enhance_check_redirect(value):
    """重定向强化检查数量，确保每类检查数至少为 5。

    Args:
        value (int): 检查次数配置值。

    Returns:
        int: 修正后的检查次数。
    """
    if isinstance(value, int):
        if value < 5:
            return 5
    return value


def emotion_mode_redirect(value):
    """重定向心情计算与低心情警告模式（CalculateEmotion + IgnoreLowEmotionWarn -> Emotion.Mode）。

    Args:
        value (tuple[bool, bool]): (calculate, ignore) 二元组。

    Returns:
        str: 对应的心情处理模式 ('calculate_ignore', 'calculate', 'ignore')。
    """
    calculate, ignore = value
    if calculate:
        if ignore:
            return 'calculate_ignore'
        else:
            return 'calculate'
    else:
        if ignore:
            return 'ignore'
        else:
            # 无效状态，回退为 calculate
            return 'calculate'


def change_ship_redirect(value):
    """重定向旗舰更换及装备更换设置（FlagshipChange + FlagshipEquipChange -> ChangeFlagship）。

    Args:
        value (tuple[bool, bool]): (ship, equip) 二元组。

    Returns:
        str: 对应的更换模式 ('disabled', 'ship_equip', 'ship')。
    """
    ship, equip = value
    if not ship:
        return 'disabled'
    elif equip:
        return 'ship_equip'
    else:
        return 'ship'


def api_redirect2(value):
    """移除上海反向代理，重定向到广州反向代理。

    Args:
        value (str): 代理配置值。

    Returns:
        str: 重定向后的代理配置值。
    """
    if value == 'cn_sh_reverse_proxy':
        return 'cn_gz_reverse_proxy'
    else:
        return value


def coalition_to_frostfall(value):
    """
    将通用难度名转换为霜落活动的内部关卡编号。
    """
    if value == 'easy':
        return 'tc1'
    elif value == 'normal':
        return 'tc2'
    elif value == 'hard':
        return 'tc3'
    else:
        return value


def coalition_to_little_academy(value):
    """
    将旧联动活动的 TC 关卡编号转换为通用难度名。
    """
    normalized = str(value).lower().replace('-', '')
    if normalized == 'tc1':
        return 'easy'
    elif normalized == 'tc2':
        return 'normal'
    elif normalized == 'tc3':
        return 'hard'
    else:
        return value


def execute_fixed_patrol_scan_redirect(value):
    """
    OpsiHazard1Leveling.ExecuteFixedPatrolScan 旧等级枚举 → 布尔开关。

    该配置的形态变过两轮：布尔开关 → 0/1/2 等级 → 又合并回开关（保守模式
    并入效率模式）。存量配置里的数字档位要清洗成布尔，否则复选框会显示
    数字，运行时也容易读错：
    - 0（关闭）           → False
    - 1/2/3（各档强制移动）→ True（等级已合并成同一个效率模式）
    - 布尔值直接透传。
    """
    if isinstance(value, bool):
        return value
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return bool(value)


# 大世界掉落截图拆成按任务分类的开关后的参数名（DropRecord 组内），
# 最后一个 OpsiOther 兜底未单独列出的任务。
OPSI_RECORD_ARGS = (
    'OpsiHazard1Leveling',
    'OpsiMeowfficerFarming',
    'OpsiDaily',
    'OpsiObscure',
    'OpsiAbyssal',
    'OpsiStronghold',
    'OpsiExplore',
    'OpsiOther',
)


def opsi_record_redirect(value):
    """
    OpsiRecord → 按任务拆分的 8 个掉落截图开关。

    旧的单一开关同时管着所有大世界任务，拆分后旧值原样铺给每一个开关，
    升级后各任务的截图行为与升级前一致，不会突然多出或丢掉截图。
    """
    return [value] * len(OPSI_RECORD_ARGS)


def opsi_explore_cleanup_state_redirect(value):
    """只迁移已有补扫断点；原开荒月度标记不能当成补扫进度。"""
    if isinstance(value, dict) and value.get('phase') in ('cleanup', 'done') and 'order' in value:
        return dict(value)
    return None


def opsi_pending_event_redirect(value):
    """保留旧明石续查记录，将其纳入按事件类型区分的恢复。"""
    if isinstance(value, dict):
        return dict(value, kind='is_akashi', phase='interact')
    return None
