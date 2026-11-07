"""战斗快进处理器模块。定义 FastForwardHandler，管理战斗中的快进开关、舰队锁定、
自动搜索等开关控件，以及地图文件加载和自动搜索设置。"""

import os
import re

from module.base.timer import Timer
from module.base.utils import color_bar_percentage
from module.handler.assets import *
from module.handler.auto_search import AutoSearchHandler
from module.logger import logger
from module.ui.switch import Switch


FLEET_LOCK = Switch('Fleet_Lock', offset=(5, 20))
FLEET_LOCK.add_state('on', check_button=FLEET_LOCKED)
FLEET_LOCK.add_state('off', check_button=FLEET_UNLOCKED)


class SwitchClearMode(Switch):
    """通关模式（Clear Mode）开关。"""

    def get(self, main):
        """获取通关模式开关状态。

        Args:
            main (ModuleBase): 包含设备与截图的上下文对象。

        Returns:
            str: 开关状态（'on'、'off' 或 'unknown'）。
        """
        title = main.appear(CLEAR_MODE_TITLE, offset=(20, 20))
        if not title:
            return 'unknown'
        # 查找标题右侧的复选区域
        CLEAR_MODE_CHECK.load_offset(CLEAR_MODE_TITLE)
        # 青色文字表示开启（on）
        if main.image_color_count(CLEAR_MODE_CHECK.button, color=(130, 229, 255), threshold=30, count=50):
            return 'on'
        # 白色按钮表示关闭（off）
        if main.image_color_count(CLEAR_MODE_CHECK.button, color=(255, 255, 255), threshold=30, count=200):
            return 'off'
        return 'unknown'


CLEAR_MODE = SwitchClearMode('Clear_Mode')
CLEAR_MODE.add_state('on', check_button=CLEAR_MODE_TITLE, click_button=CLEAR_MODE_CHECK)
CLEAR_MODE.add_state('off', check_button=CLEAR_MODE_TITLE, click_button=CLEAR_MODE_CHECK)


class SwitchAutoSearch(Switch):
    """自动搜索（Auto Search）开关。"""

    def get(self, main):
        """获取自动搜索开关状态。

        Args:
            main (ModuleBase): 包含设备与截图的上下文对象。

        Returns:
            str: 开关状态（'on'、'off' 或 'unknown'）。
        """
        title = None
        if main.appear(AUTO_SEARCH_TITLE, offset=(20, 20)):
            title = AUTO_SEARCH_TITLE
        # 日服困难模式和普通模式下的字符间距不同
        if not title:
            if main.appear(AUTO_SEARCH_TITLE2, offset=(20, 20)):
                title = AUTO_SEARCH_TITLE2
        if not title:
            if main.appear(AUTO_SEARCH_TITLE3, offset=(20, 20)):
                title = AUTO_SEARCH_TITLE3
        if not title:
            return 'unknown'
        # 查找标题右侧的复选区域
        AUTO_SEARCH_CHECK.load_offset(title)
        # 绿色方块表示开启（on）
        if main.image_color_count(AUTO_SEARCH_CHECK.button, color=(158, 234, 94), threshold=30, count=50):
            return 'on'
        # 无法直接检测 off，若标题出现且不是 on 则返回 off
        return 'off'


AUTO_SEARCH = SwitchAutoSearch('Auto_Search')
AUTO_SEARCH.add_state('on', check_button=AUTO_SEARCH_TITLE, click_button=AUTO_SEARCH_CHECK)
AUTO_SEARCH.add_state('off', check_button=AUTO_SEARCH_TITLE, click_button=AUTO_SEARCH_CHECK)


def map_files(event):
    """获取指定活动目录下的地图文件列表。

    Args:
        event (str): './campaign' 下的活动名称。

    Returns:
        list[str]: 地图文件名列表，如 ['sp1', 'sp2', 'sp3']。
    """
    folder = f'./campaign/{event}'

    if not os.path.exists(folder):
        logger.warning(f'地图文件夹: {folder} 不存在，无法获取地图文件')
        return []

    files = []
    for file in os.listdir(folder):
        name, ext = os.path.splitext(file)
        if ext != '.py':
            continue
        if name == 'campaign_base':
            continue
        files.append(name)
    return files


