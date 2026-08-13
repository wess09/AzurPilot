import json
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta

import inflection
from cached_property import cached_property

from module.base.decorator import del_cached_property
from module.base.api_client import ApiClient
from module.base.ssh import clear_ssh_host_key
from module.config.config import AzurLaneConfig, TaskEnd
from module.config.deep import deep_get, deep_set
from module.config.time_source import now as current_time
from module.config.utils import (
    DEFAULT_CONFIG_NAME,
    ensure_time,
    filepath_i18n,
    get_server_last_update,
    get_server_next_update,
    read_file,
)
from module.exception import *
from module.logger import logger
from module.notify import handle_notify, notify_webui

# 缓存 i18n 任务名查找
_i18n_task_names = None
def _get_task_display_name(task_command):
    """从 i18n 获取任务的本地化显示名，找不到则返回英文名"""
    global _i18n_task_names
    if _i18n_task_names is None:
        _i18n_task_names = {}
        try:
            # 优先使用 deploy.yaml 中配置的语言，否则默认 zh-CN
            deploy_cfg = read_file('./config/deploy.yaml')
            lang = 'zh-CN'
            if isinstance(deploy_cfg, dict):
                lang = deploy_cfg.get('Language', 'zh-CN')
        except Exception:
            lang = 'zh-CN'

        try:
            i18n_file = filepath_i18n(lang)
            if os.path.exists(i18n_file):
                with open(i18n_file, encoding='utf-8') as f:
                    data = json.load(f)
                _i18n_task_names = {
                    k: v.get('name', k)
                    for k, v in data.get('Task', {}).items()
                }
        except Exception:
            pass
    return _i18n_task_names.get(task_command, task_command)




