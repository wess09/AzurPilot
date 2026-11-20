"""大舰队后勤模块。

处理大舰队后勤页面中的所有交互操作，包括：
- 大舰队物资补给的领取
- 每周大舰队任务的接取与奖励领取
- 大舰队资源兑换（使用舰队资源兑换物品）

该模块支持多服务器（CN/EN/JP/TW）的差异化处理，
通过 `@Config.when(SERVER=...)` 装饰器实现服务器特定的任务状态检测逻辑。

配置项前缀：`GuildLogistics_*`
"""

import re

from module.base.button import ButtonGrid
from module.base.decorator import Config, cached_property
from module.base.filter import Filter
from module.base.runtime_params import GUILD_EXCHANGE_BUG_RETRY, GUILD_SUPPLY_MAX_RETRY
from module.base.timer import Timer
from module.base.utils import *
from module.config.utils import read_run_param
from module.combat.assets import GET_ITEMS_1
from module.exception import GameBugError
from module.guild.assets import *
from module.guild.base import GuildBase
from module.logger import logger
from module.ocr.ocr import Digit
from module.statistics.item import ItemGrid

EXCHANGE_GRIDS = ButtonGrid(
    origin=(470, 470), delta=(198.5, 0), button_shape=(83, 83), grid_shape=(3, 1), name='EXCHANGE_GRIDS')
EXCHANGE_BUTTONS = ButtonGrid(
    origin=(440, 609), delta=(198.5, 0), button_shape=(144, 31), grid_shape=(3, 1), name='EXCHANGE_BUTTONS')
EXCHANGE_FILTER = Filter(regex=re.compile('^(.*?)$'), attr=('name',))
# 补给重试与兑换 BUG 判定阈值走 WebUI「运行参数」页（RunParams.UiWait），
# 默认值集中在 module/base/runtime_params.py（界面等待域）。


class ExchangeLimitOcr(Digit):
    """大舰队兑换次数 OCR 识别器。

    对图像进行反色和灰度映射预处理，以提高兑换次数数字的识别精度。
    """
    def pre_process(self, image):
        """对图像进行反色和灰度映射预处理。

        Args:
            image (np.ndarray): 待处理的 RGB 图像矩阵。

        Returns:
            np.ndarray: 预处理后的灰度图像矩阵。
        """
        return 255 - color_mapping(rgb2gray(image), max_multiply=2.5)


GUILD_EXCHANGE_LIMIT = ExchangeLimitOcr(OCR_GUILD_EXCHANGE_LIMIT, threshold=64)


