"""
宿舍计划舰船互动逻辑。

管理宿舍计划中与舰船角色的互动流程，包括目标房间导航、
对话事件处理、互动按钮点击和完成状态检测。
支持多目标舰船（安克雷奇、能代、天狼星等）的互动编排。

页面s: in: PRIVATE_QUARTERS
"""
from module.base.runtime_params import (
    PQ_INTERACT_BUTTON_TIMEOUT, PQ_INTERACT_CLICK_WAIT, PQ_INTERACT_END_TIMEOUT, PQ_INTERACT_EXIT_TIMEOUT, PQ_INTERACT_START_TIMEOUT,
)
from module.config.utils import read_run_param
from module.base.timer import Timer
from module.base.utils import random_rectangle_vector
from module.handler.assets import POPUP_CANCEL
from module.logger import logger
from module.private_quarters.assets import *
from module.ui.page import page_private_quarters
from module.ui.ui import UI

# 等待与超时的秒数走 WebUI「运行参数」页（RunParams.UiWait），默认值集中在
# module/base/runtime_params.py（界面等待域）；帧数下限是与秒数成对使用的
# 内部语义（慢设备上重新点击须同时满足秒数和帧数两个下限），不开放配置。
PQ_INTERACT_BUTTON_FRAMES = 6  # 帧
PQ_INTERACT_CLICK_FRAMES = 2  # 帧
PQ_INTERACT_START_FRAMES = 6  # 帧
PQ_INTERACT_END_FRAMES = 10  # 帧
PQ_INTERACT_EXIT_FRAMES = 6  # 帧


