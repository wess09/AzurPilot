"""异常层次结构。

定义 AzurPilot 的所有自定义异常。异常按严重程度和可恢复性分为以下层次：

正常战役结束（可预期的流程终止）：
    - CampaignEnd: 战役正常结束（回到关卡选择页面）
    - OilExhausted: 石油耗尽，无法继续出击
    - OilMaxed: 石油已达上限，需要消耗

地图导航错误（可恢复，触发重试）：
    - MapDetectionError: 地图透视检测失败（网格识别错误）
    - MapWalkError: 舰队行走错误（目标不可达）
    - MapEnemyMoved: 敌人移动导致路径失效，需要重新规划
    - CampaignNameError: 关卡名称无法识别

游戏状态错误（触发模拟器重启）：
    - GameStuckError: 游戏卡死（1 分钟内无有效操作，战斗期间 5 分钟）
    - GameBugError: 游戏客户端 bug（重启通常可恢复）
    - GameTooManyClickError: 点击次数过多（15 次操作中同一按钮被点 ≥12 次）

连接/页面错误（触发重启或人工干预）：
    - GameNotRunningError: 游戏未运行
    - GamePageUnknownError: 无法识别当前页面
    - EmulatorNotRunningError: 模拟器未运行

开发者/脚本错误：
    - ScriptError: 脚本逻辑错误（通常是代码 bug）
    - ScriptEnd: 脚本正常结束（用于中断当前任务流程）

不可恢复错误（需要人工干预）：
    - RequestHumanTakeover: 请求人工接管（配置错误等严重问题）
    - AutoSearchSetError: 自动搜索设置失败
    - HardNotSatisfied: 困难模式前置条件不满足
"""


class CampaignEnd(Exception):
    """战役正常结束。

    当舰队回到关卡选择页面时抛出，由调度循环捕获并处理后续逻辑
    （如推进关卡、记录掉落等）。
    """
    pass


class OilExhausted(Exception):
    """石油耗尽。

    当战斗准备界面检测到石油不足时抛出，结束当前战役任务。
    """
    pass


class OilMaxed(Exception):
    """石油已达上限。

    当石油溢出时抛出，提示需要消耗石油以免浪费。
    """
    pass


class MapDetectionError(Exception):
    """地图透视检测失败。

    当无法从截图中正确解析地图网格信息时抛出。
    可能原因：信息栏遮挡、弹窗干扰、游戏画面异常。
    """
    pass


class MapWalkError(Exception):
    """舰队行走错误。

    当舰队无法到达目标格子时抛出，可能原因包括路径被阻断、步数不足等。
    """
    pass


class MapEnemyMoved(Exception):
    """敌人移动导致路径失效。

    在可移动敌人系统中，敌人回合移动后当前路径可能不再有效，
    需要重新规划路径。此异常用于中断当前行走并触发重新寻路。
    """
    pass


class CampaignNameError(Exception):
    """关卡名称无法识别。

    当配置中的关卡名称无法映射到有效的地图文件时抛出。
    """
    pass


class ScriptError(Exception):
    """脚本逻辑错误。

    通常是开发者的代码错误，但也可能是偶发的随机问题。
    触发模拟器重启尝试恢复。
    """
    pass


class ScriptEnd(Exception):
    """脚本正常结束。

    用于中断当前任务流程（如情绪不足需要延迟），
    不视为错误，不计入失败次数。
    """
    pass


class GameStuckError(Exception):
    """游戏卡死。

    1 分钟内无有效截图操作（战斗/启动期间为 5 分钟）时触发。
    通常通过重启模拟器恢复。
    """
    pass


class GameBugError(Exception):
    """碧蓝航线游戏客户端发生错误，AzurPilot 无法自行处理。

    通常重启游戏即可恢复。
    """
    pass


class GameTooManyClickError(Exception):
    """点击次数过多，疑似陷入循环。

    最近 15 次操作中，同一按钮被点击 ≥12 次，
    或两个按钮各被点击 ≥6 次时触发。
    """
    pass


class EmulatorNotRunningError(Exception):
    """模拟器未运行。

    当 ADB 连接失败且模拟器进程不存在时抛出。
    """
    pass


class GameNotRunningError(Exception):
    """游戏未运行。

    当截图为黑屏或游戏进程已退出时抛出。
    """
    pass


class GamePageUnknownError(Exception):
    """无法识别当前游戏页面。

    当页面检测逻辑无法匹配任何已知页面时抛出。
    """
    pass


class RequestHumanTakeover(Exception):
    """请求人工接管。

    AzurPilot 无法处理此类错误，可能是由于配置错误导致。
    需要用户手动检查并修正问题。
    """
    pass


class WorkerStop(Exception):
    """单进程宿主请求当前实例协作式停止。

    该异常只用于线程宿主的控制流，必须从任务处理器向上透传至调度循环；不能
    被当作普通任务错误触发游戏或模拟器重启。
    """
    pass


class OcrServerUnavailable(Exception):
    """单进程模式下远程 OCR 服务不可用。

    单进程 worker 禁止回退本地 OCR，以免每个实例重新加载 ONNX 模型并失去
    内存收益。因此该异常会终止当前 worker，等待 OCR 服务恢复后由用户重启。
    """
    pass


class AutoSearchSetError(Exception):
    """自动搜索设置失败。

    当无法正确设置自动搜索选项时抛出（如舰队准备界面异常）。
    """
    pass


class HardNotSatisfied(RequestHumanTakeover):
    """困难模式前置条件不满足。

    继承自 RequestHumanTakeover，当困难关卡的前置条件未满足时抛出。
    """
    pass