def to_map_input_name(name: str) -> str:
    """将地图名称转换为用户输入格式。

    例如：7-2 -> 7-2，campaign_7_2 -> 7-2，d3 -> D3。

    Args:
        name (str): 原始地图名称。

    Returns:
        str: 规范化后的用户输入格式地图名称。
    """
    # 移除空白字符
    name = re.sub('[ \t\n]', '', name).lower()
    # B-1 -> B1
    res = re.match(r'([a-zA-Z]+)[- ]+(\d+)', name)
    if res:
        name = f'{res.group(1)}{res.group(2)}'
    # 转为大写以便移除 campaign 前缀
    name = str(name).upper()
    # campaign_7_2 -> 7-2
    name = name.replace('CAMPAIGN_', '').replace('_', '-')
    return name


def to_map_file_name(name: str) -> str:
    """将地图名称转换为地图文件名格式。

    例如：7-2 -> campaign_7_2，campaign_7_2 -> campaign_7_2，D3 -> d3。

    Args:
        name (str): 原始地图名称。

    Returns:
        str: 规范化后的地图文件名格式。
    """
    name = str(name).lower()
    # 移除空白字符
    name = re.sub('[ \t\n]', '', name).lower()
    # B-1 -> B1
    res = re.match(r'([a-zA-Z]+)[- ]+(\d+)', name)
    if res:
        name = f'{res.group(1)}{res.group(2)}'
    # 7-2 -> campaign_7_2
    if name and name[0].isdigit():
        name = 'campaign_' + name.replace('-', '_')
    return name