class AzurLaneAutoScript:
    stop_event: threading.Event = None

    def __init__(self, config_name=DEFAULT_CONFIG_NAME):
        logger.hr('Start', level=0)
        self.config_name = config_name
        # 跳过启动后的第一次 Restart 任务
        self.is_first_task = True
        # 任务失败计数器，key 为任务名，value 为连续失败次数
        self.failure_record = {}
        # 连续卡死/ADB 离线计数，用于判断是否需要重启模拟器
        self.consecutive_game_stuck = 0
        self.consecutive_adb_offline = 0
        # ScriptError 连续计数，达到阈值后退出（代码 bug 重试无意义）
        self.script_error_count = 0
        # 上次计划重启模拟器的时间戳
        self.last_emulator_restart_time = time.monotonic()
        # 待恢复的大世界特殊海域子任务名（跨模拟器/设备重建存活），消费后置 None
        self.game_stuck_recovery_task = None

    def _try_restart_emulator(self):
        """
        尝试重启模拟器。永不放弃，一直重试。

        不再受 Error_AdbOfflineRestart 开关限制，
        超过阈值时仅增加等待间隔，不停止重试。
        优先使用已缓存的 device 对象，否则根据平台回退创建新实例。

        Returns:
            bool: 重启成功返回 True，本次重启失败返回 False（调度器会继续尝试）。
        """
        import sys

        self.consecutive_adb_offline += 1
        limit = int(self.config.Error_AdbOfflineThreshold)
        logger.warning(f'[Alas] EmulatorNotRunningError: 连续次数 {self.consecutive_adb_offline}/{limit}')

        # 超过阈值时不放弃，仅增加等待间隔后继续重试
        if self.consecutive_adb_offline > limit:
            wait_seconds = min(300, 30 * (self.consecutive_adb_offline - limit + 1))
            logger.warning(
                f'[Alas] 已超过重启阈值 {limit}，'
                f'等待 {wait_seconds} 秒后继续重试（永不放弃）'
            )
            time.sleep(wait_seconds)

        logger.hr('[Alas] 正在重启模拟器', level=1)
        try:
            # 优先使用已缓存的设备对象
            device = self.__dict__.get('device', None)
            if device is None:
                # device 缓存不存在时，按平台回退创建新实例
                if sys.platform == 'darwin':
                    from module.device.platform.platform_mac import PlatformMac
                    device = PlatformMac(self.config)
                else:
                    from module.device.platform.platform_windows import PlatformWindows
                    device = PlatformWindows(self.config)

            logger.info('[Alas] 正在停止模拟器...')
            device.emulator_stop()
            time.sleep(5)
            logger.info('[Alas] 正在启动模拟器...')
            device.emulator_start()
            logger.info('[Alas] 模拟器重启完成')

            # 清除 device 缓存，下次访问时重新建立连接
            if 'device' in self.__dict__:
                del_cached_property(self, 'device')
            # 重置连续离线计数
            self.consecutive_adb_offline = 0
            return True
        except Exception as e:
            logger.exception_context(
                title='重启模拟器失败',
                exc=e,
                impact='模拟器仍可能处于离线状态，调度器将继续尝试。',
                action='检查模拟器进程权限、ADB 服务和模拟器管理配置。',
            )
            return False

    def _start_emulator_after_long_wait(self):
        """
        长时间等待关闭模拟器后，显式启动模拟器。

        这是省资源功能的正常恢复路径，不受 ADB 离线重启开关和次数限制。

        Returns:
            bool: 启动成功返回 True，失败返回 False。
        """
        logger.hr('[Alas] 长时间等待后启动模拟器', level=1)
        try:
            from module.device.platform import Platform

            platform = Platform(self.config, connect=False)
            if platform.emulator_instance is None:
                logger.warning('[Alas] 未找到模拟器实例，无法在长时间等待后启动模拟器')
                return False

            if platform.emulator_start():
                logger.info('[Alas] 长时间等待后模拟器启动完成')
                if 'device' in self.__dict__:
                    del_cached_property(self, 'device')
                return True

            logger.warning('[Alas] 长时间等待后启动模拟器失败，继续调度恢复流程')
            return False
        except Exception as e:
            logger.warning(f'[Alas] 长时间等待后启动模拟器失败，继续调度恢复流程: {e}')
            return False

    @cached_property
    def config(self):
        try:
            config = AzurLaneConfig(config_name=self.config_name)
            return config
        except RequestHumanTakeover:
            logger.error_context(
                title='配置初始化需要人工介入',
                reason='配置加载或配置校验未通过，自动修复无法继续。',
                impact='调度器无法启动。',
                action='检查配置文件和最近一次错误堆栈，修正配置后重新启动。',
                level=50,
            )
            exit(1)
        except Exception as e:
            logger.exception_context(
                title='配置初始化失败', exc=e,
                impact='调度器无法启动。',
                action='检查 config 目录中的配置格式、参数名称和文件权限。',
                level=50,
            )
            exit(1)

    @cached_property
    def device(self):
        try:
            from module.device.device import Device
            device = Device(config=self.config)
            return device
        except RequestHumanTakeover:
            logger.error_context(
                title='设备初始化需要人工介入',
                reason='设备连接或设备参数校验未通过，自动修复无法继续。',
                impact='调度器无法控制模拟器。',
                action='确认模拟器已启动、ADB 可用且分辨率为 1280x720，然后重新启动。',
                level=50,
            )
            exit(1)
        except Exception as e:
            logger.exception_context(
                title='设备初始化失败', exc=e,
                impact='调度器无法控制模拟器。',
                action='检查模拟器、ADB 连接和当前截图/控制方案配置。',
                level=50,
            )
            exit(1)

    @cached_property
    def checker(self):
        try:
            from module.server_checker import ServerChecker
            checker = ServerChecker(server=self.config.Emulator_ServerName)
            return checker
        except Exception as e:
            logger.exception_context(
                title='服务器状态检查器初始化失败', exc=e,
                impact='无法判断服务器维护状态，调度器无法继续。',
                action='检查网络连接、服务器配置和相关依赖后重新启动。',
                level=50,
            )
            exit(1)

    def _check_sensitive_exit(self, command, error):
        """
        检查当前任务是否为敏感任务，如果是则直接退出。

        敏感任务出错时不做任何重启或恢复，完全停止 Alas 运行。

        Args:
            command (str): 任务方法名（下划线形式，如 opsi_cross_month）。
            error (Exception): 触发的异常对象。

        Returns:
            bool: True 表示已退出（不会返回），False 表示非敏感任务，继续原有逻辑。
        """
        task_name = inflection.camelize(command)
        sensitive = self.config.cross_get(
            keys=f'{task_name}.Scheduler.Sensitive', default=False
        )
        if not sensitive:
            return False

        logger.error_context(
            title=f'敏感任务失败，禁止自动重启（{task_name}）',
            reason=f'任务抛出了 {type(error).__name__}，且该任务被配置为重启敏感任务。',
            impact='为避免状态或数据损坏，AzurPilot 将停止运行。',
            action='查看错误现场并手动确认游戏状态；修复配置或根因后再启动。',
            exc=error,
            level=50,
        )
        handle_notify(
            self.config.Error_OnePushConfig,
            title=f"AzurPilot <{self.config_name}> 敏感任务出错",
            content=f"<{self.config_name}> 敏感任务 `{task_name}` 出错，AzurPilot 已停止运行\n{error}",
        )
        notify_webui(
            self.config_name,
            title=f"敏感任务 {task_name} 出错喵！AzurPilot 已停止喵！",
            content=f"因为 {task_name} 是敏感任务，出错后不会重启喵~\n{error}",
        )
        exit(1)

    def _record_game_stuck_recovery(self, command):
        """
        记录卡死/闪退重启，供大世界特殊海域恢复自律使用。

        仅隐秘/深渊海域任务（直接运行，或由智能调度/防溢出代跑）时记录；
        其他任务及 GameTooManyClickError 保持原有恢复行为。

        标志保存在实例 self 上（跨模拟器/设备重建存活），并在 device 可用时同步，
        供 os_init() 通过 device 读取。

        Args:
            command (str): 任务方法名（下划线形式）。
        """
        task_name = inflection.camelize(command)
        device = self.__dict__.get('device', None)
        proxy_task = getattr(device, 'game_stuck_proxy_task', None) if device is not None else None
        if task_name in ('OpsiObscure', 'OpsiAbyssal'):
            recovery_task = task_name
        elif proxy_task in ('OpsiObscure', 'OpsiAbyssal'):
            recovery_task = proxy_task
        else:
            recovery_task = None
        # 清理代跑子任务标志，避免残留影响后续判断。
        if device is not None and hasattr(device, 'game_stuck_proxy_task'):
            delattr(device, 'game_stuck_proxy_task')
        # 权威存储在 self 上，跨模拟器重启存活。
        self.game_stuck_recovery_task = recovery_task
        if device is not None:
            device.game_stuck_recovery_task = recovery_task

    def run(self, command, skip_first_screenshot=False):
        """
        执行指定任务命令，捕获异常并决定后续行为。

        根据异常类型自动判断：重启游戏、重启模拟器、请求人工介入或直接终止。
        敏感任务出错时直接停止，不做任何重启。

        任务执行前会进行一次截图（除非 skip_first_screenshot=True）。

        Args:
            command (str): 任务方法名（驼峰转下划线后的形式）。
            skip_first_screenshot (bool): 是否跳过执行前的首次截图。

        Returns:
            bool | str:
                True — 任务成功完成。
                False — 不可恢复的失败，计入连续失败限制。
                'recoverable' — 可恢复的失败，不计入连续失败限制。
        """
        try:
            if not skip_first_screenshot:
                self.device.screenshot()
            self.__getattribute__(command)()
            return True
        except TaskEnd:
            return True
        except GameNotRunningError as e:
            # 游戏未运行，调度 Restart 任务自动恢复
            logger.error_context(
                title='游戏进程未运行',
                reason='任务执行前未检测到碧蓝航线游戏进程。',
                impact='当前任务跳过，调度器将自动安排 Restart 任务。',
                action='通常无需处理；若反复发生，请检查游戏包名、模拟器状态和登录流程。',
                exc=e,
                level=30,
                # 预期恢复路径仅保留异常摘要，避免堆栈淹没后续重启日志。
                with_traceback=False,
            )
            self._check_sensitive_exit(command, e)
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> 游戏未运行 - 将自动重启游戏",
            )
            notify_webui(
                self.config_name,
                title=f" <{self.config_name}> 发出了警告喵！",
                content=f"<{self.config_name}> 游戏未运行喵 将自动重启游戏喵~",
            )
            # 记录闪退重启，供大世界特殊海域恢复自律使用。
            self._record_game_stuck_recovery(command)
            self.config.task_call('Restart')
            return 'recoverable'
        except (GameStuckError, GameTooManyClickError) as e:
            # 游戏卡住或点击过多，尝试重启游戏；连续卡死则重启模拟器
            logger.error_context(
                title='游戏状态无法推进',
                reason='截图状态在限定时间内没有变化，或同一按钮被连续点击过多。',
                impact='当前任务已中断，将尝试重启游戏；重复发生时会重启模拟器。',
                action='确认模拟器没有被手动操作，检查截图方案、游戏分辨率和资源版本。',
                exc=e,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)

            if self.config.Error_GameStuckRestart:
                self.consecutive_game_stuck += 1
                limit = int(self.config.Error_GameStuckThreshold)
                logger.warning(f'[Alas] GameStuckError: {self.consecutive_game_stuck}/{limit}')
                if self.consecutive_game_stuck >= limit:
                    logger.warning('[Alas] 游戏卡住次数过多，正在重启模拟器...')
                    # 先记录恢复标志；模拟器重启会重建 device，标志存到 self 跨重启存活。
                    if isinstance(e, GameStuckError):
                        self._record_game_stuck_recovery(command)
                    if self._try_restart_emulator():
                        self.consecutive_game_stuck = 0
                        self.config.task_call('Restart')
                        return 'recoverable'

            logger.warning(f'[Alas] 游戏卡住，{self.device.package} 将在10秒后重启')
            logger.warning('[Alas] 如果您正在手动操作，请停止 AzurPilot')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> 游戏卡住 - 将自动重启游戏",
            )
            notify_webui(
                self.config_name,
                title=f"<{self.config_name}> 发出了警告喵！",
                content=f"<{self.config_name}> 游戏卡住 将自动重启游戏喵~",
            )
            # 记录卡死重启，供大世界特殊海域恢复自律使用。
            # 仅 GameStuckError 记录；GameTooManyClickError 保持原有恢复行为。
            if isinstance(e, GameStuckError):
                self._record_game_stuck_recovery(command)
            self.config.task_call('Restart')
            self.device.sleep(10)
            return 'recoverable'
        except GameBugError as e:
            # 游戏客户端 bug，重启游戏修复
            logger.error_context(
                title='游戏客户端发生异常',
                reason='检测到碧蓝航线客户端的异常状态。',
                impact='当前任务已中断，正在重启游戏尝试恢复。',
                action='等待自动重启；若反复出现，请更新游戏和 AzurPilot，并保留错误现场。',
                exc=e,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)
            logger.warning('[Alas] 碧蓝航线游戏客户端发生错误，AzurPilot 无法处理')
            logger.warning(f'[Alas] 正在重启 {self.device.package} 以修复问题')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> 游戏客户端错误 - 将自动重启游戏",
            )
            notify_webui(
                self.config_name,
                title=f"<{self.config_name}> 发出了警告喵！",
                content=f"<{self.config_name}> 游戏客户端错误 将自动重启游戏喵~",
            )
            self.config.task_call('Restart')
            self.device.sleep(10)
            return 'recoverable'
        except GamePageUnknownError as e:
            logger.info('[Alas] 游戏服务器可能正在维护或网络连接中断，正在检查服务器状态')
            self.checker.check_now()
            if self.checker.is_available():
                # 服务器可用但页面未知，尝试重启游戏恢复
                logger.error_context(
                    title='无法识别游戏页面',
                    reason='服务器可用，但当前截图不符合任何已知游戏页面。',
                    impact='当前任务中断，将尝试重启游戏恢复。',
                    action='确认游戏版本、服务器和分辨率；若更新后出现，请更新 AzurPilot 资源。',
                    exc=e,
                )
                self.save_error_log()
                self._check_sensitive_exit(command, e)
                logger.warning('[Alas] 无法识别游戏页面，尝试重启游戏恢复')
                handle_notify(
                    self.config.Error_OnePushConfig,
                    title=f"AzurPilot <{self.config_name}> 警告",
                    content=f"<{self.config_name}> 无法识别页面 - 将自动重启游戏",
                )
                notify_webui(
                    self.config_name,
                    title=f"<{self.config_name}> 发出了警告喵！",
                    content=f"<{self.config_name}> 无法识别页面 将自动重启游戏喵~",
                )
                self.config.task_call('Restart')
                return 'recoverable'
            else:
                self.checker.wait_until_available()
                return False
        except ScriptError as e:
            # 代码 bug，先重试3次再退出
            self.script_error_count += 1
            logger.exception_context(
                title=f'任务脚本执行失败（第 {self.script_error_count}/3 次）', exc=e,
                impact='当前任务无法继续，将尝试重启恢复。',
                action='根据堆栈定位脚本错误；如果是新版本回归，请提交错误日志和截图。',
                level=50,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)

            if self.script_error_count >= 3:
                logger.error_context(
                    title='ScriptError 重试次数已达上限',
                    reason=f'脚本错误已连续发生 {self.script_error_count} 次，可能是代码 bug。',
                    impact='重试无意义，AzurPilot 将退出。',
                    action='查看错误现场中的 log.txt 和截图，修复代码后重新启动。',
                    level=50,
                )
                handle_notify(
                    self.config.Error_OnePushConfig,
                    title=f"AzurPilot <{self.config_name}> 崩溃",
                    content=f"<{self.config_name}> ScriptError (连续 {self.script_error_count} 次)",
                )
                notify_webui(
                    self.config_name,
                    title=f"出大问题了喵！{self.config_name}崩溃了喵！",
                    content=f"因为 ScriptError 连续 {self.script_error_count} 次喵！",
                )
                exit(1)

            logger.warning(f'[Alas] ScriptError 第 {self.script_error_count}/3 次，尝试重启恢复')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> ScriptError - 将尝试重启恢复 ({self.script_error_count}/3)",
            )
            notify_webui(
                self.config_name,
                title=f"<{self.config_name}> 发出了警告喵！",
                content=f"<{self.config_name}> ScriptError 将尝试重启恢复喵~",
            )
            self.config.task_call('Restart')
            return 'recoverable'
        except EmulatorNotRunningError as e:
            # 模拟器离线或死机，尝试自动重启，永不退出
            logger.error_context(
                title='模拟器连接中断',
                reason='任务执行期间无法访问模拟器或 ADB 设备。',
                impact='当前任务中断，系统将尝试重启模拟器。',
                action='确认模拟器进程和 ADB 服务正常；连续失败时检查端口、代理和模拟器保活设置。',
                exc=e,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)
            # 始终尝试重启模拟器，即使失败也不退出
            self._try_restart_emulator()
            self.config.task_call('Restart')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> 模拟器离线 - 正在尝试重启模拟器",
            )
            notify_webui(
                self.config_name,
                title=f"{self.config_name} 出了点小问题喵~",
                content=f"模拟器离线喵 正在重启模拟器喵",
            )
            return 'recoverable'
        except RequestHumanTakeover as e:
            # 几乎所有报错都应通过重启模拟器/游戏解决，不再直接终止
            logger.error_context(
                title='任务需要人工介入（将尝试自动恢复）',
                reason='当前状态无法由自动化流程安全判断或修复。',
                impact='调度器将尝试重启模拟器恢复，而非直接终止。',
                action='查看错误现场和堆栈；若自动恢复失败，再手动处理。',
                level=50,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)
            # 尝试通过重启模拟器恢复
            logger.warning('[Alas] RequestHumanTakeover: 尝试通过重启模拟器恢复')
            self._try_restart_emulator()
            self.config.task_call('Restart')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> 需要人工介入 - 正在尝试自动重启恢复",
            )
            notify_webui(
                self.config_name,
                title=f"{self.config_name} 出了点小问题喵~",
                content=f"遇到需要人工介入的问题喵 正在尝试自动重启恢复喵",
            )
            return 'recoverable'
        except AutoSearchSetError as e:
            # 自动搜索设置失败，尝试重启游戏恢复
            logger.error_context(
                title='自动搜索设置失败',
                reason='无法将游戏切换到所需的自动搜索状态。',
                impact='当前任务中断，将尝试重启游戏恢复。',
                action='检查编队、关卡限制和游戏页面；确认后手动设置自动搜索并重新启动。',
                exc=e,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)
            logger.warning('[Alas] 自动搜索设置失败，尝试重启游戏恢复')
            self.config.task_call('Restart')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> 自动搜索设置失败 - 将自动重启游戏",
            )
            notify_webui(
                self.config_name,
                title=f"<{self.config_name}> 发出了警告喵！",
                content=f"<{self.config_name}> 自动搜索设置失败 将自动重启游戏喵~",
            )
            return 'recoverable'
        except Exception as e:
            # 未预期异常，尝试重启恢复而非直接终止
            logger.exception_context(
                title=f'任务执行发生未处理异常（{command}）', exc=e,
                impact='当前任务无法确认执行结果，调度器将尝试重启恢复。',
                action='查看错误现场中的 log.txt、截图和完整堆栈，确认是否需要更新资源或提交问题。',
                level=50,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)
            logger.warning('[Alas] 未处理异常，尝试重启模拟器恢复')
            self._try_restart_emulator()
            self.config.task_call('Restart')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 警告",
                content=f"<{self.config_name}> 发生异常 - 正在尝试自动重启恢复",
            )
            notify_webui(
                self.config_name,
                title=f"<{self.config_name}> 发出了警告喵！",
                content=f"<{self.config_name}> 发生异常 正在尝试自动重启恢复喵~",
            )
            return 'recoverable'

    def keep_last_errlog(self, folder_path, n: int = 30):
        """
        清理旧的错误日志文件夹，只保留最近的 n 个。

        Args:
            folder_path (str): 错误日志根目录路径。
            n (int): 保留的文件夹数量，<=0 时不清理。
        """
        if n <= 0:
            return
        folders = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if os.path.isdir(os.path.join(folder_path, f))
        ]
        for folder in folders[:-n]:
            shutil.rmtree(folder)

    def save_error_log(self):
        """
        保存错误现场：最近截图和日志文件到 ./log/error/<config-name>/<timestamp>/。

        同时触发 LLM 错误分析（如果启用）。
        """
        import pathlib
        from module.base.utils import save_image
        from module.handler.sensitive_info import (handle_sensitive_image,
                                                   handle_sensitive_logs)
                                                   
        # LLM 错误分析放在最前面，避免后续截图保存时二次崩溃导致分析未执行
        try:
            if hasattr(self, 'config') and getattr(self.config, 'Error_LlmAnalysis', False):
                from module.llm import analyze_exception
                import sys
                _, exc_value, _ = sys.exc_info()
                if exc_value is not None:
                    analyze_exception(self.config, exc_value)
        except Exception as e:
            logger.exception_context(
                title='LLM 错误分析失败',
                exc=e,
                impact='不影响任务恢复，但本次错误不会生成 LLM 分析结果。',
                action='检查 LLM API 配置、网络和配额；直接根据错误现场排查。',
                level=30,
            )

        if getattr(self.config, 'Error_SaveError', False):
            config_folder = pathlib.Path(f"./log/error/{self.config_name}")
            folder = config_folder.joinpath(str(int(time.time() * 1000)))
            folder.mkdir(parents=True, exist_ok=True)
            logger.warning(f'[Alas] 保存错误日志: {folder}')

            try:
                # 只在已经初始化了设备时才尝试保存截图，避免按需初始化时二次崩溃
                if 'device' in self.__dict__:
                    for data in self.device.screenshot_deque:
                        image_time = datetime.strftime(data['time'], '%Y-%m-%d_%H-%M-%S-%f')
                        image = handle_sensitive_image(data['image'])
                        save_image(image, f'{folder}/{image_time}.png')
            except Exception as e:
                logger.error(f"[Alas] 保存错误截图失败: {e}")

            try:
                with open(logger.log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    start = 0
                    for index, line in enumerate(lines):
                        line = line.strip(' \r\t\n')
                        if re.match('^═{15,}$', line):
                            start = index
                    lines = lines[start - 2:]
                    lines = handle_sensitive_logs(lines)
                with open(f'{folder}/log.txt', 'w', encoding='utf-8') as f:
                    f.writelines(lines)
            except Exception as e:
                logger.error(f"[Alas] 保存错误日志失败: {e}")
                
            self.keep_last_errlog(config_folder, getattr(self.config, 'Error_SaveErrorCount', 0))

    def restart(self):
        from module.handler.login import LoginHandler
        if self.delay_due_restart():
            return
        LoginHandler(self.config, device=self.device).app_restart()
        self.delay_next_restart()

    def restart_random_delay_minutes(self):
        """获取每日重启的随机延后分钟数。"""
        random_delay = getattr(self.config, 'Restart_RandomDelay', 0)
        if isinstance(random_delay, list) and len(random_delay) == 2:
            random_delay = tuple(random_delay)
        try:
            delay = int(ensure_time(random_delay, n=1, precision=0))
        except (TypeError, ValueError):
            logger.warning(f'[Alas] 无效的重启随机延后设置: {random_delay}, 使用 0 分钟')
            delay = 0

        return max(delay, 0)

    def delay_due_restart(self):
        """把已排在服务器刷新整点的每日重启改排到随机延后时间。"""
        current = self.config.Scheduler_NextRun
        if not isinstance(current, datetime):
            return False

        last_update = get_server_last_update(self.config.Scheduler_ServerUpdate).replace(microsecond=0)
        if current.replace(microsecond=0) != last_update:
            return False

        delay = self.restart_random_delay_minutes()
        if delay <= 0:
            return False

        next_run = last_update + timedelta(minutes=delay)
        if next_run <= current_time().replace(microsecond=0):
            logger.info(f'[Alas] 每日重启随机延后 {delay} 分钟已到达，继续重启')
            return False

        logger.info(f'[Alas] 每日重启命中服务器刷新时间，随机延后 {delay} 分钟至 {next_run}')
        self.config.task_delay(target=next_run)
        return True

    def delay_next_restart(self):
        """将下一次每日重启延后到服务器刷新后的随机时间。"""
        delay = self.restart_random_delay_minutes()
        next_run = get_server_next_update(self.config.Scheduler_ServerUpdate) + timedelta(minutes=delay)
        if delay:
            logger.info(f'[Alas] 每日重启随机延后 {delay} 分钟')
        self.config.task_delay(target=next_run)

    def start(self):
        from module.handler.login import LoginHandler
        LoginHandler(self.config, device=self.device).app_start()

    def goto_main(self):
        from module.handler.login import LoginHandler
        from module.ui.ui import UI
        if self.device.app_is_running():
            logger.info('[Alas] 应用已在运行，前往主页面')
            UI(self.config, device=self.device).ui_goto_main()
        else:
            logger.info('[Alas] 应用未运行，启动应用并前往主页面')
            LoginHandler(self.config, device=self.device).app_start()
            UI(self.config, device=self.device).ui_goto_main()

    def research(self):
        from module.research.research import RewardResearch
        RewardResearch(config=self.config, device=self.device).run()

    def commission(self):
        from module.commission.commission import RewardCommission
        RewardCommission(config=self.config, device=self.device).run()

    def tactical(self):
        from module.tactical.tactical_class import RewardTacticalClass
        RewardTacticalClass(config=self.config, device=self.device).run()

    def dorm(self):
        from module.dorm.dorm import RewardDorm
        RewardDorm(config=self.config, device=self.device).run()

    def meowfficer(self):
        from module.meowfficer.meowfficer import RewardMeowfficer
        RewardMeowfficer(config=self.config, device=self.device).run()

    def guild(self):
        from module.guild.guild_reward import RewardGuild
        RewardGuild(config=self.config, device=self.device).run()

    def reward(self):
        from module.reward.reward import Reward
        Reward(config=self.config, device=self.device).run()

    def awaken(self):
        from module.awaken.awaken import Awaken
        Awaken(config=self.config, device=self.device).run()

    def shop_frequent(self):
        from module.shop.shop_reward import RewardShop
        RewardShop(config=self.config, device=self.device).run_frequent()

    def shop_once(self):
        from module.shop.shop_reward import RewardShop
        RewardShop(config=self.config, device=self.device).run_once()

    def event_shop(self):
        from module.shop_event.shop_event import EventShop
        EventShop(config=self.config, device=self.device).run()

    def shipyard(self):
        from module.shipyard.shipyard_reward import RewardShipyard
        RewardShipyard(config=self.config, device=self.device).run()

    def gacha(self):
        from module.gacha.gacha_reward import RewardGacha
        RewardGacha(config=self.config, device=self.device).run()

    def freebies(self):
        from module.freebies.freebies import Freebies
        Freebies(config=self.config, device=self.device).run()

    def minigame(self):
        from module.minigame.minigame import Minigame
        Minigame(config=self.config, device=self.device).run()

    def private_quarters(self):
        from module.private_quarters.private_quarters import PrivateQuarters
        PrivateQuarters(config=self.config, device=self.device).run()

    def island(self):
        from module.island.island import Island
        Island(config=self.config, device=self.device).run()

    def island_mine_forest(self):
        from module.island.island_mine_forest import IslandMineForest
        IslandMineForest(config=self.config, device=self.device).run()

    def island_farm(self):
        from module.island.island_farm import IslandFarm
        IslandFarm(config=self.config, device=self.device).run()

    def island_rancher(self):
        from module.island.island_rancher import IslandRancher
        IslandRancher(config=self.config, device=self.device).run()

    def island_fishery(self):
        from module.island.island_fishery import IslandFishery
        IslandFishery(config=self.config, device=self.device).run()

    def island_grill(self):
        from module.island.island_grill import IslandGrill
        IslandGrill(config=self.config, device=self.device).run()

    def island_teahouse(self):
        from module.island.island_teahouse import IslandTeahouse
        IslandTeahouse(config=self.config, device=self.device).run()

    def island_restaurant(self):
        from module.island.island_restaurant import IslandRestaurant
        IslandRestaurant(config=self.config, device=self.device).run()

    def island_juu_coffee(self):
        from module.island.island_juu_coffee import IslandJuuCoffee
        IslandJuuCoffee(config=self.config, device=self.device).run()

    def island_juu_eatery(self):
        from module.island.island_juu_eatery import IslandJuuEatery
        IslandJuuEatery(config=self.config, device=self.device).run()

    def island_daily_gather(self):
        from module.island.island_daily_gather import IslandDailyGather
        IslandDailyGather(config=self.config, device=self.device).run()

    def island_manufacture(self):
        from module.island.island_manufacture import IslandManufacture
        IslandManufacture(config=self.config, device=self.device).run()

    def island_air_drop(self):
        from module.island.island_air_drop import IslandAirDrop
        IslandAirDrop(config=self.config, device=self.device).run()

    def island_cargo_preparation(self):
        from module.island.island_cargo_preparation import IslandCargoPreparation
        IslandCargoPreparation(config=self.config, device=self.device).run()

    def island_business(self):
        from module.island.island_business import IslandBusiness
        IslandBusiness(config=self.config, device=self.device).run()

    def island_daily_order(self):
        from module.island.island_daily_order import IslandDailyOrder
        IslandDailyOrder(config=self.config, device=self.device).run()

    def island_daily_interact(self):
        from module.island.island_daily_interact import IslandDailyInteract
        IslandDailyInteract(config=self.config, device=self.device).run()

    def island_pearl_sell(self):
        from module.island.island_pearl_sell import IslandPearlSell
        IslandPearlSell(config=self.config, device=self.device).run()

    def daily(self):
        from module.daily.daily import Daily
        Daily(config=self.config, device=self.device).run()

    def hard(self):
        from module.hard.hard import CampaignHard
        CampaignHard(config=self.config, device=self.device).run()

    def exercise(self):
        from module.exercise.exercise import Exercise
        Exercise(config=self.config, device=self.device).run()

    def sos(self):
        from module.sos.sos import CampaignSos
        CampaignSos(config=self.config, device=self.device).run()

    def war_archives(self):
        from module.war_archives.war_archives import CampaignWarArchives
        CampaignWarArchives(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def raid_daily(self):
        from module.raid.daily import RaidDaily
        RaidDaily(config=self.config, device=self.device).run()

    def event_a(self):
        from module.event.campaign_abcd import CampaignABCD
        CampaignABCD(config=self.config, device=self.device).run()

    def event_b(self):
        from module.event.campaign_abcd import CampaignABCD
        CampaignABCD(config=self.config, device=self.device).run()

    def event_c(self):
        from module.event.campaign_abcd import CampaignABCD
        CampaignABCD(config=self.config, device=self.device).run()

    def event_d(self):
        from module.event.campaign_abcd import CampaignABCD
        CampaignABCD(config=self.config, device=self.device).run()

    def event_sp(self):
        from module.event.campaign_sp import CampaignSP
        CampaignSP(config=self.config, device=self.device).run()

    def maritime_escort(self):
        from module.event.maritime_escort import MaritimeEscort
        MaritimeEscort(config=self.config, device=self.device).run()

    def opsi_ash_assist(self):
        from module.os_ash.meta import AshBeaconAssist
        AshBeaconAssist(config=self.config, device=self.device).run()

    def opsi_ash_beacon(self):
        from module.os_ash.meta import OpsiAshBeacon
        OpsiAshBeacon(config=self.config, device=self.device).run()

    def opsi_explore(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_explore()

    def opsi_shop(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_shop()

    def opsi_voucher(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_voucher()

    def opsi_daily(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_daily()

    def opsi_obscure(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_obscure()

    def opsi_month_boss(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_month_boss()

    def opsi_abyssal(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_abyssal()

    def opsi_archive(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_archive()

    def opsi_stronghold(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_stronghold()

    def opsi_meowfficer_farming(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_meowfficer_farming()

    def opsi_hazard1_leveling(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_hazard1_leveling()

    def opsi_scheduling(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_scheduling()

    def opsi_prevent_action_point_overflow(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_prevent_action_point_overflow()

    def opsi_cross_month(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_cross_month()

    def opsi_daily_delay(self):
        from module.campaign.os_run import OSCampaignRun
        OSCampaignRun(config=self.config, device=self.device).opsi_daily_delay()

    def main(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def main2(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def main3(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def event(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def event2(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def event3(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def raid(self):
        from module.raid.run import RaidRun
        RaidRun(config=self.config, device=self.device).run()

    def raid_scuttle(self):
        from module.raid.scuttle import RaidScuttleRun
        RaidScuttleRun(config=self.config, device=self.device).run()

    def hospital(self):
        from module.event_hospital.hospital import Hospital
        Hospital(config=self.config, device=self.device).run()

    def hospital_event(self):
        from module.event_hospital.hospital_event import HospitalEvent
        HospitalEvent(config=self.config, device=self.device).run()

    def coalition(self):
        from module.coalition.coalition import Coalition
        Coalition(config=self.config, device=self.device).run()

    def coalition_sp(self):
        from module.coalition.coalition_sp import CoalitionSP
        CoalitionSP(config=self.config, device=self.device).run()

    def coalition_scuttle(self):
        from module.coalition.coalition_scuttle import CoalitionScuttleRun
        CoalitionScuttleRun(config=self.config, device=self.device).run()

    def c72_mystery_farming(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def c122_medium_leveling(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def c124_large_leveling(self):
        from module.campaign.run import CampaignRun
        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def gems_farming(self):
        from module.campaign.gems_farming import GemsFarming
        GemsFarming(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def three_oil_low_cost(self):
        from module.campaign.gems_farming import GemsFarming
        GemsFarming(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name, folder=self.config.Campaign_Event, mode=self.config.Campaign_Mode)

    def ambush11(self):
        from module.campaign.ambush_1_1 import Ambush11
        Ambush11(config=self.config, device=self.device).run()

    def daemon(self):
        from module.daemon.daemon import AzurLaneDaemon
        AzurLaneDaemon(config=self.config, device=self.device, task="Daemon").run()

    def opsi_daemon(self):
        from module.daemon.os_daemon import AzurLaneDaemon
        AzurLaneDaemon(config=self.config, device=self.device, task="OpsiDaemon").run()

    def event_story(self):
        from module.eventstory.eventstory import EventStory
        EventStory(config=self.config, device=self.device, task="EventStory").run()

    def box_disassemble(self):
        from module.storage.box_disassemble import StorageBox
        StorageBox(config=self.config, device=self.device, task="BoxDisassemble").run()

    def auto_equip(self):
        from module.auto_equip.auto_equip import AutoEquip
        AutoEquip(config=self.config, device=self.device, task="AutoEquip").run()

    def azur_lane_uncensored(self):
        from module.daemon.uncensored import AzurLaneUncensored
        AzurLaneUncensored(config=self.config, device=self.device, task="AzurLaneUncensored").run()

    def benchmark(self):
        from module.daemon.benchmark import run_benchmark
        run_benchmark(config=self.config)

    def ocr_benchmark(self):
        from module.daemon.ocr_benchmark import run_ocr_benchmark
        run_ocr_benchmark(config=self.config)

    def fleet_scan(self):
        from module.retire.fleet_management import FleetManagement
        FleetManagement(config=self.config, device=self.device, task="FleetScan").run()

    def game_manager(self):
        from module.daemon.game_manager import GameManager
        GameManager(config=self.config, device=self.device, task="GameManager").run()

    def emulator_manager(self):
        import subprocess
        # 优先使用 EmulatorInfo 中的 SSH 配置
        if getattr(self.config, 'EmulatorInfo_EnableRemoteSSH', False):
            host = getattr(self.config, 'EmulatorInfo_RemoteSSHHost', '')
            port = getattr(self.config, 'EmulatorInfo_RemoteSSHPort', 22)
            user = getattr(self.config, 'EmulatorInfo_RemoteSSHUser', '')
            command = getattr(self.config, 'EmulatorInfo_RemoteStartCommand', '')
            key = getattr(self.config, 'EmulatorInfo_RemoteSSHPublicKey', '')
        else:
            # 回退到 EmulatorManager 配置
            enable = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.EnableRemoteSSH', False)
            if not enable:
                logger.warning('[Alas-SSH] 模拟器管理器设置中未启用远程SSH')
                return

            host = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHHost', '')
            port = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHPort', 22)
            user = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHUser', '')
            command = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteStartCommand', '')
            if not command:
                command = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteCommand', '')
            key = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHPublicKey', '')

        if not host or not command:
            logger.warning(f'[Alas-SSH] 远程SSH主机 ({host}) 或远程启动命令 ({command}) 为空，跳过远程SSH命令')
            return

        logger.hr('远程SSH命令', level=1)
        target = f'{user}@{host}' if user else host
        clear_ssh_host_key(host, port)
        # -n: 禁用标准输入  -T: 禁用伪终端分配  BatchMode: 避免密码提示导致挂起
        cmd = [
            'ssh', '-n', '-T', '-p', str(port),
            '-o', 'StrictHostKeyChecking=no',
            '-o', f'UserKnownHostsFile={os.devnull}',
            '-o', f'GlobalKnownHostsFile={os.devnull}',
            '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
        ]
        
        key_file = None
        if key and len(key) > 50:
            import tempfile
            try:
                fd, key_file = tempfile.mkstemp()
                with os.fdopen(fd, 'w') as f:
                    f.write(key.strip() + '\n')
                
                if os.name == 'nt':
                    import subprocess
                    user_env = os.environ.get('USERNAME')
                    subprocess.run(['icacls', key_file, '/reset'], capture_output=True)
                    subprocess.run(['icacls', key_file, '/inheritance:r'], capture_output=True)
                    subprocess.run(['icacls', key_file, '/grant:r', f'{user_env}:F'], capture_output=True)
                else:
                    os.chmod(key_file, 0o600)

                cmd += ['-i', key_file]
                logger.info(f'[Alas-SSH] 使用提供的私钥进行认证')
            except Exception as e:
                logger.error(f'[Alas-SSH] 创建或保护临时密钥文件失败: {e}')

        cmd += [target, command]
        logger.info(f'[Alas-SSH] 执行远程命令: {" ".join(cmd)}')

        try:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # 缓存 stderr 输出，仅在失败时打印
            stderr_content = []
            import threading
            
            def collect_stderr():
                for line in process.stderr:
                    stderr_content.append(line.strip())
            
            def collect_stdout():
                for line in process.stdout:
                    logger.info(f'[Alas-SSH] 远程输出: {line.strip()}')

            stderr_thread = threading.Thread(target=collect_stderr)
            stdout_thread = threading.Thread(target=collect_stdout)
            stderr_thread.start()
            stdout_thread.start()

            try:
                # 主线程等待进程退出
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                logger.error('[Alas-SSH] 远程SSH命令超时（30秒）')
                return
            finally:
                stderr_thread.join(timeout=5)
                stdout_thread.join(timeout=5)

            if process.returncode == 0:
                logger.info('[Alas-SSH] 远程命令执行成功')
            else:
                logger.error(f'[Alas-SSH] 远程命令失败，返回码 {process.returncode}')
                for line in stderr_content:
                    logger.error(f'[Alas-SSH] 远程错误: {line}')
        except Exception as e:
            logger.error(f'[Alas-SSH] 执行远程SSH命令失败: {e}')
        finally:
            if key_file and os.path.exists(key_file):
                try:
                    os.remove(key_file)
                except:
                    pass

    def wait_until(self, future):
        """
        阻塞等待直到指定时间到达。

        等待期间每 5 秒检查一次配置文件变更和停止事件。

        Args:
            future (datetime): 目标等待时间。

        Returns:
            bool: 正常等到返回 True，检测到配置变更返回 False。
        """
        future = future + timedelta(seconds=1)
        self.config.start_watching()
        while 1:
            if current_time() > future:
                return True
            if self.stop_event is not None:
                if self.stop_event.is_set():
                    logger.info('[Alas] 检测到更新事件')
                    logger.info(f'[{self.config_name}] 已退出。原因: 更新 | Reason: Update')
                    exit(0)

            time.sleep(5)

            if self.config.should_reload():
                return False

    def get_next_task(self):
        """
        获取下一个待执行的任务。

        如果任务尚未到执行时间，根据 Optimization_WhenTaskQueueEmpty 设置
        选择等待策略（关闭游戏 / 前往主页 / 停留原地），然后阻塞等待。

        Returns:
            str: 下一个任务的方法名（如 'Restart'、'Commission'）。
        """
        while 1:
            task = self.config.get_next()
            self.config.task = task
            self.config.bind(task)

            from module.base.resource import release_resources
            if self.config.task.command != 'Alas':
                release_resources(next_task=task.command)

            if task.next_run > current_time():
                logger.info(f'[Alas] 等待直到 {task.next_run} 执行任务 `{task.command}`')
                self.is_first_task = False
                method = self.config.Optimization_WhenTaskQueueEmpty
                wait_duration = task.next_run - current_time()
                if (
                    self.config.Optimization_CloseEmulatorDuringLongWait
                    and wait_duration > timedelta(hours=3)
                    and 'device' in self.__dict__ and self.device.emulator_instance is not None  # 远程设备（无线 ADB / SSH）没有本地模拟器实例可管理，跳过关闭流程，走常规等待逻辑
                ):
                    logger.info(
                        f'下一个任务 `{task.command}` 将在 {wait_duration} 后运行，'
                        '等待期间关闭模拟器'
                    )
                    release_resources()
                    self.device.release_during_wait()
                    try:
                        if self.device.emulator_stop():
                            logger.info('[Alas] 等待期间已关闭模拟器')
                        else:
                            logger.warning('[Alas] 等待期间关闭模拟器失败，继续等待')
                    except Exception as e:
                        logger.warning(f'[Alas] 等待期间关闭模拟器失败，继续等待: {e}')
                    if 'device' in self.__dict__:
                        del_cached_property(self, 'device')
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
                    self._start_emulator_after_long_wait()
                    if task.command != 'Restart':
                        self.config.task_call('Restart')
                        del_cached_property(self, 'config')
                        continue
                elif method == 'close_game':
                    logger.info('[Alas] 等待期间关闭游戏')
                    self.device.app_stop()
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
                    if task.command != 'Restart':
                        self.config.task_call('Restart')
                        del_cached_property(self, 'config')
                        continue
                elif method == 'goto_main':
                    logger.info('[Alas] 等待期间前往主页面')
                    self.run('goto_main')
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
                elif method == 'stay_there':
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
                else:
                    logger.warning(f'[Alas] 无效的 Optimization_WhenTaskQueueEmpty: {method}, 回退到 stay_there')
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
            break

        AzurLaneConfig.is_hoarding_task = False
        return task.command

    def loop(self):
        logger.set_file_logger(self.config_name)
        logger.info(f'[Alas] 启动调度器循环: {self.config_name}')

        from module.config.utils import is_oobe_needed

        if is_oobe_needed():
            logger.error_context(
                title='未检测到配置文件',
                reason='项目尚未完成首次配置，或 config 目录中的配置文件缺失。',
                impact='调度器无法启动。',
                action='运行 `uv run python gui.py` 打开 WebUI，完成初次设置后再启动调度器。',
                level=50,
            )
            exit(1)

        # 全局异常连续失败计数（仅用于日志展示和退避策略，不再触发退出）
        consecutive_global_failures = 0
        RESTART_DELAY = 20
        LONG_WAIT = 300

        while 1:
            try:
                # 检查来自GUI的更新事件
                if self.stop_event is not None:
                    if self.stop_event.is_set():
                        logger.info('[Alas] 检测到更新事件')
                        logger.info(f"[Alas] [{self.config_name}] 已退出。原因: 更新 | Reason: Update")
                        break
                # 检查游戏服务器维护
                self.checker.wait_until_available()
                if self.checker.is_recovered():
                    # 服务器恢复后强制刷新配置，修复阻塞期间配置未更新的问题
                    del_cached_property(self, 'config')
                    logger.info('[Alas] 服务器或网络已恢复。重启游戏客户端')
                    self.config.task_call('Restart')
                # 检查计划的模拟器重启（在任务之间，不会中断正在运行的任务）
                if self.config.EmulatorManagement_ScheduledEmulatorRestart:
                    elapsed_hours = (time.monotonic() - self.last_emulator_restart_time) / 3600
                    interval = self.config.EmulatorManagement_RestartIntervalHours
                    if elapsed_hours >= interval:
                        logger.hr('[Alas] 计划的模拟器重启', level=1)
                        logger.info(f'[Alas] 模拟器已运行 {elapsed_hours:.1f} 小时, '
                                    f'计划重启间隔为 {interval} 小时')
                        if self._try_restart_emulator():
                            self.last_emulator_restart_time = time.monotonic()
                            self.config.task_call('Restart')
                            del_cached_property(self, 'config')
                            continue
                        else:
                            logger.warning('[Alas] 计划的模拟器重启失败，继续正常运行')

                # 获取任务
                task = self.get_next_task()
                # 初始化设备并更改服务器
                _ = self.device
                self.device.config = self.config
                # 同步跨模拟器/设备重建的待恢复标志到当前 device，供 os_init() 读取。
                if self.game_stuck_recovery_task:
                    self.device.game_stuck_recovery_task = self.game_stuck_recovery_task
                    self.game_stuck_recovery_task = None
                # 跳过第一次重启
                if self.is_first_task and task == 'Restart':
                    logger.info('[Alas] 调度器启动时跳过任务 `Restart`')
                    self.delay_next_restart()
                    del_cached_property(self, 'config')
                    continue

                # 运行
                logger.info(f'[Alas] 调度器: 开始任务 `{task}`')
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                logger.hr(task, level=0)
                success = self.run(inflection.underscore(task))
                logger.info(f'[Alas] 调度器: 结束任务 `{task}`')
                self.is_first_task = False

                # 每任务推送通知（须在 config_generated 刷新前读取）
                if success is not None:
                    try:
                        if getattr(self.config, 'Scheduler_PushNotification', False):
                            if success == True:
                                status = '成功'
                            elif success == 'recoverable':
                                status = '成功（有可恢复错误需关注）'
                            else:
                                status = '失败'
                            task_display = _get_task_display_name(task)
                            handle_notify(
                                self.config.Error_OnePushConfig,
                                title=f"[AzurPilot] <{self.config_name}> {task_display} {status}",
                                content=f"<{self.config_name}> 任务 {task_display} —— {status}",
                            )
                    except Exception:
                        logger.warning('[Alas] 每任务推送通知异常，已跳过')

                # 检查失败
                # 任务失败次数统计：可恢复错误 (success == 'recoverable') 不计入失败次数。
                # 非敏感任务永不退出，连续失败时强制重启模拟器+游戏恢复；
                # 敏感任务（StrictRestart=True 且 Sensitive=True）失败后立即退出。
                failed = deep_get(self.failure_record, keys=task, default=0)
                if success == True:
                    failed = 0  # 成功，重置计数
                elif success == 'recoverable':
                    # 可恢复错误（如 GameStuckError），不增加失败计数
                    # 但也不重置，保持之前的计数
                    logger.info(f'[Alas] 任务 `{task}` 遇到可恢复错误，不计入失败限制')
                else:
                    failed = failed + 1  # 不可恢复错误，增加计数
                deep_set(self.failure_record, keys=task, value=failed)

                strict_restart = self.config.Error_StrictRestart and failed >= 1 and self.config.cross_get(
                    keys=f'{task}.Scheduler.Sensitive', default=False
                )
                if strict_restart:
                    # 仅敏感任务失败后立即退出，避免状态或数据损坏
                    logger.error_context(
                        title=f'敏感任务失败，禁止自动重启（{task}）',
                        reason=f'该任务是重启敏感任务，已连续失败 {failed} 次。',
                        impact='为避免状态或数据损坏，AzurPilot 将停止运行。',
                        action='查看错误现场并手动确认游戏状态；如需自动恢复，请关闭对应任务的 StrictRestart。',
                        level=50,
                    )
                    handle_notify(
                        self.config.Error_OnePushConfig,
                        title=f"AzurPilot <{self.config_name}> crashed",
                        content=f"<{self.config_name}> RequestHumanTakeover\nTask `{task}` failed {failed} or more times.",
                    )
                    notify_webui(
                        self.config_name,
                        title=f"诶呀！{self.config_name}出现了问题喵！",
                        content=f"因为 {task} 任务失败次数过多喵！",
                    )
                    logger.warning("[Alas] 任务连续失败次数过多，正在上报错误日志...")
                    ApiClient.submit_bug_log(f"AzurPilot <{self.config_name}> crashed\nTask `{task}` failed {failed} or more times.")
                    exit(1)

                if failed >= 3:
                    # 非敏感任务连续失败：不退出，强制重启模拟器+游戏后继续调度
                    logger.warning(
                        f'[Alas] 任务 `{task}` 已连续失败 {failed} 次，'
                        f'非敏感任务不退出，强制重启模拟器+游戏后继续调度。'
                    )
                    handle_notify(
                        self.config.Error_OnePushConfig,
                        title=f"AzurPilot <{self.config_name}> 警告",
                        content=f"<{self.config_name}> 任务 `{task}` 连续失败 {failed} 次，将强制重启恢复",
                    )
                    notify_webui(
                        self.config_name,
                        title=f"{self.config_name} 出了点小问题喵~",
                        content=f"任务 `{task}` 失败次数过多喵 正在强制重启恢复喵",
                    )
                    try:
                        self._try_restart_emulator()
                    except Exception as restart_emu_e:
                        logger.warning(f'[Alas] 模拟器重启失败，将继续调度: {restart_emu_e}')
                    self.config.task_call('Restart')
                    # 重置该任务的失败计数，避免下次循环立即再次触发
                    deep_set(self.failure_record, keys=task, value=0)

                if success == True:
                    del_cached_property(self, 'config')
                    consecutive_global_failures = 0 # 任务成功时重置全局失败计数器
                    self.consecutive_game_stuck = 0
                    self.consecutive_adb_offline = 0
                    continue
                elif success == 'recoverable' or self.config.Error_HandleError:
                    # 可恢复错误或启用了错误处理，刷新配置后继续循环
                    del_cached_property(self, 'config')
                    self.checker.check_now()
                    continue
                else:
                    break

            # 捕获全局异常并执行重启
            # 说明：调度器永不主动退出，所有未处理异常均通过指数退避重试恢复，
            # 唯一例外是 ScriptError（开发者代码错误），其在 run() 中已限制连续 3 次后退出。
            # 敏感任务失败由 _check_sensitive_exit 处理，仍会主动退出。
            except Exception as e:
                consecutive_global_failures += 1
                self.is_first_task = False
                import traceback
                logger.exception_context(
                    title='调度器循环发生未处理异常',
                    exc=e,
                    impact='本轮任务中断，调度器将尝试执行 Restart 后继续运行。',
                    action='关注下方堆栈；若连续发生，请检查设备连接、配置和最近更新的资源。',
                )

                # 即使没有达到重启或失败上限，也第一时间自动请求分析崩溃原因
                try:
                    if hasattr(self, 'config') and getattr(self.config, 'Error_LlmAnalysis', False):
                        from module.llm import analyze_exception
                        analyze_exception(self.config, e)
                except Exception as ex:
                    logger.error(f'[Alas] LLM错误分析失败: {ex}')

                logger.warning(
                    f">>> 这是第 {consecutive_global_failures} 次连续全局失败，"
                    f"调度器永不放弃，将持续重试恢复。"
                )

                # 不再因连续失败次数达到上限而退出，改为持续重试
                # 上报错误日志（首次失败时上报，避免刷屏）
                if consecutive_global_failures == 1:
                    try:
                        self.save_error_log()
                        logger.warning("[Alas] 首次全局异常，正在上报错误日志...")
                        ApiClient.submit_bug_log(
                            f"AzurPilot <{self.config_name}> 调度器发生异常。\n"
                            f"调度器将自动重试恢复（永不退出）。\n"
                            f"{traceback.format_exc()}"
                        )
                    except Exception as report_e:
                        logger.warning(f'[Alas] 错误日志上报失败: {report_e}')

                # 尝试重启模拟器（始终尝试，永不放弃）
                logger.warning("[Alas] 尝试通过重启模拟器 + 强制执行 RESTART 任务来恢复...")
                try:
                    self._try_restart_emulator()
                except Exception as restart_emu_e:
                    logger.warning(f'[Alas] 模拟器重启失败，将继续尝试: {restart_emu_e}')

                try:
                    # 注入 Restart 任务
                    self.config.task_call('Restart')
                    # 重新加载配置
                    del_cached_property(self, 'config')
                    logger.info("[Alas] 已为下一个循环安排了 `Restart` 任务。")
                except Exception as restart_e:
                    logger.exception_context(
                        title='无法安排 Restart 恢复任务',
                        exc=restart_e,
                        impact='调度器将继续重试，但本轮循环可能再次失败。',
                        action='检查配置是否可读、Restart 任务是否启用，以及设备是否仍在线。',
                    )

                # 指数退避：失败次数越多，等待时间越长，但上限 300 秒
                wait_seconds = min(LONG_WAIT, RESTART_DELAY * (2 ** min(consecutive_global_failures - 1, 4)))
                logger.info(
                    f"调度器将在 {wait_seconds} 秒后从头重试（第 {consecutive_global_failures} 次重试，"
                    f"永不放弃）。"
                )
                time.sleep(wait_seconds)

if __name__ == '__main__':
    alas = AzurLaneAutoScript()
    alas.loop()
