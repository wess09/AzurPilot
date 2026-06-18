import copy
from datetime import datetime, timedelta

from scipy import signal

from module.base.timer import Timer
import time
from module.base.utils import *
from module.combat.assets import *
from module.commission.assets import *
from module.commission.preset import DICT_FILTER_PRESET, SHORTEST_FILTER
from module.commission.project import COMMISSION_FILTER, Commission
from module.config.config_generated import GeneratedConfig
from module.config.utils import get_server_last_update, get_server_next_update, nearest_future
from module.dorm.dorm import RewardDorm
from module.exception import GameStuckError, OilMaxed, RequestHumanTakeover
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.retire.assets import DOCK_CHECK
from module.ui.assets import BACK_ARROW, REWARD_GOTO_COMMISSION
from module.tactical.assets import TACTICAL_CLASS_START, TACTICAL_CLASS_CANCEL
from module.ui.page import page_commission, page_reward
from module.ui.scroll import Scroll
from module.ui.switch import Switch
from module.ui.ui import UI
from module.ui_white.assets import REWARD_1_WHITE, REWARD_GOTO_COMMISSION_WHITE
from datetime import timedelta

COMMISSION_SWITCH = Switch('Commission_switch', is_selector=True)
COMMISSION_SWITCH.add_state('daily', COMMISSION_DAILY)
COMMISSION_SWITCH.add_state('urgent', COMMISSION_URGENT)
COMMISSION_SCROLL = Scroll(COMMISSION_SCROLL_AREA, color=(247, 211, 66), name='COMMISSION_SCROLL')


