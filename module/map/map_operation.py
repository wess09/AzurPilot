"""地图操作与战斗准备。

本模块提供战役地图中的基础操作，包括：
- 舰队切换与准备（fleet_set、fleet_preparation）
- 进入战役关卡的完整流程（enter_map）
- 地图难度模式切换（handle_map_mode_switch）
- 地图准备阶段处理（handle_map_preparation）
- 撤退操作（withdraw）
- 猫猫攻击跳过（handle_map_cat_attack）
- 舰队顺序反转处理（handle_fleet_reverse）

``MapOperation`` 继承了 ``MysteryHandler``（神秘格子处理）、
``FleetPreparation``（舰队准备）、``Retirement``（退役处理）
和 ``FastForwardHandler``（快进处理），组合了进入地图所需的全部子流程。
"""

from datetime import datetime, timedelta

import cv2

from module.base.runtime_params import HANDOVER_CONFLICT_RETRY_MINUTES
from module.base.timer import Timer
from module.config.time_source import now as current_time
from module.config.utils import read_run_param
from module.exception import CampaignEnd, RequestHumanTakeover, ScriptEnd
from module.handler.fast_forward import FastForwardHandler
from module.handler.mystery import MysteryHandler
from module.logger import logger
from module.map.assets import *
from module.map.map_fleet_preparation import FleetPreparation
from module.notify import handle_notify
from module.retire.retirement import Retirement
from module.ui.assets import BACK_ARROW, DAILY_CHECK

# 读不到作战委托结束时间时的兜底重试间隔走 WebUI「运行参数」页
# （RunParams.Handover），默认值集中在 module/base/runtime_params.py。


