from datetime import timedelta

from module.base.timer import Timer
from module.base.utils import *
from module.config.utils import DEFAULT_TIME, get_os_next_reset
from module.logger import logger
from module.map_detection.utils import fit_points
from module.os.assets import GLOBE_GOTO_MAP
from module.os.globe_detection import GLOBE_MAP_SHAPE
from module.os.globe_operation import GlobeOperation
from module.os.globe_zone import Zone, ZoneManager
from module.os_handler.assets import *


class MissionAtCurrentZone(Exception):
    """当前海域有任务异常。"""
    pass


class MissionHandler(GlobeOperation, ZoneManager):
    _os_mission_submitted = False

    def _os_find_checkout_offset_skip_monthly_boss(self, checkout_offset):
        """
        查找非月度 Boss 的任务结算行。

        Args:
            checkout_offset (tuple): 初始结算按钮偏移量。

        Returns:
            tuple | None: 非月度 Boss 任务行的偏移量，如果未找到则返回 None。
        """
        row_offset = checkout_offset
        # 任务行垂直排列，间隔约 110 像素
        # 扫描多行以处理月度 Boss 不在第一行的情况
        for _ in range(8):
            has_checkout = self.match_template_color(MISSION_CHECKOUT, offset=row_offset, similarity=0.78)
            if has_checkout and not self.appear(MISSION_MONTHLY_BOSS, offset=row_offset):
                return row_offset
            row_offset = area_offset(row_offset, (0, 110))

        return None

    def get_mission_zone(self):
        """
        获取任务所在的海域。

        Returns:
            Zone: 任务海域对象。
        """
        area = (341, 72, 1217, 648)
        # 黄色 `!` 的点
        image = color_similarity_2d(self.image_crop(area, copy=False), color=(255, 207, 66))
        points = np.array(np.where(image > 235)).T[:, ::-1]
        if not len(points):
            logger.warning('Unable to find mission on OS mission map')

        point = fit_points(points, mod=(1000, 1000), encourage=5) + (0, 11)
        # 海域位置
        # (2570, 1694) 是 os_globe_map.png 的形状
        point *= np.array(GLOBE_MAP_SHAPE) / np.subtract(area[2:], area[:2])

        zone = self.camera_to_zone(tuple(point))
        return zone

    def is_in_os_mission(self):
        return self.appear(MISSION_CHECK, offset=(20, 20))

    def os_mission_enter(self, skip_siren_mission=False, skip_first_screenshot=True):
        """
        进入任务列表并领取任务奖励。

        Args:
            skip_siren_mission (bool): 是否跳过塞壬研究任务。
            skip_first_screenshot (bool): 是否跳过第一次截图。

        Returns:
            tuple: MISSION_CHECKOUT 的按钮偏移量。

        Pages:
            in: MISSION_ENTER
            out: MISSION_CHECK
        """
        logger.info('OS mission enter')
        checkout_offset = (-20, -20, 20, 20)
        confirm_timer = Timer(2, count=6).start()
        for _ in self.loop():
            # 结束
            if self.is_in_os_mission() \
                    and not self.appear(MISSION_FINISH, offset=checkout_offset) \
                    and not self.match_template_color(MISSION_CHECKOUT, offset=checkout_offset, similarity=0.78):
                # 未找到任务，等待确认。任务可能加载较慢。
                if confirm_timer.reached():
                    logger.info('No OS mission found.')
                    break
            elif self.is_in_os_mission() \
                    and self.match_template_color(MISSION_CHECKOUT, offset=checkout_offset, similarity=0.78):
                # 找到至少一个任务
                logger.info('Found at least one OS missions.')
                break
            else:
                confirm_timer.reset()

            # 点击
            if self.appear_then_click(MISSION_ENTER, offset=(200, 5), interval=5):
                confirm_timer.reset()
                continue
            if skip_siren_mission and self.appear(MISSION_SIREN_RESEARCH, offset=checkout_offset):
                if self.appear(MISSION_FINISH, offset=checkout_offset):
                    # 两个任务行之间大约 110 像素
                    checkout_offset = area_offset(checkout_offset, (0, 110))
                    confirm_timer.reset()
                    continue
            else:
                if self.appear_then_click(MISSION_FINISH, offset=checkout_offset, interval=2):
                    confirm_timer.reset()
                    continue
                if self.handle_popup_confirm('MISSION_FINISH'):
                    confirm_timer.reset()
                    continue
                if self.handle_map_get_items():
                    confirm_timer.reset()
                    continue
                if self.handle_info_bar():
                    confirm_timer.reset()
                    continue

            if self.appear_then_click(GLOBE_GOTO_MAP, offset=(20, 20), interval=2):
                # 意外进入地球仪
                confirm_timer.reset()
                continue
        return checkout_offset

    def os_mission_quit(self):
        """
        退出任务列表。
        """
        logger.info('OS mission quit')
        for _ in self.loop():
            # 结束
            # 有时任务弹窗没有黑色模糊背景
            # MISSION_QUIT 和 is_in_map 同时出现
            if not self.appear(MISSION_QUIT, offset=(20, 20)):
                if self.is_in_map():
                    break
            # 点击
            if self.appear_then_click(MISSION_QUIT, offset=(20, 20), interval=3):
                continue

    def os_get_next_mission(self, skip_siren_mission=False):
        """
        获取下一个大世界任务。

        点击 MISSION_CHECKOUT 后，AL 会直接切换到目标海域，而非显示无意义的地图。
        如果已在目标海域，则显示信息栏并关闭任务列表。

        Args:
            skip_siren_mission (bool): 是否跳过塞壬研究任务。

        Returns:
            str: pinned_at_mission_zone、already_at_mission_zone、pinned_at_archive_zone，
                如果没有更多任务则返回 False。
        """
        checkout_offset = self.os_mission_enter(skip_siren_mission=skip_siren_mission)
        checkout_offset = self._os_find_checkout_offset_skip_monthly_boss(checkout_offset)
        if checkout_offset is None:
            logger.info('No more non-monthly-boss OS missions')
            self.os_mission_quit()
            return False

        if self.is_in_opsi_explore():
            logger.info('OpsiExplore is under scheduling, accept missions and receive rewards only')
            self.os_mission_quit()
            return False

        logger.info('Checkout os mission')
        for _ in self.loop():
            # 结束
            if self.is_zone_pinned():
                if self.get_zone_pinned_name() == 'ARCHIVE':
                    logger.info('Pinned at archive zone')
                    self.globe_enter(zone=self.name_to_zone(72))
                    return 'pinned_at_archive_zone'
                else:
                    logger.info('Pinned at mission zone')
                    self.globe_enter(zone=self.name_to_zone(72))
                    return 'pinned_at_mission_zone'
            if self.is_in_map() and self.info_bar_count():
                logger.info('Already at mission zone')
                return 'already_at_mission_zone'

            if self.appear_then_click(MISSION_CHECKOUT, offset=checkout_offset, interval=2, similarity=0.78):
                continue
            if self.handle_popup_confirm('OS_MISSION_CHECKOUT'):
                # 弹窗：退出当前海域后潜艇将撤退
                continue

    def os_mission_overview_accept(self, skip_siren_mission=False, skip_first_screenshot=True):
        """
        在任务总览中接受所有任务。

        Args:
            skip_siren_mission (bool): 是否跳过塞壬研究任务。
            skip_first_screenshot (bool): 是否跳过第一次截图。

        Returns:
            bool: 所有任务已接受或未找到任务时返回 True，无法接受更多任务时返回 False。

        Pages:
            in: is_in_map
            out: is_in_map
        """
        logger.hr('OS mission overview accept', level=1)
        # is_in_map
        self.os_map_goto_globe(unpin=False)
        # is_in_globe
        self.ui_click(MISSION_OVERVIEW_ENTER, check_button=MISSION_OVERVIEW_CHECK,
                      offset=(200, 20), retry_wait=3, additional=self.handle_manjuu,
                      skip_first_screenshot=True)

        timeout = 5
        accept_button_timer = Timer(timeout)
        self.interval_timer[MISSION_OVERVIEW_ACCEPT_SINGLE.name] = accept_button_timer
        self.interval_timer[MISSION_OVERVIEW_ACCEPT.name] = accept_button_timer
        # MISSION_OVERVIEW_CHECK
        success = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束
            if self.handle_manjuu():
                continue
            if self.info_bar_count():
                if skip_siren_mission:
                    logger.info('Unable to accept missions, '
                                'because there are multiple Siren Research missions with the same name')
                    success = True
                else:
                    logger.info('Unable to accept missions, because reached the maximum number of missions')
                    success = False
                break
            if self.appear(MISSION_OVERVIEW_EMPTY, offset=(20, 20)):
                logger.info('No more missions to accept')
                success = True
                break

            if self.appear_then_click(MISSION_OVERVIEW_ACCEPT, offset=(20, 20), interval=2):
                self.interval_reset(MISSION_OVERVIEW_ACCEPT_SINGLE)
                continue
            if self.appear_then_click(MISSION_OVERVIEW_ACCEPT_SINGLE, offset=(20, 20), interval=2):
                self.interval_reset(MISSION_OVERVIEW_ACCEPT)
                continue

        # is_in_globe
        self.ui_back(appear_button=MISSION_OVERVIEW_CHECK, check_button=self.is_in_globe,
                     skip_first_screenshot=True)
        # is_in_map
        self.os_globe_goto_map()
        return success

    def is_in_opsi_explore(self):
        """
        判断任务 OpsiExplore 是否正在调度中。

        Returns:
            bool: OpsiExplore 是否正在调度中。
        """
        enable = self.config.is_task_enabled('OpsiExplore')
        next_run = self.config.cross_get(keys='OpsiExplore.Scheduler.NextRun', default=DEFAULT_TIME)
        next_reset = get_os_next_reset()
        logger.attr('OpsiNextReset', next_reset)
        logger.attr('OpsiExplore', (enable, next_run))
        # -12 小时以处理夏令时
        # `next_run` 可能在夏令时之前计算，但现在是夏令时
        # 2023-03-14 11:15:28.423 | INFO | [OpsiNextReset] 2023-04-01 03:00:00
        # 2023-03-14 11:15:28.425 | INFO | [OpsiExplore] (True, datetime.datetime(2023, 4, 1, 2, 0))
        # 2023-03-14 11:15:28.426 | INFO | OpsiExplore is still running, accept missions only...
        if enable and next_run < next_reset - timedelta(hours=12):
            logger.info('OpsiExplore is still running, accept missions only. '
                        'Missions will be finished when OpsiExplore visits every zones, '
                        'no need to worry they are left behind.')
            return True
        else:
            logger.info('Not in OpsiExplore, able to do OpsiDaily')
            return False
