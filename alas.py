import json
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import inflection
from cached_property import cached_property

import module.config.server as server_config
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
    filepath_config,
    get_server_last_update,
    get_server_next_update,
    read_file,
)
from module.exception import *
from module.logger import logger
from module.notify import handle_notify, notify_webui


# 看门狗配置
# 守护线程每 N 秒检查一次任务运行状态；任务执行期间若超过配置的
# 超时时间，则判定任务逻辑死循环，强制杀死模拟器进程以中断任务。
# 看门狗仅在任务执行阶段（self.run() 期间）激活，空闲等待（wait_until、
# 服务器维护检查）期间自动暂停，避免误触发。
WATCHDOG_CHECK_INTERVAL = 30
# 单个任务最长运行时间（分钟），仅作为配置读取失败的兜底默认值
# 实际值从配置 Error.WatchdogTaskTimeout 读取，0 表示禁用
WATCHDOG_TASK_TIMEOUT_DEFAULT = 120
# 模拟器 stop/start 单次操作的硬超时秒数
RESTART_EMULATOR_OP_TIMEOUT = 120
DAILY_SUMMARY_CHECK_INTERVAL = 1


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
        # 未预期异常连续计数，先重启游戏，连续多次才重启模拟器
        self.consecutive_unexpected_error = 0
        # ScriptError 连续计数，达到阈值后退出（代码 bug 重试无意义）
        self.script_error_count = 0
        # 上次计划重启模拟器的时间戳
        self.last_emulator_restart_time = time.monotonic()
        # 看门狗状态
        self._watchdog_stop = threading.Event()
        self._watchdog_active = False  # 仅在任务执行期间激活
        self._watchdog_thread = None
        self._watchdog_task_start = 0.0  # 当前任务开始时间（monotonic）
        self._watchdog_task_name = ''    # 当前任务名
        # 日报关闭时不创建线程同步原语、服务或数据库；所有对象均在启用后按需创建。
        self._daily_summary_enabled = False
        self._daily_summary_service = None
        self._daily_summary_stop = None
        self._daily_summary_thread = None
        self._daily_summary_settings_mtime = None
        self._daily_summary_settings = None

    def _get_daily_summary_service(self):
        """惰性获取实例级日报服务，避免普通运行引入额外 I/O。"""
        if getattr(self, '_daily_summary_service', None) is None:
            from module.statistics.daily_summary import DailySummaryService

            self._daily_summary_service = DailySummaryService(self.config_name)
        return self._daily_summary_service

    @staticmethod
    def _daily_summary_settings_from_config(config):
        """从主线程已加载的配置创建日报专用只读快照。"""
        return SimpleNamespace(
            DailySummary_Enable=bool(
                getattr(config, 'DailySummary_Enable', False)
            ),
            DailySummary_TriggerTime=getattr(
                config, 'DailySummary_TriggerTime', '20:00'
            ),
            Emulator_PackageName=getattr(
                config, 'Emulator_PackageName', 'auto'
            ),
            Emulator_ServerName=getattr(
                config, 'Emulator_ServerName', 'disabled'
            ),
            Error_LlmApiKey=getattr(config, 'Error_LlmApiKey', ''),
            Error_LlmApiBase=getattr(config, 'Error_LlmApiBase', ''),
            Error_LlmModel=getattr(config, 'Error_LlmModel', ''),
            Error_OnePushConfig=getattr(config, 'Error_OnePushConfig', ''),
        )

    @staticmethod
    def _daily_summary_settings_from_data(data):
        """仅从配置文件数据创建日报快照，不访问调度器配置对象。"""
        alas = data.get('Alas') if isinstance(data, dict) else None
        if not isinstance(alas, dict):
            alas = {}

        def read(group, key, default):
            values = alas.get(group)
            return values.get(key, default) if isinstance(values, dict) else default

        return SimpleNamespace(
            DailySummary_Enable=bool(read('DailySummary', 'Enable', False)),
            DailySummary_TriggerTime=read('DailySummary', 'TriggerTime', '20:00'),
            Emulator_PackageName=read('Emulator', 'PackageName', 'auto'),
            Emulator_ServerName=read('Emulator', 'ServerName', 'disabled'),
            Error_LlmApiKey=read('Error', 'LlmApiKey', ''),
            Error_LlmApiBase=read('Error', 'LlmApiBase', ''),
            Error_LlmModel=read('Error', 'LlmModel', ''),
            Error_OnePushConfig=read('Error', 'OnePushConfig', ''),
        )

    def _check_daily_summary(self, config=None):
        """检查日报，不连接设备，也不影响调度器主流程。"""
        try:
            if config is None:
                config = self._get_daily_summary_settings()
            if not bool(getattr(config, 'DailySummary_Enable', False)):
                return
            current_server = (
                server_config.server if 'device' in self.__dict__ else None
            )
            self._get_daily_summary_service().check_due(
                config,
                current_server=current_server,
                now=current_time(),
            )
        except Exception as error:
            logger.warning(f'[日报] 调度检查失败，已忽略: {type(error).__name__}')

    def _get_daily_summary_settings(self):
        """读取最新日报设置，不重载正在执行任务的完整配置对象。"""
        try:
            config_path = filepath_config(self.config_name)
            modified_at = os.stat(config_path).st_mtime_ns
        except OSError:
            return self._daily_summary_settings or self._daily_summary_settings_from_data({})

        if (
            self._daily_summary_settings is not None
            and self._daily_summary_settings_mtime == modified_at
        ):
            return self._daily_summary_settings

        try:
            with open(config_path, encoding='utf-8') as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            logger.warning('[日报] 读取最新配置失败，继续使用日报配置快照')
            return self._daily_summary_settings or self._daily_summary_settings_from_data({})

        self._daily_summary_settings = self._daily_summary_settings_from_data(data)
        self._daily_summary_settings_mtime = modified_at
        return self._daily_summary_settings

    def _daily_summary_loop(self):
        """独立检查日报时间，避免长任务或服务器等待错过触发时刻。"""
        stop_event = self._daily_summary_stop
        if stop_event is None:
            return
        try:
            while not stop_event.is_set():
                config = self._get_daily_summary_settings()
                if not bool(getattr(config, 'DailySummary_Enable', False)):
                    self._daily_summary_enabled = False
                    logger.info('[日报] 功能已关闭，停止独立定时检查')
                    return
                self._check_daily_summary(config)
                stop_event.wait(DAILY_SUMMARY_CHECK_INTERVAL)
        finally:
            if self._daily_summary_thread is threading.current_thread():
                self._daily_summary_stop = None
                self._daily_summary_thread = None

    def _start_daily_summary_scheduler(self, config=None):
        """启动不依赖游戏任务的日报定时检查线程。"""
        # 只使用调用方已经持有的配置；绝不通过 self.config 触发懒加载。
        if config is None or not bool(
            getattr(config, 'DailySummary_Enable', False)
        ):
            return False
        if (
            self._daily_summary_thread is not None
            and self._daily_summary_thread.is_alive()
        ):
            return True
        settings = self._daily_summary_settings_from_config(config)
        try:
            settings_mtime = os.stat(
                filepath_config(self.config_name)
            ).st_mtime_ns
        except OSError:
            settings_mtime = None

        # 在线程启动前由主线程完成服务初始化，避免定时线程和任务线程同时创建服务。
        try:
            self._get_daily_summary_service()
        except Exception as error:
            logger.warning(f'[日报] 初始化失败，未启动定时检查: {type(error).__name__}')
            return False

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._daily_summary_loop,
            daemon=True,
            name=f'daily-summary-scheduler-{self.config_name}',
        )
        self._daily_summary_settings = settings
        self._daily_summary_settings_mtime = settings_mtime
        self._daily_summary_stop = stop_event
        self._daily_summary_thread = thread
        self._daily_summary_enabled = True
        try:
            thread.start()
        except Exception as error:
            self._daily_summary_enabled = False
            self._daily_summary_stop = None
            self._daily_summary_thread = None
            logger.warning(f'[日报] 定时检查启动失败: {type(error).__name__}')
            return False
        logger.info('[日报] 独立定时检查已启动')
        return True

    def _stop_daily_summary_scheduler(self):
        """停止日报定时检查线程。"""
        stop_event = self._daily_summary_stop
        thread = self._daily_summary_thread
        if stop_event is None and thread is None:
            return False
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._daily_summary_enabled = False
        self._daily_summary_stop = None
        self._daily_summary_thread = None
        logger.info('[日报] 独立定时检查已停止')
        return True

    def _record_daily_summary_task_start(self, task: str):
        """为启用日报的实例记录任务开始，不向调度器传播存储错误。"""
        if not self._daily_summary_enabled:
            return None
        try:
            return self._get_daily_summary_service().store.record_task_start(
                self.config_name, task, current_time()
            )
        except Exception as error:
            logger.warning(f'[日报] 记录任务开始失败，已忽略: {type(error).__name__}')
            return None

    def _record_daily_summary_task_finish(
        self, run_id, success, started_at: datetime
    ):
        """记录任务结果；日报存储异常不能改变既有错误恢复逻辑。"""
        if run_id is None:
            return
        try:
            if success is True:
                status = 'success'
            elif success == 'recoverable':
                status = 'recoverable'
            else:
                status = 'failed'
            finished_at = current_time()
            duration = max(0.0, (finished_at - started_at).total_seconds())
            self._get_daily_summary_service().store.record_task_finish(
                self.config_name, run_id, finished_at, status, duration
            )
        except Exception as error:
            logger.warning(f'[日报] 记录任务结果失败，已忽略: {type(error).__name__}')

    def _try_restart_emulator(self):
        """
        尝试重启模拟器。永不放弃，一直重试。

        不再受 Error_AdbOfflineRestart 开关限制，
        超过阈值时仅增加等待间隔，不停止重试。
        优先使用已缓存的 device 对象，否则根据平台回退创建新实例。

        Returns:
            bool: 重启成功返回 True，本次重启失败返回 False（调度器会继续尝试）。
        """
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
                # connect=False 避免在模拟器离线时先建立 ADB 连接。
                from module.device.platform import Platform
                device = Platform(self.config, connect=False)

            logger.info('[Alas] 正在停止模拟器...')
            self._emulator_op_with_timeout(
                device.emulator_stop,
                timeout=RESTART_EMULATOR_OP_TIMEOUT,
                operation_name='模拟器停止',
            )
            time.sleep(5)
            logger.info('[Alas] 正在启动模拟器...')
            self._emulator_op_with_timeout(
                device.emulator_start,
                timeout=RESTART_EMULATOR_OP_TIMEOUT,
                operation_name='模拟器启动',
            )
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

    def _emulator_op_with_timeout(self, func, *, timeout, operation_name):
        """带硬超时执行模拟器启停操作，防止恢复流程本身卡死。

        emulator_stop / emulator_start 底层调用 subprocess（taskkill /
        ldconsole / MuMuManager 等），正常情况下秒级完成。但若模拟器进程
        僵死或子进程管理卡住，调用可能长时间不返回。此方法在独立 daemon
        线程中执行操作，超时后抛出 TimeoutError，由外层 try/except 捕获
        并返回 False，调度器会退避重试。

        Args:
            func: 无参数的可调用对象。
            timeout (int | float): 超时秒数。
            operation_name (str): 操作名称，用于日志。

        Raises:
            TimeoutError: 操作超时。
            Exception: 操作本身抛出的异常会被原样向上抛出。
        """
        result = [None]
        exception = [None]

        def worker():
            try:
                result[0] = func()
            except BaseException as e:
                exception[0] = e

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            logger.critical(
                f'[Alas] {operation_name} 超过 {timeout}s 未完成，'
                f'跳过此操作（daemon 线程残留，进程退出时自动清理）'
            )
            raise TimeoutError(
                f'{operation_name} 超过 {timeout}s 未完成'
            )

        if exception[0] is not None:
            raise exception[0]
        return result[0]

    def _start_watchdog(self):
        """启动看门狗守护线程。

        以下任一条件满足时启动：
        1. Error.WatchdogEnable 为 True（任务超时检测）
        2. EmulatorManagement.ScheduledEmulatorRestart 和 ForceScheduledRestart
           都为 True（强制定时重启）

        启动后各检测由对应子开关单独控制。
        """
        # 检查是否需要启动看门狗
        try:
            master_enable = bool(self.config.Error_WatchdogEnable)
        except Exception:
            master_enable = False
        try:
            force_restart = (
                bool(self.config.EmulatorManagement_ScheduledEmulatorRestart)
                and bool(self.config.EmulatorManagement_ForceScheduledRestart)
            )
        except Exception:
            force_restart = False

        if not master_enable and not force_restart:
            logger.info('[Alas][看门狗] 无需启动看门狗（总开关和强制定时重启均未开启）')
            return

        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            logger.warning('[Alas][看门狗] 看门狗已在运行，跳过启动')
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name='alas-watchdog'
        )
        self._watchdog_thread.start()
        logger.info(
            f'[Alas][看门狗] 看门狗已启动'
            f'（任务超时: {master_enable}, 强制定时重启: {force_restart}）'
        )

    def _stop_watchdog(self):
        """停止看门狗守护线程。"""
        self._watchdog_stop.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5)
            self._watchdog_thread = None
        logger.info('[Alas][看门狗] 看门狗已停止')

    def _watchdog_loop(self):
        """看门狗主循环：检测任务运行时间超时和强制定时重启。

        看门狗在 _start_watchdog 判断是否启动（任一检测开启即启动）。
        各检测由对应开关单独控制：

        1. 任务运行时间超时：Error.WatchdogEnable + Error.WatchdogTaskEnable
           单个任务运行超过配置的 WatchdogTaskTimeout 分钟
           → 任务逻辑死循环（如 story_skip 不断点击但剧情无法跳过）
           此时日志仍在更新，但任务无法自然退出
        2. 强制定时重启：EmulatorManagement.ScheduledEmulatorRestart +
           EmulatorManagement.ForceScheduledRestart
           到达重启间隔且当前为非敏感任务，强制重启模拟器

        恢复方式：强制杀死模拟器进程，使主线程的下次 I/O 调用失败并抛出
        异常，触发正常的异常恢复流程。
        """
        while not self._watchdog_stop.wait(WATCHDOG_CHECK_INTERVAL):
            if not self._watchdog_active:
                continue

            # 检查 1：强制定时重启（非敏感任务时强制中断）
            # 需要 ScheduledEmulatorRestart 和 ForceScheduledRestart 都为 True
            try:
                scheduled = bool(self.config.EmulatorManagement_ScheduledEmulatorRestart)
                force = bool(self.config.EmulatorManagement_ForceScheduledRestart)
            except Exception:
                scheduled = False
                force = False
            if scheduled and force and self._watchdog_task_name:
                # 检查当前任务是否为敏感任务
                task_name_camelize = inflection.camelize(self._watchdog_task_name)
                try:
                    sensitive = self.config.cross_get(
                        keys=f'{task_name_camelize}.Scheduler.Sensitive', default=False
                    )
                except Exception:
                    sensitive = False
                if not sensitive:
                    # 检查是否到了重启间隔
                    try:
                        interval = int(self.config.EmulatorManagement_RestartIntervalHours)
                    except Exception:
                        interval = 4
                    elapsed_hours = (time.monotonic() - self.last_emulator_restart_time) / 3600
                    if elapsed_hours >= interval:
                        logger.critical(
                            f'[Alas][看门狗] 模拟器已运行 {elapsed_hours:.1f} 小时'
                            f'（超过 {interval} 小时），开启强制定时重启，'
                            f'当前任务 `{self._watchdog_task_name}` 为非敏感任务，'
                            f'强制杀死模拟器进程以中断任务'
                        )
                        self._watchdog_recover(
                            elapsed_hours * 3600,
                            reason='force_scheduled_restart',
                            task_name=self._watchdog_task_name,
                        )
                        continue

            # 检查 2：任务运行时间超时（逻辑死循环）
            # 需要 WatchdogEnable 和 WatchdogTaskEnable 都为 True
            # 即使日志在更新，如果任务运行时间过长，说明陷入了无法
            # 自然退出的循环（如 GameTooManyClickError 被 click_record_clear
            # 绕过、地图寻路死循环等），需强制中断
            try:
                task_enable = bool(self.config.Error_WatchdogTaskEnable)
            except Exception:
                task_enable = False
            if task_enable and self._watchdog_task_start > 0:
                # 从配置读取超时阈值（分钟），0 表示禁用
                try:
                    timeout_min = int(self.config.Error_WatchdogTaskTimeout)
                except Exception:
                    timeout_min = WATCHDOG_TASK_TIMEOUT_DEFAULT
                if timeout_min > 0:
                    elapsed_task = time.monotonic() - self._watchdog_task_start
                    if elapsed_task > timeout_min * 60:
                        self._watchdog_recover(
                            elapsed_task,
                            reason='task_timeout',
                            task_name=self._watchdog_task_name,
                        )

    def _watchdog_recover(self, elapsed, reason='task_timeout', task_name=''):
        """看门狗恢复动作：强制杀死模拟器进程以中断任务。

        任务陷入逻辑死循环（如 story_skip 不断点击但剧情无法跳过），
        日志仍在更新但任务无法自然退出。杀死模拟器进程会同时杀死
        atx-agent，使主线程的下次 I/O 调用因连接断开而失败并抛出异常，
        触发正常的异常恢复流程
        （EmulatorNotRunningError → _try_restart_emulator + task_call('Restart')）。

        emulator_stop() 本身也可能卡住（如 psutil 遍历缓慢或 subprocess
        不返回），因此用 _emulator_op_with_timeout 包装，超时后放弃本轮
        恢复，等待下一个阈值周期重试。

        Args:
            elapsed (float): 已经过的秒数。
            reason (str): 触发原因，当前仅支持 'task_timeout'。
            task_name (str): 当前任务名。
        """
        if reason == 'task_timeout':
            try:
                timeout_min = int(self.config.Error_WatchdogTaskTimeout)
            except Exception:
                timeout_min = WATCHDOG_TASK_TIMEOUT_DEFAULT
            logger.critical(
                f'[Alas][看门狗] 任务 `{task_name}` 已运行 {int(elapsed)} 秒'
                f'（超过 {timeout_min} 分钟），判定逻辑死循环，'
                f'强制杀死模拟器进程以中断任务'
            )
        elif reason == 'force_scheduled_restart':
            logger.critical(
                f'[Alas][看门狗] 任务 `{task_name}` 执行期间触发强制定时重启，'
                f'强制杀死模拟器进程以中断任务'
            )
            # 更新重启时间戳，避免恢复后立即重复触发
            self.last_emulator_restart_time = time.monotonic()
        else:
            logger.critical(
                f'[Alas][看门狗] 检测到异常（reason={reason}），'
                f'强制杀死模拟器进程以中断任务'
            )

        try:
            from module.device.platform import Platform
            platform = Platform(self.config, connect=False)
            self._emulator_op_with_timeout(
                platform.emulator_stop,
                timeout=RESTART_EMULATOR_OP_TIMEOUT,
                operation_name='[看门狗] 强制停止模拟器',
            )
            logger.info(
                '[Alas][看门狗] 已强制停止模拟器，主线程的下次 I/O 调用将失败并触发恢复'
            )
        except TimeoutError:
            logger.warning(
                '[Alas][看门狗] 强制停止模拟器超时，等待下个周期重试'
            )
        except Exception as e:
            logger.warning(f'[Alas][看门狗] 强制停止模拟器失败: {e}')

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
            # 未预期异常，先重启游戏，连续多次失败才重启模拟器
            logger.exception_context(
                title=f'任务执行发生未处理异常（{command}）', exc=e,
                impact='当前任务无法确认执行结果，调度器将尝试重启恢复。',
                action='查看错误现场中的 log.txt、截图和完整堆栈，确认是否需要更新资源或提交问题。',
                level=50,
            )
            self.save_error_log()
            self._check_sensitive_exit(command, e)

            self.consecutive_unexpected_error += 1
            limit = int(self.config.Error_GameStuckThreshold)
            if self.consecutive_unexpected_error >= limit:
                # 连续多次未预期异常，说明重启游戏无法解决，重启模拟器
                logger.warning(
                    f'[Alas] 未处理异常连续 {self.consecutive_unexpected_error}/{limit} 次，'
                    f'重启模拟器恢复'
                )
                self._try_restart_emulator()
                self.consecutive_unexpected_error = 0
            else:
                # 首次或前几次异常，先尝试重启游戏（较轻的恢复）
                logger.warning(
                    f'[Alas] 未处理异常 {self.consecutive_unexpected_error}/{limit} 次，'
                    f'先尝试重启游戏恢复'
                )
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

        # 调度器本身需要先加载配置；日报关闭时不创建任何附加线程或服务。
        config = self.config
        if config.DailySummary_Enable:
            self._start_daily_summary_scheduler(config)

        # 启动看门狗：守护线程在任务执行期间监测日志心跳，若主线程长时间
        # 无日志输出（如卡死在 u2 HTTP 调用或 ADB shell 中），则强制杀死
        # 模拟器进程以解除阻塞，使主线程的下次 I/O 失败并触发异常恢复。
        self._start_watchdog()

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
                        self._stop_daily_summary_scheduler()
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
                # 激活看门狗：任务执行期间监测日志心跳和运行时间
                # 防止主线程卡死在 I/O 调用中或陷入逻辑死循环
                self._watchdog_active = True
                self._watchdog_task_start = time.monotonic()
                self._watchdog_task_name = task
                task_started_at = current_time()
                daily_summary_run_id = None
                if self._daily_summary_enabled:
                    daily_summary_run_id = self._record_daily_summary_task_start(task)
                success = None
                try:
                    success = self.run(inflection.underscore(task))
                finally:
                    self._watchdog_active = False
                    self._watchdog_task_start = 0.0
                    self._watchdog_task_name = ''
                    self._record_daily_summary_task_finish(
                        daily_summary_run_id, success, task_started_at
                    )
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
                    self.consecutive_unexpected_error = 0
                    continue
                elif success == 'recoverable' or self.config.Error_HandleError:
                    # 可恢复错误或启用了错误处理，刷新配置后继续循环
                    del_cached_property(self, 'config')
                    self.checker.check_now()
                    continue
                else:
                    self._stop_daily_summary_scheduler()
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
                # 退避等待期间暂停看门狗，避免误触发（此为主动 sleep）
                self._watchdog_active = False
                time.sleep(wait_seconds)

if __name__ == '__main__':
    alas = AzurLaneAutoScript()
    alas.loop()
