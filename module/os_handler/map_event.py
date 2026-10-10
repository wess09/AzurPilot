"""大世界地图事件处理器。

处理大世界地图探索过程中触发的各类事件，包括战斗奖励弹窗、
故事跳过、舰队锁定开关、余烬信标弹窗、海域清除奖励以及
自动搜索奖励等，是大世界战斗和探索流程的基础事件层。
"""
from typing import Optional

from module.base.timer import Timer
from module.combat.assets import *
from module.exception import CampaignEnd, GameTooManyClickError
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM, STORY_SKIP_3
from module.logger import logger
from module.os.assets import GLOBE_GOTO_MAP
from module.os_handler.assets import *
from module.os_handler.enemy_searching import EnemySearchingHandler
from module.statistics.azurstats import DropImage
from module.ui.assets import BACK_ARROW
from module.ui.switch import Switch


class FleetLockSwitch(Switch):
    """舰队锁定开关。"""

    def handle_additional(self, main):
        """处理切换过程中的附加弹窗。

        Args:
            main: 包含 appear_then_click 方法的主控制器实例。

        Returns:
            bool: 是否处理了附加弹窗。
        """
        # 游戏 bug：上一个已清除海域的 AUTO_SEARCH_REWARD 弹出
        if main.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
            return True
        return False


fleet_lock = FleetLockSwitch('Fleet_Lock', offset=(10, 120))
fleet_lock.add_state('on', check_button=OS_FLEET_LOCKED)
fleet_lock.add_state('off', check_button=OS_FLEET_UNLOCKED)


