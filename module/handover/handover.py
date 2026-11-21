"""作战委托模块。

在主线、活动或作战档案关卡页启动「作战委托」。基础委托只增加大讲堂熟练度；
投入作战全权委托书并消耗额外石油才会获得对应的关卡掉落。委托期间主线、活动
及作战档案无法出击，因此启动前为已安排的出击预留时间。

流程：
1. 查一次停服维护时间（OperationHandover.MaintainOverride 开启时）：按当前游戏
   服务器（cn/en/jp/tw）取对应公告，维护就在今天时，当天 0 点起就整体切到维护
   模式——忽略「委托次数」和「一键消耗委托书」，把下一次运行排到维护前 10 分钟，
   到点后用「次数拉满」跑最后一次；维护时间已经过去、或是别的日子，按下面的
   正常流程走
2. 委托次数为 0 时这个任务只在有必要时才进游戏：上一次开的委托还在做就等它结束，
   做完了就进去领奖励；手上没有委托才按定时功能排下一次运行（一键消耗的触发
   时刻、维护检查）；两个功能都没开就直接关掉本任务
3. 按关卡名称进入主线或所选活动关卡页，活动图先确认普通 / 困难模式
4. 上一次的委托没结束时，目标关卡进关卡页直接弹出「作战委托 INFORM」弹窗，
   其他关卡先弹阻止页，点它的「查看委托」进同一个弹窗
5. 弹窗里委托仍在进行（HANDOVER_STOP_CHECK）则关掉弹窗，按剩余时间推迟
6. 已完成（HANDOVER_PASS_CLICK）则领取奖励。领奖路上游戏会连着弹「合计获得奖励」
   的结算、紧急委托提示、新船入手演出，全部收掉后退回章节选择页，重新点一次关卡
   把上面的流程再走一遍，继续开下一个委托（见 handover_handle_popup）
7. 检测该关卡是否支持作战委托；未启用时补一次完整连续作战，中途船坞满则复用周回
   清理并重做一次，返回关卡正向复查入口（HANDOVER_TAB / HANDOVER_TAB_UNSUPPORTED）
8. 记录当前石油数量，低于 OperationHandover.OilLimit 时直接推迟
9. 打开作战委托面板定次数：维护前拉满 > 一键消耗按委托书数量 >
   配置里的次数（见 handover_consume_all_book）
10. 比较「需要时间」与「剩余可用时间」，额度只需覆盖最后一次启动前的消耗
11. 时间不足且启用了自动补充时，用作战全权委托书兑换可用时间（1 本 = 1 小时）
12. 把面板上的「预计消耗」石油和当前石油比较，不够就关掉面板推迟，不点「开始」
13. 启用了使用委托书时，把委托书投入量拉到最大
14. 点击「开始」，从章节页重新进入原关卡，以委托详情确认启动成功
15. 一键消耗仅在委托确认启动后记录本周触发；资源不足或识别失败时推迟重试

配置路径: Campaign.Name, Campaign.Event, OperationHandover.Count,
         OperationHandover.AutoSupplementTime, OperationHandover.UseHandoverBook,
         OperationHandover.OilLimit, OperationHandover.ConsumeAllBook,
         OperationHandover.ConsumeAllBookWeekday, OperationHandover.ConsumeAllBookTime,
         OperationHandover.MaintainOverride, OperationHandover.CommissionEnd
"""

import math
import re
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from module.base import http

from deploy.api_endpoints import MAINTENANCE_API_URL
from module.base.device_id import get_device_id
from module.base.runtime_params import (
    HANDOVER_CONSUME_RETRY_MINUTES,
    HANDOVER_MAINTAIN_CHECK_MINUTES,
    HANDOVER_MAINTAIN_LEAD_MINUTES,
)
from module.base.timer import Timer
from module.config.utils import get_server_last_update, read_run_param
from module.campaign.run import CampaignRun
from module.campaign.stage_name import normalize_event_stage, normalize_post_loop_stage
from module.exception import GameStuckError, ScriptEnd
from module.config.time_source import now as current_time
from module.config.utils import SERVER_TO_TIMEZONE
from module.handler.assets import NEW_SHIP_SKIP
from module.handler.fast_forward import to_map_file_name
from module.handover.planning import daily_runs, fit_sortie_window, next_sortie
from module.logger import logger
from module.map.assets import (FLEET_PREPARATION, HANDOVER_BOOK_AMOUNT_OCR,
                               HANDOVER_BOOK_COUNT_OCR, HANDOVER_BOOK_ITEM,
                               HANDOVER_BOOK_MAX, HANDOVER_CHECK, HANDOVER_COUNT_INPUT,
                               HANDOVER_COUNT_MAX, HANDOVER_COUNT_OCR,
                               HANDOVER_DIALOG_CLOSE, HANDOVER_EXCHANGE_TIME,
                               HANDOVER_OIL_COST_OCR, HANDOVER_PANEL_CLOSE,
                               HANDOVER_PASS_CLICK, HANDOVER_REWARD, HANDOVER_REWARD_CHECK,
                               HANDOVER_START_CLICK, HANDOVER_STOP_CHECK, HANDOVER_STOP_TIME_OCR,
                               HANDOVER_TAB, HANDOVER_TAB_UNSUPPORTED,
                               HANDOVER_TIME_NEEDED_OCR, HANDOVER_TIME_REMAINING_OCR)
from module.map.assets import (
    HANDOVER_EXCHANGE_ADDED_OCR, HANDOVER_EXCHANGE_CHECK,
    HANDOVER_HELP_CHECK, HANDOVER_HELP_CLOSE, HANDOVER_HELP_SCROLL,
    MULTIPLE_SORTIES_RESULT_CHECK, MULTIPLE_SORTIES_RESULT_EXIT,
)
from module.ocr.ocr import Digit, Duration

OCR_HANDOVER_COUNT = Digit(HANDOVER_COUNT_OCR, letter=(255, 255, 255), threshold=128, alphabet='0123456789')
OCR_HANDOVER_BOOK_COUNT = Digit(HANDOVER_BOOK_COUNT_OCR, letter=(255, 255, 255), threshold=128,
                                alphabet='0123456789')
OCR_HANDOVER_BOOK_AMOUNT = Digit(HANDOVER_BOOK_AMOUNT_OCR, letter=(255, 255, 255), threshold=128,
                                 alphabet='0123456789')
class HandoverDuration(Duration):
    """区分有效的零额度与时长识别失败。"""

    def after_process(self, result):
        result = super().after_process(result).strip()
        self.last_valid = bool(re.fullmatch(r'\d{1,2}:?\d{2}:?\d{2}', result))
        return result


class HandoverOil(Digit):
    """提取绿色或红色的数字，剔除油桶图标和「石油」单位。"""

    def pre_process(self, image):
        rgb = image.astype(np.int16)
        green = (rgb[:, :, 1] - rgb[:, :, 0] > 20) & (rgb[:, :, 1] - rgb[:, :, 2] > 25)
        red = (rgb[:, :, 0] - rgb[:, :, 1] > 35) & (rgb[:, :, 0] - rgb[:, :, 2] > 35)
        mask = ((green | red) & (rgb.max(axis=2) > 140)).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        units = [x for x, y, width, height, area in stats[1:] if width >= 17 and height >= 14]
        if not units:
            return np.full(image.shape[:2], 255, dtype=np.uint8)
        mask = mask[:, :min(units)]
        visible = np.flatnonzero(mask.any(axis=0))
        if visible.size:
            mask = mask[:, visible[0]:visible[-1] + 1]
        return (255 - mask * 255).astype(np.uint8)


