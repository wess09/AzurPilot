class CampaignEnd(Exception):
    pass


class OilExhausted(Exception):
    pass


class OilMaxed(Exception):
    pass


class MapDetectionError(Exception):
    pass


class MapWalkError(Exception):
    pass


class MapEnemyMoved(Exception):
    pass


class CampaignNameError(Exception):
    pass


class ScriptError(Exception):
    # 通常是开发者的代码错误，但也可能是偶发的随机问题
    pass


class ScriptEnd(Exception):
    pass


class GameStuckError(Exception):
    pass


class GameBugError(Exception):
    # 碧蓝航线游戏客户端发生错误，AzurPilot 无法自行处理。
    # 通常重启游戏即可恢复。
    pass


class GameTooManyClickError(Exception):
    pass


class EmulatorNotRunningError(Exception):
    pass


class GameNotRunningError(Exception):
    pass


class GamePageUnknownError(Exception):
    pass


class RequestHumanTakeover(Exception):
    # 请求人工接管
    # AzurPilot 无法处理此类错误，可能是由于配置错误导致。
    pass


class AutoSearchSetError(Exception):
    pass
