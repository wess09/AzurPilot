"""
服务器配置模块。

存储全局服务器选择（如 'cn'、'en'）。
使用 'import module.config.server as server' 导入，不要使用 'from xxx import xxx'。
"""
from typing import NamedTuple

server = 'cn'  # 默认设为 cn，避免开发工具使用时出错

VALID_SERVER = ['cn', 'en', 'jp', 'tw']
VALID_PACKAGE = {
    'com.bilibili.azurlane': 'cn',
    'com.YoStarEN.AzurLane': 'en',
    'com.YoStarJP.AzurLane': 'jp',
    'com.hkmanjuu.azurlane.gp': 'tw',
}
VALID_CHANNEL_PACKAGE = {
    # 应用商店
    'com.bilibili.blhx.huawei': ('cn', '华为'),
    'com.bilibili.blhx.honor': ('cn', '荣耀'),
    'com.bilibili.blhx.mi': ('cn', '小米'),
    'com.tencent.tmgp.bilibili.blhx': ('cn', '腾讯应用宝'),
    'com.bilibili.blhx.baidu': ('cn', '百度'),
    'com.bilibili.blhx.qihoo': ('cn', '360'),
    'com.bilibili.blhx.nearme.gamecenter': ('cn', 'oppo'),
    'com.bilibili.blhx.vivo': ('cn', 'vivo'),
    'com.bilibili.blhx.mz': ('cn', '魅族'),
    'com.bilibili.blhx.dl': ('cn', '当乐'),
    'com.bilibili.blhx.lenovo': ('cn', '联想'),
    # 'com.bilibili.blhx.letv': ('cn', '乐视'),  # 未确认
    # 'com.bilibili.blhx.gionee': ('cn', '金立'),  # 未确认

    # 第三方游戏平台
    'com.bilibili.blhx.uc': ('cn', 'UC九游'),
    'com.bilibili.blhx.mzw': ('cn', '拇指玩'),
    'com.yiwu.blhx.yx15': ('cn', '一五游戏'),
    'com.bilibili.blhx.m4399': ('cn', '4399'),
    'com.bilibili.blhx.bilibiliMove': ('cn', '迁移'),

    # 台服
    'com.hkmanjuu.azurlane.gp.mc': ('tw', 'MyCard'),
}
DICT_PACKAGE_TO_ACTIVITY = {
    # com.manjuu.azurlane.MainActivity
    # VALID_PACKAGE
    'com.bilibili.azurlane': 'com.manjuu.azurlane.MainActivity',
    'com.YoStarEN.AzurLane': 'com.manjuu.azurlane.PrePermissionActivity',
    'com.YoStarJP.AzurLane': 'com.manjuu.azurlane.PrePermissionActivity',
    'com.hkmanjuu.azurlane.gp': 'com.manjuu.azurlane.PrePermissionActivity',
    # 应用商店
    'com.bilibili.blhx.huawei': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.mi': 'com.manjuu.azurlane.SplashActivity',
    'com.tencent.tmgp.bilibili.blhx': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.baidu': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.qihoo': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.nearme.gamecenter': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.vivo': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.mz': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.dl': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.lenovo': 'com.manjuu.azurlane.SplashActivity',

    # 第三方游戏平台
    'com.bilibili.blhx.uc': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.mzw': 'com.manjuu.azurlane.SplashActivity',
    'com.yiwu.blhx.yx15': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.m4399': 'com.manjuu.azurlane.SplashActivity',
    'com.bilibili.blhx.bilibiliMove': 'com.manjuu.azurlane.SplashActivity',

    # 台服
    'com.hkmanjuu.azurlane.gp.mc': 'com.manjuu.azurlane.PrePermissionActivity',
}


class ServerInfo(NamedTuple):
    """服务器检测 API 所需的固定服务器元数据。"""

    region: str
    server_id: int
    name: str