class GuildLogistics(GuildBase):
    """大舰队后勤处理器。

    负责大舰队后勤页面中的所有自动化操作：
    - 领取物资补给（supply）
    - 接取或领取每周任务奖励（mission）
    - 使用资源兑换物品（exchange）

    通过状态循环模式管理多个子任务的执行顺序，
    并处理各种弹窗和异常情况。

    Attributes:
        _guild_logistics_mission_finished (bool): 本周大舰队任务是否已完成。
        exchange_items (ItemGrid): 兑换物品网格，用于识别可兑换的物品类型。
    """
    _guild_logistics_mission_finished = False

    @cached_property
    def exchange_items(self):
        """获取兑换物品网格实例。

        加载 `./assets/stats_basic` 中的模板图像，用于识别可兑换的物品类型。

        Returns:
            ItemGrid: 兑换物品网格对象。
        """
        item_grid = ItemGrid(
            EXCHANGE_GRIDS, {}, template_area=(40, 21, 89, 70), amount_area=(60, 71, 91, 92))
        item_grid.load_template_folder('./assets/stats_basic')
        return item_grid

    def _is_in_guild_logistics(self):
        """通过颜色特征判断当前是否处于大舰队后勤界面。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS

        Returns:
            bool: 处于大舰队后勤界面返回 True，否则返回 False。
        """
        # Axis (181, 97, 99) and Azur (148, 178, 255)
        return bool(
            self.image_color_count(
                GUILD_LOGISTICS_ENSURE_CHECK,
                color=(181, 97, 99),
                threshold=30,
                count=400,
            )
            or self.image_color_count(
                GUILD_LOGISTICS_ENSURE_CHECK,
                color=(148, 178, 255),
                threshold=30,
                count=400,
            )
        )

    def _guild_logistics_ensure(self, skip_first_screenshot=True):
        """确保大舰队后勤界面已完全加载。

        进入后勤界面后，背景、看板娘立绘与后勤组件会依次加载。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_guild
            out: GUILD_LOGISTICS
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._is_in_guild_logistics():
                break

    @Config.when(SERVER='en')
    def _guild_logistics_mission_available(self, accept_timer):
        """检测大舰队任务按钮当前是否可点击或已激活（EN 服规则）。

        通过颜色采样判断任务是已完成、进行中、可领取还是可接取。

        Returns:
            bool: 按钮处于激活状态返回 True，否则返回 False。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        r, g, b = get_color(self.device.image, GUILD_MISSION.area)
        if g > max(r, b) - 10:
            # 任务完成时右下角有绿色对勾
            logger.info('[大舰队-后勤] 本周大舰队任务已完成')
            self._guild_logistics_mission_finished = True
            return False
        # EN 服中 0/300 是加粗纯白色，而领取奖励是蓝白色，因此翻转判断
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=20, count=100):

            logger.info('[大舰队-后勤] 大舰队任务按钮未激活')
            return False
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=75, count=50):
            # 白色像素少于 50，但包含蓝白色像素
            logger.info('[大舰队-后勤] 大舰队任务按钮已激活')
            return True
        else:
            # 无任务计数
            logger.info('[大舰队-后勤] 未找到大舰队任务，本周任务可能未开始')
            return False

    @Config.when(SERVER='jp')
    def _guild_logistics_mission_available(self, accept_timer):
        """根据日服后勤页面的模板判断每周任务状态。

        Args:
            accept_timer (Timer): 确认接取按钮持续可见的计时器。

        Returns:
            bool | None: 可接取或领奖为 True，当前无操作为 False，等待下一帧为 None。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        if self.info_bar_count():
            accept_timer.clear()
            return None

        if self.appear(GUILD_MISSION_FINISHED, offset=(20, 20)):
            logger.info('[大舰队-后勤] 本周大舰队任务已完成')
            self._guild_logistics_mission_finished = True
            return False
        # 进度文案居中，数字位数变化会改变 /300 的横向位置。
        if self.appear(GUILD_MISSION_IN_PROGRESS, offset=(40, 20)):
            logger.info('[大舰队-后勤] 大舰队任务进行中')
            return False
        if self.appear(GUILD_MISSION_CLAIM, offset=(20, 20)):
            accept_timer.clear()
            logger.info('[大舰队-后勤] 大舰队任务奖励可领取')
            return True
        if self.appear(GUILD_MISSION_ACCEPT, offset=(20, 20)):
            # 新任务加载时会短暂显示接取按钮，由外层循环换帧确认。
            if accept_timer.start().reached():
                logger.info('[大舰队-后勤] 大舰队任务可接取')
                return True
            return None

        logger.info('[大舰队-后勤] 大舰队任务按钮未激活')
        return False

    @Config.when(SERVER=None)
    def _guild_logistics_mission_available(self, accept_timer):
        """检测大舰队任务按钮当前是否可点击或已激活（默认规则，如 CN/TW 服）。

        Returns:
            bool: 按钮处于激活状态返回 True，否则返回 False。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        r, g, b = get_color(self.device.image, GUILD_MISSION.area)
        if g > max(r, b) - 10:
            # 任务完成时右下角有绿色对勾
            logger.info('[大舰队-后勤] 本周大舰队任务已完成')
            self._guild_logistics_mission_finished = True
            return False
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=75, count=400):
            # 未完成任务的接取/领取像素数量大约在 240 到 322 之间
            logger.info('[大舰队-后勤] 大舰队任务按钮已激活')
            return True
        elif not self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=75, count=50):
            # 无任务计数
            logger.info('[大舰队-后勤] 未找到大舰队任务，本周任务可能未开始')
            return False
        else:
            logger.info('[大舰队-后勤] 大舰队任务按钮未激活')
            return False

    def _guild_logistics_supply_available(self):
        """通过颜色采样检测大舰队补给按钮是否激活。

        Returns:
            bool: 按钮处于激活状态返回 True，否则返回 False。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        color = get_color(self.device.image, GUILD_SUPPLY.area)
        # 激活按钮为白色字体，未激活按钮为灰色字体
        if np.max(color) > np.mean(color) + 25:
            # 普通成员点击领取补给；指挥官点击购买并领取补给
            logger.info('[大舰队-后勤] 大舰队补给按钮已激活')
            return True
        else:
            logger.info('[大舰队-后勤] 大舰队补给按钮未激活')
            return False

    def _handle_guild_fleet_mission_start(self):
        """选择并开启新的每周大舰队任务（需要司令或副司令权限）。

        Returns:
            bool: 是否点击了开启或选择任务按钮。
        """
        if not self.config.GuildLogistics_SelectNewMission:
            return False

        if self.appear_then_click(GUILD_MISSION_NEW, offset=(20, 20), interval=2):
            return True
        return bool(
            self.appear_then_click(
                GUILD_MISSION_SELECT, offset=(20, 20), interval=2
            )
        )

    def _guild_logistics_supply_check_finished(self, state):
        """标记补给已完成检查，并清除待处理的点击状态。

        Args:
            state (dict): 补给状态追踪字典。
        """
        state['checked'] = True
        state['clicked'] = False

    def _guild_logistics_supply_handle(self, state, click_interval, result_timer):
        """处理大舰队补给领取的重试与确认流程。

        Args:
            state (dict): 补给状态字典。
            click_interval (Timer): 点击间隔计时器。
            result_timer (Timer): 结果等待计时器。

        Returns:
            bool: 补给逻辑已处理且循环应继续返回 True，否则返回 False。
        """
        if state['checked']:
            return False

        if not state['clicked']:
            if not self._guild_logistics_supply_available():
                return False

            if click_interval.reached():
                self.device.click(GUILD_SUPPLY)
                click_interval.reset()
                state['clicked'] = True
                state['click_count'] += 1
                result_timer.reset()
            return True

        if not self._guild_logistics_supply_available():
            self._guild_logistics_supply_check_finished(state)
            return False

        if not result_timer.reached():
            return True

        supply_max_retry = int(read_run_param(
            self.config, 'UiWait_GuildSupplyMaxRetry', GUILD_SUPPLY_MAX_RETRY, 1, 10))
        if state['click_count'] >= supply_max_retry:
            logger.warning('[大舰队-后勤] 重试后大舰队补给仍可用，本次跳过')
            self._guild_logistics_supply_check_finished(state)
            return False

        if click_interval.reached():
            self.device.click(GUILD_SUPPLY)
            click_interval.reset()
            state['click_count'] += 1
            result_timer.reset()
        return True

    def _guild_logistics_exchange_bug_check(self, exchange_count):
        """检查多次兑换失败是否触发了游戏内置的时间刷新 Bug。

        跨天挂机时兑换大舰队可能提示时间未到，通常重进后勤页面或重启可恢复。

        Args:
            exchange_count (int): 当前已尝试的兑换点击次数。

        Raises:
            GameBugError: 连续多次兑换无响应，判定触发游戏 Bug。
        """
        exchange_bug_retry = int(read_run_param(
            self.config, 'UiWait_GuildExchangeBugRetry', GUILD_EXCHANGE_BUG_RETRY, 1, 20))
        if exchange_count < exchange_bug_retry:
            return

        # 跨天挂机时若执行大舰队兑换，可能出现提示时间未到的游戏 Bug
        # 单纯重启游戏无法解决，需要进入一次大舰队后勤后再重启
        logger.warning(
            'Unable to do guild exchange, probably because the timer in game was bugged')
        raise GameBugError('Triggered guild logistics refresh bug')

    def _guild_logistics_timer_reset(self, confirm_timer, exchange_interval=None):
        """重置后勤界面的确认稳定计时器与兑换重试计时器。

        Args:
            confirm_timer (Timer): 页面稳定计时器。
            exchange_interval (Timer, optional): 兑换重试间隔计时器。
        """
        confirm_timer.reset()
        if exchange_interval is not None:
            exchange_interval.reset()

    def _guild_logistics_popup_handle(self, supply_state, confirm_timer, exchange_interval):
        """处理后勤界面弹窗、获得物资界面及开启任务弹窗。

        Args:
            supply_state (dict): 补给状态字典。
            confirm_timer (Timer): 页面稳定计时器。
            exchange_interval (Timer): 兑换重试间隔计时器。

        Returns:
            bool: 检测并处理了弹窗返回 True，否则返回 False。
        """
        if self.handle_popup_confirm('GUILD_LOGISTICS'):
            self._guild_logistics_timer_reset(confirm_timer, exchange_interval)
            return True

        if self.appear_then_click(GET_ITEMS_1, interval=2):
            if supply_state['clicked']:
                self._guild_logistics_supply_check_finished(supply_state)
            self._guild_logistics_timer_reset(confirm_timer, exchange_interval)
            return True

        if self._handle_guild_fleet_mission_start():
            self._guild_logistics_timer_reset(confirm_timer)
            return True

        return False

    def _guild_logistics_mission_handle(self, mission_checked, click_interval, accept_timer):
        """处理大舰队每周任务的领取或接取操作。

        Args:
            mission_checked (bool): 任务是否已被检查。
            click_interval (Timer): 点击间隔计时器。
            accept_timer (Timer): 日服接取按钮的稳定确认计时器。

        Returns:
            tuple[bool, bool]: 更新后的已检查状态，以及循环是否应继续处理下一帧。
        """
        if mission_checked:
            return True, False

        available = self._guild_logistics_mission_available(accept_timer)
        if available is None:
            return False, True
        if not available:
            return True, False

        if click_interval.reached():
            self.device.click(GUILD_MISSION)
            click_interval.reset()
            accept_timer.clear()
        return False, True

    def _guild_logistics_exchange_handle(self, exchange_checked, exchange_count, exchange_interval):
        """处理大舰队物资兑换操作。

        Args:
            exchange_checked (bool): 兑换是否已完成检查。
            exchange_count (int): 当前轮次已执行的兑换次数。
            exchange_interval (Timer): 兑换重试间隔计时器。

        Returns:
            tuple[bool, int, bool]: 更新后的已检查状态、累计兑换次数，以及是否处理了兑换。
        """
        if exchange_checked or not exchange_interval.reached():
            return exchange_checked, exchange_count, False

        if not self._guild_exchange():
            return True, exchange_count, False

        exchange_interval.reset()
        return False, exchange_count + 1, True

    def _guild_logistics_collect(self, skip_first_screenshot=True):
        """执行后勤界面的补给领取、任务接取/领奖与物资兑换循环。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 所有后勤项目均已完成检查返回 True，否则返回 False。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        logger.hr('大舰队后勤')
        logger.attr('舰队司令/副司令', self.config.GuildLogistics_SelectNewMission)
        confirm_timer = Timer(1.5, count=3).start()
        exchange_interval = Timer(1.5, count=3)
        click_interval = Timer(0.5, count=1)
        mission_accept_timer = Timer(0.5, count=1)
        supply_state = {
            'checked': False,
            'clicked': False,
            'click_count': 0,
        }
        supply_result_timer = Timer(1.5, count=3)
        mission_checked = False
        exchange_checked = False
        exchange_count = 0

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._guild_logistics_popup_handle(supply_state, confirm_timer, exchange_interval):
                mission_accept_timer.clear()
                continue

            if self._is_in_guild_logistics():
                if self._guild_logistics_supply_handle(supply_state, click_interval, supply_result_timer):
                    mission_accept_timer.clear()
                    self._guild_logistics_timer_reset(confirm_timer)
                    continue
                mission_checked, handled = self._guild_logistics_mission_handle(
                    mission_checked, click_interval, mission_accept_timer)
                if handled:
                    self._guild_logistics_timer_reset(confirm_timer)
                    continue
                exchange_checked, exchange_count, handled = self._guild_logistics_exchange_handle(
                    exchange_checked, exchange_count, exchange_interval)
                if handled:
                    self._guild_logistics_timer_reset(confirm_timer)
                    continue
                if not self.info_bar_count() and confirm_timer.reached():
                    break
                self._guild_logistics_exchange_bug_check(exchange_count)

            else:
                mission_accept_timer.clear()
                confirm_timer.reset()

        logger.info(f"supply_checked: {supply_state['checked']}, mission_checked: {mission_checked}, "
                    f'exchange_checked: {exchange_checked}, mission_finished: {self._guild_logistics_mission_finished}')
        return all([supply_state['checked'], mission_checked, exchange_checked])

    def _guild_exchange_scan(self):
        """扫描当前可兑换的物品列表并标记资源是否充足。

        Returns:
            list[Item]: 识别出的兑换物品对象列表。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        # 扫描当前显示的候选兑换物品
        items = self.exchange_items.predict(self.device.image, name=True, amount=False)

        # 遍历 EXCHANGE_GRIDS 检测右下角是否存在材料不足的红字
        for item, button in zip(items, EXCHANGE_GRIDS.buttons):
            area = area_offset((35, 64, 83, 83), button.area[:2])
            item.enough = not self.image_color_count(area, color=(255, 93, 90), threshold=30, count=20)

        text = [str(item.name) if item.enough else f'{item.name} (not enough)' for item in items]
        logger.info(f'[大舰队-后勤] 兑换物品: {", ".join(text)}')
        return items

    def _guild_exchange(self):
        """执行大舰队物资兑换匹配与点击。

        根据配置过滤器筛选满足条件且持有充足兑换材料的物品进行兑换。

        Returns:
            bool: 成功点击兑换按钮返回 True，无剩余次数或无匹配项返回 False。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        if GUILD_EXCHANGE_LIMIT.ocr(self.device.image) <= 0:
            return False

        items = self._guild_exchange_scan()
        EXCHANGE_FILTER.load(self.config.GuildLogistics_ExchangeFilter)
        selected = EXCHANGE_FILTER.apply(items, func=lambda item: item.enough)
        logger.attr('兑换排序', ' > '.join([str(item.name) for item in selected]))

        if len(selected):
            button = EXCHANGE_BUTTONS.buttons[items.index(selected[0])]
            self.device.click(button)
            return True
        else:
            logger.warning('[大舰队-后勤] 没有符合当前筛选条件的兑换物品，或资源不足')
            return False

    def guild_logistics(self):
        """执行大舰队后勤所有操作的主入口。

        Returns:
            bool: 后勤各项目是否均已完成检查。

        Pages:
            in: page_guild
            out: page_guild, GUILD_LOGISTICS
        """
        logger.hr('大舰队后勤', level=1)
        self.guild_side_navbar_ensure(bottom=3)
        self._guild_logistics_ensure()

        result = self._guild_logistics_collect()
        logger.info(f'[大舰队-后勤] 后勤运行成功: {result}')
        return result