OCR_HANDOVER_OIL_COST = HandoverOil(HANDOVER_OIL_COST_OCR, alphabet='0123456789')
OCR_HANDOVER_TIME_NEEDED = HandoverDuration(HANDOVER_TIME_NEEDED_OCR, letter=(255, 255, 255), threshold=128)
# 剩余可用时间是绿色字 (110,184,48)，面板上其余文字都是白/浅灰。extract_letters() 对
# 白色 letter 走「按最小通道取反」的快速分支，非白色走逐通道差值分支；绿字用白色会把
# 文字和深色背景一起提成纯白，送模图成为空白图，OCR 恒返回 0:00:00。
OCR_HANDOVER_TIME_REMAINING = HandoverDuration(HANDOVER_TIME_REMAINING_OCR, letter=(110, 184, 48), threshold=128)
# 进行中委托的剩余时间同样是绿色字 (99,215,131)，理由同上
OCR_HANDOVER_STOP_TIME = HandoverDuration(HANDOVER_STOP_TIME_OCR, letter=(99, 215, 131), threshold=128)
OCR_HANDOVER_EXCHANGE_ADDED = HandoverDuration(
    HANDOVER_EXCHANGE_ADDED_OCR, letter=(158, 234, 94), threshold=128)

# 一本作战全权委托书可兑换 1 小时可用时间
HANDOVER_BOOK_HOURS = 1
HANDOVER_BOOK_SECONDS = HANDOVER_BOOK_HOURS * 3600

# 一键消耗委托书的周几选项，下标与 datetime.weekday() 一致（周一 = 0）
HANDOVER_WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
HANDOVER_WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 消耗重试、维护前提前量与维护核对间隔走 WebUI「运行参数」页
# （RunParams.Handover），默认值集中在 module/base/runtime_params.py。

# 停服维护时间接口，顶层是国服公告的聚合结果，servers 里按 cn/jp/en/tw 分别给出
# maintenance_date(YYYY-MM-DD) 与 start_time(HH:MM)
HANDOVER_MAINTAIN_API = MAINTENANCE_API_URL
# 接口里服务器时区的形状，如 `UTC+8`、`UTC-7`、`UTC+08:00`
HANDOVER_MAINTAIN_TIMEZONE = re.compile(r'^UTC([+-])(\d{1,2})(?::?(\d{2}))?$')
# 委托结束时间的初始值，表示脚本手上没有开过委托
HANDOVER_COMMISSION_NONE = datetime(2020, 1, 1)


