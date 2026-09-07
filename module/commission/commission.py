"""委托任务执行模块。

负责碧蓝航线委托系统的自动化处理，包括委托奖励领取、委托检测、
委托选择过滤、委托启动以及奖励收入统计。支持每日委托和紧急委托
两大类别，通过 OCR 和图像匹配识别委托信息，并根据用户配置的
过滤规则自动选择最优委托组合。

主要流程：
    1. 从奖励页面进入委托页面
    2. 领取已完成的委托奖励（commission_receive）
    3. 扫描当前所有委托列表（_commission_scan_all）
    4. 根据过滤规则选择待启动的委托（_commission_choose）
    5. 逐一查找并启动选中的委托（commission_start）
    6. 根据运行中委托的完成时间计算下次调度

依赖：
    - module.commission.project: 委托信息解析（Commission 类）
    - module.commission.preset: 预设过滤规则
    - module.ui.ui: 页面导航
    - module.handler.info_handler: 弹窗/信息栏处理
"""

import copy
from datetime import timedelta

from scipy import signal

from module.base.timer import Timer
from module.base.utils import *
from module.combat.assets import *
from module.commission.assets import *
from module.commission.planner import (
    DEFAULT_VALUE_MODEL,
    CommissionPlanJob,
    CommissionValueModel,
    optimize_commission_plan,
)
from module.commission.preset import DICT_FILTER_PRESET, SHORTEST_FILTER
from module.commission.project import COMMISSION_FILTER, Commission
from module.config.config_generated import GeneratedConfig
from module.config.time_source import now as current_time
from module.config.utils import get_server_last_update, get_server_next_update, nearest_future
from module.dorm.dorm import RewardDorm
from module.exception import GameStuckError, OilMaxed, RequestHumanTakeover
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.notify.notify import handle_notify, notify_webui
from module.map.map_grids import SelectedGrids
from module.retire.assets import DOCK_CHECK
from module.statistics.item import AmountOcr
from module.ui.assets import BACK_ARROW, REWARD_GOTO_COMMISSION
from module.tactical.assets import TACTICAL_CLASS_START, TACTICAL_CLASS_CANCEL
from module.ui.page import page_commission, page_reward
from module.ui.scroll import Scroll
from module.ui.switch import Switch
from module.ui.ui import UI
from module.ui_white.assets import REWARD_1_WHITE, REWARD_GOTO_COMMISSION_WHITE

COMMISSION_SWITCH = Switch('Commission_switch', is_selector=True)
COMMISSION_SWITCH.add_state('daily', COMMISSION_DAILY)
COMMISSION_SWITCH.add_state('urgent', COMMISSION_URGENT)
COMMISSION_SCROLL = Scroll(COMMISSION_SCROLL_AREA, color=(247, 211, 66), name='COMMISSION_SCROLL')

# 委托收益截图保留张数：与统计页「最近委托记录」的 50 条上限保持一致
COMMISSION_REWARD_SCREENSHOT_KEEP = 50


class CommissionAmount(AmountOcr):
    """委托收益数量 OCR：碎片过滤 + 2 倍放大 + 裁剪。

    委托页数字很小（高约 14px），直接识别时两处系统性误读：
    - 不裁剪时右缘被截断的数字会被丢掉（71 → 7）；
    - 裁剪后原尺寸下两个 7 会丢掉一个（77 → 7）。
    实测「裁剪 + 放大 2 倍」后 71/77/97/13 等读数全部正确。
    """
    remove_fragments = True

    def pre_process(self, image):
        import cv2

        image = cv2.resize(image, (0, 0), fx=2, fy=2, interpolation=2)
        return super().pre_process(image)


def lines_detect(image):
    """检测委托列表中各委托条目底部的白色分割线位置。

    通过分析截图中分割线区域（x: 597-619）的灰度均值，
    使用 scipy.signal.find_peaks 定位白色线条的 Y 坐标。

    Args:
        image (np.ndarray): 游戏截图。

    Returns:
        np.ndarray: 每个委托下方白色分割线的 Y 坐标数组。
    """
    # 通过查找每个委托下方的白色分割线来定位委托位置。
    # (597, 0, 619, 720) 是只有白色分割线的区域。
    color_height = np.mean(rgb2gray(crop(image, (597, 0, 619, 720), copy=False)), axis=1)
    parameters = {'height': 200, 'distance': 100}
    peaks, _ = signal.find_peaks(color_height, **parameters)
    # 67 是委托列表头部的高度
    # 117 是单个委托卡片的高度。
    peaks = [y for y in peaks if y > 67 + 117]
    return np.array(peaks)