def lines_detect(image):
    """
    Args:
        image:

    Returns:
        np.ndarray: 每个委托下方白色分割线的 Y 坐标。
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
        logger.hr('Commission detect')
        commission = []
        for y in lines_detect(image):
            comm = Commission(image, y=y, config=self.config)
            logger.attr('Commission', comm)
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

            if commissions.count >= 2 and commissions.select(valid=False).count == 1:
                logger.warning('Found 1 invalid commission, retry commission detect')
                continue
            else:
                return commissions

        logger.info('trials of commission detect exhausted, stop')
        return commissions

    def _commission_choose(self, daily, urgent):
        """
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
        logger.attr('Running', f'{running_count}/{self.max_commission}')

        # 加载过滤器字符串
        preset = self.config.Commission_PresetFilter
        if preset == 'custom':
            string = self.config.Commission_CustomFilter
        else:
            if f'{preset}_night' in DICT_FILTER_PRESET:
                start_time = get_server_last_update('02:00')
                end_time = get_server_last_update('21:00')
                if start_time < end_time:
                    preset = f'{preset}_night'
            if preset not in DICT_FILTER_PRESET:
                logger.warning(f'Preset not found: {preset}, use default preset')
                preset = GeneratedConfig.Commission_PresetFilter
            string = DICT_FILTER_PRESET[preset]
        logger.attr('Commission Filter', preset)

        # 过滤
        COMMISSION_FILTER.load(string)
        run = COMMISSION_FILTER.apply(total.grids, func=self._commission_check)
        logger.attr('Filter_sort', ' > '.join([str(c) for c in run]))
        run = SelectedGrids(run)

        # 添加最短时间委托
        if self.config.Commission_AddShortest == False and preset == 'custom':
            logger.info('Not enough commissions to run')
        else:
            no_shortest = run.delete(SelectedGrids(['shortest']))
            if no_shortest.count + running_count < self.max_commission:
                if daily.count:
                    logger.info('Not enough commissions to run, add shortest daily commissions')
                    COMMISSION_FILTER.load(SHORTEST_FILTER)
                    shortest = COMMISSION_FILTER.apply(daily[::-1], func=self._commission_check)
                    # 反转每日委托列表以选择更好的委托
                    run = no_shortest.add_by_eq(SelectedGrids(shortest))
                    logger.attr('Filter_sort', ' > '.join([str(c) for c in run]))
                else:
                    logger.info('Not enough commissions to run')

        # 优先处理快过期重要委托
        if 'expire' in run:
            logger.info('尝试提前快过期委托')

            valid_runs = [c for c in run if isinstance(c, Commission)]
            queue = running_list + valid_runs[:self.max_commission - running_count]

            if queue:
                min_duration_time = queue[0].duration
                for c in queue:
                    if c.duration < min_duration_time:
                        min_duration_time = c.duration
            else:
                min_duration_time = timedelta(seconds=0)
            logger.attr('Min Duration Time', min_duration_time)

            expire_index = run.grids.index('expire')
            important = run[:expire_index].filter(lambda c: isinstance(c, Commission) and c.expire)
            priority = [c for c in important if c.expire < min_duration_time]
            run = run.delete(SelectedGrids(['expire']))
            run = SelectedGrids(priority).add_by_eq(run)
            logger.attr('Filter_sort', ' > '.join([str(c) for c in run]))

        self.comm_choose = run
        if running_count >= self.max_commission:
            return SelectedGrids([]), SelectedGrids([])

        # 分离每日和紧急委托
        run = run[:self.max_commission - running_count]
        daily_choose = run.intersect_by_eq(daily)
        urgent_choose = run.intersect_by_eq(urgent)
        if daily_choose:
            logger.info('Choose daily commission')
            for comm in daily_choose:
                logger.info(comm)
        if urgent_choose:
            logger.info('Choose urgent commission')
            for comm in urgent_choose:
                logger.info(comm)

        return daily_choose, urgent_choose

    def _commission_check(self, commission):
        """
        Args:
            commission (Commission):

        Returns:
            bool:
        """
        if not commission.valid or commission.status != 'pending':
            return False
        if not self.config.Commission_DoMajorCommission and commission.category_str == 'major':
            return False

        return True

    def _commission_ensure_mode(self, mode):
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
        logger.hr('Commission mode reset')
        if self.appear(COMMISSION_DAILY):
            current, another = 'daily', 'urgent'
        elif self.appear(COMMISSION_URGENT):
            current, another = 'urgent', 'daily'
        else:
            logger.warning('Unknown Commission mode')
            return False

        self._commission_ensure_mode(another)
        self._commission_ensure_mode(current)

        return True

    def _commission_swipe(self):
        if COMMISSION_SCROLL.appear(main=self):
            if COMMISSION_SCROLL.at_bottom(main=self):
                return False
            else:
                COMMISSION_SCROLL.next_page(main=self)
                return True
        else:
            return False

    def _commission_swipe_to_top(self):
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
        logger.hr('Commission scan', level=1)
        # 紧急委托列表是懒加载的，先切换以强制刷新。
        self._commission_ensure_mode('urgent')

        logger.hr('Scan daily', level=2)
        self._commission_ensure_mode('daily')
        self._commission_swipe_to_top()
        daily = self._commission_scan_list()

        urgent = SelectedGrids([])
        for _ in range(2):
            logger.hr('Scan urgent', level=2)
            self._commission_ensure_mode('urgent')
            self._commission_swipe_to_top()
            urgent = self._commission_scan_list()
            # 将额外委托转换为夜间委托
            urgent.call('convert_to_night')

            # 不在 21:00~03:00 时间段，但扫描到了夜间委托
            # 可能是过期委托，刷新即可解决
            if datetime.now() - get_server_next_update('21:00') > timedelta(hours=6):
                night = urgent.select(category_str='night')
                if night:
                    logger.warning('Not in 21:00~03:00, but scanned night commissions')
                    for comm in night:
                        logger.attr('Commission', comm)
                    logger.info('Re-scan urgent commission list')
                    # 虽然不是最佳方式，但在罕见情况下可以接受
                    self.device.sleep(2)
                    self._commission_ensure_mode('daily')
                    continue

            break

        logger.hr('Showing commission', level=2)
        logger.info('Daily commission')
        for comm in daily.sort('status', 'genre'):
            logger.attr('Commission', comm)
        if urgent.count:
            logger.info('Urgent commission')
            for comm in urgent.sort('status', 'genre'):
                logger.attr('Commission', comm)

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
        logger.hr('Commission start')
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
                logger.warning('Triggered commission list flashing bug')
                raise GameStuckError('Triggered commission list flashing bug')

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
                logger.info(f'equip_enter {DOCK_CHECK} -> {BACK_ARROW}')
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
                    if current == comm:
                        logger.info('Selected to the correct commission')
                    else:
                        logger.warning('Selected to the wrong commission')
                        return False
                else:
                    logger.warning('No selected commission detected, assuming correct')
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
            logger.hr('Commission find and start', level=2)
            logger.info(f'Finding commission {comm}')

            failed = True

            for _ in range(15):
                new = self.commission_detect(trial=2)
                if is_urgent:
                    new.call('convert_to_night')  # 将额外委托转换为夜间委托

                # 更新委托位置。
                # 不同扫描中委托信息相同，但位置可能不同。
                current = None
                for new_comm in new:
                    if new_comm == comm:
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
                logger.warning(f'Failed to select commission: {comm}')
                self._commission_mode_reset()
                self._commission_swipe_to_top()
                self.device.click_record_clear()
                continue
            else:
                logger.warning(f'Commission not found: {comm}')
                self.device.click_record_clear()
                return False

        logger.warning(f'Failed to select commission after 3 trial')
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

        logger.hr('Commission run', level=1)
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
            logger.info('No commission chose')

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
                logger.info('Commission income: template folder not found, skip')
                return

            grid = ItemGrid(None, {}, template_area=(40, 21, 89, 70), amount_area=(50, 71, 91, 92))
            grid.item_class = Item
            grid.similarity = 0.92
            grid.load_template_folder(template_folder)

            if not grid.templates:
                logger.info('Commission income: no templates loaded, skip')
                return

            get_items = GetItemsStatistics()

            merged_items = {}
            item_count = 0

            images = getattr(self, '_commission_reward_images', None)
            if not images:
                logger.info('Commission income: no reward images collected')
                return

            COMMISSION_TRACKED_ITEMS = ['Gem', 'Cube', 'Chip', 'Oil', 'Coin']

            COMMISSION_ITEM_NAME_MAP = {
                'Gems': 'Gem',
                'Cubes': 'Cube',
                'CognitiveChips': 'Chip',
                'Coins': 'Coin',
            }

            logger.info(f'Commission income: processing {len(images)} reward screenshot(s)')
            for idx, image in enumerate(images):
                try:
                    if INFO_BAR_1.appear_on(image):
                        logger.info(f'Commission income: screenshot[{idx}] has info_bar, skip')
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
                        logger.info(f'Commission income: screenshot[{idx}] not a get_items page, skip')
                        continue
                    grid.predict(image)
                    recognized = []
                    for item in grid.items:
                        if item.is_known_item() and item.name not in ('DefaultItem',):
                            mapped_name = COMMISSION_ITEM_NAME_MAP.get(item.name, item.name)
                            if mapped_name not in COMMISSION_TRACKED_ITEMS:
                                logger.info(f'Commission income: screenshot[{idx}] ignored {item.name} (not tracked)')
                                continue
                            merged_items[mapped_name] = merged_items.get(mapped_name, 0) + item.amount
                            item_count += 1
                            recognized.append(f'{mapped_name}x{item.amount}')
                    if recognized:
                        logger.info(f'Commission income: screenshot[{idx}] recognized {len(recognized)} item(s): {", ".join(recognized)}')
                    else:
                        logger.info(f'Commission income: screenshot[{idx}] no known items recognized')
                except Exception as e:
                    logger.info(f'Commission income: screenshot[{idx}] recognition failed: {e}')
                    continue

            if merged_items:
                instance = self.config.config_name
                cl1_db.add_commission_income(instance, merged_items, commission_count=1)
                item_str = ', '.join([f'{k}x{v}' for k, v in merged_items.items()])
                logger.info(f'Commission income recorded: {item_str} (instance={instance})')
            else:
                logger.info('Commission income: no known items recognized from all screenshots')

        except Exception as e:
            logger.warning(f'Commission income recording failed: {e}')

    def _commission_receive(self, skip_first_screenshot=True):
        logger.hr('Reward receive')

        reward = False
        click_timer = Timer(1)
        self._commission_reward_images = []

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
                            if self._commission_reward_images:
                                self._record_commission_income()
                                self._commission_reward_images = []
                        else:
                            self._commission_reward_images.append(self.device.image.copy())
                            logger.info(f'Commission income: collected reward screenshot (trigger={button.name})')

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
                logger.info("Oil maxed, buy food to consume oil")
                RewardDorm(self.config, self.device).dorm_food_run(amount=10)
                self.ui_ensure(page_reward)

        logger.critical(f'Failed to handle oil maxed after 3 trial')
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
            logger.info('Detected TACTICAL_CLASS_START, clicking cancel to exit')
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
        logger.info(f'Commission finish: {[str(f) for f in future_finish]}')
        if len(future_finish):
            self.config.task_delay(target=future_finish)
        else:
            logger.info('No commission running')
            self.config.task_delay(success=False)

        # 延迟钻石 farming / 三油低耗任务
        # 遍历使用 GemsFarming 配置组的任务，检查是否启用且开启了 CommissionLimit
        limit_tasks = [
            task for task in ['GemsFarming', 'ThreeOilLowCost']
            if self.config.is_task_enabled(task)
            and self.config.cross_get(keys=f'{task}.GemsFarming.CommissionLimit', default=False)
        ]

        if limit_tasks:
            daily = self.daily.select(category_str='daily', status='pending').count
            filtered_urgent = self.comm_choose.intersect_by_eq(self.urgent.select(status='pending')).count
            filtered_extra = self.comm_choose.intersect_by_eq(self.daily.select(category_str='extra', status='pending')).count
            logger.info(f'Daily commission: {daily}, filtered_urgent: {filtered_urgent}, filtered_extra: {filtered_extra}')
            future = nearest_future(future_finish) if len(future_finish) else None
            if daily > 0 and filtered_urgent >= 1:
                for task in limit_tasks:
                    logger.info(f"Having daily commissions to do, delay task '{task}'")
                    self.config.task_delay(minute=None if future else 120, target=future, task=task)
            elif filtered_urgent >= 4:
                for task in limit_tasks:
                    logger.info(f"Having too many urgent commissions, delay task '{task}'")
                    self.config.task_delay(minute=None if future else 120, target=future, task=task)