class OperationHandover(CampaignRun):
    """作战委托执行器。

    继承 CampaignRun 以复用 load_campaign()，拿到 self.campaign（config 已
    deepcopy 合并过的 CampaignBase 实例），借它的 ensure_campaign_ui() 与
    fleet_preparation() 复用战役 UI 能力。入口未启用时调用连续作战补充记录；
    已启用的关卡直接设置离线委托。

    Attributes:
        campaign: 战役执行实例，由 CampaignRun.load_campaign() 提供。
    """

    def run(self):
        """执行一次作战委托。

        Pages:
            in: 任意页面
            out: 关卡页
        """
        logger.hr('作战委托', level=1)
        count = self.config.OperationHandover_Count
        auto_supplement = self.config.OperationHandover_AutoSupplementTime
        use_book = self.config.OperationHandover_UseHandoverBook
        oil_limit = self.config.OperationHandover_OilLimit
        consume_all, reason = self.handover_consume_all_book_state()
        maintain, maintain_reason, maintain_queried = self.handover_maintain_state()
        # 维护当天从 0 点起就整体切到维护模式：忽略「委托次数」和「一键消耗委托书」，
        # 下一次运行只排到维护前 HANDOVER_MAINTAIN_LEAD_MINUTES 分钟那一次。
        # 维护已经开始的当天不再算维护模式，免得一直重启游戏
        maintain_run = maintain is not None and maintain > current_time()
        logger.attr('委托关卡', self.config.Campaign_Name)
        logger.attr('委托次数', count)
        logger.attr('自动补充时间', auto_supplement)
        logger.attr('使用作战全权委托书', use_book)
        logger.attr('石油低于 X 后推迟', oil_limit)
        logger.attr('一键消耗作战全权委托书', '是' if consume_all else f'否（{reason}）')
        logger.attr('维护当天作战委托', f'是（{maintain_reason}）' if maintain_run
                    else f'否（{maintain_reason}）')

        commission_end = self.handover_commission_end()
        maintenance_claim_only = False
        if maintain_run:
            lead_minutes = int(read_run_param(
                self.config, 'Handover_MaintainLeadMinutes',
                HANDOVER_MAINTAIN_LEAD_MINUTES, 2, 60))
            run_at = maintain - timedelta(minutes=lead_minutes)
            if current_time() < run_at:
                if commission_end > current_time():
                    self.config.task_delay(target=min(run_at, commission_end))
                    return
                if commission_end > HANDOVER_COMMISSION_NONE:
                    maintenance_claim_only = True
                else:
                    logger.info(f'[作战委托] 还没到维护前的运行时间，推迟到 {run_at}')
                    self.config.task_delay(target=run_at)
                    return
            logger.info(f'[作战委托] 到维护前 {lead_minutes} 分钟了，'
                        f'作战次数拉满跑最后一次')

        # 委托次数为 0：这个任务平时没事可做，只在开启的定时功能触发时才动。
        # 三个开关全关就直接关掉任务，避免每天空跑
        now = current_time()
        if count <= 0:
            consume_enabled = self.config.OperationHandover_ConsumeAllBook
            maintain_enabled = self.config.OperationHandover_MaintainOverride
            if not consume_enabled and not maintain_enabled and commission_end <= HANDOVER_COMMISSION_NONE:
                logger.warning('[作战委托] 委托次数为 0，一键消耗委托书和维护当天作战委托'
                               '都没开启，这个任务没有事可做，直接关闭')
                self.config.cross_set(keys='OperationHandover.Scheduler.Enable', value=False)
                self.config.task_stop('委托次数为 0，两个定时功能都没开启')

            # 维护当天优先级最高，当天 0 点起就整体切到维护模式，
            # 忽略「委托次数」和「一键消耗委托书」
            if not maintain_run and not consume_all:
                if commission_end > now:
                    # 上一次开的委托还在做，等它结束回来领奖励，别一直晾着——
                    # 领奖前它会一直挡着别的出击任务
                    logger.info(f'[作战委托] 委托次数为 0，上一次委托 {commission_end} 才结束，'
                                f'等它做完回来领取')
                    self.config.task_delay(target=commission_end)
                    return
                if commission_end <= HANDOVER_COMMISSION_NONE:
                    # 手上根本没有委托，按定时功能排下一次运行
                    self.handover_idle_delay(maintain, maintain_queried)
                    return
                logger.info('[作战委托] 委托次数为 0，上一次委托做完了，进去领取奖励')

        # 进入目标关卡页，并按 Fleet 组准备编队
        self.handover_enter()

        # 上一次的委托仍在进行，不打断它，关掉弹窗等它做完再回来领取
        self.device.screenshot()
        if self.appear(HANDOVER_STOP_CHECK, offset=(20, 20)):
            remaining = OCR_HANDOVER_STOP_TIME.ocr(self.device.image)
            logger.attr('委托剩余时间', remaining)
            self.device.click(HANDOVER_DIALOG_CLOSE)
            # OCR 读成 0 时给个下限，免得下一秒又跑一遍
            remaining = max(remaining, timedelta(minutes=1))
            self.handover_commission_set(current_time() + remaining)
            self.handover_delay(remaining)
            return

        # 上一次的委托已完成，领取奖励。领完退回章节选择页，要重新点一次关卡
        claimed = self.handover_reward()
        if claimed or commission_end > HANDOVER_COMMISSION_NONE:
            self.handover_commission_clear()
        if maintenance_claim_only:
            self.config.task_delay(target=run_at)
            return

        # 委托次数为 0 又没有定时功能要跑：奖励领完就收工，不开新委托
        if count <= 0 and not maintain_run and not consume_all:
            self.handover_commission_clear()
            if not consume_enabled and not maintain_enabled:
                self.config.cross_set(keys='OperationHandover.Scheduler.Enable', value=False)
                self.config.task_stop('已有委托已回收，关闭无启动计划的任务')
            self.handover_idle_delay(maintain, maintain_queried)
            return

        used = daily_runs(self.config, get_server_last_update('00:00'), current_time())
        limit = getattr(self.config, 'OperationHandover_DailyRunCount', 1)
        if not (maintain_run or consume_all) and limit > 0 and used >= limit:
            logger.info(f'[作战委托] 今日普通委托已启动 {used}/{limit} 批，等待次日刷新')
            self.config.task_delay(server_update=True)
            return

        sortie = next_sortie(self.config)
        now = current_time()
        if sortie is not None and sortie[1] <= now + timedelta(minutes=2):
            logger.info(f'[作战委托] 为出击任务 {sortie[0]} 保留运行窗口，暂不启动新委托')
            self.config.task_delay(target=max(now + timedelta(minutes=2), sortie[1] + timedelta(minutes=1)))
            return

        if claimed:
            self.handover_enter()

        # 面板打开后就看不到顶栏的石油了，先把当前油量读出来备用
        oil = self.get_oil()
        logger.attr('当前石油', oil)
        if oil_limit and oil < oil_limit and (use_book or consume_all):
            logger.warning(f'[作战委托] 石油 {oil} 低于设定值 {oil_limit}，推迟任务')
            self.handover_delay()
            return

        # 灰色入口也可能只是没有完整自律记录；船坞满中断后允许清理并重做一次。
        support = self.handover_check_support()
        if support is None:
            self.config.task_delay(minute=5)
            return
        if not support:
            if not self.handover_unlock():
                self.handover_delay()
                return
            oil = self.get_oil()

        # 打开作战委托面板
        self.handover_panel_enter()

        # 游戏的「最大」已经受剩余额度限制，补时间必须在拉满或限制次数前进行。
        if auto_supplement and not self.handover_prepare_time(
                count if count > 0 and not (maintain_run or consume_all) else 1,
                oil, use_book=use_book or consume_all):
            self.handover_close_panel()
            return

        # 次数怎么定：维护前拉满 > 一键消耗按委托书数量 > 配置里的次数
        if maintain_run:
            if self.handover_count_max() < 0:
                self.handover_close_panel()
                self.handover_delay()
                return
        elif consume_all:
            book = self.handover_consume_all_book()
            if book < 0:
                self.handover_close_panel()
                self.handover_delay()
                return
            if book == 0:
                # 本次无书可投入时保留每周触发，后续获得委托书后仍可重试。
                self.handover_close_panel()
                self.handover_delay()
                return
        else:
            if not self.handover_set_count(count):
                self.handover_close_panel()
                self.handover_delay()
                return

        consume_partial = False
        if sortie is not None:
            self.device.screenshot()
            selected = OCR_HANDOVER_COUNT.ocr(self.device.image)
            needed = OCR_HANDOVER_TIME_NEEDED.ocr(self.device.image)
            if not (OCR_HANDOVER_COUNT.last_valid and OCR_HANDOVER_TIME_NEEDED.last_valid):
                self.handover_close_panel()
                self.config.task_delay(minute=5)
                return
            allowed = fit_sortie_window(selected, needed, sortie[1], current_time())
            if allowed <= 0:
                self.handover_close_panel()
                self.config.task_delay(target=max(current_time() + timedelta(minutes=2),
                                                  sortie[1] + timedelta(minutes=1)))
                return
            if allowed < selected:
                logger.info(f'[作战委托] 为 {sortie[0]} 留出时间，次数 {selected} -> {allowed}')
                if not self.handover_input_count(allowed):
                    self.handover_close_panel()
                    self.config.task_delay(minute=5)
                    return
                consume_partial = consume_all and not maintain_run

        if consume_partial and not self.handover_book_max():
            self.handover_close_panel()
            self.config.task_delay(minute=5)
            return

        if use_book and not (consume_all and not maintain_run):
            if not self.handover_book_max():
                self.handover_close_panel()
                self.handover_delay()
                return

        # 兑换会实际消耗委托书，必须先确认本次投入后的油量够用。
        self.device.screenshot()
        if not self.handover_oil_enough(oil):
            self.handover_close_panel()
            self.handover_delay()
            return

        # 判断剩余可用时间能否完成委托
        self.device.screenshot()
        needed, remaining = self.handover_get_time()
        actual_count = OCR_HANDOVER_COUNT.ocr(self.device.image)
        if (needed <= timedelta() or actual_count <= 0 or not OCR_HANDOVER_COUNT.last_valid
                or not OCR_HANDOVER_TIME_NEEDED.last_valid or not OCR_HANDOVER_TIME_REMAINING.last_valid):
            self.handover_close_panel()
            self.config.task_delay(minute=5)
            return
        deficit = self.handover_time_deficit(needed, remaining, actual_count)
        if deficit > timedelta():
            if not auto_supplement:
                logger.warning('[作战委托] 剩余可用时间不足以完成委托，且未启用自动补充时间')
                self.handover_close_panel()
                self.handover_delay()
                return
            if not self.handover_exchange_time(deficit, reserve_books=int(use_book or consume_all)):
                self.handover_close_panel()
                self.handover_delay()
                return
            # 兑换弹窗关闭后画面已更新，重新截图供后续使用
            self.device.screenshot()

        # 点「开始」之前用面板上的「预计消耗」核对油量：油不够时游戏不会关面板，
        # 只会在面板里提示「资源不足，无法开始」，面板留在屏幕上会把后面所有
        # 任务的页面识别都带崩
        self.device.screenshot()
        if not self.handover_oil_enough(oil):
            self.handover_close_panel()
            self.handover_delay()
            return

        if not self.handover_start():
            self.handover_close_panel()
            self.handover_delay()
            return

        if not (consume_all or maintain_run):
            with self.config.multi_set():
                self.config.OperationHandover_DailyRunCountUsed = used + 1
                self.config.OperationHandover_DailyRunCountRecord = current_time()

        if consume_all and not maintain_run and not consume_partial:
            self.handover_consume_all_book_record()
        # 记下委托什么时候结束：次数为 0 时靠它回来领奖励，别的任务靠它算推迟多久
        self.handover_commission_set(current_time() + needed)
        self.config.task_delay(minute=needed.total_seconds() / 60)

    def handover_unlock(self):
        """补充完整连续作战记录；船坞满中断时清理后重做，并以入口状态确认解锁。

        Pages:
            in: 关卡页
            out: 关卡页
        """
        if self.campaign.config.MAP_IS_ONE_TIME_STAGE:
            logger.warning('[作战委托] 一次性关卡不尝试补充连续作战记录')
            return False
        for attempt in range(2):
            logger.info('[作战委托] 尚未解锁，先完成一次完整连续作战')
            try:
                self.campaign.run_multiple_sorties(
                    1, oil_limit=self.config.OperationHandover_OilLimit)
            except ScriptEnd as exc:
                logger.warning(f'[作战委托] 连续作战未完成: {exc}')
                self.handover_enter()
                return False
            self.handover_enter()
            support = self.handover_check_support()
            if support is True:
                return True
            if support is None:
                return False
            if not self.campaign.__dict__.get('_multiple_sorties_dock_interrupted', False):
                return False
            if attempt == 0:
                logger.info('[作战委托] 船坞满中断了通关记录，已按周回策略清理，重新完成一次')
        logger.warning('[作战委托] 清理后仍未解锁，停止本轮尝试，避免反复刷图')
        return False

    @staticmethod
    def handover_time_deficit(needed, remaining, count):
        """额度只需覆盖最后一次开始前的消耗，最后一次允许超出剩余额度。"""
        if count <= 0 or needed <= timedelta():
            raise ValueError('委托次数与耗时必须大于零')
        required = needed - needed / count + timedelta(seconds=1)
        return max(required - remaining, timedelta())

    def handover_prepare_time(self, count, oil, use_book=False):
        """先按请求次数检查额度，预留掉落用书和石油后再兑换时间。

        Pages:
            in: 作战委托面板
            out: 作战委托面板
        """
        self.device.screenshot()
        current = OCR_HANDOVER_COUNT.ocr(self.device.image)
        needed, remaining = self.handover_get_time()
        if not (current > 0 and OCR_HANDOVER_COUNT.last_valid and needed > timedelta()
                and OCR_HANDOVER_TIME_NEEDED.last_valid and OCR_HANDOVER_TIME_REMAINING.last_valid):
            self.config.task_delay(minute=5)
            return False
        requested = needed / current * count
        sortie = next_sortie(self.config)
        if sortie is not None:
            allowed = fit_sortie_window(count, requested, sortie[1], current_time())
            if allowed <= 0:
                self.config.task_delay(target=max(current_time() + timedelta(minutes=2),
                                                  sortie[1] + timedelta(minutes=1)))
                return False
            count = allowed
            requested = needed / current * count
        deficit = self.handover_time_deficit(requested, remaining, count)
        if deficit <= timedelta():
            return True
        if use_book:
            if not self.handover_book_max():
                self.handover_delay()
                return False
            books = OCR_HANDOVER_BOOK_COUNT.ocr(self.device.image)
            cost = self.handover_oil_cost()
            if not OCR_HANDOVER_BOOK_COUNT.last_valid or books <= 0 or cost is None:
                self.config.task_delay(minute=5)
                return False
            if oil < math.ceil(cost / books * count):
                logger.warning('[作战委托] 石油不足以支持请求次数，不兑换时间')
                self.handover_delay()
                return False
        if not self.handover_exchange_time(deficit, reserve_books=int(use_book)):
            self.handover_delay()
            return False
        return True

    def handover_enter(self):
        """进入主线或活动关卡页，并按 Fleet 组准备编队。

        进入方式与地图模块 MapOperation.enter_map() 一致：ensure_campaign_ui()
        只切换章节，不会点开关卡节点，必须再点击一次 ENTRANCE 才进得了关卡页。
        编队栏与舰队准备都在关卡页上，不在章节选择页上。

        上一次的委托还在时，进关卡页会弹出「作战委托 INFORM」弹窗，或是先弹出
        阻止页，点它的「查看委托」进弹窗，两种情况都在这里收住，交给 run() 判断
        委托是完成了还是仍在进行。

        上一轮领奖没来得及收干净的结算 / 紧急委托 / 新船入手画面也会挡在这里，
        它们把关卡页整个盖住，下面的页面判断一个都命不中，所以循环里先收掉。

        Pages:
            in: 任意页面
            out: 关卡页 / 作战委托弹窗
        """
        name = to_map_file_name(self.config.Campaign_Name)
        folder = 'campaign_main' if self.stage_is_main(name) else self.config.Campaign_Event
        name = normalize_post_loop_stage(normalize_event_stage(name, folder), folder)
        self.load_campaign(name, folder=folder)
        if folder.startswith('war_archives_'):
            self.campaign.config.override(USE_DATA_KEY=True)

        self.device.screenshot()
        self.campaign.ensure_campaign_ui(name=self.stage, mode='normal', skip_first_screenshot=True)

        campaign_timer = Timer(5)
        fleet_timer = Timer(5)
        while 1:
            self.device.screenshot()

            # 上一轮领奖没来得及收干净的结算、紧急委托、新船入手画面会盖住关卡页，
            # 下面的页面判断一个都命不中，先收掉再往下走
            if self.handover_handle_popup():
                continue

            # 进行中或已完成的委托会挡住难度开关，先交给 run() 处理。
            if self.handover_dialog_appear():
                break
            if self.appear_then_click(HANDOVER_CHECK, offset=(20, 20), interval=3):
                continue

            # 新活动的 A/C、B/D 共用关卡入口。先在准备页确认实际难度，
            # 切换后的新截图才可用于检查委托入口和配置舰队。
            stage_ready = self.appear(HANDOVER_TAB) or self.appear(HANDOVER_TAB_UNSUPPORTED)
            fleet_ready = self.campaign.appear(FLEET_PREPARATION, offset=(20, 50))
            if (stage_ready or fleet_ready) and not self.campaign.handle_map_mode_switch(
                    self.campaign.config.Campaign_Mode):
                self.campaign.map_fleet_checked = False
                continue

            # 舰队准备。与 enter_map() 相同，只有编队准备界面出现时才调用
            # fleet_preparation()，在章节选择页上调用会卡死在 FleetOperator.clear()。
            if fleet_timer.reached() and fleet_ready:
                if not self.campaign.map_fleet_checked:
                    self.campaign.fleet_preparation()
                    self.campaign.map_fleet_checked = True
                fleet_timer.reset()
                campaign_timer.reset()
                continue

            # 已到关卡页
            if stage_ready:
                break

            # 进入关卡
            if campaign_timer.reached() and self.campaign.appear_then_click(self.campaign.ENTRANCE):
                campaign_timer.reset()
                continue

        logger.info('[作战委托] 已进入关卡页')

    def handover_dialog_appear(self):
        """「作战委托 INFORM」弹窗是否出现。

        弹窗里显示委托的剩余时间与完成次数，底部按钮是「领取奖励」（已完成）或
        「终止作战」（仍在进行），用它判断委托做完了没有。

        Returns:
            bool: 弹窗出现返回 True。
        """
        return (
            self.appear(HANDOVER_PASS_CLICK, offset=(20, 20))
            or self.appear(HANDOVER_STOP_CHECK, offset=(20, 20))
        )

    def handover_handle_popup(self):
        """处理委托结束后会连着冒出来的一串画面。

        委托做完的那一下游戏按顺序弹好几屏：合计获得奖励的结算、紧急委托提示、
        新船入手演出。它们都会盖住关卡页，而卡死检测只看画面有没有变化——认不出来
        就一直空转到 GameStuckError，所以领奖和进关卡两条路都要先把它们收掉。

        Returns:
            bool: 处理了画面返回 True，调用方应重新截图。
        """
        if self.handle_handover_help():
            return True
        if self.appear(MULTIPLE_SORTIES_RESULT_CHECK, offset=(20, 20)):
            return self.appear_then_click(MULTIPLE_SORTIES_RESULT_EXIT, offset=(20, 20), interval=2)

        # 委托结算「合计获得奖励」，点「确定」收起
        if self.appear(HANDOVER_REWARD_CHECK, offset=(20, 20)):
            return self.appear_then_click(HANDOVER_REWARD, offset=(20, 20), interval=3)

        # 紧急委托提示「出现紧急委托《XXX》」，点「确定」收起
        if self.handle_urgent_commission():
            return True

        # 新船入手演出的 SKIP。底条是半透明的，船的稀有度不同、底下的立绘不同，
        # 底色就跟着变；归一化模板匹配本身会减掉整体底色偏移，这里再把阈值放宽一点
        # 兜住立绘的渐变（其它画面实测都在 0.16 以下，放宽不会误判）
        if self.appear_then_click(NEW_SHIP_SKIP, offset=(20, 20), interval=2, similarity=0.75):
            return True

        return False

    def handle_handover_help(self):
        """关闭首次进入时的说明；滚动条同时确认，避免误关委托冲突弹窗。"""
        if (self.appear(HANDOVER_HELP_CHECK, offset=(20, 20))
                and self.image_color_count(HANDOVER_HELP_SCROLL.area,
                                           color=(255, 215, 74), threshold=45, count=30)):
            return self.appear_then_click(HANDOVER_HELP_CLOSE, offset=(20, 20), interval=2)
        return False

    def handover_check_support(self):
        """检测当前关卡是否支持作战委托。

        HANDOVER_TAB 与 HANDOVER_TAB_UNSUPPORTED 的区域完全相同，只有填充色不同，
        因此用颜色判定区分。

        Returns:
            bool | None: 支持返回 True，稳定的灰色入口返回 False，未确认入口返回 None。
        """
        unsupported = Timer(0.8, count=2).start()
        timeout = Timer(4).start()
        while True:
            self.device.screenshot()
            if self.appear(HANDOVER_TAB):
                logger.info('[作战委托] 该关卡支持作战委托')
                return True
            if self.appear(HANDOVER_TAB_UNSUPPORTED):
                if unsupported.reached():
                    logger.warning('[作战委托] 该关卡尚未启用作战委托')
                    return False
            else:
                unsupported.reset()
            if timeout.reached():
                logger.warning('[作战委托] 未确认作战委托入口，稍后重试')
                return None

    def handover_panel_appear(self):
        """作战委托设置面板是否已打开。

        「最大」按钮只在面板内出现，用它作为面板标志物。该按钮与次数加号等
        按钮颜色相同，因此必须用模板匹配而不是颜色判定。

        Returns:
            bool: 面板已打开返回 True。
        """
        return self.appear(HANDOVER_COUNT_MAX, offset=(20, 20))

    def handover_panel_enter(self, skip_first_screenshot=True):
        """点击作战委托入口，打开作战委托面板。

        Pages: in: 关卡页, out: 作战委托面板
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handover_panel_appear():
                break

            if self.handle_handover_help():
                continue

            if self.appear_then_click(HANDOVER_TAB, interval=2):
                continue

        logger.info('[作战委托] 已打开作战委托面板')

    def handover_reward(self):
        """领取上一次已完成委托的奖励。

        委托完成后弹窗底部的按钮是「领取奖励」。点击后游戏会连着弹一串画面：
        「合计获得奖励」的结算、紧急委托提示、新船入手演出，再加上大讲堂熟练度
        溢出之类的通用信息弹窗。全部收掉后游戏退回章节选择页，关卡入口按钮重新
        出现，此时才算领完。

        Pages: in: 作战委托弹窗, out: 章节选择页

        Returns:
            bool: 本次领取了奖励返回 True。
        """
        self.device.screenshot()
        if not self.appear(HANDOVER_PASS_CLICK, offset=(20, 20)):
            return False

        logger.info('[作战委托] 上一次的委托已完成，领取奖励')
        # 结算弹窗是半透明的，点完「领取奖励」到它真正出现之间会有一帧露出底下的
        # 章节选择页。看一眼关卡入口就收工会赶在弹窗出现之前退出，把弹窗留在屏幕上
        # 把后面所有任务带崩，所以要求连续两帧以上、且持续 0.6 秒都只剩章节选择页
        # 才算真的领完
        settled = Timer(0.6, count=1).start()
        reward_confirmed = False
        while 1:
            self.device.screenshot()

            # 领取结算界面、紧急委托提示、新船入手演出
            settlement = (self.appear(HANDOVER_REWARD_CHECK, offset=(20, 20))
                          and not self.appear(MULTIPLE_SORTIES_RESULT_CHECK, offset=(20, 20)))
            if self.handover_handle_popup():
                reward_confirmed |= settlement
                settled.reset()
                continue

            # 大讲堂熟练度溢出等通用信息弹窗
            if self.handle_popup_confirm('HANDOVER'):
                settled.reset()
                continue

            # 弹窗上的按钮先判，保证弹窗还在时不会误判成已经退回章节选择页
            if self.appear_then_click(HANDOVER_PASS_CLICK, offset=(20, 20), interval=3):
                settled.reset()
                continue

            # 领取后可能先露出章节页，再播放新船和总奖励；必须确认已收起总奖励。
            if not reward_confirmed:
                continue

            # 退回章节选择页，关卡入口重新出现，委托已经没有了
            if self.campaign.appear(self.campaign.ENTRANCE):
                if settled.reached():
                    break
                continue

            # 关卡页
            if self.appear(HANDOVER_TAB) or self.appear(HANDOVER_TAB_UNSUPPORTED):
                if settled.reached():
                    break
                continue

            settled.reset()

        logger.info('[作战委托] 已领取委托奖励')
        return True

    def handover_set_count(self, count):
        """把委托次数设置到指定值。

        先确认游戏当前的最大次数，再通过输入框设置并回读，避免向不可达的值连点。

        Args:
            count (int): 目标委托次数。

        Returns:
            bool: 设置后回读与实际目标一致。
        """
        maximum = self.handover_count_max()
        if maximum <= 0:
            return False
        target = min(max(count, 0), maximum)
        if target != count:
            logger.info(f'[作战委托] 次数 {count} 超过当前上限，改用 {target}')
        return self.handover_input_count(target)

    def handover_get_time(self):
        """识别委托需要的时间和当天剩余可用时间。

        Returns:
            tuple[timedelta, timedelta]: (需要时间, 剩余可用时间)。
        """
        needed = OCR_HANDOVER_TIME_NEEDED.ocr(self.device.image)
        remaining = OCR_HANDOVER_TIME_REMAINING.ocr(self.device.image)
        logger.attr('需要时间', needed)
        logger.attr('剩余可用时间', remaining)
        return needed, remaining

    def handover_exchange_time(self, deficit, reserve_books=0):
        """用作战全权委托书兑换可用时间。

        Pages: in: 作战委托面板, out: 作战委托面板

        Args:
            deficit (timedelta): 缺少的时间。
            reserve_books (int): 兑换后至少保留的掉落用委托书。

        Returns:
            bool: 兑换成功返回 True。
        """
        need = math.ceil(deficit.total_seconds() / HANDOVER_BOOK_SECONDS)
        logger.info(f'[作战委托] 剩余时间不足，需补充 {need} 小时，即 {need} 本作战全权委托书')

        before = OCR_HANDOVER_TIME_REMAINING.ocr(self.device.image)
        if not OCR_HANDOVER_TIME_REMAINING.last_valid:
            return False
        expected = before + timedelta(hours=need)
        inventory_checked = False
        cancelled = False
        confirmed = False
        timeout = Timer(20).start()
        while True:
            self.device.screenshot()
            if timeout.reached():
                raise GameStuckError('[作战委托] 兑换时间后未确认额度变化')
            if self.handover_panel_appear():
                if cancelled:
                    return False
                if confirmed:
                    remaining = OCR_HANDOVER_TIME_REMAINING.ocr(self.device.image)
                    if OCR_HANDOVER_TIME_REMAINING.last_valid and remaining >= expected:
                        logger.info(f'[作战委托] 已确认补充 {need} 小时可用时间')
                        return True
                    continue
                if self.appear_then_click(HANDOVER_EXCHANGE_TIME, interval=2):
                    continue
            if self.appear(HANDOVER_EXCHANGE_CHECK, offset=(20, 20)):
                if not inventory_checked:
                    current = OCR_HANDOVER_BOOK_AMOUNT.ocr(self.device.image)
                    if not OCR_HANDOVER_BOOK_AMOUNT.last_valid:
                        continue
                    inventory_checked = True
                    cancelled = current < need + reserve_books
                    logger.attr('作战全权委托书', f'持有 {current}，兑换需要 {need}，保留 {reserve_books}')
                if cancelled:
                    if self.handle_popup_cancel('HANDOVER'):
                        continue
                else:
                    selected = OCR_HANDOVER_EXCHANGE_ADDED.ocr(self.device.image)
                    if not OCR_HANDOVER_EXCHANGE_ADDED.last_valid:
                        continue
                    if selected < timedelta(hours=need):
                        if self.appear_then_click(HANDOVER_BOOK_ITEM, offset=(20, 20), interval=1):
                            continue
                    elif selected > timedelta(hours=need):
                        cancelled = True
                    elif self.handle_popup_confirm('HANDOVER'):
                        confirmed = True
                        continue
            elif confirmed and self.handle_popup_confirm('HANDOVER'):
                continue

    def handover_click_until_stable(self, button, ocr, name):
        """反复点同一个按钮，直到数值不再变化。

        至少两次实际点击后，要求有效 OCR 数值持续稳定，避免把延迟反馈当成上限。

        Args:
            button (Button): 要点的按钮，比如「最大」或减号。
            ocr (Ocr): 读取当前数值的 OCR。
            name (str): 日志里显示的名字。

        Returns:
            int: 最终数值，未找到按钮返回 -1。
        """
        if not self.appear(button, offset=(20, 20)):
            logger.warning(f'[作战委托] 未找到{name}的按钮')
            return -1

        value = -1
        clicks = 0
        stable = Timer(0.6, count=2).start()
        timeout = Timer(12).start()
        while 1:
            self.device.screenshot()
            if timeout.reached():
                logger.warning(f'[作战委托] 未能确认{name}，停止本次设置')
                return -1
            current = ocr.ocr(self.device.image)
            if not getattr(ocr, 'last_valid', True):
                stable.reset()
                continue
            if current != value:
                value = current
                stable.reset()
            if clicks >= 2 and stable.reached():
                break
            if self.appear_then_click(button, offset=(20, 20), interval=2):
                clicks += 1
                stable.reset()
                continue

        logger.attr(name, value)
        return value

    def handover_book_max(self):
        """把作战全权委托书的投入量拉到最大。

        Pages: in: 作战委托面板

        Returns:
            bool: 找到并使用「最大」按钮返回 True。
        """
        count = self.handover_click_until_stable(
            HANDOVER_BOOK_MAX, OCR_HANDOVER_BOOK_COUNT, '投入作战全权委托书')
        if count == 0:
            logger.warning('[作战委托] 没有可投入的委托书，本次不启动仅熟练度委托')
        return count > 0

    def handover_count_max(self):
        """把作战次数拉到最大。

        Pages: in: 作战委托面板

        Returns:
            int: 拉满后的作战次数，失败返回 -1。
        """
        return self.handover_click_until_stable(HANDOVER_COUNT_MAX, OCR_HANDOVER_COUNT, '作战次数(最大)')

    def handover_input_count(self, count):
        """用输入法把作战次数改成指定值。

        点一下次数文本框聚焦，把原来的数字删掉再输入新值，最后回车收起输入法。
        输入法弹出来会挡住面板下半屏，所以输入完要等它收起来再截图。

        这里用颜色判定而不是模板匹配：框里的数字是每次都会变的，模板里带着数字
        就只会在数字刚好一样时才命中。

        Pages: in: 作战委托面板

        Args:
            count (int): 目标作战次数。

        Returns:
            bool: 输入后读回的次数正确返回 True。
        """
        self.device.screenshot()
        if not self.appear(HANDOVER_COUNT_INPUT):
            logger.warning('[作战委托] 未找到作战次数输入框')
            return False

        self.appear_then_click(HANDOVER_COUNT_INPUT)
        self.device.sleep(0.5)

        text = str(count)
        clear = ' '.join(['KEYCODE_DEL'] * (len(text) + 10))
        self.device.adb_shell(f'input keyevent KEYCODE_MOVE_END {clear}', timeout=5)
        self.device.adb_shell(f'input text {text}', timeout=5)
        self.device.adb_shell('input keyevent KEYCODE_ENTER', timeout=1)

        # 等输入法收起来再核对，最多等 5 秒
        timeout = Timer(5).start()
        while 1:
            self.device.screenshot()
            current = OCR_HANDOVER_COUNT.ocr(self.device.image)
            if current == count:
                logger.attr('作战次数(输入后)', current)
                return True
            if timeout.reached():
                logger.warning(f'[作战委托] 作战次数输入失败，期望 {count}，识别到 {current}')
                return False

    def handover_consume_all_book(self):
        """一键消耗作战全权委托书。

        作战次数拉满 → 使用委托书拉满 → 读出投入的委托书数量 → 把作战次数改成
        这个数量，让这次委托正好把委托书用光。

        Pages: in: 作战委托面板, out: 作战委托面板

        Returns:
            int: 设置好的作战次数；没有可投入的委托书返回 0；界面操作失败返回 -1。
        """
        # 作战次数先拉满：使用委托书的上限受作战次数限制，次数太小委托书拉不满
        if self.handover_count_max() < 0:
            return -1

        # 委托书拉满后的数值，就是要设置的作战次数
        book = self.handover_click_until_stable(HANDOVER_BOOK_MAX, OCR_HANDOVER_BOOK_COUNT,
                                       '投入作战全权委托书')
        if book < 0:
            return -1
        if book == 0:
            logger.warning('[作战委托] 没有可投入的作战全权委托书')
            return 0

        if not self.handover_input_count(book):
            return -1
        return book

    @staticmethod
    def handover_week_key(time):
        """把时间换算成「年+周数」字符串，用来判断本周是否已经触发过。

        Args:
            time (datetime.datetime): 时间。

        Returns:
            str: 如 `2026W37`。
        """
        year, week, _ = time.isocalendar()
        return f'{year}W{week:02d}'

    def handover_consume_all_book_record_key(self):
        """读回本周一键消耗的记录，统一成周 key 再比较。

        配置系统写盘前会把字符串交给 datetime.fromisoformat()，而 `2026W37` 正好
        是 ISO 周日期格式（Python 3.11+ 支持），于是它在磁盘上变成了那一周周一的
        datetime。拿它和字符串比永远不会相等，同一周会被反复当成「还没触发过」，
        所以这里先按类型还原成周 key。

        Returns:
            str: 记录的周 key，没有记录时返回原值的字符串形式。
        """
        record = self.config.OperationHandover_ConsumeAllBookRecord
        if isinstance(record, datetime):
            return self.handover_week_key(record)
        return str(record)

    def handover_maintain_query(self):
        """查询停服维护接口，取出当前游戏服务器的那一份公告。

        使用 v2 按当前区服查询，RFC 3339 时间转换为当前区服时区。
        其他区服没有计划时返回空结果，不退回国服公告。

        Returns:
            tuple[dict | None, datetime.timedelta, str]:
                (维护公告, 公告时间所用的兜底时区, 失败原因)。取不到公告时公告为 None。
        """
        server = self.config.SERVER
        try:
            result = http.get(HANDOVER_MAINTAIN_API, params={'server': server},
                                  headers={'X-AzurPilot-ID': get_device_id()}, timeout=10)
            result.raise_for_status()
            response = result.json()
            if response.get('schema_version') != 2 or response.get('server') != server or 'maintenance' not in response:
                raise ValueError('维护接口返回了无效或其他区服的数据')
            plan = response['maintenance']
            default = SERVER_TO_TIMEZONE.get(server, SERVER_TO_TIMEZONE['cn'])
            if plan is None:
                return {}, default, ''
            at = datetime.fromisoformat(plan['starts_at'].replace('Z', '+00:00'))
            if at.tzinfo is None:
                raise ValueError('维护时间缺少时区')
            at = at.astimezone(timezone(default))
            minutes = int(default.total_seconds() / 60)
            sign = '+' if minutes >= 0 else '-'
            absolute = abs(minutes)
            tz = f'UTC{sign}{absolute // 60}' + (f':{absolute % 60:02d}' if absolute % 60 else '')
            return {'maintenance_date': at.strftime('%Y-%m-%d'), 'start_time': at.strftime('%H:%M'),
                    'timezone': tz, 'name': plan.get('name', server)}, default, ''
        except Exception as e:
            logger.warning(f'[作战委托] 查询维护时间失败，按不维护处理: {e}')
            return None, timedelta(), '查询维护时间失败'

    def handover_maintain_timezone(self, payload, default):
        """解析维护公告所用的服务器时区。

        接口在每条服务器公告里给了 timezone（如 `UTC+8`），以它为准；缺失或者
        格式不认识时用兜底时区。

        Args:
            payload (dict): 一条服务器维护公告。
            default (datetime.timedelta): 兜底时区偏移。

        Returns:
            datetime.timedelta: 相对 UTC 的时区偏移。
        """
        text = str(payload.get('timezone', '')).strip().upper()
        match = HANDOVER_MAINTAIN_TIMEZONE.match(text)
        if not match:
            logger.warning(f'[作战委托] 无法识别的服务器时区 {text!r}，按 {default} 处理')
            return default

        offset = timedelta(hours=int(match.group(2)), minutes=int(match.group(3) or 0))
        return offset if match.group(1) == '+' else -offset

    def handover_maintain_state(self):
        """今天有没有停服维护，有的话返回维护开始时间（可能已经开始）。

        数据来自统一云 API，按当前游戏服务器取对应公告，公告里的服务器本地
        时间先换算成本机时间。不是今天的维护一律返回 None；今天已经开始的维护仍然
        返回时间，好让调用方区分「今天没事了」和「等维护」。

        Returns:
            tuple[datetime.datetime | None, str, bool]:
                (今天的维护开始时间, 原因, 这次有没有成功查到公告)。
                没查到公告时第三个值为 False，调用方应过一会儿再查，而不是当成
                「今天没有维护」直接等到明天。
        """
        if not self.config.OperationHandover_MaintainOverride:
            return None, '开关未开启', False

        payload, default, error = self.handover_maintain_query()
        if payload is None:
            return None, error, False
        if not payload:
            return None, '未发布维护安排', True

        try:
            start = datetime.strptime(
                f"{payload.get('maintenance_date', '')} {payload.get('start_time', '')}",
                '%Y-%m-%d %H:%M')
        except ValueError:
            logger.warning(f'[作战委托] 维护公告时间无法识别，按不维护处理: '
                           f"{payload.get('maintenance_date')} {payload.get('start_time')}")
            return None, '维护公告时间无法识别', False

        # 服务器本地时间 → 本机时间，后续调度用的都是本机时间
        offset = self.handover_maintain_timezone(payload, default)
        start = start.replace(tzinfo=timezone(offset)).astimezone().replace(tzinfo=None)

        now = current_time()
        if start.date() != now.date():
            if start < now:
                return None, f'{start} 已经过去', True
            return None, f'下次维护 {start}，不是今天', True
        if start <= now:
            return start, f'今天 {start} 的维护已经过去', True

        name = payload.get('name') or self.config.SERVER
        lead_minutes = int(read_run_param(
            self.config, 'Handover_MaintainLeadMinutes',
            HANDOVER_MAINTAIN_LEAD_MINUTES, 2, 60))
        return start, (f'今天 {start} 停服维护（{name}），'
                       f'维护前 {lead_minutes} 分钟运行'), True

    def handover_commission_end(self):
        """脚本上一次开的委托预计什么时候结束。

        这个时间是自己开委托时按「需要时间」记下来的，用于判断该不该回来领奖励，
        以及委托期间该把别的任务推迟到什么时候。手动在游戏里开的委托脚本不知道，
        会一直返回 HANDOVER_COMMISSION_NONE。

        Returns:
            datetime.datetime: 结束时间；手上没有委托时返回 HANDOVER_COMMISSION_NONE。
        """
        end = self.config.OperationHandover_CommissionEnd
        if not isinstance(end, datetime):
            return HANDOVER_COMMISSION_NONE
        return end

    def handover_commission_set(self, end):
        """记下这次委托什么时候结束。

        Args:
            end (datetime.datetime): 委托预计结束时间。
        """
        self.config.OperationHandover_CommissionEnd = end
        logger.attr('委托预计结束', end)

    def handover_commission_clear(self):
        """清掉委托结束时间，表示手上已经没有委托了。"""
        self.config.OperationHandover_CommissionEnd = HANDOVER_COMMISSION_NONE

    def handover_idle_time(self, maintain, maintain_queried=True):
        """委托次数为 0、手上没有委托时，下一次该在什么时候看一眼。

        两头取早的：一键消耗的触发时刻，以及维护检查。维护检查成功查到公告、
        今天又没有还没开始的维护时，今天就不必再看，排到第二天 0 点；
        没查到公告（网络失败、接口没有该服数据）才隔
        HANDOVER_MAINTAIN_CHECK_MINUTES 分钟重试。

        Args:
            maintain (datetime.datetime | None): 今天的维护开始时间，没有则为 None。
            maintain_queried (bool): 这次有没有成功查到维护公告。

        Returns:
            datetime.datetime | None: 下一次运行时间；两个开关都没开时返回 None。
        """
        now = current_time()
        candidates = []

        if self.config.OperationHandover_ConsumeAllBook:
            target = self.handover_consume_all_book_next_time()
            if target is not None:
                candidates.append(target)

        if self.config.OperationHandover_MaintainOverride:
            if maintain_queried:
                # 公告查到了，今天要么没有维护、要么维护已经开始，今天不用再看
                candidates.append(
                    (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
            else:
                candidates.append(now + timedelta(minutes=int(read_run_param(
                    self.config, 'Handover_MaintainCheckMinutes',
                    HANDOVER_MAINTAIN_CHECK_MINUTES, 15, 720))))

        if not candidates:
            return None
        return min(candidates)

    def handover_idle_delay(self, maintain, maintain_queried=True):
        """委托次数为 0、手上没有委托时，把下一次运行排到该看的时间点。

        Args:
            maintain (datetime.datetime | None): 今天的维护开始时间，没有则为 None。
            maintain_queried (bool): 这次有没有成功查到维护公告。
        """
        target = self.handover_idle_time(maintain, maintain_queried)
        if target is None:
            logger.warning('[作战委托] 委托次数为 0，但读不到下一次运行时间，按普通间隔重试')
            self.handover_delay()
            return
        logger.info(f'[作战委托] 委托次数为 0，手上没有委托，下次运行 {target}')
        self.config.task_delay(target=target)

    def handover_consume_all_book_trigger(self):
        """解析一键消耗委托书的触发配置。

        Returns:
            tuple[int, int, int] | None: (周几, 时, 分)，配置不合法返回 None。
        """
        weekday = self.config.OperationHandover_ConsumeAllBookWeekday
        if weekday not in HANDOVER_WEEKDAYS:
            logger.warning(f'[作战委托] 无法识别的星期: {weekday}')
            return None

        trigger = str(self.config.OperationHandover_ConsumeAllBookTime)
        try:
            hour, minute = [int(part) for part in trigger.split(':')[:2]]
            if not 0 <= hour < 24 or not 0 <= minute < 60:
                raise ValueError
        except ValueError:
            logger.warning(f'[作战委托] 无法识别的触发时间: {trigger}')
            return None

        return HANDOVER_WEEKDAYS.index(weekday), hour, minute

    def handover_consume_all_book_state(self):
        """当前该不该执行一键消耗委托书，以及不执行的原因。

        周几和几点几分由用户配置，本周成功触发过一次就不再触发。委托没开起来
        （比如触发时正好有委托在进行）不算触发过，下一次运行会接着试。

        Returns:
            tuple[bool, str]: (是否执行, 不执行的原因)。
        """
        if not self.config.OperationHandover_ConsumeAllBook:
            return False, '开关未开启'

        now = current_time()
        if self.handover_consume_all_book_record_key() == self.handover_week_key(now):
            return False, '本周已处理过'

        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return False, '触发日或触发时间配置不合法'
        weekday, hour, minute = trigger

        if now.weekday() != weekday:
            name = HANDOVER_WEEKDAY_NAMES[weekday]
            if now.weekday() < weekday:
                return False, f'还没到{name}'
            else:
                return False, f'{name}已经过了，等下周'

        if (now.hour, now.minute) < (hour, minute):
            return False, f'还没到触发时间 {hour:02d}:{minute:02d}'

        return True, ''

    def handover_consume_all_book_waiting(self):
        """一键消耗委托书今天还有机会触发吗。

        今天就是触发日、本周又还没触发过时，本次没开成委托也不能把任务推迟到
        次日——次日已经过了触发日，这一周的一键消耗就整个没了。

        Returns:
            bool: 应该稍后重试而不是等次日返回 True。
        """
        if not self.config.OperationHandover_ConsumeAllBook:
            return False

        now = current_time()
        if self.handover_consume_all_book_record_key() == self.handover_week_key(now):
            return False

        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return False
        return now.weekday() == trigger[0]

    def handover_consume_all_book_next_time(self):
        """下一次一键消耗委托书的触发时刻。

        委托次数为 0 时用这个时间当下一次运行时间，中间不用进游戏。今天就是
        触发日但时间已经过了（或者本周已经触发过）时顺延到下周。

        Returns:
            datetime.datetime | None: 下一次触发时刻，触发配置不合法返回 None。
        """
        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return None

        weekday, hour, minute = trigger
        now = current_time()
        target = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=7)
        return target

    def handover_consume_all_book_record(self, reason='已完成'):
        """记下本周的一键消耗不用再试了。

        记录同时覆盖两种收场：真的把委托书消耗掉了，以及触发时手上没有可投入的
        委托书——后者本周再试也不会有结果。存的是执行时刻（配置项里可见、可改），
        判断「是不是本周」时再还原成周 key。

        Args:
            reason (str): 收场方式，写进日志。
        """
        now = current_time().replace(microsecond=0)
        self.config.OperationHandover_ConsumeAllBookRecord = now
        logger.info(f'[作战委托] 本周一键消耗委托书{reason}，'
                    f'记录 {now}（{self.handover_week_key(now)}）')

    def handover_consume_all_book_give_up(self, reason, maintain=None, maintain_queried=True):
        """一键消耗开不成委托，而且当天再试也没有意义：本周不再尝试。

        作战全权委托书不会当天补货，石油也不像能靠等几十分钟凑齐，所以不按
        HANDOVER_CONSUME_RETRY_MINUTES 反复重试——每次重试都要重新进一次游戏，
        白占别人的出击时间。记下本周的收场，按定时功能排下一次运行。

        Args:
            reason (str): 放弃本周的原因，写进日志。
            maintain (datetime.datetime | None): 今天的维护开始时间，没有则为 None。
            maintain_queried (bool): 这次有没有成功查到维护公告。
        """
        logger.warning(f'[作战委托] 一键消耗委托书{reason}，本周不再尝试')
        self.handover_consume_all_book_record(reason)
        # 走到这里说明上一次的委托已经不在了（还在做会从上面的 HANDOVER_STOP_CHECK 返回）
        self.handover_commission_clear()
        self.handover_idle_delay(maintain, maintain_queried)

    def handover_oil_cost(self):
        """识别面板上的「预计消耗」石油数量。

        额外油耗以绿色或红色显示。只识别数字，避免把油桶图标拼成额外的 1。

        Pages: in: 作战委托面板

        Returns:
            int | None: 预计消耗石油；无委托书时为 0，无法确认时返回 None。
        """
        books = OCR_HANDOVER_BOOK_COUNT.ocr(self.device.image)
        if not OCR_HANDOVER_BOOK_COUNT.last_valid:
            return None
        if books == 0:
            return 0
        cost = OCR_HANDOVER_OIL_COST.ocr(self.device.image)
        if not OCR_HANDOVER_OIL_COST.last_valid or cost <= 0:
            logger.warning('[作战委托] 未识别到有效的额外油耗')
            return None
        return cost

    def handover_oil_enough(self, oil):
        """点「开始」之前，用面板上的「预计消耗」核对油量。

        Args:
            oil (int): 打开面板之前读到的石油数量。

        Returns:
            bool: 已确认无额外油耗，或当前石油足够时返回 True。
        """
        cost = self.handover_oil_cost()
        logger.attr('预计消耗石油', cost)
        if cost is None:
            logger.warning('[作战委托] 未确认预计油耗，本次不启动或兑换时间')
            return False
        if oil < cost:
            logger.warning(f'[作战委托] 石油不足，需要 {cost}，当前 {oil}')
            return False
        return True

    def handover_close_panel(self, skip_first_screenshot=True):
        """关掉作战委托面板，回到关卡页。

        面板留在屏幕上会让后面所有任务的页面识别都失败，所以每个「本次不开始
        委托」的出口都要先把面板关掉。

        Pages: in: 作战委托面板, out: 关卡页
        """
        timeout = Timer(10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(HANDOVER_TAB) or self.appear(HANDOVER_TAB_UNSUPPORTED):
                logger.info('[作战委托] 已关闭作战委托面板')
                return

            if timeout.reached():
                raise GameStuckError('[作战委托] 无法确认已回到关卡页')

            if self.appear_then_click(HANDOVER_PANEL_CLOSE, offset=(20, 20), interval=2):
                continue

    def handover_start(self, skip_first_screenshot=True):
        """点击「开始」，并确认委托真的开起来了。

        返回章节页后重新进入原关卡，以进行中或已完成的委托详情确认成功。
        未看到详情时，不更新结束时间或本周消耗记录。

        Pages: in: 作战委托面板, out: 章节选择页

        Returns:
            bool: 委托已开始返回 True。
        """
        clicked = False
        verified = False
        timeout = Timer(15).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_popup_confirm('HANDOVER_START'):
                continue

            if timeout.reached():
                logger.warning('[作战委托] 未确认委托启动成功')
                return False

            if clicked and self.handover_dialog_appear():
                verified = True
                if self.appear_then_click(HANDOVER_DIALOG_CLOSE, offset=(20, 20), interval=2):
                    continue

            # 开始后返回章节页，再进入原关卡，以委托详情正向验证启动结果。
            if clicked and self.campaign.appear(self.campaign.ENTRANCE):
                if verified:
                    logger.info('[作战委托] 已确认委托详情，启动成功')
                    return True
                if self.campaign.appear_then_click(self.campaign.ENTRANCE, interval=2):
                    continue

            if self.handover_panel_appear() and self.appear_then_click(
                    HANDOVER_START_CLICK, offset=(20, 20), interval=3):
                if not clicked:
                    clicked = True
                    timeout.reset()
                continue

    def handover_delay(self, delay=None):
        """本次无法开始委托，推迟下次运行。

        作战委托的可用时间额度每天 0 点重置，因此没开始委托时统一推迟到次日。
        但一键消耗委托书如果今天才轮到触发、本周又还没触发过，就不能跳到次日
        （次日已经过了触发日），改成隔一段时间重试。

        Args:
            delay (timedelta): 进行中委托的剩余时间。None 表示本次未开始委托。
        """
        if delay is None:
            if self.handover_consume_all_book_waiting():
                consume_retry = int(read_run_param(
                    self.config, 'Handover_ConsumeRetryMinutes',
                    HANDOVER_CONSUME_RETRY_MINUTES, 5, 240))
                logger.warning(f'[作战委托] 本次未开始委托，一键消耗委托书今天还没触发，'
                               f'{consume_retry} 分钟后再试')
                self.config.task_delay(minute=consume_retry)
            else:
                logger.warning('[作战委托] 本次未开始委托，推迟到下一个可用时间额度刷新')
                self.config.task_delay(server_update=True)
        else:
            logger.info(f'[作战委托] 委托仍在进行，{delay} 后回来领取奖励')
            self.config.task_delay(minute=delay.total_seconds() / 60)
