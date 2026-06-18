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
from module.config.config import AzurLaneConfig, TaskEnd
from module.config.deep import deep_get, deep_set
from module.config.utils import DEFAULT_CONFIG_NAME, filepath_i18n, read_file
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
        # 上次计划重启模拟器的时间戳
        self.last_emulator_restart_time = time.time()

    def _try_restart_emulator(self):
        """
        尝试重启模拟器。

        需要启用 AdbOfflineRestart 且未超过重试上限。
        优先使用已缓存的 device 对象，否则根据平台回退创建新实例。

        Returns:
            bool: 重启成功返回 True，无法重启返回 False。
        """
        import sys

        if not self.config.Error_AdbOfflineRestart:
            logger.warning('AdbOfflineRestart 已禁用，无法自动重启模拟器')
            return False

        self.consecutive_adb_offline += 1
        limit = int(self.config.Error_AdbOfflineThreshold)
        logger.warning(f'EmulatorNotRunningError: 连续次数 {self.consecutive_adb_offline}/{limit}')

        if self.consecutive_adb_offline > limit:
            logger.critical(f'EmulatorNotRunningError: 已达到重启限制 ({limit})')
            return False

        logger.hr('正在重启模拟器', level=1)
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

            logger.info('正在停止模拟器...')
            device.emulator_stop()
            time.sleep(5)
            logger.info('正在启动模拟器...')
            device.emulator_start()
            logger.info('模拟器重启完成')

            # 清除 device 缓存，下次访问时重新建立连接
            if 'device' in self.__dict__:
                del_cached_property(self, 'device')
            return True
        except Exception as e:
            logger.error(f'重启模拟器失败: {e}')
            return False

    @cached_property
    def config(self):
        try:
            config = AzurLaneConfig(config_name=self.config_name)
            return config
        except RequestHumanTakeover:
            logger.critical('杂鱼杂鱼~ 没用的大叔连这点事都办不好？这就滚回来求我接管吧❤')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    @cached_property
    def device(self):
        try:
            from module.device.device import Device
            device = Device(config=self.config)
            return device
        except RequestHumanTakeover:
            logger.critical('杂鱼杂鱼~ 没用的大叔连这点事都办不好？这就滚回来求我接管吧❤')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    @cached_property
    def checker(self):
        try:
            from module.server_checker import ServerChecker
            checker = ServerChecker(server=self.config.Emulator_ServerName)
            return checker
        except Exception as e:
            logger.exception(e)
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

        logger.critical(f'敏感任务 `{task_name}` 出错，禁止重启，AzurPilot 将停止运行')
        logger.critical(f'异常: {error}')
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
            logger.warning(e)
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
            logger.error(e)
            self.save_error_log()
            self._check_sensitive_exit(command, e)

            if self.config.Error_GameStuckRestart:
                self.consecutive_game_stuck += 1
                limit = int(self.config.Error_GameStuckThreshold)
                logger.warning(f'GameStuckError: {self.consecutive_game_stuck}/{limit}')
                if self.consecutive_game_stuck >= limit:
                    logger.warning('游戏卡住次数过多，正在重启模拟器...')
                    if self._try_restart_emulator():
                        self.consecutive_game_stuck = 0
                        self.config.task_call('Restart')
                        return 'recoverable'

            logger.warning(f'游戏卡住，{self.device.package} 将在10秒后重启')
            logger.warning('如果您正在手动操作，请停止 AzurPilot')
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
            logger.warning(e)
            self.save_error_log()
            self._check_sensitive_exit(command, e)
            logger.warning('碧蓝航线游戏客户端发生错误，AzurPilot 无法处理')
            logger.warning(f'正在重启 {self.device.package} 以修复问题')
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
        except GamePageUnknownError:
            logger.info('游戏服务器可能正在维护或网络连接中断，正在检查服务器状态')
            self.checker.check_now()
            if self.checker.is_available():
                logger.critical('哈？你这游戏进的是什么鬼地方？这种破页面我都懒得认识！真逊~')
                self.save_error_log()
                handle_notify(
                    self.config.Error_OnePushConfig,
                    title=f"AzurPilot <{self.config_name}> 崩溃",
                    content=f"<{self.config_name}> GamePageUnknownError",
                )
                notify_webui(
                    self.config_name,
                    title=f"出大问题了喵！{self.config_name} 崩溃了喵！",
                    content=f"因为 GamePageUnknownError 喵！",
                )
                exit(1)
            else:
                self.checker.wait_until_available()
                return False
        except ScriptError as e:
            logger.exception(e)
            logger.critical('噗噗~ 恭喜大叔触发了诡异Bug！果然废材的人品就是差呢❤')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 崩溃",
                content=f"<{self.config_name}> ScriptError",
            )
            notify_webui(
                self.config_name,
                title=f"出大问题了喵！{self.config_name}崩溃了喵！",
                content=f"因为 ScriptError 喵！",
            )
            raise
        except EmulatorNotRunningError as e:
            # 模拟器离线或死机，尝试自动重启
            logger.error('任务执行期间模拟器未运行')
            self.save_error_log()
            self._check_sensitive_exit(command, e)
            if self._try_restart_emulator():
                # 重启成功，调度 Restart 任务恢复游戏
                self.config.task_call('Restart')
                handle_notify(
                    self.config.Error_OnePushConfig,
                    title=f"AzurPilot <{self.config_name}> 警告",
                    content=f"<{self.config_name}> 模拟器离线 - 已自动重启模拟器",
                )
                notify_webui(
                    self.config_name,
                    title=f"{self.config_name} 出了点小问题喵~",
                    content=f"模拟器离线喵 所以重启了喵",
                )
                return 'recoverable'
            else:
                # 重启失败或未启用自动重启，终止程序
                logger.critical('模拟器都死透了你还在那看？赶紧动手去救它啊，没用的大叔！')
                handle_notify(
                    self.config.Error_OnePushConfig,
                    title=f"AzurPilot <{self.config_name}> 崩溃",
                    content=f"<{self.config_name}> EmulatorNotRunningError",
                )
                notify_webui(
                    self.config_name,
                    title=f"出大问题了喵！{self.config_name}崩溃了喵！",
                    content=f"因为 模拟器出问题了 喵！",
                )
                exit(1)
        except RequestHumanTakeover:
            logger.critical('你行你上啊，盯着我看干什么？难道大叔也想让我这种小鬼帮你接管吗？❤')
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 崩溃",
                content=f"<{self.config_name}> RequestHumanTakeover",
            )
            notify_webui(
                self.config_name,
                title=f"出大问题了喵！{self.config_name}崩溃了喵！",
                content=f"因为 需要人工介入 喵！",
            )
            exit(1)
        except AutoSearchSetError:
            logger.critical('笨——蛋——大叔！自动搜索都不会设，你是在等我也嘲笑你的困难编队吗？❤')
            logger.critical('看懂了吗？滚过来接管。')
            exit(1)
        except Exception as e:
            logger.exception(e)
            self.save_error_log()
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config_name}> 崩溃",
                content=f"<{self.config_name}> 发生异常",
            )
            notify_webui(
                self.config_name,
                title=f"出大问题了喵！{self.config_name}崩溃了喵！",
                content=f"因为 发生异常 喵！",
            )
            raise

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
            logger.error(f'LLM Analysis failed: {e}')

        if getattr(self.config, 'Error_SaveError', False):
            config_folder = pathlib.Path(f"./log/error/{self.config_name}")
            folder = config_folder.joinpath(str(int(time.time() * 1000)))
            folder.mkdir(parents=True, exist_ok=True)
            logger.warning(f'保存错误日志: {folder}')

            try:
                # 只在已经初始化了设备时才尝试保存截图，避免按需初始化时二次崩溃
                if 'device' in self.__dict__:
                    for data in self.device.screenshot_deque:
                        image_time = datetime.strftime(data['time'], '%Y-%m-%d_%H-%M-%S-%f')
                        image = handle_sensitive_image(data['image'])
                        save_image(image, f'{folder}/{image_time}.png')
            except Exception as e:
                logger.error(f"Save error screenshot failed: {e}")

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
                logger.error(f"Save error logs failed: {e}")
                
            self.keep_last_errlog(config_folder, getattr(self.config, 'Error_SaveErrorCount', 0))

    def restart(self):
        from module.handler.login import LoginHandler
        LoginHandler(self.config, device=self.device).app_restart()
        self.config.task_delay(server_update=True)

    def start(self):
        from module.handler.login import LoginHandler
        LoginHandler(self.config, device=self.device).app_start()

    def goto_main(self):
        from module.handler.login import LoginHandler
        from module.ui.ui import UI
        if self.device.app_is_running():
            logger.info('应用已在运行，前往主页面')
            UI(self.config, device=self.device).ui_goto_main()
        else:
            logger.info('应用未运行，启动应用并前往主页面')
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

    def island_season_task(self):
        from module.island.season_task import IslandSeasonTaskHandler
        IslandSeasonTaskHandler(config=self.config, device=self.device).run()

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

    def azur_lane_uncensored(self):
        from module.daemon.uncensored import AzurLaneUncensored
        AzurLaneUncensored(config=self.config, device=self.device, task="AzurLaneUncensored").run()

    def benchmark(self):
        from module.daemon.benchmark import run_benchmark
        run_benchmark(config=self.config)

    def ocr_benchmark(self):
        from module.daemon.ocr_benchmark import run_ocr_benchmark
        run_ocr_benchmark(config=self.config)

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
                logger.warning('Remote SSH is not enabled in EmulatorManager settings.')
                return

            host = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHHost', '')
            port = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHPort', 22)
            user = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHUser', '')
            command = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteStartCommand', '')
            if not command:
                command = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteCommand', '')
            key = deep_get(self.config.data, 'EmulatorManager.EmulatorManager.RemoteSSHPublicKey', '')

        if not host or not command:
            logger.warning(f'RemoteSSHHost ({host}) or RemoteStartCommand ({command}) is empty, skip remote SSH command')
            return

        logger.hr('Remote SSH Command', level=1)
        target = f'{user}@{host}' if user else host
        # -n: 禁用标准输入  -T: 禁用伪终端分配  BatchMode: 避免密码提示导致挂起
        cmd = ['ssh', '-n', '-T', '-p', str(port), '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
        
        key_file = None
        if key and len(key) > 50:
            import tempfile
            import os
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
                logger.info(f'Using provided private key for authentication')
            except Exception as e:
                logger.error(f'Failed to create or secure temporary key file: {e}')

        cmd += [target, command]
        logger.info(f'Executing remote command: {" ".join(cmd)}')

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
                    logger.info(f'Remote: {line.strip()}')
            
            stderr_thread = threading.Thread(target=collect_stderr)
            stdout_thread = threading.Thread(target=collect_stdout)
            stderr_thread.start()
            stdout_thread.start()

            try:
                # 主线程等待进程退出
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                logger.error('Remote SSH command timed out after 30 seconds')
                return
            finally:
                stderr_thread.join(timeout=5)
                stdout_thread.join(timeout=5)

            if process.returncode == 0:
                logger.info('Remote command executed successfully')
            else:
                logger.error(f'Remote command failed with return code {process.returncode}')
                for line in stderr_content:
                    logger.error(f'Remote Error: {line}')
        except Exception as e:
            logger.error(f'Failed to execute remote SSH command: {e}')
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
            if datetime.now() > future:
                return True
            if self.stop_event is not None:
                if self.stop_event.is_set():
                    logger.info("检测到更新事件")
                    logger.info(f"[{self.config_name}] 已退出。原因: 更新 | Reason: Update")
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

            if task.next_run > datetime.now():
                logger.info(f'等待直到 {task.next_run} 执行任务 `{task.command}`')
                self.is_first_task = False
                method = self.config.Optimization_WhenTaskQueueEmpty
                if method == 'close_game':
                    logger.info('等待期间关闭游戏')
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
                    logger.info('等待期间前往主页面')
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
                    logger.warning(f'无效的 Optimization_WhenTaskQueueEmpty: {method}, 回退到 stay_there')
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
        logger.info(f'启动调度器循环: {self.config_name}')

        from module.config.utils import is_oobe_needed

        if is_oobe_needed():
            logger.critical(
                "未检测到配置文件。\n"
                "请先运行 WebUI 完成初次设置:\n"
                "    python gui.py\n"
                "No configuration files detected.\n"
                "Please run the WebUI first:\n"
                "    python gui.py"
            )
            exit(1)

        # 全局异常连续失败计数与阈值
        consecutive_global_failures = 0
        MAX_GLOBAL_FAILURES = 3
        RESTART_DELAY = 20
        LONG_WAIT = 300

        while 1:
            try:
                # 检查来自GUI的更新事件
                if self.stop_event is not None:
                    if self.stop_event.is_set():
                        logger.info("检测到更新事件")
                        logger.info(f"AzurPilot [{self.config_name}] 已退出。原因: 更新 | Reason: Update")
                        break
                # 检查游戏服务器维护
                self.checker.wait_until_available()
                if self.checker.is_recovered():
                    # 服务器恢复后强制刷新配置，修复阻塞期间配置未更新的问题
                    del_cached_property(self, 'config')
                    logger.info('服务器或网络已恢复。重启游戏客户端')
                    self.config.task_call('Restart')
                # 检查计划的模拟器重启（在任务之间，不会中断正在运行的任务）
                if self.config.EmulatorManagement_ScheduledEmulatorRestart:
                    elapsed_hours = (time.time() - self.last_emulator_restart_time) / 3600
                    interval = self.config.EmulatorManagement_RestartIntervalHours
                    if elapsed_hours >= interval:
                        logger.hr('计划的模拟器重启', level=1)
                        logger.info(f'模拟器已运行 {elapsed_hours:.1f} 小时, '
                                    f'计划重启间隔为 {interval} 小时')
                        if self._try_restart_emulator():
                            self.last_emulator_restart_time = time.time()
                            self.config.task_call('Restart')
                            del_cached_property(self, 'config')
                            continue
                        else:
                            logger.warning('计划的模拟器重启失败，继续正常运行')

                # 获取任务
                task = self.get_next_task()
                # 初始化设备并更改服务器
                _ = self.device
                self.device.config = self.config
                # 跳过第一次重启
                if self.is_first_task and task == 'Restart':
                    logger.info('调度器启动时跳过任务 `Restart`')
                    self.config.task_delay(server_update=True)
                    del_cached_property(self, 'config')
                    continue

                # 运行
                logger.info(f'调度器: 开始任务 `{task}`')
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                logger.hr(task, level=0)
                success = self.run(inflection.underscore(task))
                logger.info(f'调度器: 结束任务 `{task}`')
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
                        logger.warning('每任务推送通知异常，已跳过')

                # 检查失败
                # 单个任务连续失败三次终止程序
                # 注意：可恢复错误 (success == 'recoverable') 不计入失败次数
                failed = deep_get(self.failure_record, keys=task, default=0)
                if success == True:
                    failed = 0  # 成功，重置计数
                elif success == 'recoverable':
                    # 可恢复错误（如 GameStuckError），不增加失败计数
                    # 但也不重置，保持之前的计数
                    logger.info(f'任务 `{task}` 遇到可恢复错误，不计入失败限制')
                else:
                    failed = failed + 1  # 不可恢复错误，增加计数
                deep_set(self.failure_record, keys=task, value=failed)

                strict_restart = self.config.Error_StrictRestart and failed >= 1 and self.config.cross_get(
                    keys=f'{task}.Scheduler.Sensitive', default=False
                )
                if failed >= 3 or strict_restart:
                    logger.critical(f"任务 `{task}` 失败 {failed} 次或更多。")
                    logger.critical("可能原因 #1: 您未正确使用。请阅读选项的帮助文本。")
                    logger.critical("可能原因 #2: 此任务存在问题。请联系开发者或尝试自行修复。")
                    if strict_restart:
                        logger.critical("可能原因 #3: 这是重启敏感任务。请手动接管游戏或关闭 'StrictRestart' 选项。")
                    logger.critical('请求人工接管')
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
                    logger.warning("任务连续失败次数过多，正在上报错误日志...")
                    ApiClient.submit_bug_log(f"AzurPilot <{self.config_name}> crashed\nTask `{task}` failed {failed} or more times.")
                    exit(1)

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
            except Exception as e:
                consecutive_global_failures += 1
                self.is_first_task = False
                logger.error("调度器循环中发生意外的全局异常！")
                import traceback
                logger.error(traceback.format_exc())
                
                # 即使没有达到重启或失败上限，也第一时间自动请求分析崩溃原因
                try:
                    if hasattr(self, 'config') and getattr(self.config, 'Error_LlmAnalysis', False):
                        from module.llm import analyze_exception
                        analyze_exception(self.config, e)
                except Exception as ex:
                    logger.error(f'LLM Analysis failed: {ex}')

                logger.warning(
                    f">>> 这是第 {consecutive_global_failures} 次连续全局失败，共 {MAX_GLOBAL_FAILURES} 次。"
                )

                # 检查是否达到重试上限
                if consecutive_global_failures >= MAX_GLOBAL_FAILURES:
                    logger.critical(
                        f"连续崩了 {MAX_GLOBAL_FAILURES} 次！AzurPilot 已经被你气死了！"
                    )
                    logger.critical("这错误没救了，重启一百次也没用。")
                    self.save_error_log()
                    logger.critical("调度器罢工了！赶紧滚过来人工救场！")
                    logger.warning("遇到无法恢复的致命错误，正在上报错误日志...")
                    ApiClient.submit_bug_log(f"AzurPilot <{self.config_name}> 调度器终止。\n已达到最大全局失败次数 ({MAX_GLOBAL_FAILURES})。\n{traceback.format_exc()}")
                    exit(1)

                # 尝试重启
                logger.warning("尝试通过强制执行 RESTART 任务来恢复...")
                try:
                    # 注入 Restart 任务
                    self.config.task_call('Restart')
                    # 重新加载配置
                    del_cached_property(self, 'config')
                    logger.info("已为下一个循环安排了 `Restart` 任务。")
                except Exception as restart_e:
                    logger.error("甚至无法安排重启任务！")
                    logger.error(f"安排错误: {restart_e}")

                # 等待一段时间后开始下一次循环
                wait_seconds = RESTART_DELAY if consecutive_global_failures < 4 else LONG_WAIT
                logger.info(
                    f"调度器将在 {wait_seconds} 秒后从头重试。"
                )
                time.sleep(wait_seconds)

if __name__ == '__main__':
    alas = AzurLaneAutoScript()
    alas.loop()
