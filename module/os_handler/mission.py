"""大世界任务管理模块。

处理大世界（Operation Siren）的任务系统，包括任务提交、
任务奖励领取、任务结算界面导航以及月度 Boss 任务的特殊处理。
通过 OCR 和图像匹配检测任务状态，自动完成任务流程。
"""
from datetime import datetime, timedelta

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.template import Template
from module.base.utils import *
from module.config.time_source import now as current_time
from module.config.utils import DEFAULT_TIME, get_os_next_reset, get_server_next_update
from module.exception import MapDetectionError
from module.logger import logger
from module.map_detection.utils import fit_points
from module.os.assets import GLOBE_GOTO_MAP
from module.os.globe_detection import GLOBE_MAP_SHAPE
from module.os.globe_operation import GlobeOperation, OSExploreError
from module.os.globe_zone import Zone, ZoneManager
from module.os_handler.assets import *


class MissionAtCurrentZone(Exception):
    """当前海域有任务异常。"""
    pass


class MissionHandler(GlobeOperation, ZoneManager):
    """大世界任务处理器。"""

    _os_mission_submitted = False
    _os_mission_index = 0

    @cached_property
    def _os_mission_checkout_template(self):
        template = Template(MISSION_CHECKOUT.file)
        MISSION_CHECKOUT.ensure_template()
        template.image = MISSION_CHECKOUT.image
        return template

    def _os_mission_checkout_offsets(self):
        """从当前页匹配任务按钮，避免滚动后仍按固定行号点击。"""
        offsets = []
        for button in self._os_mission_checkout_template.match_multi(self.device.image, similarity=0.78):
            x, y, _, bottom = button.area
            if (abs(x - MISSION_CHECKOUT.area[0]) <= 20 and 190 <= y and bottom <= 650
                    and color_similar(button.color, MISSION_CHECKOUT.color, threshold=30)):
                offsets.append(area_offset((-20, -20, 20, 20),
                                           (x - MISSION_CHECKOUT.area[0], y - MISSION_CHECKOUT.area[1])))
        return sorted(offsets, key=lambda offset: offset[1])

    def _os_find_checkout_offset_skip_monthly_boss(self, checkout_offset, skip=0):
        """查找非月度Boss的任务结算行。

        Args:
            checkout_offset (tuple): 初始结算按钮偏移量。
            skip (int): 跳过本轮已延期的未完成委托数量，不计月度 Boss。

        Returns:
            tuple | None: 跳过指定数量的未完成委托和月度 Boss 后，下一任务按钮的偏移。
        """
        if not skip:
            # 没有延期行时保持原有选择逻辑，避免改变其他任务。
            row_offset = checkout_offset
            for _ in range(8):
                has_checkout = self.match_template_color(MISSION_CHECKOUT, offset=row_offset, similarity=0.78)
                if has_checkout and not self.appear(MISSION_MONTHLY_BOSS, offset=row_offset):
                    return row_offset
                row_offset = area_offset(row_offset, (0, 110))
            return None

        # 延期委托仍留在列表中，超过一页时继续查找后面的委托。
        scrolling = None
        stable = Timer(0.3, count=2)
        timeout = Timer(5, count=10)
        scroll_distance = None
        for _ in self.loop():
            if scrolling is not None:
                anchor, anchor_y, previous = scrolling
                image = self.image_crop((600, 170, 1000, 650), copy=False)
                result = cv2.matchTemplate(image, anchor, cv2.TM_CCOEFF_NORMED)
                _, similarity, _, point = cv2.minMaxLoc(result)
                if similarity >= 0.90:
                    distance = anchor_y - (170 + point[1])
                    if scroll_distance is None or abs(distance - scroll_distance) > 2:
                        scroll_distance = distance
                        stable.reset()
                    elif stable.reached():
                        if distance > 2:
                            skip -= sum(MISSION_CHECKOUT.area[1] + offset[1] + 20 - distance < 190
                                        for offset in previous)
                            skip = max(skip, 0)
                            scrolling = None
                            continue
                        if abs(distance) <= 2:
                            # 拖动后任务行稳定停在原位置，已到列表底部。
                            return None
                else:
                    stable.reset()
                if timeout.reached():
                    raise MapDetectionError('无法确认大世界任务列表滚动位置')
                continue

            offsets = self._os_mission_checkout_offsets()
            eligible = [offset for offset in offsets if not self.appear(MISSION_MONTHLY_BOSS, offset=offset)]
            if skip < len(eligible):
                return eligible[skip]
            if not offsets:
                return None
            y = MISSION_CHECKOUT.area[1] + offsets[-1][1] + 20
            anchor_y = max(170, y - 35)
            anchor = self.image_crop((600, anchor_y, 1000, min(650, y + 45)))
            scrolling = (anchor, anchor_y, eligible)
            scroll_distance = None
            stable.reset()
            timeout.reset()
            self.device.drag((820, 550), (820, 330), name='MISSION_SCROLL')

    def _os_deferred_mission_zones(self):
        """延期记录只保存进不了的委托目标海域，到下次日更自动失效。"""
        state = self.config.cross_get('OpsiDaily.OpsiDaily.DeferredMissions')
        if not isinstance(state, dict):
            return set()
        try:
            until = datetime.fromisoformat(state['until'])
        except (KeyError, TypeError, ValueError):
            return set()
        if until.tzinfo is not None:
            return set()
        if current_time() >= until:
            self.config.cross_set('OpsiDaily.OpsiDaily.DeferredMissions', None)
            return set()
        zones = state.get('zones', [])
        return {zone for zone in zones if type(zone) is int} if isinstance(zones, list) else set()

    def _os_defer_mission_zone(self, zone):
        zones = self._os_deferred_mission_zones() | {zone.zone_id}
        until = get_server_next_update(
            self.config.cross_get('OpsiDaily.Scheduler.ServerUpdate', default='00:00'))
        self.config.cross_set('OpsiDaily.OpsiDaily.DeferredMissions',
                              dict(until=until.isoformat(), zones=sorted(zones)))
        logger.warning(f'每日委托目标海域 {zone} 无法进入，仅延期该海域的委托至 {until}，继续其他委托')

    def _os_return_from_unavailable_mission(self):
        self.ensure_no_zone_pinned()
        self.os_globe_goto_map()

    def get_mission_zone(self):
        """获取任务所在的海域。

        Returns:
            Zone: 任务海域对象。
        """
        area = (341, 72, 1217, 648)
        # 黄色 `!` 的点
        image = color_similarity_2d(self.image_crop(area, copy=False), color=(255, 207, 66))
        points = np.array(np.where(image > 235)).T[:, ::-1]
        if not len(points):
            logger.warning('无法在大世界任务地图中找到任务')

        point = fit_points(points, mod=(1000, 1000), encourage=5) + (0, 11)
        # 海域位置
        # (2570, 1694) 是 os_globe_map.png 的形状
        point *= np.array(GLOBE_MAP_SHAPE) / np.subtract(area[2:], area[:2])

        zone = self.camera_to_zone(tuple(point))
        return zone

    def is_in_os_mission(self):
        """判断是否处于大世界任务列表界面。

        Returns:
            bool: 是否在任务列表界面。
        """
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
        logger.info('[大世界处理-任务] 进入大世界任务')
        self._os_mission_submitted = False
        checkout_offset = (-20, -20, 20, 20)
        confirm_timer = Timer(2, count=6).start()
        for _ in self.loop():
            # 结束
            if self.is_in_os_mission() \
                    and not self.appear(MISSION_FINISH, offset=checkout_offset) \
                    and not self.match_template_color(MISSION_CHECKOUT, offset=checkout_offset, similarity=0.78):
                # 未找到任务，等待确认。任务可能加载较慢。
                if confirm_timer.reached():
                    logger.info('[大世界处理-任务] 未找到大世界任务')
                    break
            elif self.is_in_os_mission() \
                    and self.match_template_color(MISSION_CHECKOUT, offset=checkout_offset, similarity=0.78):
                # 找到至少一个任务
                logger.info('[大世界处理-任务] 至少找到一个大世界任务')
                break
            else:
                confirm_timer.reset()

            # 点击
            # 保留海域中断自律并退出战斗后，结算「合计获得奖励」会延迟弹出，
            # 可能到进入任务列表这一步才盖住界面；不处理会一直等不到任务列表
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                confirm_timer.reset()
                continue
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
                    self._os_mission_submitted = True
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
        """退出任务列表。

        Pages:
            in: MISSION_QUIT
            out: is_in_map
        """
        logger.info('[大世界处理-任务] 退出大世界任务')
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

    def os_get_next_mission(self, skip_siren_mission=False, skip_unavailable=False, mission_index=0):
        """
        获取下一个大世界任务。

        点击 MISSION_CHECKOUT 后，AL 会直接切换到目标海域，而非显示无意义的地图。
        如果已在目标海域，则显示信息栏并关闭任务列表。

        Args:
            skip_siren_mission (bool): 是否跳过塞壬研究任务。
            skip_unavailable (bool): 仅每日任务使用，延期进不了海域的委托并继续后续委托。
            mission_index (int): 本轮已经跳过的未完成委托数量。

        Returns:
            str: pinned_at_mission_zone、already_at_mission_zone、pinned_at_archive_zone，
                mission_zone_unavailable 表示仅延期本条委托；没有更多任务则返回 False。
        """
        checkout_offset = self.os_mission_enter(skip_siren_mission=skip_siren_mission)
        skip_unavailable = skip_unavailable and self.config.task.command == 'OpsiDaily'
        self._os_mission_index = 0 if self._os_mission_submitted else mission_index
        if skip_unavailable:
            checkout_offset = self._os_find_checkout_offset_skip_monthly_boss(
                checkout_offset, skip=self._os_mission_index)
        else:
            checkout_offset = self._os_find_checkout_offset_skip_monthly_boss(checkout_offset)
        if checkout_offset is None:
            logger.info('[大世界处理-任务] 没有更多非月度Boss的大世界任务')
            self.os_mission_quit()
            return False

        if self.is_in_opsi_explore():
            logger.info('[大世界处理-任务] 每月开荒正在运行，仅接取任务并领取奖励')
            self.os_mission_quit()
            return False

        logger.info('[大世界处理-任务] 接取大世界任务')
        for _ in self.loop():
            # 结束
            if self.is_zone_pinned():
                if self.get_zone_pinned_name() == 'ARCHIVE':
                    logger.info('[大世界处理-任务] 固定在档案区域')
                    self.globe_enter(zone=self.name_to_zone(72))
                    return 'pinned_at_archive_zone'
                else:
                    logger.info('[大世界处理-任务] 固定在任务区域')
                    if skip_unavailable:
                        # 从当前固定海域定位真实目标，不把历史占位海域 72 当成委托身份。
                        self.globe_update()
                        zone = self.get_globe_pinned_zone()
                        if zone.zone_id in self._os_deferred_mission_zones():
                            logger.info(f'每日委托目标海域 {zone} 仍在延期中，继续其他委托')
                            self._os_return_from_unavailable_mission()
                            return 'mission_zone_unavailable'
                        try:
                            self.globe_enter(zone=zone)
                        except OSExploreError:
                            self._os_defer_mission_zone(zone)
                            self._os_return_from_unavailable_mission()
                            return 'mission_zone_unavailable'
                        return 'pinned_at_mission_zone'
                    self.globe_enter(zone=self.name_to_zone(72))
                    return 'pinned_at_mission_zone'
            if self.is_in_map() and self.info_bar_count():
                logger.info('[大世界处理-任务] 已在任务区域')
                return 'already_at_mission_zone'

            # 保留海域中断自律后的结算弹窗也会延迟到这一步才弹出，先点掉
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
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
        logger.hr('大世界任务总览接取', level=1)
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
                    logger.info('[大世界处理-任务] 无法接受任务，存在多个同名塞壬研究任务')
                    success = True
                else:
                    logger.info('[大世界处理-任务] 无法接受任务，已达任务数量上限')
                    success = False
                break
            if self.appear(MISSION_OVERVIEW_EMPTY, offset=(20, 20)):
                logger.info('[大世界处理-任务] 无更多任务可接受')
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
        判断任务每月开荒是否正在调度中。

        Returns:
            bool: 每月开荒是否正在调度中。
        """
        from module.os.tasks.smart_explore import smart_explore_enabled

        if smart_explore_enabled(self.config):
            # 智能开荒由智能调度按黄币状态推进，不能被月度开荒闸门挡住。
            return False
        enable = self.config.is_task_enabled('OpsiExplore')
        next_run = self.config.cross_get(keys='OpsiExplore.Scheduler.NextRun', default=DEFAULT_TIME)
        next_reset = get_os_next_reset()
        logger.debug(f'[大世界-每月开荒] 启用={enable}，下次运行={next_run}，下次重置={next_reset}')
        # -12 小时以处理夏令时
        # `next_run` 可能在夏令时之前计算，但现在是夏令时
        # 2023-03-14 11:15:28.423 | INFO | [OpsiNextReset] 2023-04-01 03:00:00
        # 2023-03-14 11:15:28.425 | INFO | [OpsiExplore] (True, datetime.datetime(2023, 4, 1, 2, 0))
        # 2023-03-14 11:15:28.426 | INFO | 每月开荒仍在运行，仅接取任务...
        if enable and next_run < next_reset - timedelta(hours=12):
            logger.info('每月开荒仍在运行，仅接取任务。每月开荒访问所有区域时会完成这些任务，不必担心遗漏。')
            return True
        else:
            return False
