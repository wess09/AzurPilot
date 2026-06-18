"""
服务器配置模块。

存储全局服务器选择（如 'cn'、'en'）。
使用 'import module.config.server as server' 导入，不要使用 'from xxx import xxx'。
"""
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
VALID_SERVER_LIST = {
    'cn_android': [
        '莱茵演习', '巴巴罗萨', '霸王行动', '冰山行动', '彩虹计划',
        '发电机计划', '瞭望台行动', '十字路口行动', '朱诺行动',
        '杜立特空袭', '地狱犬行动', '开罗宣言', '奥林匹克行动',
        '小王冠行动', '波茨坦公告', '白色方案', '瓦尔基里行动',
        '曼哈顿计划', '八月风暴', '秋季旅行', '水星行动', '莱茵河卫兵',
        '北极光计划', '长戟计划', '暴雨行动', '水仙行动', '冬月计划',
        '长弓计划', '裁决协议',
    ],
    'cn_ios': [
        '夏威夷', '珊瑚海', '中途岛', '铁底湾', '所罗门', '马里亚纳',
        '莱特湾', '硫磺岛', '冲绳岛', '阿留申群岛', '马耳他'
    ],
    'cn_channel': [
        '皇家巡游', '大西洋宪章', '十字军行动', '龙骑兵行动', '冥王星行动', '群岛计划',
    ],
    'en': [
        'Avrora', 'Lexington', 'Sandy', 'Washington', 'Amagi',
        'Little Enterprise'
    ],
    'jp': [
        'ブレスト', '横須賀', '佐世保', '呉', '舞鶴',
        'ルルイエ', 'サモア', '大湊', 'トラック', 'ラバウル',
        '鹿児島', 'マドラス', 'サンディエゴ', '竹敷', 'キール',
        '若松', 'オデッサ', 'スイートバン'
    ]
}


def set_server(package_or_server: str):
    """
    设置全局服务器，影响资源文件和服务器特定方法。

    Args:
        package_or_server: 包名或服务器名称。
    """
    global server
    server = to_server(package_or_server)

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