class MapOperation(MysteryHandler, FleetPreparation, Retirement, FastForwardHandler):
    """地图操作处理器。

    封装战役地图中的所有基础操作，包括进入关卡、舰队切换、
    撤退、模式切换等。组合了神秘格子、舰队准备、退役和快进处理。

    Attributes:
        map_cat_attack_timer (Timer): 猫猫攻击检测的节流计时器。
        map_clear_percentage_prev (float): 上一次记录的地图通关百分比。
        map_clear_percentage_timer (Timer): 通关百分比变化检测计时器。
        fleet_show_index (int): 屏幕上显示的舰队编号（1 或 2）。
        fleet_current_index (int): 当前逻辑舰队编号（考虑舰队顺序反转）。
    """

    map_cat_attack_timer = Timer(2)
    map_clear_percentage_prev = -1
    map_clear_percentage_timer = Timer(0.3, count=1)

    # 屏幕上显示的舰队编号。
    fleet_show_index = 1
    # 注意：这与 get_fleet_current_index() 不同。
    # 在 fleet_current_index 中，1 表示道中队，2 表示 Boss 队。
    fleet_current_index = 1

    def get_fleet_show_index(self):
        """获取屏幕上当前显示的舰队编号。

        Returns:
            int: 屏幕显示的舰队编号（1 或 2）。

        Pages:
            in: in_map
        """
        if self.appear(FLEET_NUM_1, offset=(20, 20)):
            self.fleet_show_index = 1
            return 1
        elif self.appear(FLEET_NUM_2, offset=(20, 20)):
            self.fleet_show_index = 2
            return 2
        else:
            logger.warning('[地图-操作] 未知的舰队当前索引，默认使用1')
            self.fleet_show_index = 1
            return 1

    def get_fleet_current_index(self):
        """获取当前逻辑舰队编号（考虑舰队顺序反转）。

        Returns:
            int: 逻辑舰队编号（1 为道中队，2 为 Boss 队）。
        """
        if self.fleets_reversed:
            self.fleet_current_index = 3 - self.fleet_show_index
            return self.fleet_current_index
        else:
            self.fleet_current_index = self.fleet_show_index
            return self.fleet_current_index

    def fleet_set(self, index=None, skip_first_screenshot=True):
        """切换到目标逻辑舰队。

        Args:
            index (int, optional): 目标逻辑舰队编号（1 或 2）。默认为 None。
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 是否进行了舰队切换。
        """
        logger.info(f'[地图-操作] 舰队设置为 {index}')
        timeout = Timer(5, count=10).start()
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('[地图-操作] 舰队设置超时，假设当前舰队正确')
                break

            if self.handle_story_skip():
                timeout.reset()
                continue
            if self.handle_in_stage():
                timeout.reset()
                continue

            self.get_fleet_show_index()
            self.get_fleet_current_index()
            logger.info(f'[地图-操作] 舰队: {self.fleet_show_index}, 当前舰队索引: {self.fleet_current_index}')
            if self.fleet_current_index == index:
                break
            elif self.appear_then_click(SWITCH_OVER):
                count += 1
                self.device.sleep((1, 1.5))
                timeout.reset()
                continue
            else:
                logger.warning('[地图-操作] 未找到切换按钮')
                continue

        return count > 0

    def handover_conflict_appear(self):
        """当前画面是不是作战委托的阻止弹窗。

        两种弹窗都算：
        - 委托的不是当前关卡：游戏通用的「信息 INFORMATION」弹窗，右侧是「查看委托」
        - 委托的正是当前关卡：直接弹出「作战委托 INFORM」弹窗，底部是「终止作战」
          或「领取奖励」

        Returns:
            bool: 屏幕上有作战委托阻止弹窗返回 True。
        """
        return (
            self.appear(HANDOVER_CONFLICT_CHECK, offset=(20, 20))
            or self.appear(HANDOVER_STOP_CHECK, offset=(20, 20))
            or self.appear(HANDOVER_PASS_CLICK, offset=(20, 20))
        )

    def handle_handover_conflict(self):
        """处理作战委托进行中的阻止弹窗。

        作战委托进行时，出击类任务点关卡节点会被上面 handover_conflict_appear()
        列的两种弹窗拦下。两个弹窗都不能用 handle_popup_cancel()：它要求画面上
        同时有通用弹窗的「确定」和「取消」，而「信息」弹窗右侧是「查看委托」
        （位置正好压在通用「确定」上），通用素材在这里一个都命中不了，只会让
        截图循环空转；「作战委托 INFORM」弹窗的按钮更是完全另一套。必须用弹窗
        各自的专用素材点击。

        关掉弹窗后把当前任务推迟到作战委托结束之后：委托期间出击类任务都无法
        进行，但委托是有明确结束时间的，不必整天不刷。委托是脚本自己开的
        （任务开关为开）时额外推送一次「功能冲突」提示。

        Pages:
            in: 关卡页（阻止弹窗）
            out: 关卡页

        Raises:
            TaskEnd: 作战委托进行中无法出击，当前任务到此为止。
        """
        if not self.handover_conflict_appear():
            return

        logger.hr('功能冲突: 作战委托进行中', level=2)

        # 无论委托是不是脚本自己开的都要先关掉弹窗，
        # 否则脚本会卡在这个页面上，之后所有页面识别都会失败。
        closed = self.handover_close_conflict()
        target = self.handover_conflict_delay()

        if self.config.is_task_enabled('OperationHandover'):
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f'AzurPilot <{self.config.config_name}> 功能冲突',
                content=f'<{self.config.config_name}> 作战委托未结束，'
                        f'{self.config.task.command} 无法出击，已推迟到 {target}',
            )
        else:
            logger.warning('[功能冲突] 作战委托任务未启用，'
                           '当前委托可能是手动开启的，本次不推送通知')

        if not closed:
            logger.warning('[功能冲突] 阻止弹窗关闭失败，当前页面可能无法正常操作')

        self.config.task_stop('作战委托进行中，无法出击')

    def handover_conflict_delay(self):
        """把当前任务推迟到作战委托结束之后。

        作战委托开委托时会把结束时间记在 OperationHandover.CommissionEnd，
        优先用它——作战委托任务自己的 NextRun 不一定是委托结束时间（委托次数为 0
        时它只是下一次触发时刻，可能在一周以后）。两个都读不到或者都已经过期时，
        改为 HANDOVER_CONFLICT_RETRY_MINUTES 分钟后再试，避免把任务排到过去。

        Returns:
            datetime.datetime: 实际推迟到的时间点。
        """
        now = current_time()
        commission_end = self.config.cross_get(
            keys=['OperationHandover', 'OperationHandover', 'CommissionEnd'], default=None)
        next_run = self.config.cross_get(
            keys=['OperationHandover', 'Scheduler', 'NextRun'], default=None)
        candidates = [
            t for t in (commission_end, next_run)
            if isinstance(t, datetime) and t > now
        ]

        if candidates:
            end = min(candidates)
            target = (end + timedelta(minutes=1)).replace(microsecond=0)
            logger.info(f'[功能冲突] 作战委托预计 {end} 结束，推迟到 {target}')
        else:
            conflict_retry = int(read_run_param(
                self.config, 'Handover_ConflictRetryMinutes',
                HANDOVER_CONFLICT_RETRY_MINUTES, 5, 120))
            target = (now + timedelta(minutes=conflict_retry)).replace(microsecond=0)
            logger.warning(f'[功能冲突] 读不到作战委托的结束时间'
                           f'（{commission_end} / {next_run}），'
                           f'{conflict_retry} 分钟后再试')

        self.config.task_delay(target=target)
        return target

    def handover_close_conflict(self):
        """关闭作战委托阻止弹窗。

        两种弹窗都要关：
        - 「信息 INFORMATION」弹窗：点左下角「取消」
        - 「作战委托 INFORM」弹窗：点右上角红叉。底部那颗按钮不能点，
          「终止作战」会把委托停掉，「领取奖励」会提前领奖。

        Pages:
            in: 关卡页（阻止弹窗）
            out: 关卡页

        Returns:
            bool: 弹窗已关闭返回 True，超时仍未关闭返回 False。
        """
        # 30 秒的静态画面检测会抛 GameStuckError，这里的超时要更短，
        # 保证失败时还能继续走完推迟任务的流程。
        timeout = Timer(10).start()
        while 1:
            self.device.screenshot()

            if not self.handover_conflict_appear():
                logger.info('[功能冲突] 已关闭作战委托提示弹窗')
                return True

            if timeout.reached():
                return False

            if self.appear_then_click(HANDOVER_CONFLICT_CANCEL, offset=(20, 20), interval=1):
                continue
            if self.appear_then_click(HANDOVER_DIALOG_CLOSE, offset=(20, 20), interval=1):
                continue

    def enter_map(self, button, mode='normal', skip_first_screenshot=True):
        """进入战役关卡。

        包含关卡点击、准备页面检测、自律与通关模式配置、舰队切换、剧情跳过等。

        Args:
            button (Button): 要进入的战役按钮。
            mode (str, optional): 难度模式，'normal' 或 'hard'。默认为 'normal'。
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 成功进入地图返回 True，若已在地图中则返回 False。

        Raises:
            RequestHumanTakeover: 点击次数过多或未满足限制时抛出，请求人工接管。
            ScriptEnd: 达成关卡停止条件时抛出。
        """
        logger.hr('进入地图')
        campaign_timer = Timer(5)
        map_timer = Timer(5)
        fleet_timer = Timer(5)
        campaign_click = 0
        map_click = 0
        fleet_click = 0
        checked_in_map = False
        self.stage_entrance = button
        self.map_clear_percentage_prev = -1
        self.map_clear_percentage_timer.reset()

        with self.stat.new(
                genre=self.config.campaign_name, method=self.config.DropRecord_CombatRecord
        ) as drop:
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 检查错误
                if campaign_click > 5:
                    logger.critical(f"[Map] 无法进入 {button}，对 {button} 的点击次数过多")
                    logger.critical("[Map] 可能原因 #1: 您尚未达到解锁该关卡的指挥官等级。")
                    raise RequestHumanTakeover
                if fleet_click > 5:
                    logger.critical(f"[Map] 无法进入 {button}，对 FLEET_PREPARATION 的点击次数过多")
                    logger.critical("[Map] 可能原因 #1: "
                                    "您的舰队尚未满足该关卡的属性限制。")
                    logger.critical("[Map] 可能原因 #2: "
                                    "该关卡每天只能刷一次，"
                                    "但这是您第二次进入")
                    raise RequestHumanTakeover

                # 已在地图中
                if not checked_in_map and self.is_in_map():
                    logger.info('[地图-操作] 已在地图中，跳过进入地图')
                    return False
                else:
                    checked_in_map = True

                # 意外点击处理
                if self.appear(DAILY_CHECK, offset=(20, 20), interval=3):
                    logger.info(f'{DAILY_CHECK} -> {BACK_ARROW}')
                    self.device.click(BACK_ARROW)
                    continue

                # 作战委托进行中，出击会被游戏阻止
                self.handle_handover_conflict()

                # 地图准备
                if map_timer.reached() and self.handle_map_mode_switch(mode):
                    prep_button = self.handle_map_preparation()
                else:
                    prep_button = None
                if prep_button:
                    self.map_get_info()
                    self.handle_map_walk_speedup()
                    self.handle_fast_forward()
                    self.handle_auto_search()
                    if self.triggered_map_stop():
                        self.enter_map_cancel()
                        self.handle_map_stop()
                        raise ScriptEnd(f'Reach condition: {self.config.StopCondition_MapAchievement}')
                    self.device.click(prep_button)
                    map_click += 1
                    map_timer.reset()
                    campaign_timer.reset()
                    # always clear self.map_fleet_checked after MAP_PREPARATION
                    # we will enter FLEET_PREPARATION very soon,
                    # fleets get reset when leaving FLEET_PREPARATION, it only get stored after entering stage,
                    self.map_fleet_checked = False
                    continue

                # 舰队准备
                if fleet_timer.reached() and self.appear(FLEET_PREPARATION, offset=(20, 50)):
                    if mode == 'normal' or mode == 'hard':
                        self.handle_2x_book_setting(mode='prep')
                        self.fleet_preparation()
                        self.handle_auto_submarine_call_disable()
                        self.handle_auto_search_setting()
                        self.map_fleet_checked = True
                        # re-check FLEET_PREPARATION after tons of preparation clicks
                        # and also update FLEET_PREPARATION.button because fleet_bar re-detected it as avoid_area
                        if not self.appear(FLEET_PREPARATION, offset=(20, 50)):
                            logger.warning('FLEET_PREPARATION button disappeared after fleet_preparation()')
                            continue
                    self.device.click(FLEET_PREPARATION)
                    fleet_click += 1
                    fleet_timer.reset()
                    campaign_timer.reset()
                    continue

                # 自动搜索继续
                if self.handle_auto_search_continue(drop=drop):
                    campaign_timer.reset()
                    continue

                # 退役
                if self.handle_retirement():
                    continue

                # 使用数据密钥
                if self.handle_use_data_key():
                    continue

                # 16-1/16-2 潜艇支援弹窗
                if self.handle_submarine_support_popup():
                    continue

                # 情绪处理
                if self.handle_combat_low_emotion():
                    continue

                # 紧急委托
                if self.handle_urgent_commission(drop=drop):
                    continue

                # 2倍经验书弹窗
                if self.handle_2x_book_popup():
                    continue

                if self.handle_submarine_cost_popup():
                    continue

                # 剧情跳过
                if self.handle_story_skip():
                    campaign_timer.reset()
                    continue

                # 进入战役
                if campaign_timer.reached() and self.appear_then_click(button):
                    campaign_click += 1
                    campaign_timer.reset()
                    continue

                # 结束判断
                if self.map_is_auto_search:
                    if self.is_auto_search_running():
                        logger.info('[地图-操作] 自动搜索运行中出现')
                        break
                    if hasattr(self, 'is_combat_loading') and self.is_combat_loading():
                        logger.warning('[地图-操作] 进入地图时战斗加载画面出现')
                        break
                else:
                    if hasattr(self, 'is_combat_loading') and self.is_combat_loading():
                        logger.warning('[地图-操作] 进入地图时战斗加载画面出现')
                        break
                    if self.handle_in_map_with_enemy_searching():
                        # self.handle_map_after_combat_story()
                        break

        return True

    def enter_map_cancel(self, skip_first_screenshot=True):
        """取消进入地图，从地图准备界面退回关卡选择界面。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 始终返回 True。
        """
        logger.hr('取消进入地图')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束判断
            if self.is_in_stage():
                break

            if self.appear(MAP_PREPARATION, offset=(20, 20), interval=2) \
                    or self.appear(MAP_PREPARATION_HARD, offset=(20, 20), interval=2):
                self.device.click(MAP_PREPARATION_CANCEL)
                continue
            if self.appear(FLEET_PREPARATION, offset=(20, 50), interval=2):
                self.device.click(MAP_PREPARATION_CANCEL)
                continue

        return True

    def handle_map_mode_switch(self, mode):
        """处理地图难度模式切换（普通/困难）。

        Args:
            mode (str): 目标模式，'normal' 或 'hard'。

        Returns:
            bool: 地图模式是否满足要求。若地图无模式切换则始终返回 True。
        """
        if not self.config.MAP_HAS_MODE_SWITCH:
            return True

        if mode == 'normal':
            if self.match_template_color(MAP_MODE_SWITCH_NORMAL, offset=(20, 20)):
                logger.attr('地图模式', '普通')
                return True
            if self._is_mod_switch_hard_appear(active=False, interval=2):
                logger.attr('地图模式', '困难')
                MAP_MODE_SWITCH_NORMAL.clear_offset()
                self.device.click(MAP_MODE_SWITCH_NORMAL)
                self.interval_reset(MAP_MODE_SWITCH_HARD)
            return False
        elif mode == 'hard':
            if self._is_mod_switch_hard_appear(active=True):
                logger.attr('地图模式', '困难')
                return True
            if self.match_template_color(MAP_MODE_SWITCH_NORMAL, offset=(20, 20), interval=2):
                logger.attr('地图模式', '普通')
                MAP_MODE_SWITCH_HARD.clear_offset()
                self.device.click(MAP_MODE_SWITCH_HARD)
                return False
            return False
        else:
            logger.attr('地图模式', '未知')
            return False

    def _is_mod_switch_hard_appear(self, active=True, interval=0):
        """检测困难模式切换按钮是否出现。

        遍历多个可能的困难模式按钮模板进行匹配。

        Args:
            active (bool, optional): 是否需要检查按钮处于激活状态。默认为 True。
            interval (int | float, optional): 操作间隔时间（秒）。默认为 0。

        Returns:
            bool: 困难模式按钮是否出现（且若需要检查则是否处于激活状态）。
        """
        if interval:
            interval = self.get_interval_timer(MAP_MODE_SWITCH_HARD, interval=interval)
            if not interval.reached():
                return False

        for button in [
            MAP_MODE_SWITCH_HARD,
            MAP_MODE_SWITCH_HARD2,
            MAP_MODE_SWITCH_HARD3,
            MAP_MODE_SWITCH_HARD4,
            MAP_MODE_SWITCH_HARD5,
            MAP_MODE_SWITCH_HARD6,
        ]:
            if self.appear(button, offset=(20, 20), similarity=0.7):
                if active:
                    return self._is_mod_switch_hard_active(button)
                else:
                    return True
        return False

    def _is_mod_switch_hard_active(self, button):
        """通过颜色检测判断困难模式按钮是否处于激活状态。

        激活状态的按钮包含白色图标（RGB 最大值 > 235 的像素占比 > 50%）。

        Args:
            button (Button): 困难模式切换按钮。

        Returns:
            bool: 按钮是否处于激活状态。
        """
        image = self.image_crop(button.button)
        # 取 RGB 三通道最大值
        r, g, b = cv2.split(image)
        cv2.max(r, g, dst=r)
        cv2.max(r, b, dst=r)
        # 活跃按钮有白色图标，检查是否有颜色 > 235 的像素
        cv2.inRange(r, 235, 255, dst=r)
        sum_ = cv2.countNonZero(r)
        total = r.shape[0] * r.shape[1]
        return sum_ / total > 0.5

    def handle_map_preparation(self):
        """处理地图准备阶段，等待地图信息动画完成。

        Returns:
            Button | None: 地图准备页出现且信息动画结束时，返回普通或困难模式
                对应的准备按钮；否则返回 None。
        """
        if self.appear(MAP_PREPARATION, offset=(20, 20)):
            prep_button = MAP_PREPARATION
        elif self.appear(MAP_PREPARATION_HARD, offset=(20, 20)):
            prep_button = MAP_PREPARATION_HARD
        else:
            self.map_clear_percentage_prev = -1
            self.map_clear_percentage_timer.reset()
            return None
        if not self.config.MAP_HAS_CLEAR_PERCENTAGE:
            logger.attr('地图有通关百分比', self.config.MAP_HAS_CLEAR_PERCENTAGE)
            return prep_button
        if self.config.MAP_IS_ONE_TIME_STAGE:
            logger.attr('地图是一次性关卡', self.config.MAP_IS_ONE_TIME_STAGE)
            return prep_button
        # 信息栏会遮挡进度条和 MAP_GREEN
        if self.info_bar_count():
            return None

        percent = self.get_map_clear_percentage()
        logger.attr('地图通关百分比', f'{int(percent * 100)}%')
        # 注意：进度条从 100% 开始，然后从 0% 增加到实际值。
        # 2022.08.21 当 `percent` 从 0 上升时仍然启用此逻辑。
        if percent > 0.95 and 0 <= self.map_clear_percentage_prev < 0.95:
            # 地图通关进度达到 100%，直接退出
            return prep_button
        if abs(percent - self.map_clear_percentage_prev) < 0.02:
            self.map_clear_percentage_prev = percent
            if self.map_clear_percentage_timer.reached():
                return prep_button
            else:
                return None
        else:
            self.map_clear_percentage_prev = percent
            self.map_clear_percentage_timer.reset()
            return None

    def withdraw(self, skip_first_screenshot=True):
        """从当前战役地图撤退。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Raises:
            CampaignEnd: 成功撤退并回到关卡选择界面时抛出。
        """
        logger.hr('地图撤退')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(FLEET_SWITCH_CONFIRM, offset=(30, 30)):
                continue
            if self.handle_popup_confirm('WITHDRAW'):
                continue
            if self.appear_then_click(WITHDRAW, interval=5):
                continue
            if self.handle_auto_search_exit():
                continue
            # 意外点击处理
            if self.appear(DAILY_CHECK, offset=(20, 20), interval=3):
                logger.info(f'{DAILY_CHECK} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                continue

            # 结束判断
            if self.handle_in_stage():
                raise CampaignEnd('Withdraw')

    def handle_map_cat_attack(self):
        """处理地图上的指挥喵伏击/攻击动画并点击跳过。

        Returns:
            bool: 是否检测到并点击跳过了动画。
        """
        if not self.map_cat_attack_timer.reached():
            return False
        if self.image_color_count(MAP_CAT_ATTACK, color=(255, 231, 123), threshold=30, count=100):
            logger.info('[地图-操作] 跳过指挥喵攻击')
            self.device.click(MAP_CAT_ATTACK)
            self.map_cat_attack_timer.reset()
            return True
        if not self.map_is_clear_mode:
            # 威胁检测：Medium 模式有 106 像素计数，MAP_CAT_ATTACK_MIRROR 有 290。
            if self.image_color_count(MAP_CAT_ATTACK_MIRROR, color=(255, 231, 123), threshold=30, count=200):
                logger.info('[地图-操作] 跳过地图被攻击')
                self.device.click(MAP_CAT_ATTACK)
                self.map_cat_attack_timer.reset()
                return True

        return False

    @property
    def fleets_reversed(self):
        """是否反转了道中队与 Boss 队在游戏界面上的出击顺序。

        Returns:
            bool: 是否反转。
        """
        if not self.config.FLEET_2:
            return False
        return self.config.Fleet_FleetOrder in ['fleet1_boss_fleet2_mob', 'fleet1_standby_fleet2_all']

    def handle_fleet_reverse(self):
        """处理舰队出击顺序反转。

        游戏会选择编号较小的舰队作为第一舰队，无论我们在舰队准备中如何选择。
        自动搜索更新后，游戏不再忽略用户设置。

        Returns:
            bool: 舰队是否发生了变更。
        """
        if not self.map_is_hard_mode \
                and self.config.Fleet_FleetOrder in ['fleet1_boss_fleet2_mob', 'fleet1_standby_fleet2_all']:
            logger.warning(f"[地图-操作] 普通模式不应使用反转的舰队顺序 ({self.config.Fleet_FleetOrder})。")
            logger.warning('[地图-操作] 请交换舰队 1 和舰队 2 的配置，'
                           '使用 "fleet1_mob_fleet2_boss" 或 "fleet1_all_fleet2_standby"')
            # raise RequestHumanTakeover

        if not self.fleets_reversed:
            return False

        return self.fleet_set(index=2)