class MapEventHandler(EnemySearchingHandler):
    """大世界地图事件处理类。"""

    ash_popup_canceled = False

    def handle_map_get_items(self, interval=2, drop=None):
        """处理大世界地图中掉落物品的获取弹窗。

        Args:
            interval (int): 点击间隔秒数。默认 2。
            drop (DropImage, optional): 掉落记录对象。

        Returns:
            bool: 是否检测到并点击关闭了物品弹窗。
        """
        if self.is_in_map():
            return False

        if self.appear(GET_ITEMS_1, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ITEMS_1} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ITEMS_2, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ITEMS_2} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ITEMS_3, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ITEMS_3} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ADAPTABILITY, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_ADAPTABILITY} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_MEOWFFICER_ITEMS_1, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_MEOWFFICER_ITEMS_1} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(GET_MEOWFFICER_ITEMS_2, interval=interval):
            if drop:
                drop.handle_add(main=self, before=2)
            logger.info(f'{GET_MEOWFFICER_ITEMS_2} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True

        return False

    def handle_map_archives(self, drop=None):
        """处理大世界档案文件获取弹窗。

        Args:
            drop (DropImage, optional): 掉落记录对象。

        Returns:
            bool: 是否处理了档案弹窗。
        """
        if self.appear(MAP_ARCHIVES, interval=5):
            if drop:
                drop.add(self.device.image)
            logger.info(f'{MAP_ARCHIVES} -> {CLICK_SAFE_AREA}')
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear_then_click(MAP_WORLD, offset=(20, 20), interval=5):
            return True

        return False

    def handle_os_game_tips(self):
        """处理并关闭大世界首次开启自动搜索时的游戏提示，以及大型作战引导系统（O.A.G.S）。

        Returns:
            bool: 是否点击关闭了提示。
        """
        # 关闭大型作战引导系统（O.A.G.S）或首次开启自动搜索时的游戏提示
        if self.appear_then_click(OS_GAME_TIPS, offset=(20, 20), interval=2):
            logger.info('[大世界处理-事件] 检测到游戏引导/提示界面 (O.A.G.S)，点击退出')
            return True

        return False

    def handle_ash_popup(self):
        """处理余烬坐标收集满时的弹窗，点击取消以避免误入挑战。

        Returns:
            bool: 是否处理了余烬弹窗。
        """
        name = 'ASH'
        # 2021.12.09
        # 余烬弹窗不再显示红色文字，改为检测 "Ashes Coordinates" 文字
        if self.appear(POPUP_CONFIRM, offset=self._popup_offset) \
                and self.appear(POPUP_CANCEL, offset=self._popup_offset, interval=2) \
                and self.appear(ASH_POPUP_CHECK, offset=(20, 20)):
            POPUP_CANCEL.name = POPUP_CANCEL.name + '_' + name
            self.device.click(POPUP_CANCEL)
            POPUP_CANCEL.name = POPUP_CANCEL.name[:-len(name) - 1]
            self.ash_popup_canceled = True
            return True
        else:
            return False

    def handle_leave_os_popup(self):
        """处理「需要暂时离开大型作战么?」弹窗，点击右上角 X 留在大型作战。

        点击过快、点到海域地图外时游戏会弹出该确认框，点击确定会退出大型作战。
        检测到「暂时离开」提示时点击关闭按钮取消，并返回 True 阻止后续弹窗
        处理器把它当成普通确认框点掉。

        Returns:
            bool: 弹窗存在返回 True（已点击或处于点击冷却中）。
        """
        if self.appear(LEAVE_OS_POPUP_CHECK, offset=(20, 20)):
            if self.appear_then_click(LEAVE_OS_POPUP_CLOSE, offset=(20, 20), interval=2):
                logger.info('[大世界处理-事件] 检测到离开大型作战弹窗，点击关闭按钮')
            return True
        return False

    def handle_map_event(self, drop=None):
        """
        处理大世界地图事件。

        Args:
            drop (DropImage): 掉落图像对象。

        Returns:
            str: 已处理的事件名称。
        """
        # 优先处理余烬信标弹窗，避免被 handle_popup_confirm 误点击确认进入 META 界面
        # 余烬弹窗也包含 POPUP_CONFIRM 和 POPUP_CANCEL，若先匹配 DEPART_CONFIRM
        # 会点击确认进入 META 界面，导致 auto search 循环无法识别而卡死
        if self.handle_ash_popup():
            return 'ash_popup'
        # 处理指挥猫搜寻时退出海域的确认弹窗 (issue #100)
        # 这类弹窗会阻止其他操作,必须优先处理
        # handle_popup_confirm 的 name 参数仅用于日志记录,实际识别使用通用的 POPUP_CONFIRM 按钮
        if self.handle_popup_confirm('DEPART_CONFIRM'):
            return 'depart_confirm'
        if self.handle_map_get_items(drop=drop):
            return 'map_get_items'
        if self.handle_os_game_tips():
            return 'os_game_tips'
        if self.handle_map_archives(drop=drop):
            return 'map_archives'
        if self.handle_guild_popup_cancel():
            return 'guild_popup_cancel'
        if self.handle_urgent_commission(drop=drop):
            return 'urgent_commission'
        if self.handle_story_skip(drop=drop):
            return 'story_skip'

        return ''

    _story_timeout = Timer(60)

    def story_skip(self, drop=None):
        """大世界按新截图快速点击右上角跳过，必选项仍优先处理。"""
        click_interval = 0.5
        if self.__dict__.get('_os_story_click_interval') != click_interval:
            # 计时器属于本对象，避免改动其他页面共用的基类计时器。
            self._os_story_click_interval = click_interval
            self._story_option_timer = Timer(click_interval)
            self._story_option_confirm = Timer(0.3).start()
            self._story_option_record = 0
            self._story_confirm = Timer(0.2, count=1).start()
        # 游戏的世界剧情跳过会停在重要选项；仍逐帧先处理选项，不改全局配置。
        return super().story_skip(drop=drop, click_interval=click_interval, prefer_skip=True)

    def handle_story_skip(self, drop=None):
        """处理大世界剧情跳过及卡剧情超时恢复。

        Args:
            drop (DropImage, optional): 掉落记录对象。

        Returns:
            bool: 是否处理了剧情跳过。
        """
        if super().handle_story_skip(drop):
            self._story_timeout.reset()
            return True

        if self.appear(STORY_SKIP_3, offset=(20, 20), interval=0):
            if self._story_timeout.reached():
                logger.warning('[大世界处理-事件] 等待剧情选项超时')
                self._story_timeout.reset()

                # 重启应用
                self.device.app_stop()
                self.device.app_start()

                from module.handler.login import LoginHandler
                LoginHandler(self.config, self.device).handle_app_login()

                from module.ui.page import page_os
                self.ui_ensure(page_os)

                return True

            if not self._story_timeout.started():
                self._story_timeout.start()
        else:
            self._story_timeout.reset()

        return False

    _os_in_map_confirm_timer = Timer(1.5, count=3)

    def handle_os_in_map(self):
        """确认是否已返回大世界地图。

        Returns:
            bool: 是否在地图中并已确认。
        """
        if self.is_in_map():
            if self._os_in_map_confirm_timer.reached():
                return True
            else:
                return False
        else:
            self._os_in_map_confirm_timer.reset()
            return False

    def ensure_no_map_event(self):
        """确保地图上没有未处理的事件，直到稳定回到地图。"""
        self._os_in_map_confirm_timer.reset()

        for _ in self.loop():
            if self.handle_map_event():
                continue
            # 结束
            if self.handle_os_in_map():
                break

    def os_auto_search_quit(self, drop=None):
        """
        退出大世界自动搜索。

        Args:
            drop (DropImage): 掉落图像对象。

        Returns:
            bool: 当前地图是否已清除。
        """
        confirm_timer = Timer(1.2, count=3).start()
        cleared = False
        for _ in self.loop():
            if self.appear(AUTO_SEARCH_REWARD, offset=(50, 50), interval=2):
                if drop:
                    if self.ensure_no_info_bar():
                        cleared = True
                    drop.handle_add(main=self, before=4)
                elif self.info_bar_count():
                    # 不记录掉落时只检查当前截图中的清除提示，直接确认奖励。
                    cleared = True
                self.device.click(AUTO_SEARCH_REWARD)
                self.interval_reset([
                    AUTO_SEARCH_REWARD,
                    AUTO_SEARCH_OS_MAP_OPTION_ON,
                    AUTO_SEARCH_OS_MAP_OPTION_OFF,
                    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                ])
                confirm_timer.reset()
                continue
            if self.handle_map_event():
                confirm_timer.reset()
                continue
            if self.appear_then_click(GLOBE_GOTO_MAP, offset=(20, 20), interval=2):
                # 有时点击 AUTO_SEARCH_REWARD 后会意外进入地球仪地图
                # 因为重复点击或点击到地图外部区域
                confirm_timer.reset()
                continue
            # 不知为何进入了仓库，直接退出
            # 等效于 is_in_storage，但此处无法继承 StorageHandler
            # STORAGE_CHECK 是重复名称，这里是 os_handler/STORAGE_CHECK，不是 handler/STORAGE_CHECK
            if self.appear(STORAGE_CHECK, offset=(20, 20), interval=5):
                logger.info(f'{STORAGE_CHECK} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                confirm_timer.reset()
                continue

            # 结束
            if self.is_in_map():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        return cleared

    _os_auto_search_enable_timeout = 45

    def _os_auto_search_enable_click(self, button):
        """开启自律寻敌的带预算重试点击。

        装置探测演出、剧情收尾期间游戏可能持续数秒不响应该按钮，
        连续重试是有意行为：与剧情选项处理同法，点击后清空共用点击
        记录，避免被「15 次内同一按钮 ≥12 次」的防连点阈值在快刷
        间隔下约 7 秒就判死；改由 _os_auto_search_enable_timeout 秒
        预算兜底，超时仍未生效才按点击无效上报。

        Args:
            button: AUTO_SEARCH_OS_MAP_OPTION_OFF 或 _OFF_DISABLED。
        """
        if '_os_auto_search_enable_timer' not in self.__dict__:
            self._os_auto_search_enable_timer = Timer(self._os_auto_search_enable_timeout)
        if not self._os_auto_search_enable_timer.started():
            self._os_auto_search_enable_timer.start()
        elif self._os_auto_search_enable_timer.reached():
            self._os_auto_search_enable_timer.clear()
            raise GameTooManyClickError(
                f'[大世界-搜索] 自律寻敌连续点击 {self._os_auto_search_enable_timeout} 秒仍未生效')
        self.device.click(button)
        # 连续重试会累积共用点击记录，点击后清空；卡死检测由上方预算兜底
        self.device.click_record_clear()

    def _os_auto_search_enable_budget_clear(self):
        """关闭外观消失或界面被剧情挡住时，清零开启自律的重试预算。"""
        timer = self.__dict__.get('_os_auto_search_enable_timer')
        if timer is not None:
            timer.clear()

    def handle_os_auto_search_map_option(self, drop=None, enable: Optional[bool] = True):
        """
        处理大世界自动搜索地图选项。

        Args:
            drop (DropImage): 掉落图像对象。
            enable (bool): True/False，或 None 表示不操作。

        Returns:
            bool: 是否点击了选项。
        """
        command = getattr(getattr(self.config, 'task', None), 'command', None)
        fast_farming = command in ('OpsiHazard1Leveling', 'OpsiMeowfficerFarming')
        if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120)):
            if self.info_bar_count() >= 2:
                self.device.screenshot_interval_set()
                self.os_auto_search_quit(drop=drop)
                raise CampaignEnd
        if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120)):
            if self.info_bar_count() >= 2:
                self.device.screenshot_interval_set()
                self.os_auto_search_quit(drop=drop)
                raise CampaignEnd
        if self.appear(AUTO_SEARCH_REWARD, offset=(50, 50)):
            self.device.screenshot_interval_set()
            cleared = self.os_auto_search_quit(drop=drop)
            if fast_farming and enable is True \
                    and getattr(self, '_os_auto_search_started', False):
                # 正常刷图奖励表示本次搜索已结束，不再开一次空自律探测。
                # 未确认本轮已开启时，奖励可能是上一海域延迟弹出的，保留原恢复。
                # META、退役等中断仍由 os_auto_search_run 的外层恢复分支处理。
                task_name = '侵蚀1' if command == 'OpsiHazard1Leveling' else '耄耋相接'
                logger.info(f'[大世界-搜索] {task_name}奖励已确认，结束本次搜索')
                raise CampaignEnd
            if cleared:
                # 当前地图没有更多物品
                raise CampaignEnd
            else:
                # 自动搜索已停止但地图未清除
                return True

        if enable is None:
            pass
        elif enable:
            click_interval = 0.5 if fast_farming else 3
            if click_interval < 3:
                # 剧情可能透出地图按钮，先处理剧情；回到地图后才重试开启自律。
                if self.appear(STORY_SKIP_3, offset=(20, 20)):
                    self._os_auto_search_enable_budget_clear()
                    return False
                if not self.is_in_map():
                    self._os_auto_search_enable_budget_clear()
                    return False
            if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF,
                                         offset=(5, 120), interval=click_interval):
                self._os_auto_search_enable_click(AUTO_SEARCH_OS_MAP_OPTION_OFF)
                # 两种关闭外观共用重试间隔，避免按钮变灰后在下一帧重复点击。
                self.get_interval_timer(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                                        interval=click_interval, renew=True).reset()
                return True
            # 游戏客户端有时会 bug，AUTO_SEARCH_OS_MAP_OPTION_OFF 灰显但仍可点击
            if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                                         offset=(5, 120), interval=click_interval):
                self._os_auto_search_enable_click(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED)
                self.get_interval_timer(AUTO_SEARCH_OS_MAP_OPTION_OFF,
                                        interval=click_interval, renew=True).reset()
                return True
            # 关闭外观消失：自律已开启或界面已切换，重试预算清零
            self._os_auto_search_enable_budget_clear()
        else:
            if self.match_template_color(AUTO_SEARCH_OS_MAP_OPTION_ON, offset=(5, 120), interval=3):
                self.device.click(AUTO_SEARCH_OS_MAP_OPTION_ON)
                return True

        return False

    def handle_os_map_fleet_lock(self, enable=None):
        """
        处理大世界地图舰队锁定。

        Args:
            enable (bool): 默认为 None，使用 Campaign_UseFleetLock 配置。

        Returns:
            bool: 是否切换了锁定状态。
        """
        # 舰队锁定取决于是否在地图上显示，而非地图状态
        # 因为如果已在地图中，则没有地图状态
        if not fleet_lock.appear(main=self):
            logger.info('[大世界处理-事件] 未找到舰队锁定选项')
            return False

        if enable is None:
            enable = self.config.Campaign_UseFleetLock
        state = 'on' if enable else 'off'
        changed = fleet_lock.set(state, main=self)

        return changed
