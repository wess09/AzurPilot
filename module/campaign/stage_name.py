"""活动关卡文件名的纯转换规则，不访问配置、文件系统或游戏。"""


SPECIAL_SP_ALIASES = {
    'event_20201126_cn': {'vsp': 'sp'},
    'event_20210723_cn': {'vsp': 'sp'},
    'event_20220324_cn': {'esp': 'sp'},
    'event_20220818_cn': {'esp': 'sp'},
    'event_20221124_cn': {'asp': 'sp', 'a.sp': 'sp'},
    'event_20240425_cn': {'μsp': 'sp', 'usp': 'sp', 'iisp': 'sp'},
    'event_20240724_cn': {'ysp': 'sp', 'y.sp': 'sp'},
}

# 这些活动还接受 A1~A6、SP1~SP6 作为 T1~T6 的别名。
T_CHAPTER_FOLDERS = {
    'event_20211125_cn',
    'event_20231026_cn',
    'event_20241024_cn',
    'event_20250424_cn',
    'event_20250724_cn',
    'event_20250814_cn',
    'event_20251023_cn',
    'event_20260326_cn',
    'event_20260625_cn',
    'war_archives_20230525_cn',
    'war_archives_20231026_cn',
    'war_archives_20240725_cn',
}
T_STAGE_ALIASES = {
    f'{prefix}{index}': f't{index}'
    for prefix in ('a', 'sp')
    for index in range(1, 7)
}
T_HT_CHAPTER_FOLDERS = T_CHAPTER_FOLDERS | {
    'event_20200917_cn',
    'event_20221124_cn',
    'event_20230525_cn',
    'war_archives_20200917_cn',
    'event_20231123_cn',
    'event_20240725_cn',
    'event_20240829_cn',
    'event_20241121_cn',
}
ABCD_TO_T_HT = {
    'a1': 't1', 'a2': 't2', 'a3': 't3',
    'b1': 't4', 'b2': 't5', 'b3': 't6',
    'c1': 'ht1', 'c2': 'ht2', 'c3': 'ht3',
    'd1': 'ht4', 'd2': 'ht5', 'd3': 'ht6',
}
T_HT_TO_ABCD = {value: key for key, value in ABCD_TO_T_HT.items()}


def normalize_event_stage(name, folder):
    """按原顺序转换已标准化的地图文件名，必须在循环别名选择之前调用。

    Args:
        name (str): 已经 to_map_file_name 处理的名称，不是原始用户输入。
        folder (str): 已选定的活动或作战档案目录。

    Returns:
        str: 活动规则转换后的名称。
    """
    name = SPECIAL_SP_ALIASES.get(folder, {}).get(name, name)
    if folder == 'event_20240425_cn':
        # 先识别精确的 iisp 等 SP 别名，再处理 ISP 拼写，不能交换顺序。
        name = name.replace('lsp', 'isp').replace('1sp', 'isp')
        if name == 'isp':
            name = 'isp1'

    if folder in T_CHAPTER_FOLDERS:
        name = T_STAGE_ALIASES.get(name, name)
    if folder in T_HT_CHAPTER_FOLDERS:
        name = ABCD_TO_T_HT.get(name, name)
    else:
        name = T_HT_TO_ABCD.get(name, name)

    if folder == 'event_20221124_cn':
        name = name.replace('ht', 'th')
    if folder == 'event_20230817_cn' and name.startswith('e0'):
        name = 'a1'
    if folder == 'event_20240829_cn' and name == 'tp':
        name = 'sp'
    return name


def normalize_post_loop_stage(name, folder):
    """保留在循环选择之后才生效的活动别名，不重复执行其他名称转换。"""
    if folder == 'event_20260417_cn' and name == 'vsp':
        return 'sp'
    return name