class PQInteract(UI):
    # Key: str, target ship name
    # Value: list[Button], button instances
    #        (房间_Entrance, 页面_Locale)
    available_targets = {
        'anchorage': (PRIVATE_QUARTERS_SHIP_ANCHORAGE, PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        'noshiro': (PRIVATE_QUARTERS_SHIP_NOSHIRO, PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        'sirius': (PRIVATE_QUARTERS_SHIP_SIRIUS, PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        'new_jersey': (PRIVATE_QUARTERS_SHIP_NEW_JERSEY, PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        'taihou': (PRIVATE_QUARTERS_SHIP_TAIHOU, PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        'aegir': (PRIVATE_QUARTERS_SHIP_AEGIR, PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        'nakhimov': (PRIVATE_QUARTERS_SHIP_NAKHIMOV, PRIVATE_QUARTERS_PAGE_LOCALE_VILLA),
        'implacable': (PRIVATE_QUARTERS_SHIP_IMPLACABLE, PRIVATE_QUARTERS_PAGE_LOCALE_VILLA),
    }

    def _pq_handle_dialogue(self):
        """处理舰船对话序列。

        在大凤等舰船实装后对话偶尔会出现延迟卡顿，
        因此在进入房间及其他异常状态时均会调用此方法快速跳过对话。
        """

        # 辅助函数：延迟连击直到加载状态消失
        def after_loading_state():
            return not self.appear(PRIVATE_QUARTERS_LOADING_CHECK, offset=(20, 20))

        def additional():
            return True

        self.ui_click(
            click_button=PRIVATE_QUARTERS_ROOM_SAFE_CLICK_AREA,
            check_button=PRIVATE_QUARTERS_ROOM_CHECK,
            appear_button=after_loading_state,
            additional=additional,
            confirm_wait=3,
            offset=(20, 20),
            retry_wait=1.5
        )

    def _pq_target_appear(self):
        """通过头顶气泡确认房间内的舰娘已就绪。

        进房对话由入口流程处理；视角偏离时最多微量上拖一次，
        随后在有限窗口内等待气泡，未就绪交由房间导航退出重试。

        Returns:
            bool: 检测到舰娘气泡返回 True，等待超时返回 False。

        Pages:
            in: 舰娘房间，进入对话已处理。
            out: 舰娘房间。
        """
        camera_adjusted = False
        for _ in self.loop(timeout=Timer(1.5, count=3)):
            if self.appear(PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1, offset=(100, 100)):
                return True
            if self.appear(PRIVATE_QUARTERS_ROOM_TARGET_CHECK_2, offset=(100, 100)):
                return True
            if self.appear(PRIVATE_QUARTERS_ROOM_TARGET_CHECK_3, offset=(100, 100)):
                return True

            if not camera_adjusted and self.appear(PRIVATE_QUARTERS_ROOM_CHECK, offset=(20, 20)):
                p1, p2 = random_rectangle_vector(
                    (0, -30), box=PRIVATE_QUARTERS_ROOM_SAFE_CLICK_AREA.area,
                    random_range=(-10, -10, 10, 10), padding=5)
                self.device.drag(p1, p2, segments=2,
                                 shake=(0, 25), point_random=(0, 0, 0, 0),
                                 shake_random=(0, -5, 0, 5))
                camera_adjusted = True

        return False

    def _pq_goto_room_seek(self, target_ship):
        """翻页寻找目标舰船所在的宿舍区域。

        Args:
            target_ship (str): 目标舰船标识符。

        Returns:
            bool: 成功找到并翻到目标区域返回 True，否则返回 False。
        """
        target_title = target_ship.title().replace('_', ' ')
        if target_ship not in self.available_targets:
            logger.error(f'[宿舍计划-互动] 不支持的目标舰娘: {target_title}，无法继续子任务')
            return False
        elif len(self.available_targets[target_ship]) < 2:
            logger.error(f'[宿舍计划-互动] 目标舰娘 {target_title} 缺少页面位置信息，无法继续子任务')
            return False

        page_btn = self.available_targets[target_ship][1]
        logger.hr(f'[宿舍计划-互动] 寻找 {target_title} 页面', level=2)

        # 根据当前页面位置依次尝试左翻和右翻
        directions = [PRIVATE_QUARTERS_PAGE_LEFT, PRIVATE_QUARTERS_PAGE_RIGHT]
        if not self.appear(PRIVATE_QUARTERS_PAGE_LEFT, offset=(20, 20)):
            directions.reverse()

        # 执行翻页查找
        skip_first_screenshot = True
        self.interval_clear(directions)
        settle_timer = Timer(1.5, count=3).start()
        for direction in directions:
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 成功找到目标位置
                if self.appear(page_btn, offset=(20, 20)):
                    logger.info(f'[宿舍计划-互动] 已到达 {target_title} 页面')
                    return True

                if self.appear_then_click(direction, offset=(20, 20), interval=1):
                    settle_timer.reset()
                    continue

                if settle_timer.reached():
                    break

        logger.warning(f'[宿舍计划-互动] 未找到 {target_title} 页面')
        return False

    def _pq_goto_room_check(self):
        """检查是否处于加载中或被下载资源弹窗阻挡。

        Returns:
            bool: 处于加载或弹窗状态返回 True。
        """
        if self.appear(PRIVATE_QUARTERS_LOADING_CHECK, offset=(20, 20)):
            return True
        if self.appear(POPUP_CANCEL, offset=(20, 20)):
            return True
        return False

    def _pq_goto_room_enter(self, target_ship):
        """点击并进入目标舰船的房间。

        Args:
            target_ship (str): 目标舰船标识符。

        Returns:
            bool: 成功进入房间且好感度未满返回 True，需要下载资源或好感度已满返回 False。
        """
        target_title = target_ship.title().replace('_', ' ')
        if target_ship not in self.available_targets:
            logger.error(f'[宿舍计划-互动] 不支持的目标舰娘: {target_title}，无法继续子任务')
            return False
        elif len(self.available_targets[target_ship]) < 1:
            logger.error(f'[宿舍计划-互动] 目标舰娘 {target_title} 缺少房间入口信息，无法继续子任务')
            return False

        target_btn = self.available_targets[target_ship][0]
        self.ui_click(
            click_button=target_btn,
            check_button=self._pq_goto_room_check,
            appear_button=page_private_quarters.check_button,
            offset=(20, 20),
            skip_first_screenshot=True)

        # 检查是否弹出下载资源弹窗
        if self.handle_popup_cancel('PRIVATE_QUARTERS_DOWNLOAD_ASSET', offset=(20, 20)):
            logger.error(f'[宿舍计划-互动] 无法进入 {target_title} 的房间，请先下载所需资源')
            return False

        # 处理进入房间时的对话
        self._pq_handle_dialogue()

        # 检查好感度是否已满
        if self.appear(PRIVATE_QUARTERS_ROOM_TARGET_INTIMACY_MAX, offset=(20, 20)):
            logger.warning(
                f'[宿舍计划-互动] {target_title} 契合度已满，请更换目标或关闭子任务')
            return False

        return True

    def _pq_goto_room_exit(self):
        """退出当前舰船房间返回宿舍计划主界面。"""
        # 互动画面还没结束时，返回键会被互动画面吃掉，先按住返回把互动结束掉
        for _ in self.loop(timeout=Timer(read_run_param(
                self.config, 'UiWait_PqInteractExitTimeout',
                PQ_INTERACT_EXIT_TIMEOUT, 5, 120), count=PQ_INTERACT_EXIT_FRAMES)):
            if self.appear(PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20), interval=2):
                self.device.click(PRIVATE_QUARTERS_ROOM_BACK)
                continue
            break

        if (not self.appear(PRIVATE_QUARTERS_ROOM_CHECK, offset=(20, 20)) and
            not self.appear(PRIVATE_QUARTERS_INTERACT, offset=(-10, 0, 0, 65))):
                self._pq_handle_dialogue()

        self.interval_clear(PRIVATE_QUARTERS_ROOM_BACK)
        self.ui_click(
            click_button=PRIVATE_QUARTERS_ROOM_BACK,
            check_button=page_private_quarters.check_button,
            offset=(20, 20),
            retry_wait=3,
            skip_first_screenshot=True
        )
        self.handle_info_bar()

    def pq_interact(self):
        """执行与目标舰船的日常互动流程。

        点击舰船唤出互动按钮，循环 3 次执行互动并等待动作结束返回。
        精力耗尽或超时时自动退出房间。
        """
        # 点击舰娘进入第 1 阶段
        logger.hr('[宿舍计划-互动] 互动开始', level=2)
        interact_offset = (-10, 0, 0, 65)
        target_timer = Timer(2.5, count=1)

        # 点舰娘直到出现互动按钮；精力用完后按钮不会出现，必须有超时
        for _ in self.loop(timeout=Timer(read_run_param(
                self.config, 'UiWait_PqInteractButtonTimeout',
                PQ_INTERACT_BUTTON_TIMEOUT, 5, 120), count=PQ_INTERACT_BUTTON_FRAMES)):
            if self.appear(PRIVATE_QUARTERS_INTERACT, offset=interact_offset):
                break

            if target_timer.reached():
                self.device.click(PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA)
                target_timer.reset()
        else:
            logger.warning('[宿舍计划-互动] 未能出现互动按钮，'
                           '可能今日精力已用完，跳过互动')
            self._pq_goto_room_exit()
            return

        # 重复执行 3 次互动循环
        for i in range(1, 4):
            logger.hr(f'[宿舍计划-互动] 互动循环 {i}/3', level=3)
            self.interval_clear([PRIVATE_QUARTERS_INTERACT_CHECK,
                                 PRIVATE_QUARTERS_INTERACT])

            click_wait = read_run_param(
                self.config, 'UiWait_PqInteractClickWait', PQ_INTERACT_CLICK_WAIT, 2, 60)
            click_timer = Timer(click_wait, count=PQ_INTERACT_CLICK_FRAMES)
            for _ in self.loop(timeout=Timer(read_run_param(
                    self.config, 'UiWait_PqInteractStartTimeout',
                    PQ_INTERACT_START_TIMEOUT, 5, 120), count=PQ_INTERACT_START_FRAMES)):
                if self.appear(PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20)):
                    break

                if self.appear(PRIVATE_QUARTERS_INTERACT, offset=interact_offset) \
                        and click_timer.reached():
                    self.device.click(PRIVATE_QUARTERS_INTERACT)
                    click_timer.reset()
            else:
                logger.warning(f'[宿舍计划-互动] 第 {i} 次互动没有进入互动画面，'
                               '可能今日精力已用完，结束互动')
                break

            # 等互动结束：互动按钮重新出现；互动画面用返回结束
            for _ in self.loop(timeout=Timer(read_run_param(
                    self.config, 'UiWait_PqInteractEndTimeout',
                    PQ_INTERACT_END_TIMEOUT, 10, 300), count=PQ_INTERACT_END_FRAMES)):
                if self.appear(PRIVATE_QUARTERS_INTERACT, offset=interact_offset):
                    break

                if self.appear(PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20), interval=2):
                    self.device.click(PRIVATE_QUARTERS_ROOM_BACK)
            else:
                logger.warning(f'[宿舍计划-互动] 第 {i} 次互动没有正常结束，结束互动')
                break

        logger.hr('[宿舍计划-互动] 互动结束', level=2)
        self._pq_goto_room_exit()

    def pq_goto_room(self, target_ship, retry=3):
        """导航并进入指定舰船的房间。

        Args:
            target_ship (str): 目标舰船名称标识符。
            retry (int): 目标未就绪时的最大重试次数，默认为 3。

        Returns:
            bool: 成功进入且舰船就绪返回 True，否则返回 False。
        """
        success = False
        target_title = target_ship.title().replace('_', ' ')
        logger.hr(f'[宿舍计划-互动] 进入 {target_title} 房间', level=1)

        if not self._pq_goto_room_seek(target_ship):
            return success

        for _ in range(retry):
            if not self._pq_goto_room_enter(target_ship):
                break

            if self._pq_target_appear():
                logger.info(f'[宿舍计划-互动] {target_title} 正在等待你的到来！')
                success = True
                break
            logger.warning(f'[宿舍计划-互动] {target_title} 未就绪，退出重试; 剩余次数={retry - (_ + 1)}')

            self._pq_goto_room_exit()

        return success