class RewardCommission(UI, InfoHandler):
    """委托任务处理器。

    继承 UI 和 InfoHandler，负责委托系统的完整自动化流程，
    包括委托检测、过滤选择、启动执行和奖励领取。

    Attributes:
        daily (SelectedGrids): 当前扫描到的每日委托列表。
        urgent (SelectedGrids): 当前扫描到的紧急委托列表。
        daily_choose (SelectedGrids): 经过滤器选中的待启动每日委托。
        urgent_choose (SelectedGrids): 经过滤器选中的待启动紧急委托。
        comm_choose (SelectedGrids): 所有选中的委托（含每日和紧急），
            用于调度判断和延迟任务计算。
        max_commission (int): 最大可同时运行的委托数量，默认 4。
            当存在活动委托（daily_event）时提升为 5。
    """

    daily: SelectedGrids
    urgent: SelectedGrids
    daily_choose: SelectedGrids
    urgent_choose: SelectedGrids
    comm_choose: SelectedGrids
    max_commission = 4

    def _commission_detect(self, image):
        """
        从图像中获取所有委托。

        Args:
            image (np.ndarray):

        Returns:
            SelectedGrids:
        """
        logger.hr('委托检测')
        commission = []
        for y in lines_detect(image):
            comm = Commission(image, y=y, config=self.config)
            logger.attr('委托', comm)
            repeat = len([c for c in commission if c == comm])
            comm.repeat_count += repeat
            commission.append(comm)

        return SelectedGrids(commission)

    def commission_detect(self, trial=1, area=None, skip_first_screenshot=True):
        """
        Args:
            trial (int): 遇到无效委托时重试次数，
                         通常是因为 info_bar 未完全消失。
            area (tuple):
            skip_first_screenshot (bool):

        Returns:
            SelectedGrids:
        """
        commissions = SelectedGrids([])
        for _ in range(trial):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            image = self.device.image
            if area is not None:
                image = crop(image, area, copy=False)
            commissions = self._commission_detect(image)

            invalid_count = commissions.select(valid=False).count
            if invalid_count:
                logger.warning(f'[委托-检测] 发现{invalid_count}个无效委托，重试委托检测')
                continue
            else:
                return commissions

        logger.info('[委托-检测] 委托检测重试次数已耗用，停止')
        return commissions

    def _commission_choose(self, daily, urgent):
        """根据实验开关分派委托选择算法。"""
        blacklist = self._commission_blacklist()
        if blacklist:
            logger.attr('委托黑名单', ', '.join(blacklist))
        dynamic = bool(getattr(self.config, 'Commission_DynamicProgramming', False))
        logger.attr('委托选择算法', '动态规划（实验性）' if dynamic else '传统贪心策略')
        if dynamic:
            return self._commission_choose_dynamic(daily, urgent)
        return self._commission_choose_legacy(daily, urgent)

    def _commission_blacklist(self):
        """解析以英文半角逗号分隔的委托过滤规则。"""
        blacklist = []
        raw = getattr(self.config, 'Commission_Blacklist', '') or ''
        for rule in str(raw).split(','):
            rule = rule.strip()
            if not rule:
                continue
            if rule not in blacklist:
                blacklist.append(rule)
        return blacklist

    def _commission_is_blacklisted(self, commission):
        """检查委托是否匹配任一黑名单过滤规则。"""
        for rule in self._commission_blacklist():
            parsed = COMMISSION_FILTER.parse_filter(rule)
            if COMMISSION_FILTER.apply_filter_to_obj(commission, parsed):
                return True
        return False

    def _commission_filter_get(self):
        """获取当前时段实际生效的委托过滤器。"""
        preset = self.config.Commission_PresetFilter
        if preset == 'custom':
            return preset, self.config.Commission_CustomFilter

        if f'{preset}_night' in DICT_FILTER_PRESET:
            start_time = get_server_last_update('02:00')
            end_time = get_server_last_update('21:00')
            if start_time < end_time:
                preset = f'{preset}_night'
        if preset not in DICT_FILTER_PRESET:
            logger.warning(f'[委托-过滤] 预设未找到: {preset}，使用默认预设')
            preset = GeneratedConfig.Commission_PresetFilter
        return preset, DICT_FILTER_PRESET[preset]

    def _commission_high_value_count(self, filter_count):
        """统计前若干条委托过滤规则匹配的待执行委托数量。"""
        preset, string = self._commission_filter_get()
        COMMISSION_FILTER.load(string)
        total = self.daily.add_by_eq(self.urgent)
        high_value = COMMISSION_FILTER.apply_first(
            total.grids,
            count=filter_count,
            func=self._commission_check,
        )
        logger.info(
            f'[委托-调度] 高价值过滤器: {preset} 前{filter_count}条，'
            f'待执行委托: {len(high_value)}'
        )
        for comm in high_value:
            logger.info(comm)
        return len(high_value)

    def _commission_choose_legacy(self, daily, urgent):
        """按过滤器顺序贪心选择委托，保持默认传统行为。"""
        self.comm_choose = SelectedGrids([])
        total = daily.add_by_eq(urgent)[::-1]
        self.max_commission = 5 if any(comm.genre == 'daily_event' for comm in total) else 4
        running_count = len([comm for comm in total if comm.status == 'running'])
        logger.attr('运行中', f'{running_count}/{self.max_commission}')

        preset, string = self._commission_filter_get()
        logger.attr('委托过滤器', preset)

        # tier 和 shortest 是实验模型控制标记，传统策略不把它们当作委托。
        COMMISSION_FILTER.load(string)
        run = SelectedGrids(COMMISSION_FILTER.apply(total.grids, func=self._commission_check))
        run = run.delete(SelectedGrids(['tier', 'shortest']))
        logger.attr('过滤排序', ' > '.join(str(comm) for comm in run))

        # 过滤结果不足时，保持传统行为并按耗时从短到长补足当前空槽。
        selected_count = sum(isinstance(comm, Commission) for comm in run)
        if selected_count + running_count < self.max_commission:
            candidate = daily.add_by_eq(urgent)
            if candidate.count:
                logger.info('[委托-选择] 委托数量不足，添加耗时最短的委托（每日和紧急）')
                COMMISSION_FILTER.load(SHORTEST_FILTER)
                shortest = COMMISSION_FILTER.apply(candidate[::-1], func=self._commission_check)
                run = run.add_by_eq(SelectedGrids(shortest))
                logger.attr('过滤排序', ' > '.join(str(comm) for comm in run))
            else:
                logger.info('[委托-选择] 委托数量不足，无每日和紧急委托可选')

        self.comm_choose = run
        if running_count >= self.max_commission:
            return SelectedGrids([]), SelectedGrids([])

        run = run[:self.max_commission - running_count]
        daily_choose = run.intersect_by_eq(daily)
        urgent_choose = run.intersect_by_eq(urgent)
        if daily_choose:
            logger.info('[委托-选择] 选择每日委托')
            for comm in daily_choose:
                logger.info(comm)
        if urgent_choose:
            logger.info('[委托-选择] 选择紧急委托')
            for comm in urgent_choose:
                logger.info(comm)

        return daily_choose, urgent_choose

    def _commission_choose_dynamic(self, daily, urgent):
        """使用启动时间折现价值选择当前应启动的委托。

        tier 使用有限倍率表示基础价值，层内候选编号提供有下限的价值修正。
        每条委托统一按预计启动等待、最晚启动窗口和基础等待半衰期折现；
        没有游戏内截止时间的委托以服务器刷新时刻作为截止时间。规划器最大化
        折现价值总和，因此低价值委托只有在收益足以覆盖等待损失时才会被保留。

        Args:
            daily (SelectedGrids):
            urgent (SelectedGrids):

        Returns:
            SelectedGrids, SelectedGrids: 选中的每日委托，选中的紧急委托
        """
        self.comm_choose = SelectedGrids([])
        # 统计委托数量
        total = daily.add_by_eq(urgent)
        # 后缀编号较大的委托总是在较小编号的下方
        # 反转委托列表以优先选择后缀编号较大的委托
        total = total[::-1]
        self.max_commission = 4
        for comm in total:
            if comm.genre == 'daily_event':
                self.max_commission = 5
        running_list = [c for c in total if c.status == 'running']
        running_count = len(running_list)
        logger.attr('运行中', f'{running_count}/{self.max_commission}')

        # 加载过滤器字符串
        preset, string = self._commission_filter_get()
        logger.attr('委托过滤器', preset)

        # 旧配置没有 tier 时，每条规则仍视作独立层级。
        COMMISSION_FILTER.load(string)
        tiers = COMMISSION_FILTER.apply_tiers(total.grids, func=self._commission_check)
        candidates = SelectedGrids([comm for tier in tiers for _, comm in tier])
        self.comm_choose = candidates
        logger.hr('委托最优策略', level=2)
        start_now = SelectedGrids([])
        if candidates:
            logger.info('[委托-规划] 有限价值层级: ' + ' > '.join(
                f'T{index + 1}' for index in range(len(tiers))
            ))
            for index, tier in enumerate(tiers):
                if not tier:
                    continue
                logger.info(f'[委托-规划] T{index + 1}（层内编号越小价值越高）: ' + ' | '.join(
                    f'#{filter_index} {comm}'
                    for filter_index, comm in tier
                ))

            plan_time = current_time()
            server_update = getattr(self.config, 'Scheduler_ServerUpdate', '00:00')
            horizon_time = get_server_next_update(server_update)
            horizon = int((horizon_time - plan_time).total_seconds())
            if horizon <= 0:
                horizon = 24 * 60 * 60
                horizon_time = plan_time + timedelta(seconds=horizon)

            jobs = []
            source_index = 0
            for tier_index, tier in enumerate(tiers):
                for filter_index, comm in tier:
                    # 规划层只接受统一的有限截止时间。源数据的 None 仅表示游戏
                    # 没有显式倒计时，此时使用本轮实际服务器刷新时刻。
                    deadline_time = getattr(comm, 'deadline_time', None) or horizon_time
                    deadline = int((deadline_time - plan_time).total_seconds())
                    if deadline <= 0:
                        logger.info(f'[委托-规划] 忽略已过期委托: {comm}')
                        continue
                    jobs.append(CommissionPlanJob(
                        source_index=source_index,
                        tier=tier_index,
                        duration=max(int(comm.duration.total_seconds()), 1),
                        deadline=deadline,
                        commission=comm,
                        filter_index=filter_index,
                    ))
                    source_index += 1

            slot_available = [max(int(comm.duration.total_seconds()), 0) for comm in running_list]
            slot_available.extend([0] * max(self.max_commission - running_count, 0))
            try:
                value_model = CommissionValueModel.from_config(self.config)
            except (TypeError, ValueError) as error:
                logger.warning(f'[委托-规划] 价值模型参数无效，使用默认值: {error}')
                value_model = DEFAULT_VALUE_MODEL
            logger.info(f'[委托-规划] Tier 价值倍率: {value_model.tier_value_ratio}')
            logger.info(f'[委托-规划] 基础等待半衰期: {timedelta(seconds=value_model.delay_half_life)}')
            logger.info(
                f'[委托-规划] Deadline 折现基准时间: '
                f'{timedelta(seconds=value_model.deadline_future_horizon)}'
            )
            logger.info(f'[委托-规划] 层内价值下限: {value_model.filter_value_floor / 100:.2f}%')
            logger.info(f'[委托-规划] 层内编号半衰期: {value_model.filter_value_half_life:g}')
            plan, planned_jobs = optimize_commission_plan(
                jobs,
                slot_available,
                horizon,
                model=value_model,
            )
            self._commission_plan_log(
                plan=plan,
                jobs=planned_jobs,
                running=running_list,
                plan_time=plan_time,
                horizon_time=horizon_time,
            )

            start_now = SelectedGrids([
                planned_jobs[action.job_index].commission
                for action in plan.actions
                if action.start == 0
            ])
        else:
            logger.info('[委托-规划] 过滤器没有匹配到可启动委托')

        daily_choose = start_now.intersect_by_eq(daily)
        urgent_choose = start_now.intersect_by_eq(urgent)
        if daily_choose:
            logger.info('[委托-选择] 选择每日委托')
            for comm in daily_choose:
                logger.info(comm)
        if urgent_choose:
            logger.info('[委托-选择] 选择紧急委托')
            for comm in urgent_choose:
                logger.info(comm)

        return daily_choose, urgent_choose

    @staticmethod
    def _commission_plan_log(plan, jobs, running, plan_time, horizon_time):
        """详细输出最优策略的价值、取舍和全部事件时间节点。"""
        score = ', '.join(f'T{index + 1}={value}' for index, value in enumerate(plan.score))
        utility = plan.utility / plan.value_scale
        full_value = plan.full_value / plan.value_scale
        delay_loss = plan.delay_loss / plan.value_scale
        logger.info(f'[委托-规划] 选择数量: {score}')
        logger.info(f'[委托-规划] 折现价值: {utility:.6f} T1')
        logger.info(f'[委托-规划] 立即启动价值: {full_value:.6f} T1')
        logger.info(f'[委托-规划] 等待损失: {delay_loss:.6f} T1')
        logger.info(
            f'[委托-规划] 搜索状态数: {plan.state_count}, '
            f'束宽: {plan.beam_width}, 裁剪: {plan.pruned_state_count}'
        )
        if plan.optimality_proven:
            logger.info('[委托-规划] 最优性证书: 已证明当前计划为全局最优')
        else:
            upper_value = plan.utility_upper_bound / plan.value_scale
            gap = plan.utility_gap / plan.value_scale
            logger.info(
                f'[委托-规划] 最优性证书: 尚未证明，严格上界 {upper_value:.6f} T1，'
                f'最大可能差距 {gap:.6f} T1'
            )
        logger.info(f'[委托-规划] 规划边界: {horizon_time:%Y-%m-%d %H:%M:%S}')
        logger.info('[委托-规划] 比较规则: 折现总价值 > 未折现总价值 > 最晚结束时间 > 完成时间总和 > 稳定编号')

        events = {0: []}
        horizon = max(int((horizon_time - plan_time).total_seconds()), 0)
        for comm in running:
            finish = max(int(comm.duration.total_seconds()), 0)
            events[0].append(f'继续运行委托: {comm.name} (预计 T+{timedelta(seconds=finish)} 完成)')
            events.setdefault(finish, []).append(f'运行中委托完成: {comm.name}')

        selected = set()
        for action in plan.actions:
            job = jobs[action.job_index]
            selected.add(job.source_index)
            tier = f'T{job.tier + 1}'
            verb = '启动' if action.start == 0 else '预计启动'
            events.setdefault(action.start, []).append(
                f'{verb} {tier} 委托: {job.commission.name} (耗时 {timedelta(seconds=job.duration)})'
            )
            events.setdefault(action.finish, []).append(
                f'预计委托完成: {job.commission.name}'
            )

        for job in jobs:
            if job.source_index in selected:
                continue
            if job.deadline < horizon:
                events.setdefault(job.deadline, []).append(
                    f'截止且放弃 T{job.tier + 1} 委托: {job.commission.name}'
                )
            else:
                events.setdefault(horizon, []).append(
                    f'刷新边界前未安排 T{job.tier + 1} 委托: {job.commission.name}'
                )

        events.setdefault(horizon, []).append('到达服务器刷新边界')
        events.setdefault(horizon, []).append('到达边界后将重新扫描并规划')

        for offset in sorted(events):
            timestamp = plan_time + timedelta(seconds=offset)
            logger.hr(f'时刻 {timestamp:%Y-%m-%d %H:%M:%S} (T+{timedelta(seconds=offset)})', level=3)
            for event in events[offset]:
                logger.info(f'[委托-规划] {event}')

    def _commission_check(self, commission):
        """检查委托是否符合执行条件。

        过滤掉无效委托、非待启动状态的委托、黑名单中的委托，以及用户配置中
        明确禁用的主线委托（major commission）。黑名单复用委托过滤器语法，
        可按委托类别、奖励类型和时长进行匹配。

        Args:
            commission (Commission): 待检查的委托对象。

        Returns:
            bool: 委托是否可以被选择执行。
        """
        if not commission.valid or commission.status != 'pending':
            return False
        if self._commission_is_blacklisted(commission):
            return False
        if not self.config.Commission_DoMajorCommission and commission.category_str == 'major':
            return False

        return True

    def _commission_ensure_mode(self, mode):
        """切换委托列表的显示模式（每日/紧急）。

        切换到指定模式后，等待列表滚动动画结束再返回，
        以避免委托条目在动画过程中被误检或漏检。

        Args:
            mode (str): 目标模式，'daily' 或 'urgent'。

        Returns:
            bool: 切换是否成功。
        """
        if COMMISSION_SWITCH.set(mode, main=self):
            # 当每日委托列表超过 4 个（通常为 5 个），且紧急委托在 1 到 4 个之间时，
            # 委托列表会出现滚动动画，
            # 导致最顶部的委托无法被检测到。
            if not COMMISSION_SCROLL.appear(main=self) or COMMISSION_SCROLL.cal_position(main=self) < 0.05 or COMMISSION_SCROLL.length / COMMISSION_SCROLL.total > 0.98:
                pre_peaks = lines_detect(self.device.image)
                self.device.screenshot()
                while 1:
                    peaks = lines_detect(self.device.image)
                    if (not len(peaks) or peaks[0] > 67 + 117) and (not len(pre_peaks) or not len(peaks) or abs(peaks[0] - pre_peaks[0]) < 3):
                        break
                    pre_peaks = peaks
                    self.device.screenshot()

            return True
        else:
            return False

    def _commission_mode_reset(self):
        """重置委托列表显示模式。

        先切换到另一个模式再切回当前模式，强制刷新列表内容，
        用于委托启动失败后恢复列表状态。

        Returns:
            bool: 重置是否成功。无法识别当前模式时返回 False。
        """
        logger.hr('委托模式重置')
        if self.appear(COMMISSION_DAILY):
            current, another = 'daily', 'urgent'
        elif self.appear(COMMISSION_URGENT):
            current, another = 'urgent', 'daily'
        else:
            logger.warning('[委托-模式] 未知的委托模式')
            return False

        self._commission_ensure_mode(another)
        self._commission_ensure_mode(current)

        return True

    def _commission_swipe(self):
        """向下翻页委托列表。

        如果滚动条可见且未到底部，则向下翻一页；否则返回 False。

        Returns:
            bool: 是否成功翻页。滚动条不可见或已到底部时返回 False。
        """
        if COMMISSION_SCROLL.appear(main=self):
            if COMMISSION_SCROLL.at_bottom(main=self):
                return False
            else:
                COMMISSION_SCROLL.next_page(main=self)
                return True
        else:
            return False

    def _commission_swipe_to_top(self):
        """将委托列表滚动到顶部。

        Returns:
            bool: 是否执行了滚动操作。滚动条不可见时返回 False。
        """
        if not COMMISSION_SCROLL.appear(main=self):
            return False
        COMMISSION_SCROLL.set_top(main=self, skip_first_screenshot=True)
        return True

    def _commission_scan_list(self):
        """
        Returns:
            SelectedGrids: 包含 Commission 对象的 SelectedGrids
        """
        self.device.click_record_clear()
        commission = SelectedGrids([])
        for _ in range(15):
            new = self.commission_detect(trial=2)
            commission = commission.add_by_eq(new)

            # 结束
            if not self._commission_swipe():
                break

        self.device.click_record_clear()
        return commission

    def _commission_scan_all(self):
        """
        Pages:
            in: page_commission
            out: page_commission
        """
        logger.hr('委托扫描', level=1)
        # 紧急委托列表是懒加载的，先切换以强制刷新。
        self._commission_ensure_mode('urgent')

        logger.hr('扫描每日委托', level=2)
        self._commission_ensure_mode('daily')
        self._commission_swipe_to_top()
        daily = self._commission_scan_list()

        logger.hr('扫描紧急委托', level=2)
        self._commission_ensure_mode('urgent')
        self._commission_swipe_to_top()
        urgent = self._commission_scan_list()
        # 将额外委托转换为夜间委托
        urgent.call('convert_to_night')

        logger.hr('显示委托', level=2)
        logger.info('[委托-显示] 每日委托')
        for comm in daily.sort('status', 'genre'):
            logger.attr('委托', comm)
        if urgent.count:
            logger.info('[委托-显示] 紧急委托')
            for comm in urgent.sort('status', 'genre'):
                logger.attr('委托', comm)

        self.daily = daily
        self.urgent = urgent
        self.daily_choose, self.urgent_choose = self._commission_choose(self.daily, self.urgent)
        return daily, urgent

    def _commission_start_click(self, comm, is_urgent=False, skip_first_screenshot=True):
        """
        启动一个委托。

        Args:
            comm (Commission):
            is_urgent (bool):
            skip_first_screenshot:

        Returns:
            bool: 是否成功

        Pages:
            in: page_commission
            out: page_commission, info_bar, commission details unfold
        """
        logger.hr('启动委托')
        self.interval_clear(COMMISSION_ADVICE)
        self.interval_clear(COMMISSION_START)
        comm_timer = Timer(7)
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束
            if self.info_bar_count():
                break
            if count >= 3:
                # 重启游戏以处理委托推荐 bug。
                # 点击"推荐"后，舰船出现后突然消失。
                # 同时委托图标闪烁。
                logger.warning('[委托-启动] 触发了委托列表闪烁bug')
                raise GameStuckError('[委托-启动] 触发了委托列表闪烁bug')

            # 点击
            if self.match_template_color(COMMISSION_START, offset=(5, 20), interval=7):
                self.device.click(COMMISSION_START)
                self.interval_reset(COMMISSION_ADVICE)
                comm_timer.reset()
                continue
            if self.handle_popup_confirm('COMMISSION_START'):
                self.interval_reset(COMMISSION_ADVICE)
                comm_timer.reset()
                continue
            # 误入船坞
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                logger.info(f'[委托-启动] 误入船坞 {DOCK_CHECK} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                comm_timer.reset()
                continue
            # 检查是否是正确的委托
            if self.appear(COMMISSION_ADVICE, offset=(5, 20), interval=7):
                area = (0, 0, image_size(self.device.image)[0], COMMISSION_ADVICE.button[1])
                current = self.commission_detect(area=area)
                if is_urgent:
                    current.call('convert_to_night')  # 将额外委托转换为夜间委托
                if current.count >= 1:
                    current = current[0]
                    if not self._commission_check(current):
                        logger.warning(f'[委托-启动] 当前委托已被过滤: {current.name}')
                        return False
                    if current == comm:
                        logger.info('[委托-启动] 已选择正确的委托')
                    else:
                        logger.warning('[委托-启动] 选择了错误的委托')
                        return False
                else:
                    logger.warning('[委托-启动] 未检测到选择的委托，假设正确')
                self.device.click(COMMISSION_ADVICE)
                count += 1
                self.interval_reset(COMMISSION_ADVICE)
                self.interval_clear(COMMISSION_START)
                comm_timer.reset()
                continue
            # 进入委托
            if comm_timer.reached():
                self.device.click(comm.button)
                self.device.sleep(0.3)
                comm_timer.reset()

        return True

    def _commission_find_and_start(self, comm, is_urgent=False):
        """
        Args:
            comm (Commission):
            is_urgent (bool):
        """
        self.device.click_record_clear()
        comm = copy.deepcopy(comm)
        comm.repeat_count = 1
        for _ in range(3):
            logger.hr('查找并启动委托', level=2)
            logger.info(f'[委托-查找] 正在查找委托 {comm}')

            failed = True

            for _ in range(15):
                new = self.commission_detect(trial=2)
                if is_urgent:
                    new.call('convert_to_night')  # 将额外委托转换为夜间委托

                # 更新委托位置。
                # 不同扫描中委托信息相同，但位置可能不同。
                current = None
                for new_comm in new:
                    if self._commission_check(new_comm) and new_comm == comm:
                        current = new_comm
                if current is not None:
                    if self._commission_start_click(current, is_urgent=is_urgent):
                        self.device.click_record_clear()
                        return True
                    else:
                        self._commission_mode_reset()
                        self._commission_swipe_to_top()
                        failed = False
                        break

                # 结束条件
                if not self._commission_swipe():
                    break

            if failed:
                logger.warning(f'[委托-查找] 选择委托失败: {comm}')
                self._commission_mode_reset()
                self._commission_swipe_to_top()
                self.device.click_record_clear()
                continue
            else:
                logger.warning(f'[委托-查找] 未找到委托: {comm}')
                self.device.click_record_clear()
                return False

        logger.warning('[委托-查找] 尝试3次后仍无法选择委托')
        self.device.click_record_clear()
        return False

    def commission_start(self):
        """
        扫描并启动所有选定的委托。

        Pages:
            in: page_commission
            out: page_commission
        """
        self._commission_scan_all()

        logger.hr('执行委托', level=1)
        if self.daily_choose:
            for comm in self.daily_choose:
                self._commission_ensure_mode('daily')
                self._commission_swipe_to_top()
                self.handle_info_bar()
                if self._commission_find_and_start(comm, is_urgent=False):
                    comm.convert_to_running()
                self._commission_mode_reset()
        if self.urgent_choose:
            for comm in self.urgent_choose:
                self._commission_ensure_mode('urgent')
                self._commission_swipe_to_top()
                self.handle_info_bar()
                if self._commission_find_and_start(comm, is_urgent=True):
                    comm.convert_to_running()
                self._commission_mode_reset()
        if not self.daily_choose and not self.urgent_choose:
            logger.info('[委托-执行] 没有选择任何委托')

    def _record_commission_income(self):
        """
        记录委托奖励的收入（物品）。

        分析委托奖励收集过程中在 `_commission_reward_images` 中截取的截图，
        识别特定物品（钻石、心智魔方、心智单元、石油、金币），
        汇总数量并保存到数据库。
        """
        try:
            from module.statistics.get_items import (
                GetItemsStatistics, ITEM_GRIDS_1_ODD, ITEM_GRIDS_1_EVEN,
                ITEM_GRIDS_2, ITEM_GRIDS_3
            )
            from module.statistics.item import ItemGrid, Item
            from module.statistics.cl1_database import db as cl1_db
            from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3
            from module.handler.assets import INFO_BAR_1
            import os

            template_folder = os.path.join('.', 'assets', 'stats_commission_items')
            if not os.path.exists(template_folder):
                logger.info('[委托-收入] 模板文件夹不存在，跳过')
                return

            grid = ItemGrid(None, {}, template_area=(40, 21, 89, 70), amount_area=(50, 71, 91, 92))
            grid.item_class = Item
            grid.similarity = 0.92
            # 过滤图标底部伸入数量区域的白色碎块，避免被 OCR 误读为数字
            # （如 11 → 211）；数字放大 2 倍后裁剪，避免小数字丢位
            # （不裁剪 71 → 7，原尺寸裁剪 77 → 7）
            grid.amount_ocr = CommissionAmount([], threshold=96, name='Amount_ocr')
            grid.load_template_folder(template_folder)

            if not grid.templates:
                logger.info('[委托-收入] 没有加载模板，跳过')
                return

            get_items = GetItemsStatistics()

            merged_items = {}
            item_count = 0
            # 通过「获取物品」页面校验的截图，结算后落盘存档供 WebUI 查看
            reward_images = []

            images = getattr(self, '_commission_reward_images', None)
            if not images:
                logger.info('[委托-收入] 没有收集到奖励截图')
                return

            COMMISSION_TRACKED_ITEMS = ['Gem', 'Cube', 'Chip', 'Oil', 'Coin']

            COMMISSION_ITEM_NAME_MAP = {
                'Gems': 'Gem',
                'Cubes': 'Cube',
                'CognitiveChips': 'Chip',
                'Coins': 'Coin',
            }

            logger.info(f'[委托-收入] 处理 {len(images)} 张奖励截图')
            for idx, image in enumerate(images):
                try:
                    if INFO_BAR_1.appear_on(image):
                        logger.info(f'[委托-收入] 截图[{idx}] 有信息栏，跳过')
                        continue
                    grid.grids = None
                    if GET_ITEMS_1.match_template_color(image, offset=(5, 0)):
                        is_odd = get_items._stats_get_items_is_odd(image)
                        grid.grids = ITEM_GRIDS_1_ODD if is_odd else ITEM_GRIDS_1_EVEN
                    elif GET_ITEMS_2.match_template_color(image, offset=(5, 0)):
                        grid.grids = ITEM_GRIDS_2
                    elif GET_ITEMS_3.match_template_color(image, offset=(5, 0)):
                        grid.grids = ITEM_GRIDS_3
                    else:
                        logger.info(f'[委托-收入] 截图[{idx}] 不是获取物品页面，跳过')
                        continue
                    reward_images.append(image)
                    # 数量 OCR 在 CommissionAmount 内先放大 2 倍再裁剪，
                    # 碎片过滤后数字右对齐的问题由放大+裁剪共同规避
                    grid.predict(image, amount_trim=True)
                    recognized = []
                    for item in grid.items:
                        if item.is_known_item() and item.name not in ('DefaultItem',):
                            mapped_name = COMMISSION_ITEM_NAME_MAP.get(item.name, item.name)
                            if mapped_name not in COMMISSION_TRACKED_ITEMS:
                                logger.info(f'[委托-收入] 截图[{idx}] 忽略 {item.name} (未跟踪)')
                                continue
                            merged_items[mapped_name] = merged_items.get(mapped_name, 0) + item.amount
                            item_count += 1
                            recognized.append(f'{mapped_name}x{item.amount}')
                    if recognized:
                        logger.info(f'[委托-收入] 截图[{idx}] 识别到 {len(recognized)} 个物品: {", ".join(recognized)}')
                    else:
                        logger.info(f'[委托-收入] 截图[{idx}] 没有识别到已知物品')
                except Exception as e:
                    logger.info(f'[委托-收入] 截图[{idx}] 识别失败: {e}')
                    continue

            if merged_items:
                instance = self.config.config_name
                screenshots = self._save_commission_reward_screenshots(reward_images, instance)
                cl1_db.add_commission_income(
                    instance, merged_items, commission_count=1, screenshots=screenshots
                )
                item_str = ', '.join([f'{k}x{v}' for k, v in merged_items.items()])
                logger.info(f'[委托-收入] 委托收入记录: {item_str} (实例={instance})')
                if self.config.Commission_CommissionNotifyReward:
                    reward_stats = None
                    if self.config.Commission_CommissionNotifyRewardStatistics:
                        reward_stats = cl1_db.get_commission_reward_stats(instance)
                    gem_count = merged_items.get("Gem", 0)
                    tracked = []
                    if gem_count > 0:
                        text = f'本次获得钻石 * {gem_count}'
                        if reward_stats:
                            text += (
                                f'\n\n今日累计: {reward_stats["today"].get("Gem", 0)}'
                                f'\n本周累计: {reward_stats["week"].get("Gem", 0)}'
                                f'\n本月累计: {reward_stats["month"].get("Gem", 0)}'
                            )
                        tracked.append(text)
                    if tracked:

                        msg = '\n'.join(tracked)
                        webui_msg = msg.replace('\n\n', '\n')
                        title = f"AzurPilot <{instance}> 委托获得奖励喵！"
                        webui_title = f"AzurPilot <{instance}> 委托获得奖励喵！"
                        if gem_count >= 50:
                            title = f"AzurPilot <{instance}> 大成功！！！委托获得顶级奖励喵！"
                            webui_title = f"AzurPilot <{instance}> 大成功！！！委托获得顶级奖励喵！"

                        elif gem_count > 0:
                            title = f"AzurPilot <{instance}> 委托获得顶级奖励喵！"
                            webui_title = f"AzurPilot <{instance}> 委托获得顶级奖励喵！"
                        handle_notify(
                            self.config.Error_OnePushConfig,
                            title=title,
                            content=msg,
                        )

                        notify_webui(
                            instance,
                            title=webui_title,
                            content=webui_msg,
                        )

            else:
                logger.info('[委托-收入] 所有截图都没有识别到已知物品')

        except Exception as e:
            logger.warning(f'[委托-收入] 委托收入记录失败: {e}')

    def _save_commission_reward_screenshots(self, images, instance):
        """保存本次结算的委托收益截图。

        截图落盘到 ``./log/commission_rewards/<instance>/<YYYY-MM>/`` 目录，
        文件名使用毫秒时间戳避免冲突。返回相对 ``log/commission_rewards``
        根目录的路径列表（POSIX 风格），写入数据库供 WebUI 查看截图使用。

        Args:
            images: 通过「获取物品」页面校验的截图列表（RGB numpy 数组）。
            instance: 配置实例名称。

        Returns:
            list[str]: 保存成功的截图相对路径列表，失败时返回空列表。
        """
        import os

        if not images:
            return []

        month_str = current_time().strftime('%Y-%m')
        folder = os.path.join('.', 'log', 'commission_rewards', instance, month_str)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            logger.warning(f'[委托-收入] 创建截图目录失败: {e}')
            return []

        stamp = current_time().strftime('%Y%m%d_%H%M%S_%f')
        paths = []
        for idx, image in enumerate(images):
            filename = f'{stamp}_{idx}.png'
            try:
                save_image(image, os.path.join(folder, filename))
            except Exception as e:
                logger.warning(f'[委托-收入] 保存截图失败 {filename}: {e}')
                continue
            paths.append(f'{instance}/{month_str}/{filename}')
            logger.info(f'[委托-收入] 已保存收益截图: log/commission_rewards/{instance}/{month_str}/{filename}')

        self._prune_commission_reward_screenshots(instance)
        return paths

    @staticmethod
    def _prune_commission_reward_screenshots(instance, max_keep=None):
        """清理实例目录下超量的委托收益截图，仅保留最近 max_keep 张。

        截图保留张数与统计页「最近委托记录」的 50 条上限对应：
        超过保留数量的旧截图按修改时间排序删除，并移除清空后的
        空月份目录。清理在每次保存截图后顺带执行。

        Args:
            instance: 配置实例名称。
            max_keep: 保留的截图张数上限，默认使用模块级常量
                COMMISSION_REWARD_SCREENSHOT_KEEP。
        """
        import os

        if max_keep is None:
            max_keep = COMMISSION_REWARD_SCREENSHOT_KEEP

        base = os.path.join('.', 'log', 'commission_rewards', instance)
        if not os.path.isdir(base):
            return
        files = []
        for folder, _, names in os.walk(base):
            for name in names:
                if not name.endswith('.png'):
                    continue
                file = os.path.join(folder, name)
                try:
                    files.append((os.path.getmtime(file), file))
                except OSError:
                    continue
        files.sort(reverse=True)
        for _, file in files[max_keep:]:
            try:
                os.remove(file)
            except OSError:
                continue
        for folder, _, _ in os.walk(base, topdown=False):
            try:
                os.rmdir(folder)
            except OSError:
                pass

    def _handle_research_genre_t_update(self, completed_commission_count):
        """更新 T 类科研任务的剩余委托计数。

        当存在 T 类科研（要求完成指定次数委托）时，将已完成的委托次数
        从剩余计数中扣除。计数归零时触发科研任务调度。

        Args:
            completed_commission_count (int): 本次领取奖励时完成的委托数量。
        """
        if completed_commission_count <= 0:
            return
        required_commissions = self.config.cross_get('Research.Research.RemainingCommissions', -1)
        if required_commissions <= -1:
            return

        new_value = max(required_commissions - completed_commission_count, 0)
        logger.info(f'T类科研要求进行委托{required_commissions}次，当前进行了{completed_commission_count}次，剩余{new_value}次')
        self.config.cross_set('Research.Research.RemainingCommissions', new_value)
        if new_value <= 0:
            logger.info('T类科研要求已完成，叫出科研任务')
            self.config.task_call('Research')

    def _commission_receive(self, skip_first_screenshot=True):
        """领取已完成的委托奖励。

        在委托页面和奖励页面之间循环，点击所有可领取的奖励弹窗
        （经验、物品、舰船），同时收集奖励截图用于收入统计。
        处理石油溢出的情况（触发宿舍喂食消耗石油）。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图，复用上一状态的截图。

        Returns:
            bool: 是否领取了任何奖励。

        Raises:
            OilMaxed: 石油溢出且喂食 3 次仍无法解决时抛出。
        """
        logger.hr('领取奖励')

        reward = False
        click_timer = Timer(1)
        self._commission_reward_images = []
        completed_commission_count = 0

        try:
            with self.stat.new(
                    'commission', method=self.config.DropRecord_CommissionRecord
            ) as drop:
                while 1:
                    if skip_first_screenshot:
                        skip_first_screenshot = False
                    else:
                        self.device.screenshot()

                    if self.ui_page_appear(page_commission, offset=(20, 20)):
                        break

                    for button in [EXP_INFO_S_REWARD, GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3]:
                        if self.appear(button, interval=1):
                            self.ensure_no_info_bar(timeout=1)

                            if drop:
                                drop.add(self.device.image)

                            if button is EXP_INFO_S_REWARD:
                                completed_commission_count += 1
                                if self._commission_reward_images:
                                    self._record_commission_income()
                                    self._commission_reward_images = []
                            else:
                                self._commission_reward_images.append(self.device.image.copy())
                                logger.info(f'[委托-收入] 收集奖励截图 (触发按钮={button.name})')

                            REWARD_SAVE_CLICK.name = button.name
                            self.device.click(REWARD_SAVE_CLICK)
                            if button is EXP_INFO_S_REWARD:
                                self.device.sleep(0.3)
                            click_timer.reset()
                            reward = True
                            continue
                    if click_timer.reached() and self.appear_then_click(REWARD_1, offset=(20, 20), interval=1):
                        self.interval_reset(GET_SHIP)
                        click_timer.reset()
                        reward = True
                        continue
                    if click_timer.reached() and self.appear_then_click(REWARD_1_WHITE, offset=(20, 20), interval=1):
                        self.interval_reset(GET_SHIP)
                        click_timer.reset()
                        reward = True
                        continue
                    if click_timer.reached() and self.appear_then_click(REWARD_GOTO_COMMISSION, offset=(20, 20)):
                        self.interval_reset(GET_SHIP)
                        click_timer.reset()
                        continue
                    if click_timer.reached() and self.appear_then_click(REWARD_GOTO_COMMISSION_WHITE, offset=(20, 20)):
                        self.interval_reset(GET_SHIP)
                        click_timer.reset()
                        continue
                    if self.ui_main_appear_then_click(page_reward, interval=3):
                        self.interval_reset(GET_SHIP)
                        continue

                    if self.config.SERVER in ['cn']:
                        if self.appear(OIL_MAXED, offset=(20, 20), interval=3):
                            raise OilMaxed

                    if self.config.Commission_DetectShipDrop:
                        for button in [GET_SHIP]:
                            if click_timer.reached() and self.appear(button, interval=1):
                                self.ensure_no_info_bar(timeout=1)
                                drop.add(self.device.image)

                                REWARD_SAVE_CLICK.name = button.name
                                self.device.click(REWARD_SAVE_CLICK)
                                click_timer.reset()
                                reward = True
                                continue
                    if click_timer.reached() and self.ui_additional():
                        click_timer.reset()
                        continue
        finally:
            self._handle_research_genre_t_update(completed_commission_count)

        if reward:
            self._record_commission_income()

        return reward

    def commission_receive(self):
        """
        Returns:
            bool: 是否领取了奖励。

        Pages:
            in: page_reward
            out: page_commission
        """
        for _ in range(3):
            try:
                return self._commission_receive()
            except OilMaxed:
                logger.info("[委托-石油] 石油溢出，购买食物消耗石油")
                RewardDorm(self.config, self.device).dorm_food_run(amount=10)
                self.ui_ensure(page_reward)

        logger.critical('[委托-石油] 尝试3次后仍无法处理石油溢出')
        raise RequestHumanTakeover

    def run(self):
        """
        Pages:
            in: Any
            out: page_commission
        """
        # 修复：如果卡在 TACTICAL_CLASS_START（技能书选择界面），点击取消退出
        # TACTICAL_CHECK 在 TACTICAL_CLASS_START 中被误检测，导致 A* 导航
        # 选择 BACK_ARROW，但从该页面无法导航到 page_reward
        self.device.screenshot()
        if self.appear(TACTICAL_CLASS_START, offset=(30, 30)):
            logger.info('[委托-战术] 检测到战术课堂开始按钮，点击取消退出')
            self.device.click(TACTICAL_CLASS_CANCEL)
            self.device.sleep((0.5, 1.0))
        self.ui_ensure(page_reward)
        self.commission_receive()

        # 在启航仪式委托获得舰船时会出现信息栏
        # 这是游戏 bug，信息栏反复显示获得舰船，直到点击 get_ship 才消失
        self.handle_info_bar()
        self.commission_start()

        # 调度
        total = self.daily.add_by_eq(self.urgent)
        future_finish = sorted([f for f in total.get('finish_time') if f is not None])
        logger.info(f'[委托-完成] 委托完成时间: {[str(f) for f in future_finish]}')
        if len(future_finish):
            self.config.task_delay(target=future_finish)
        else:
            logger.info('[委托-完成] 没有正在运行的委托')
            self.config.task_delay(success=False)

        # 延迟钻石 farming / 三油低耗任务
        # 遍历使用 GemsFarming 配置组的任务，检查是否启用且开启了 CommissionLimit
        limit_tasks = [
            task for task in ['GemsFarming', 'ThreeOilLowCost']
            if self.config.is_task_enabled(task)
            and self.config.cross_get(keys=f'{task}.GemsFarming.CommissionLimit', default=False)
        ]

        if limit_tasks:
            future = nearest_future(future_finish) if len(future_finish) else None
            for task in limit_tasks:
                filter_count = self.config.cross_get(f'{task}.GemsFarming.HighValueCommissionFilterCount')
                reserve = self.config.cross_get(f'{task}.GemsFarming.HighValueCommissionReserve')
                filter_count = max(int(filter_count), 1)
                reserve = max(int(reserve), 1)
                high_value_count = self._commission_high_value_count(filter_count)
                if high_value_count >= reserve:
                    logger.info(
                        f"[委托-调度] 高价值委托达到保留量 {high_value_count}/{reserve}，"
                        f"延迟任务 '{task}'"
                    )
                    self.config.task_delay(
                        minute=None if future else 120,
                        target=future,
                        task=task,
                    )
                else:
                    logger.info(
                        f"[委托-调度] 高价值委托未达到保留量 {high_value_count}/{reserve}，"
                        f"继续任务 '{task}'"
                    )
