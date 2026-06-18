from module.base.timer import Timer
from module.base.utils import random_rectangle_vector
from module.handler.assets import POPUP_CANCEL
from module.logger import logger
from module.private_quarters.assets import *
from module.ui.page import page_private_quarters
from module.ui.ui import UI


class PQInteract(UI):
    # 可选目标舰娘映射表
    # 键: 舰娘名称字符串
    # 值: (房间入口按钮, 所在场景页面按钮) 的元组
    available_targets = {
        'anchorage': (PRIVATE_QUARTERS_SHIP_ANCHORAGE, PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        'noshiro': (PRIVATE_QUARTERS_SHIP_NOSHIRO, PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        'sirius': (PRIVATE_QUARTERS_SHIP_SIRIUS, PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        'new_jersey': (PRIVATE_QUARTERS_SHIP_NEW_JERSEY, PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        'taihou': (PRIVATE_QUARTERS_SHIP_TAIHOU, PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        'aegir': (PRIVATE_QUARTERS_SHIP_AEGIR, PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
    }

    def _pq_handle_dialogue(self):
        """
        处理目标舰娘的对话序列。

        加入大凤后发现此序列偶尔会卡顿，
        因此在进入房间之外的其他状态也会调用。

        Pages:
            in: 私人宿舍房间内
            out: 私人宿舍房间内（对话结束）
        """

        # 辅助函数：等待加载状态消失后再点击
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
        """
        检测目标舰娘是否出现在房间中。

        使用 offset=(100, 100) 可检测安克雷奇、能代、天狼星、新泽西和大凤。
        新增舰娘时可能需要调整偏移或为每艘舰娘单独截取气泡位置。

        Returns:
            bool: 目标是否出现

        Pages:
            in: 私人宿舍房间内
        """
        settle_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：成功
            if self.appear(PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1, offset=(100, 100)):
                return True
            if self.appear(PRIVATE_QUARTERS_ROOM_TARGET_CHECK_2, offset=(100, 100)):
                return True

            # 结束条件：等待超时失败
            if settle_timer.reached():
                return False

            if self.appear(PRIVATE_QUARTERS_ROOM_CHECK, offset=(20, 20)):
                # 向上拖拽以修正默认视角与目标的距离/缩放
                p1, p2 = random_rectangle_vector(
                    (0, -30), box=PRIVATE_QUARTERS_ROOM_SAFE_CLICK_AREA.area,
                    random_range=(-10, -10, 10, 10), padding=5)
                self.device.drag(p1, p2, segments=2,
                                 shake=(0, 25), point_random=(0, 0, 0, 0),
                                 shake_random=(0, -5, 0, 5))
                settle_timer.reset()
            else:
                # 未检测到 CHECK 按钮，可能正在对话中
                self._pq_handle_dialogue()
                settle_timer.reset()

    def _pq_goto_room_seek(self, target_ship):
        """
        在私人宿舍主页左右翻页，寻找目标舰娘所在场景。

        Args:
            target_ship (str): 目标舰娘名称

        Returns:
            bool: 是否找到目标页面

        Pages:
            in: 私人宿舍主页
            out: 私人宿舍主页（目标场景页面）
        """
        target_title = target_ship.title().replace('_', ' ')
        if target_ship not in self.available_targets:
            logger.error(f'Unsupported target ship: {target_title}, '
                         'cannot continue subtask')
            return False
        elif len(self.available_targets[target_ship]) < 2:
            logger.error('Missing tuple info page locale for '
                         f'target ship: {target_title}, cannot '
                         'continue subtask')
            return False

        page_btn = self.available_targets[target_ship][1]
        logger.hr(f'Seek {target_title}\'s Page', level=2)

        # 根据当前位置决定翻页方向：先左后右或先右后左
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

                # 结束条件：成功
                if self.appear(page_btn, offset=(20, 20)):
                    logger.info(f'Reached {target_title}\'s page')
                    return True

                # 使用间隔延迟确认页面切换
                if self.appear_then_click(direction, offset=(20, 20), interval=1):
                    settle_timer.reset()
                    continue

                # 间隔到期无新点击，可安全切换方向
                if settle_timer.reached():
                    break

        logger.warning(f'{target_title}\'s page cannot be found')
        return False

    def _pq_goto_room_check(self):
        """
        检测是否处于加载中或被资源下载弹窗阻塞。

        Returns:
            bool: True 表示仍在加载或被阻塞
        """
        if self.appear(PRIVATE_QUARTERS_LOADING_CHECK, offset=(20, 20)):
            return True
        if self.appear(POPUP_CANCEL, offset=(20, 20)):
            return True
        return False

    def _pq_goto_room_enter(self, target_ship):
        """
        点击目标舰娘的房间入口，进入房间。

        点击后会等待加载画面或资源下载弹窗出现。

        Args:
            target_ship (str): 目标舰娘名称

        Returns:
            bool: 是否成功进入房间

        Pages:
            in: 私人宿舍主页（目标场景页面）
            out: 私人宿舍房间内
        """
        # 点击进入目标房间，确保加载画面或弹窗出现
        target_title = target_ship.title().replace('_', ' ')
        if target_ship not in self.available_targets:
            logger.error(f'Unsupported target ship: {target_title}, '
                         'cannot continue subtask')
            return False
        elif len(self.available_targets[target_ship]) < 1:
            logger.error('Missing tuple info room entrance for '
                         f'target ship: {target_title}, cannot '
                         'continue subtask')
            return False

        target_btn = self.available_targets[target_ship][0]
        self.ui_click(
            click_button=target_btn,
            check_button=self._pq_goto_room_check,
            appear_button=page_private_quarters.check_button,
            offset=(20, 20),
            skip_first_screenshot=True)

        # 如果弹出资源下载提示，终止运行
        if self.handle_popup_cancel('PRIVATE_QUARTERS_DOWNLOAD_ASSET', offset=(20, 20)):
            logger.error(f'Cannot enter {target_title}\'s room, please download the necessary assets first')
            return False

        # 通过点击推进对话，完全进入房间
        self._pq_handle_dialogue()

        # 如果目标好感度已满，终止运行
        if self.appear(PRIVATE_QUARTERS_ROOM_TARGET_INTIMACY_MAX, offset=(20, 20)):
            logger.warning(
                f'{target_title}\'s intimacy is maxed, configure to new target or turn off subtask altogether')
            return False

        return True

    def _pq_goto_room_exit(self):
        """
        退出当前房间，返回私人宿舍主页。

        退出前会处理可能残留的对话。

        Pages:
            in: 私人宿舍房间内
            out: 私人宿舍主页
        """
        # 退出前处理可能残留的对话
        if (not self.appear(PRIVATE_QUARTERS_ROOM_CHECK, offset=(20, 20)) and
            not self.appear(PRIVATE_QUARTERS_INTERACT, offset=(0, 60))):
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
        """
        执行目标舰娘的完整互动流程。

        分三个阶段：点击舰娘触发对话 -> 重复 3 次互动循环 -> 退出房间。
        offset=(0, 60) 用于适配不同好感度下按钮的 Y 轴偏移。

        Pages:
            in: 私人宿舍房间内
            out: 私人宿舍主页
        """
        # 第一阶段：点击舰娘触发对话序列
        logger.hr(f'Interact Start', level=2)
        click_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件
            if self.appear(PRIVATE_QUARTERS_INTERACT, offset=(0, 60)):
                break

            if click_timer.reached():
                self.device.click(PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA)
                click_timer.reset()

        # 第二、三阶段：重复互动循环 3 次
        for i in range(1, 4):
            logger.hr(f'Interact Loop {i}/3', level=3)
            self.interval_clear([PRIVATE_QUARTERS_INTERACT_CHECK,
                                 PRIVATE_QUARTERS_INTERACT])
            skip_first_screenshot = True
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 结束条件
                if self.appear(PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20)):
                    break

                if self.appear_then_click(PRIVATE_QUARTERS_INTERACT, offset=(0, 60), interval=1):
                    continue

            skip_first_screenshot = True
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 结束条件
                if self.appear(PRIVATE_QUARTERS_INTERACT, offset=(0, 60)):
                    break

                if self.appear(PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20), interval=1):
                    self.device.click(PRIVATE_QUARTERS_ROOM_BACK)
                    continue

        logger.hr(f'Interact End', level=2)
        self._pq_goto_room_exit()

    def pq_goto_room(self, target_ship, retry=3):
        """
        导航到目标舰娘的房间。

        先翻页找到目标场景，再进入房间检测舰娘是否出现。
        若初始加载时目标未出现，会退出重试。

        Args:
            target_ship (str): 目标舰娘名称
            retry (int): 最大重试次数

        Returns:
            bool: 是否成功进入目标舰娘在场的房间

        Pages:
            in: 私人宿舍主页
            out: 私人宿舍房间内（成功时）/ 私人宿舍主页（失败时）
        """
        success = False
        target_title = target_ship.title().replace('_', ' ')
        logger.hr(f'Enter {target_title}\'s Room', level=1)

        if not self._pq_goto_room_seek(target_ship):
            return success

        for _ in range(retry):
            if not self._pq_goto_room_enter(target_ship):
                break

            if self._pq_target_appear():
                logger.info(f'{target_title} is waiting and excited for your arrival!')
                success = True
                break
            logger.warning(f'{target_title} is not ready, exit and try again; retry={retry - (_ + 1)}')

            self._pq_goto_room_exit()

        return success