class FastForwardHandler(AutoSearchHandler):
    """快进与通关模式处理器。

    管理战斗中的快进开关、通关模式、舰队锁定、自动搜索选项及二倍经验书等设置。

    Attributes:
        map_clear_percentage (float): 地图通关进度百分比（0.0 ~ 1.0）。
        map_achieved_star_1 (bool): 地图是否达成 1 星。
        map_achieved_star_2 (bool): 地图是否达成 2 星。
        map_achieved_star_3 (bool): 地图是否达成 3 星。
        map_is_100_percent_clear (bool): 地图是否达到 100% 通关。
        map_is_3_stars (bool): 地图是否达成 3 星。
        map_is_threat_safe (bool): 地图威胁等级是否已降为安全（绿海）。
        map_has_clear_mode (bool): 地图是否具备通关模式。
        map_is_clear_mode (bool): 当前是否处于通关模式。
        map_is_auto_search (bool): 当前是否启用自动搜索。
        map_is_2x_book (bool): 当前是否使用二倍经验书。
    """
    map_clear_percentage = 0.
    map_achieved_star_1 = False
    map_achieved_star_2 = False
    map_achieved_star_3 = False
    map_is_100_percent_clear = False
    map_is_3_stars = False
    map_is_threat_safe = False
    map_has_clear_mode = False
    map_is_clear_mode = False  # 通关模式 == 快进
    map_is_auto_search = False
    map_is_2x_book = False

    STAGE_INCREASE = [
        """
        1-1 > 1-2 > 1-3 > 1-4
        > 2-1 > 2-2 > 2-3 > 2-4
        > 3-1 > 3-2 > 3-3 > 3-4
        > 4-1 > 4-2 > 4-3 > 4-4
        > 5-1 > 5-2 > 5-3 > 5-4
        > 6-1 > 6-2 > 6-3 > 6-4
        > 7-1 > 7-2 > 7-3 > 7-4
        > 8-1 > 8-2 > 8-3 > 8-4
        > 9-1 > 9-2 > 9-3 > 9-4
        > 10-1 > 10-2 > 10-3 > 10-4
        > 11-1 > 11-2 > 11-3 > 11-4
        > 12-1 > 12-2 > 12-3 > 12-4
        > 13-1 > 13-2 > 13-3 > 13-4
        > 14-1 > 14-2 > 14-3 > 14-4
        > 15-1 > 15-2 > 15-3 > 15-4
        > 16-1 > 16-2 > 16-3 > 16-4
        """,
        'A1 > A2 > A3',
        'B1 > B2 > B3',
        'C1 > C2 > C3',
        'D1 > D2 > D3',
        'SP1 > SP2 > SP3 > SP4 > SP5',
        'T1 > T2 > T3 > T4 > T5 > T6',
        'HT1 > HT2 > HT3 > HT4 > HT5 > HT6',
    ]
    map_fleet_checked = False

    def map_get_info(self, star=False):
        """获取地图通关、星级与安全状态信息并记录日志。

        Args:
            star (bool): 是否假定已获得星级（用于强制覆盖）。默认为 False。
        """
        self.map_clear_percentage = self.get_map_clear_percentage()
        self.map_achieved_star_1 = self._is_map_star_active(MAP_STAR_1) or star
        self.map_achieved_star_2 = self._is_map_star_active(MAP_STAR_2) or star
        self.map_achieved_star_3 = self._is_map_star_active(MAP_STAR_3) or star
        self.map_is_100_percent_clear = self.map_clear_percentage > 0.95
        self.map_is_3_stars = self.map_achieved_star_1 and self.map_achieved_star_2 and self.map_achieved_star_3
        self.map_is_threat_safe = self.appear(MAP_GREEN, offset=(20, 20))
        if self.config.Campaign_Name.lower() == 'sp':
            # 此处存在小问题
            # SP 关卡无法检测通关模式，因此使用 auto_search 选项代替
            # 如果用户手动关闭了自动搜索，alas 无法重新开启
            self.map_has_clear_mode = AUTO_SEARCH.appear(main=self)
        else:
            self.map_has_clear_mode = self.map_is_100_percent_clear and CLEAR_MODE.appear(main=self)

        # 覆盖配置
        if self.map_achieved_star_1:
            # Boss 出现前的剧情，对应 chapter_template.lua 中的 "story_refresh_boss" 属性
            self.config.MAP_HAS_MAP_STORY = False
        self.config.MAP_CLEAR_ALL_THIS_TIME = self.config.STAR_REQUIRE_3 \
            and (self.config.StopCondition_MapAchievement == 'non_stop_clear_all' \
            or (not self.__getattribute__(f'map_achieved_star_{self.config.STAR_REQUIRE_3}') \
            and (self.config.StopCondition_MapAchievement in ['map_3_stars', 'threat_safe'])))

        self.map_show_info()

    def map_show_info(self):
        """打印当前地图状态与成就条件日志。"""
        # 记录日志
        logger.attr('本次全图清除', self.config.MAP_CLEAR_ALL_THIS_TIME)
        names = ['map_achieved_star_1', 'map_achieved_star_2', 'map_achieved_star_3',
                 'map_is_100_percent_clear', 'map_is_3_stars',
                 'map_is_threat_safe', 'map_has_clear_mode']
        strip = ['map', 'achieved', 'is', 'has']
        log_names = ['_'.join([x for x in name.split('_') if x not in strip]) for name in names]
        text = ', '.join([l for l, n in zip(log_names, names) if self.__getattribute__(n)])
        text = f'{int(self.map_clear_percentage * 100)}%, ' + text
        logger.attr('地图信息', text)
        logger.attr('地图成就条件', self.config.StopCondition_MapAchievement)

    def handle_fast_forward(self):
        """处理快进与通关模式开关。

        Returns:
            bool: 开关状态是否发生了改变。
        """
        if not self.map_has_clear_mode:
            self.map_is_clear_mode = False
            self.map_is_auto_search = False
            self.map_is_2x_book = False
            return False

        if self.config.Campaign_UseClearMode:
            self.config.MAP_HAS_AMBUSH = False
            self.config.MAP_HAS_FLEET_STEP = False
            self.config.MAP_HAS_MOVABLE_ENEMY = False
            self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY = False
            self.config.MAP_HAS_PORTAL = False
            self.config.MAP_HAS_LAND_BASED = False
            self.config.MAP_HAS_MAZE = False
            self.config.MAP_HAS_FORTRESS = False
            self.config.MAP_HAS_BOUNCING_ENEMY = False
            self.config.MAP_HAS_DECOY_ENEMY = False
            self.map_is_clear_mode = True
            if self.config.MAP_CLEAR_ALL_THIS_TIME:
                logger.info('本次全图清除不兼容自动搜索，临时禁用')
                self.map_is_auto_search = False
            else:
                self.map_is_auto_search = self.config.Campaign_UseAutoSearch
            self.map_is_2x_book = self.config.Campaign_Use2xBook
        else:
            # 关闭快进时，MAP_HAS_AMBUSH 取决于地图设置
            # self.config.MAP_HAS_AMBUSH = True
            self.map_is_clear_mode = False
            self.map_is_auto_search = False
            self.map_is_2x_book = False
            pass

        state = 'on' if self.config.Campaign_UseClearMode else 'off'
        changed = CLEAR_MODE.set(state, main=self)
        if changed:
            self.map_wait_auto_search()
        return changed

    def _is_map_star_active(self, button):
        """检测指定星级按钮是否已激活（已点亮）。

        Args:
            button (Button): 星级图标按钮。

        Returns:
            bool: 该星级是否已点亮。
        """
        return self.image_color_count(button, color=(250, 232, 140), threshold=75, count=35)

    def handle_map_fleet_lock(self, enable=None):
        """处理舰队锁定开关。

        Args:
            enable (bool | None): 是否启用舰队锁定，默认为 None 时使用 Campaign_UseFleetLock 配置。

        Returns:
            bool: 是否进行了切换操作。
        """
        # 舰队锁定取决于地图上是否显示该选项，而非地图状态
        # 因为如果已在地图中，则没有地图状态
        if not FLEET_LOCK.appear(main=self):
            logger.info('无舰队锁定选项')
            return False

        if enable is None:
            enable = self.config.Campaign_UseFleetLock
        state = 'on' if enable else 'off'
        changed = FLEET_LOCK.set(state, main=self)

        return changed

    def map_wait_auto_search(self):
        """开启通关模式后等待自动搜索开关动画完全显示。

        Returns:
            bool: 是否等待成功。
        """
        timeout = Timer(1, count=3).start()
        for _ in self.loop():
            state = AUTO_SEARCH.get(main=self)
            logger.attr('自动搜索', state)
            if state != 'unknown':
                return True
            if timeout.reached():
                # 部分地图有通关模式但没有自动搜索
                logger.info('等待自动搜索超时')
                return False

    def handle_auto_search(self):
        """处理自动搜索开关。

        Pages:
            in: MAP_PREPARATION

        Returns:
            bool: 是否进行了切换操作。
        """
        # if not self.map_is_clear_mode:
        #     return False

        current = AUTO_SEARCH.get(main=self)
        logger.attr('自动搜索', current)
        if current == 'unknown':
            logger.info('无自动搜索选项')
            return False

        if self.config.Campaign_UseAutoSearch and not self.map_is_auto_search:
            logger.warning('自动搜索已启用但清除模式未确认，保持启用')
            self.map_is_auto_search = True

        state = 'on' if self.map_is_auto_search else 'off'
        changed = self._auto_search_set(state, current=current)

        return changed

    def _auto_search_set(self, state, current='unknown', skip_first_screenshot=True):
        """仅在当前状态已知时设置自动搜索开关。

        AUTO_SEARCH_ON 和 AUTO_SEARCH_OFF 共享同一点击区域。
        如果开关已开启但模板匹配暂时返回 unknown，
        点击目标 ON 区域实际上会将其关闭。

        Args:
            state (str): 目标状态（'on' 或 'off'）。
            current (str): 当前已知状态，默认为 'unknown'。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 开关状态是否发生了更改。
        """
        logger.info(f'[处理器-快进] 自动搜索设置为 {state}')
        timeout = Timer(2, count=4).start()
        click_timer = Timer(1, count=2).clear()
        changed = False

        while 1:
            if current == 'unknown':
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()
                current = AUTO_SEARCH.get(main=self)

            logger.attr('自动搜索', current)

            if current == state:
                return changed

            if current == 'unknown':
                if timeout.reached():
                    logger.warning('自动搜索开关状态未知，保持当前')
                    return changed
                continue
            else:
                timeout.reset()

            if click_timer.reached():
                AUTO_SEARCH.click(current, main=self)
                changed = True
                click_timer.reset()

            self.device.screenshot()
            current = AUTO_SEARCH.get(main=self)

    def handle_auto_search_setting(self):
        """处理编队准备界面的自动搜索设置。

        Pages:
            in: FLEET_PREPARATION

        Returns:
            bool: 是否进行了更改。

        Raises:
            AutoSearchSetError: 设置自动搜索失败且无法通知时抛出。
        """
        if not self.map_is_auto_search:
            # 手动寻敌下舰队编制选项不可用，但潜艇待命仍需同步：
            # 游戏内潜艇“自动召唤”若未关闭，每场战斗都会自动召唤潜艇，浪费油耗与潜艇弹药（#144）
            if self.map_is_clear_mode and self.config.Submarine_Fleet \
                    and self.config.Submarine_AutoSearchMode == 'sub_standby':
                logger.info('自动搜索设置（手动寻敌，仅确保潜艇待命）')
                if self.fleet_preparation_sidebar_ensure(3):
                    self.auto_search_setting_ensure('sub_standby')
                    return True
            return False

        logger.info('自动搜索设置')
        self.fleet_preparation_sidebar_ensure(3)
        if not self.auto_search_setting_ensure(self.config.Fleet_FleetOrder) \
                and self.config.task.command == 'GemsFarming':
            from module.notify import handle_notify
            if not handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config.config_name}> crashed",
                content=f"<{self.config.config_name}> RequestHumanTakeover\n"
                        f"Task GemsFarming could not set auto search settings",
                                    ):
                from module.exception import AutoSearchSetError
                raise AutoSearchSetError
            self.config.cross_set(keys='GemsFarming.Scheduler.Enable', value=False)
            logger.critical('[Handler] 无法确保自动搜索设置。')
            logger.critical('[Handler] 关闭任务：GemsFarming')
            self.config.task_stop('无法确保自动搜索设置。')
        if self.config.SUBMARINE:
            self.auto_search_setting_ensure(self.config.Submarine_AutoSearchMode)
        return True

    @property
    def is_call_submarine_at_boss(self):
        """是否在 Boss 战时呼叫潜艇。"""
        return self.config.SUBMARINE and self.config.Submarine_Mode in ['boss_only', 'hunt_and_boss']

    def handle_auto_submarine_call_disable(self):
        """禁用自动潜艇呼叫。

        Pages:
            in: FLEET_PREPARATION

        Returns:
            bool: 是否进行了更改。
        """
        if self.map_fleet_checked:
            return False
        advanced = (self.config.SUBMARINE and self.config.Submarine_Mode == 'advanced'
                    and not self.map_is_auto_search)
        if not (self.is_call_submarine_at_boss or advanced):
            return False
        # 2025.09.22 修正：舰队角色设置在通关模式后才解锁
        if not self.map_is_clear_mode:
            logger.warning('[处理器-快进] 无法设置潜艇呼叫，自动搜索不可用')
            logger.warning('[处理器-快进] 请执行以下操作：'
                           '前往任意关卡 -> 自动搜索角色 -> 设置潜艇角色为待命')
            logger.warning('[处理器-快进] 如果已设置，请忽略此警告')
            return False

        logger.info('禁用自动潜艇呼叫')
        self.fleet_preparation_sidebar_ensure(3)
        self.auto_search_setting_ensure('sub_standby')
        return True

    def handle_auto_search_continue(self, drop=None):
        """处理自动搜索继续菜单及二倍经验书设置。

        覆盖 AutoSearchHandler 的实现，用于处理二倍经验书设置。

        Args:
            drop (DropImage | None): 掉落记录对象。

        Returns:
            bool: 是否执行了继续操作。
        """
        if self.appear(AUTO_SEARCH_MENU_CONTINUE, offset=self._auto_search_menu_offset, interval=2):
            self.map_is_2x_book = self.config.Campaign_Use2xBook
            self.handle_2x_book_setting(mode='auto')
            if drop:
                drop.handle_add(main=self, before=4)
            if self.appear_then_click(AUTO_SEARCH_MENU_CONTINUE, offset=self._auto_search_menu_offset):
                self.interval_reset(AUTO_SEARCH_MENU_CONTINUE)
            else:
                # handle_2x_book_setting() 之后 AUTO_SEARCH_MENU_CONTINUE 可能已消失
                pass
            return True
        return False

    def get_map_clear_percentage(self):
        """获取地图通关进度百分比。

        Pages:
            in: MAP_PREPARATION

        Returns:
            float: 0 到 1 之间的浮点数。
        """
        percent = color_bar_percentage(self.device.image, area=MAP_CLEAR_PERCENTAGE.area, prev_color=(231, 170, 82))
        if self.config.MAP_CLEAR_PERCENTAGE_SHORT:
            percent *= 1.4
        return percent

    def campaign_name_increase(self, name):
        """将关卡名称推进到下一关。

        Args:
            name (str): 关卡名称，如 `6-1`、`a1`、`campaign_6_1`。

        Returns:
            str: 下一关的大写名称，无法推进时返回原名称。
        """
        # 复制 STAGE_INCREASE 以避免潜在的重复插入
        stage_increase = [r for r in self.STAGE_INCREASE]
        # 插入自定义推进逻辑
        if self.config.STAGE_INCREASE_AB:
            stage_increase = [
                'A1 > A2 > A3 > B1 > B2 > B3',                
            ] + stage_increase
        custom = self.config.STAGE_INCREASE_CUSTOM
        if custom:
            if isinstance(custom, str):
                custom = [custom]
            stage_increase = custom + stage_increase

        # 推进关卡
        name = to_map_input_name(name)
        for increase in stage_increase:
            increase = [i.strip(' \t\r\n') for i in increase.split('>')]
            if name in increase:
                index = increase.index(name) + 1
                if index < len(increase):
                    new = increase[index]
                    # 主线关卡不做检查，假设全部存在
                    # 主线关卡文件名为 campaign_7_2，但用户输入 7-2
                    if self.config.Campaign_Event == 'campaign_main':
                        return new
                    # 检查地图文件是否存在
                    existing = map_files(self.config.Campaign_Event)
                    logger.info(f'现有文件: {existing}')
                    if new.lower() in existing:
                        return new
                    else:
                        logger.info(f'关卡递增到达终点，新地图 {new} 不存在')
                        return name
                else:
                    logger.info('关卡递增到达终点')
                    return name

        return name

    def triggered_map_stop(self):
        """判断是否触发了地图停止条件。

        Returns:
            bool: 是否满足停止条件。
        """

        if self.config.StopCondition_MapAchievement == '100_percent_clear':
            if self.map_is_100_percent_clear:
                return True

        if self.config.StopCondition_MapAchievement == 'map_3_stars':
            if self.map_is_100_percent_clear and self.map_is_3_stars:
                return True

        if self.config.StopCondition_MapAchievement == 'threat_safe_without_3_stars':
            if self.map_is_100_percent_clear and self.map_is_threat_safe:
                return True

        if self.config.StopCondition_MapAchievement == 'threat_safe':
            if self.map_is_100_percent_clear and self.map_is_3_stars and self.map_is_threat_safe:
                return True

        return False

    def handle_map_stop(self):
        """达到停止条件后修改配置，禁用当前任务或推进关卡。"""
        if self.config.StopCondition_StageIncrease:
            prev_stage = to_map_input_name(self.config.Campaign_Name)
            next_stage = self.campaign_name_increase(prev_stage)
            if next_stage != prev_stage:
                logger.info(f'[处理器-快进] 关卡 {prev_stage} 推进到 {next_stage}')
                self.config.Campaign_Name = next_stage
            else:
                logger.info(f'[处理器-快进] 关卡 {prev_stage} 无法推进，停在当前关卡')
                self.config.Scheduler_Enable = False
        else:
            self.config.Scheduler_Enable = False

    def _set_2x_book_status(self, status, check_button, box_button, skip_first_screenshot=True):
        """设置二倍经验书的开关状态，内置重试机制，最多尝试 3 次，每次间隔 3 秒。

        Args:
            status (str): 'on' 或 'off'。
            check_button (Button): 点击前用于检查的按钮。
            box_button (Button): 用于点击和颜色计数的按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: True 表示检测到已正确设置。
                  False 可能由两个原因导致：资源图像不足以正确检测，
                  或二倍经验书设置不存在。
        """
        confirm_timer = Timer(0.3, count=1).start()
        clicked_threshold = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if clicked_threshold > 3:
                break

            if self.appear(check_button, offset=self._auto_search_menu_offset, interval=3):
                box_button.load_offset(check_button)
                enabled = self.image_color_count(box_button.button, color=(156, 255, 82), threshold=30, count=20)
                if (status == 'on' and enabled) or (status == 'off' and not enabled):
                    return True
                if (status == 'on' and not enabled) or (status == 'off' and enabled):
                    self.device.click(box_button)

                clicked_threshold += 1

            if not clicked_threshold and confirm_timer.reached():
                logger.info('地图无2倍经验书设置')
                return False

        logger.warning(f'等待时间已过，无法设置2倍经验书')
        return False

    def handle_2x_book_setting(self, mode='prep'):
        """处理二倍经验书设置（如适用）。

        Args:
            mode (str): 'prep' 或 'auto'，非 'prep' 则视为 'auto'。

        Returns:
            bool: 是否处理完成。
        """
        if not self.map_is_clear_mode:
            return False
        if not hasattr(self, 'emotion'):
            logger.info('情绪实例未加载，无法处理2倍经验书')
            return False

        logger.info(f'[处理器-快进] 处理2倍经验书设置，模式={mode}')
        if mode == 'prep':
            book_check = BOOK_CHECK_PREP
            book_box = BOOK_BOX_PREP
        else:
            book_check = BOOK_CHECK_AUTO
            book_box = BOOK_BOX_AUTO

        state = 'on' if self.map_is_2x_book else 'off'
        if self._set_2x_book_status(state, book_check, book_box):
            self.emotion.map_is_2x_book = self.map_is_2x_book
        else:
            self.map_is_2x_book = False
            self.emotion.map_is_2x_book = self.map_is_2x_book

        self.handle_info_bar()
        return True

    def handle_2x_book_popup(self):
        """处理二倍经验书使用确认弹窗。

        Returns:
            bool: 是否处理了弹窗。
        """
        if self.appear(BOOK_POPUP_CHECK, offset=(20, 20)):
            if self.handle_popup_confirm('2X_BOOK'):
                return True

        return False

    def handle_submarine_support_popup(self):
        """处理潜艇支援弹窗，应在第16章潜艇基类中重写。

        Returns:
            bool: 是否处理了弹窗。
        """
        return False

    def handle_map_walk_speedup(self, skip_first_screenshot=True):
        """开启地图行走加速，没有关闭的理由。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否成功开启地图行走加速。
        """
        if not self.config.MAP_HAS_WALK_SPEEDUP:
            return False

        timeout = Timer(2, count=4).start()
        interval = Timer(1, count=2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.image_color_count(MAP_WALK_SPEEDUP, color=(132, 255, 148), threshold=75, count=50):
                logger.attr('行走加速', '开启')
                return True
            if timeout.reached():
                logger.warning(f'等待时间已过，无法设置地图行走加速')
                return False

            if interval.reached():
                self.device.click(MAP_WALK_SPEEDUP)
                interval.reset()
                continue

    def handle_submarine_cost_popup(self):
        """处理潜艇消耗弹窗。

        Returns:
            bool: 是否处理了弹窗。
        """
        if self.config.MAP_HAS_SUBMARINE_SUPPORT and self.handle_popup_confirm('SUBMARINE_COST'):
            return True

        return False