# 此列表来自 server-checker.nanoda.work 的 /api/v1/status。
# 配置值按列表下标持久化，因此既有条目不得重排。
SERVER_CHECKER_SERVER_LIST: dict[str, tuple[ServerInfo, ...]] = {
    'cn_android': (
        ServerInfo('cn', 1, '莱茵演习'), ServerInfo('cn', 2, '巴巴罗萨'),
        ServerInfo('cn', 3, '霸王行动'), ServerInfo('cn', 4, '冰山行动'),
        ServerInfo('cn', 5, '彩虹计划'), ServerInfo('cn', 6, '发电机计划'),
        ServerInfo('cn', 7, '瞭望台行动'), ServerInfo('cn', 8, '十字路口行动'),
        ServerInfo('cn', 9, '朱诺行动'), ServerInfo('cn', 10, '杜立特空袭'),
        ServerInfo('cn', 11, '地狱犬行动'), ServerInfo('cn', 12, '开罗宣言'),
        ServerInfo('cn', 13, '奥林匹克行动'), ServerInfo('cn', 14, '小王冠行动'),
        ServerInfo('cn', 15, '波茨坦公告'), ServerInfo('cn', 16, '白色方案'),
        ServerInfo('cn', 17, '瓦尔基里行动'), ServerInfo('cn', 18, '曼哈顿计划'),
        ServerInfo('cn', 19, '八月风暴'), ServerInfo('cn', 20, '秋季旅行'),
        ServerInfo('cn', 21, '水星行动'), ServerInfo('cn', 22, '莱茵河卫兵'),
        ServerInfo('cn', 23, '北极光计划'), ServerInfo('cn', 24, '长戟计划'),
        ServerInfo('cn', 25, '暴雨行动'), ServerInfo('cn', 26, '水仙行动'),
        ServerInfo('cn', 27, '冬月计划'), ServerInfo('cn', 28, '长弓计划'),
        ServerInfo('cn', 29, '裁决协议'), ServerInfo('cn', 30, '帷幕计划'),
    ),
    'cn_ios': (
        ServerInfo('cn_ios', 1, '夏威夷'), ServerInfo('cn_ios', 2, '珊瑚海'),
        ServerInfo('cn_ios', 3, '中途岛'), ServerInfo('cn_ios', 4, '铁底湾'),
        ServerInfo('cn_ios', 5, '所罗门'), ServerInfo('cn_ios', 6, '马里亚纳'),
        ServerInfo('cn_ios', 7, '莱特湾'), ServerInfo('cn_ios', 8, '硫磺岛'),
        ServerInfo('cn_ios', 9, '冲绳岛'), ServerInfo('cn_ios', 10, '阿留申群岛'),
        ServerInfo('cn_ios', 11, '马耳他'),
    ),
    'cn_channel': (
        ServerInfo('cn_channel', 1, '皇家巡游'), ServerInfo('cn_channel', 2, '大西洋宪章'),
        ServerInfo('cn_channel', 3, '十字军行动'), ServerInfo('cn_channel', 4, '龙骑兵行动'),
        ServerInfo('cn_channel', 5, '冥王星行动'), ServerInfo('cn_channel', 6, '群岛计划'),
    ),
    'en': (
        ServerInfo('en', 1, 'Avrora'), ServerInfo('en', 2, 'Lexington'),
        ServerInfo('en', 3, 'Sandy'), ServerInfo('en', 4, 'Washington'),
        ServerInfo('en', 5, 'Amagi'), ServerInfo('en', 6, 'Little Enterprise'),
        ServerInfo('en', 7, 'Belfast'),
    ),
    'jp': (
        ServerInfo('jp', 1, 'ブレスト'), ServerInfo('jp', 2, '横須賀'),
        ServerInfo('jp', 4, '佐世保'), ServerInfo('jp', 6, '呉'),
        ServerInfo('jp', 8, '舞鶴'), ServerInfo('jp', 7, 'ルルイエ'),
        ServerInfo('jp', 5, 'サモア'), ServerInfo('jp', 10, '大湊'),
        ServerInfo('jp', 3, 'トラック'), ServerInfo('jp', 9, 'ラバウル'),
        ServerInfo('jp', 12, '鹿児島'), ServerInfo('jp', 13, 'マドラス'),
        ServerInfo('jp', 11, 'サンディエゴ'), ServerInfo('jp', 14, '竹敷'),
        ServerInfo('jp', 15, 'キール'), ServerInfo('jp', 16, '若松'),
        ServerInfo('jp', 17, 'オデッサ'), ServerInfo('jp', 18, 'スイートバン'),
    ),
    'tw': (
        ServerInfo('tw', 1, '珍珠港'), ServerInfo('tw', 2, '珊瑚海'),
        ServerInfo('tw', 3, '中途島'), ServerInfo('tw', 4, '瓜達康納爾'),
        ServerInfo('tw', 5, '雷伊泰灣'),
    ),
}

# 配置生成器和 WebUI 仅需要按现有索引顺序显示服务器名称。
VALID_SERVER_LIST = {
    group: [server.name for server in servers]
    for group, servers in SERVER_CHECKER_SERVER_LIST.items()
}


def get_server_info(server_name: str) -> ServerInfo:
    """
    将持久化的游戏服务器配置值解析为检测 API 元数据。

    Args:
        server_name: 配置中的服务器键，例如 ``jp-2``。

    Returns:
        对应的地区、API ID 和显示名称。

    Raises:
        ValueError: 配置键格式无效或不存在。
    """
    group, separator, index = server_name.rpartition('-')
    if not separator:
        raise ValueError(f'Invalid server name: {server_name}')

    try:
        return SERVER_CHECKER_SERVER_LIST[group][int(index)]
    except (IndexError, KeyError, ValueError) as e:
        raise ValueError(f'Invalid server name: {server_name}') from e


def set_server(package_or_server: str):
    """
    设置全局服务器，影响资源文件和服务器特定方法。

    Args:
        package_or_server: 包名或服务器名称。
    """
    global server
    next_server = to_server(package_or_server)
    # 多个同服实例连接设备时无需重复清空全局资源缓存。旧逻辑即使服务器没有
    # 变化也会 release_resources()，会在另一 worker 模板匹配中间撕裂缓存。
    if next_server == server:
        return
    server = next_server

    from module.base.resource import release_resources
    release_resources()


def to_server(package_or_server: str) -> str:
    """
    将包名或服务器名称转换为服务器标识。
    无法识别的包名默认视为 CN 渠道服。
    """
    if package_or_server in VALID_SERVER:
        return package_or_server
    elif package_or_server in VALID_PACKAGE:
        return VALID_PACKAGE[package_or_server]
    elif package_or_server in VALID_CHANNEL_PACKAGE:
        return VALID_CHANNEL_PACKAGE[package_or_server][0]
    else:
        return 'cn'


def to_package(package_or_server: str) -> str:
    """
    将包名或服务器名称转换为包名。
    """
    package_or_server = package_or_server.lower()
    if package_or_server in VALID_PACKAGE:
        return package_or_server

    for key, value in VALID_PACKAGE.items():
        if value == package_or_server:
            return key

    raise ValueError(f'Server invalid: {package_or_server}')
