"""大世界行动力管理模块。

处理大世界（Operation Siren）模式下的行动力（Action Point）管理。
包含行动力数值的 OCR 识别、适应性属性读取、药剂（AP Box）库存解析，
以及自动购买或使用补给品的交互逻辑。
"""
# 此文件处理大世界（Operation Siren）模式下的行动力（Action Point, AP）管理。
# 包含行动力数值 OCR 识别、药剂（AP Box）库存解析以及自动购买或使用补给的交互逻辑。
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from time import monotonic, perf_counter

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import *
from module.config.time_source import now as current_time
from module.config.deep import deep_get
from module.config.utils import filepath_config, get_server_next_update, read_file, server_time_offset
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter
from module.os_handler.assets import *
from module.os_handler.map_event import MapEventHandler
from module.os_handler.resource_state import ActionPointSnapshot, resource_fast_path
from module.os_handler.resource_write import record_resources_background
from module.statistics.item import Item, ItemGrid
from module.ui.assets import OS_CHECK
from module.ui.ui import UI
from module.log_res import LogRes

OCR_ACTION_POINT_REMAIN = Digit(ACTION_POINT_REMAIN, letter=(255, 219, 66), name='OCR_ACTION_POINT_REMAIN')
OCR_ACTION_POINT_REMAIN_OS = Digit(ACTION_POINT_REMAIN_OS, letter=(239, 239, 239),
                                   threshold=160, name='OCR_ACTION_POINT_REMAIN_OS')

OCR_OS_ADAPTABILITY = Digit([
    OS_ADAPTABILITY_ATTACK,
    OS_ADAPTABILITY_DURABILITY,
    OS_ADAPTABILITY_RECOVER
], letter=(231, 235, 239), lang="cnocr", name='OCR_OS_ADAPTABILITY')


class ActionPointBuyCounter(DigitCounter):
    """行动力购买次数计数器。"""

    def after_process(self, result):
        """后处理识别结果，修正常见误识别。

        Args:
            result (str): 识别出的原始字符串。

        Returns:
            str: 修正后的购买次数格式字符串。
        """
        result = super().after_process(result)

        # 可能的结果: 0/5, 05
        if result == '05':
            result = '0/5'

        return result


if server.server != 'jp':
    # ACTION_POINT_BUY_REMAIN 中的字符不是碧蓝航线通常使用的数字字体
    OCR_ACTION_POINT_BUY_REMAIN = ActionPointBuyCounter(
        ACTION_POINT_BUY_REMAIN, letter=(148, 247, 99), lang='cnocr', name='OCR_ACTION_POINT_BUY_REMAIN')
else:
    # 日服中 ACTION_POINT_BUY_REMAIN 的数字颜色为白色，国服和国际服为浅绿色
    OCR_ACTION_POINT_BUY_REMAIN = ActionPointBuyCounter(
        ACTION_POINT_BUY_REMAIN, letter=(255, 255, 255), lang='cnocr', name='OCR_ACTION_POINT_BUY_REMAIN')


class ActionPointItem(Item):
    """大世界行动力物品。"""

    def predict_valid(self):
        """预测当前物品是否有效。

        Returns:
            bool: 恒返回 True。
        """
        return True


ACTION_POINT_GRID = ButtonGrid(
    origin=(323, 274), delta=(173, 0), button_shape=(115, 115), grid_shape=(4, 1), name='ACTION_POINT_GRID')


class GridSlice:
    """网格切片，用于构建物品网格。

    Attributes:
        buttons (list[Button]): 切片包含的按钮列表。
    """

    def __init__(self, buttons):
        """初始化网格切片。

        Args:
            buttons (list[Button]): 按钮列表。
        """
        self.buttons = buttons

OIL_ITEM = ItemGrid(GridSlice([ACTION_POINT_GRID.buttons[0]]), templates={}, amount_area=(43, 91, 111, 113))
OIL_ITEM.item_class = ActionPointItem

ACTION_POINT_ITEMS = ItemGrid(GridSlice(ACTION_POINT_GRID.buttons[1:]), templates={}, amount_area=(75, 91, 111, 113))
ACTION_POINT_ITEMS.item_class = ActionPointItem
ACTION_POINTS_COST = {
    1: 5,
    2: 10,
    3: 15,
    4: 20,
    5: 30,
    6: 40,
}
ACTION_POINTS_COST_OBSCURE = {
    1: 10,  # CL1 实际上没有隐秘海域
    2: 10,
    3: 20,
    4: 20,
    5: 40,
    6: 40,
}
ACTION_POINTS_COST_ABYSSAL = {
    1: 80,
    2: 80,
    3: 80,  # CL4 以下实际上没有深渊海域
    4: 80,
    5: 100,
    6: 100,
}
ACTION_POINTS_BUY = {
    1: 4000,
    2: 2000,
    3: 2000,
    4: 1000,
    5: 1000,
}
ACTION_POINT_BOX = {
    0: 0,
    1: 20,
    2: 50,
    3: 100,
}
# 防溢出模式（avoid_ap_overflow）下当前行动力达到该值即直接开工，不再开箱等待
ACTION_POINT_AVOID_OVERFLOW_START = 100


class ActionPointLimit(Exception):
    """行动力不足异常。

    当行动力不足以进入目标海域时抛出。

    Attributes:
        current (int | None): 当前行动力。
        total (int | None): 总行动力（含药剂）。
        cost (int | None): 目标海域消耗。
        preserve (int | None): 保留行动力设定值。
    """

    def __init__(self, current=None, total=None, cost=None, preserve=None):
        """初始化行动力不足异常。

        Args:
            current (int, optional): 当前行动力。
            total (int, optional): 总行动力。
            cost (int, optional): 需要消耗的行动力。
            preserve (int, optional): 保留行动力限制。
        """
        super().__init__()
        self.current = current
        self.total = total
        self.cost = cost
        self.preserve = preserve

    @property
    def delay_minutes(self):
        """获取需要延迟的分钟数。

        Returns:
            int | None: 需要延迟的分钟数，如果无需延迟则返回 None。
        """
        if self.cost is None or self.current is None:
            return None

        missing = self.cost - self.current
        if missing <= 0:
            return None

        return missing * 10


class ActionPointHandler(UI, MapEventHandler):
    """大世界行动力操作处理器。"""

    _action_point_box = [0, 0, 0, 0]
    _action_point_current = 0
    _action_point_total = 0
    _action_point_total_with_box = 0

    def _action_point_identity(self):
        return (getattr(self.config, 'config_name', None), server.server)

    def invalidate_action_point_cache(self):
        """初始化或恢复后不能沿用旧画面的箱子库存。"""
        self.__dict__.pop('_ap_snapshot', None)
        self._ap_read_epoch = self.__dict__.get('_ap_read_epoch', 0) + 1

    def _remember_action_point_snapshot(self):
        if (not bool(getattr(OCR_ACTION_POINT_REMAIN, 'last_valid', False))
                or not self.__dict__.get('_ap_inventory_valid', False)
                or not 0 <= self._action_point_current <= 600
                or len(self._action_point_box) != 4 or self._action_point_box[0] <= 100):
            self.invalidate_action_point_cache()
            return
        self._ap_snapshot = ActionPointSnapshot(
            self._action_point_identity(), monotonic(),
            getattr(self.config, '_opsi_ap_inventory_revision', 0), tuple(self._action_point_box),
            int(self._action_point_current),
        )

    def action_point_cached_read(self):
        """未到检查时间时只使用保守库存，不截图、不 OCR，也不续期。

        Returns:
            tuple[int, int] | None: (当前口径总行动力, 当前行动力)，缓存不可用时为 None。

        Pages:
            in: page_os
            out: page_os
        """
        getattr(self, 'poll_background_resources', lambda: None)()
        snapshot = self.__dict__.get('_ap_snapshot')
        if not resource_fast_path(self.config) or snapshot is None:
            return None
        elapsed = monotonic() - snapshot.checked_at
        if (snapshot.identity != self._action_point_identity()
                or elapsed < 0):
            self.invalidate_action_point_cache()
            return None
        # 奖励和明石购买只会增加箱子；计时内不为它们重新开面板。
        # 开箱、石油购买及未知消耗走原有实时补给读取，不能依赖此下界。
        current = snapshot.current
        box_sum = sum(amount * ACTION_POINT_BOX[index] for index, amount in enumerate(snapshot.boxes))
        self._action_point_current = int(current)
        self._action_point_box = list(snapshot.boxes)
        self._action_point_total_with_box = int(current + box_sum)
        self.config._action_point_total_with_box = self._action_point_total_with_box
        self._action_point_total = int(current + box_sum if self.config.OS_ACTION_POINT_BOX_USE else current)
        logger.info(f'[大世界-行动点] 复用行动力下界，不等待截图与识别，距实测 {elapsed:.1f}s')
        return self._action_point_total, self._action_point_current

    def action_point_check_due(self):
        """定时读取在已有地图截图上后台执行；0 关闭定时读取。"""
        snapshot = self.__dict__.get('_ap_snapshot')
        interval = self._action_point_policy_value('OpsiHazard1Leveling_ActionPointCheckInterval')
        return (snapshot is not None and snapshot.identity == self._action_point_identity()
                and type(interval) is int and interval > 0
                and monotonic() - snapshot.checked_at >= interval * 60)

    def apply_background_action_point(self, reading):
        """扣除采样后确认的消耗；补给、恢复和实例变化后拒绝旧结果。"""
        snapshot = self.__dict__.get('_ap_snapshot')
        if (snapshot is None or reading.ap is None or reading.ap_epoch != self.__dict__.get('_ap_read_epoch', 0)
                or snapshot.identity != self._action_point_identity()):
            return
        spent_since = self.__dict__.get('_ap_spent', 0) - reading.ap_spent
        current = max(0, reading.ap - max(0, spent_since))
        box_sum = sum(amount * ACTION_POINT_BOX[index] for index, amount in enumerate(snapshot.boxes))
        self._ap_snapshot = replace(snapshot, current=current, checked_at=reading.sampled_at)
        self._action_point_current = current
        self._action_point_total_with_box = current + box_sum
        self._action_point_total = current + box_sum if self.config.OS_ACTION_POINT_BOX_USE else current
        # 箱子仍是下界，不伪装成新的实测总库存。当前 AP 的时间固定在采样帧。
        record_resources_background(self.config, {'ActionPoint': {'Value': reading.ap}},
                                    observed_at=reading.observed_at)

    def consume_cached_action_point(self, amount):
        """按已确认的出击扣减行动力下界；不把估计值作为成功观察写库。"""
        self._ap_spent = self.__dict__.get('_ap_spent', 0) + amount
        snapshot = self.__dict__.get('_ap_snapshot')
        if snapshot is not None:
            self._ap_snapshot = replace(snapshot, current=max(0, snapshot.current - amount))
            self._action_point_current = self._ap_snapshot.current
            self._action_point_total = max(0, self._action_point_total - amount)
            self._action_point_total_with_box = max(0, self._action_point_total_with_box - amount)

    def _action_point_panel_values(self):
        """同帧合并四种库存的首轮推理，异常数量仍逐项重试。"""
        image = self.device.image
        OIL_ITEM._load_image(image)
        ACTION_POINT_ITEMS._load_image(image)
        entries = [(OIL_ITEM, item) for item in OIL_ITEM.items]
        entries += [(ACTION_POINT_ITEMS, item) for item in ACTION_POINT_ITEMS.items]
        amounts = OIL_ITEM.amount_ocr.ocr_batch_with_validation(
            [item.crop(grid.amount_area_for(item.name)) for grid, item in entries],
            item_names=[item.name for _, item in entries],
            amount_max=OIL_ITEM.amount_max, amount_default_max=OIL_ITEM.amount_default_max,
            batch_first=True,
        )
        if len(amounts) != 4:
            raise ValueError('行动力面板库存必须包含石油与三种箱子')
        validities = getattr(OIL_ITEM.amount_ocr, 'last_batch_validity', ())
        self._ap_inventory_valid = len(validities) == 4 and all(validities)
        self._ap_observation_inventory_valid = self._action_point_inventory_observed(amounts, validities)
        return amounts, OCR_ACTION_POINT_REMAIN.ocr(image)

    def _action_point_inventory_observed(self, quantities, validities):
        """完整面板的空白箱格可为零；有文字却未识别的格子仍不可用于报价。"""
        if len(quantities) != 4 or len(validities) != 4:
            return False
        if all(validities):
            return True
        # 石油格不能按空白补零，加载中的弹窗也不能作为完整库存。
        if (not validities[0] or quantities[0] <= 100
                or not isinstance(self.device.image, np.ndarray)
                or not self.appear(ACTION_POINT_USE, offset=(20, 20))
                or not self.appear(ACTION_POINT_CANCEL, offset=(20, 20))
                or len(ACTION_POINT_ITEMS.items) != 3):
            return False
        for item, quantity, valid in zip(ACTION_POINT_ITEMS.items, quantities[1:], validities[1:]):
            if valid:
                continue
            if quantity != 0:
                return False
            area = ACTION_POINT_ITEMS.amount_area_for(item.name)
            letters = ACTION_POINT_ITEMS.amount_ocr.pre_process(item.crop(area))
            # 不把 OCR 的空结果直接当零：数量区存在可见字形时必须重新识别。
            if not isinstance(letters, np.ndarray) or not letters.size or np.any(letters != 255):
                return False
        return True

    @staticmethod
    def _is_in_month_end_purchase_block_week():
        """判断当前是否处于月末购买封锁周。

        在包含下个服务器月第一天的自然周（周一至周日）内，封锁每周行动力购买。
        进入下个服务器月后，购买将重新可用。

        Returns:
            bool: 是否处于月末封锁周。
        """
        diff = server_time_offset()
        server_now = current_time() - diff
        next_month = (server_now.replace(day=28) + timedelta(days=4)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        next_month_start = next_month.replace(day=1)
        current_week_start = server_now.date() - timedelta(days=server_now.weekday())
        next_month_week_start = next_month_start.date() - timedelta(days=next_month_start.weekday())
        return current_week_start == next_month_week_start

    def _is_in_action_point(self):
        """判断是否处于行动力使用弹窗。

        Returns:
            bool: 是否出现行动力使用弹窗。
        """
        return self.appear(ACTION_POINT_USE, offset=(20, 20))

    def is_current_ap_visible(self):
        """判断当前行动力数值区域是否可见。

        Returns:
            bool: 是否可见。
        """
        return self.match_template_color(CURRENT_AP_CHECK, offset=(40, 5), threshold=15)

    def action_point_use(self):
        """执行一次行动力道具使用或购买操作。

        点击使用按钮并确认，直到当前行动力数值增加。
        """
        prev = self._action_point_current
        self.interval_clear(ACTION_POINT_USE)
        for _ in self.loop():

            if self.appear_then_click(ACTION_POINT_USE, offset=(20, 20), interval=3):
                self.device.sleep(0.3)
                continue

            if self.handle_popup_confirm('ACTION_POINT_USE'):
                continue

            self.action_point_safe_get()
            if self._action_point_current > prev:
                break

    def action_point_update(self):
        """
        更新行动力信息。

        Returns:
            int: 总行动力，包括行动力药剂。
        """
        started = perf_counter()
        fast = resource_fast_path(self.config)
        if fast:
            box, current = self._action_point_panel_values()
        else:
            oil = OIL_ITEM.predict(self.device.image, name=False, amount=True)
            # 两个网格共用数量 OCR，读取箱子前保留本批石油的校验结果。
            oil_validities = getattr(OIL_ITEM.amount_ocr, 'last_batch_validity', ())
            items = ACTION_POINT_ITEMS.predict(self.device.image, name=False, amount=True)
            box = [item.amount for item in oil] + [item.amount for item in items]
            validities = (oil_validities
                          + getattr(ACTION_POINT_ITEMS.amount_ocr, 'last_batch_validity', ()))
            self._ap_inventory_valid = len(validities) == 4 and all(validities)
            self._ap_observation_inventory_valid = self._action_point_inventory_observed(box, validities)
            current = OCR_ACTION_POINT_REMAIN.ocr(self.device.image)
        ocr_finished = perf_counter()
        box_sum = np.sum(np.array(box) * tuple(ACTION_POINT_BOX.values()))
        total = current
        if self.config.OS_ACTION_POINT_BOX_USE:
            total += box_sum
        oil = box[0]

        resource_log = LogRes(self.config)
        record_options = {'defer_history': True} if fast else {}
        if oil > 100 and not fast:
            resource_log.record('Oil', oil, observed=True, **record_options)
        logger.info(f'[大世界-行动点] 行动点: {current}({total}), 石油: {oil}')
        # 统计口径的总行动力始终包含体力箱，不受 OS_ACTION_POINT_BOX_USE 临时关闭的影响
        # （防止行动力溢出任务会临时关闭该开关，导致统计快照丢箱、图表出现深坑）
        self._action_point_total_with_box = int(current + box_sum)
        self.config._action_point_total_with_box = self._action_point_total_with_box
        # 仪表盘的 Total 同样使用恒含体力箱口径：写入受开关影响的 total 时，
        # 防溢出任务运行期间它会退化成 current，WebUI 的行动力卡片会在整段时间里不显示总行动力
        ap_valid = 0 <= current <= 600 and bool(getattr(OCR_ACTION_POINT_REMAIN, 'last_valid', False))
        if fast and ap_valid and self.__dict__.get('_ap_observation_inventory_valid', False):
            values = {'ActionPoint': {'Value': int(current), 'Total': self._action_point_total_with_box}}
            if oil > 100:
                values['Oil'] = int(oil)
            record_resources_background(self.config, values)
        elif not fast:
            values = {'Value': current}
            if ap_valid and self.__dict__.get('_ap_observation_inventory_valid', False):
                values['Total'] = self._action_point_total_with_box
            resource_log.record('ActionPoint', values, observed=ap_valid, **record_options)
        recorded = perf_counter()
        if not fast:
            if self.__dict__.get('_ap_defer_config_update', False):
                self._ap_config_dirty = True
            else:
                self.config.update()
        self._action_point_current = current
        self._action_point_box = box
        self._action_point_total = total
        # 处理超出上限的情况
        if total > 3000:
            self.config.override(OpsiGeneral_DoRandomMapEvent=False)
        logger.info(f'[大世界-行动力耗时] OCR={ocr_finished - started:.3f}s，'
                    f'记录={recorded - ocr_finished:.3f}s，配置={perf_counter() - recorded:.3f}s')

    def action_point_safe_get(self):
        """
        安全获取行动力信息。

        等待行动力弹窗完全加载，并处理可能的地图事件。
        """
        self.invalidate_action_point_cache()
        timeout = Timer(3, count=6).start()
        for _ in self.loop():
            # 结束
            if self.is_current_ap_visible():
                break
            if timeout.reached():
                logger.warning('[大世界-行动点] 获取行动点超时')
                break
            # 处理行动力弹窗上方的强制地图事件
            if self.handle_map_event():
                timeout.reset()
                continue

        skip_first_screenshot = True
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('[大世界-行动点] 获取行动点超时')
                break
            # 处理行动力弹窗上方的强制地图事件
            if self.handle_map_event():
                timeout.reset()
                continue

            self.action_point_update()

            # 当前行动力过多，可能是 OCR 错误
            if self._action_point_current > 600:
                continue

            oil, boxes = self._action_point_box[0], self._action_point_box[1:]
            # 拥有药剂
            if sum(boxes) > 0:
                if oil > 100:
                    self._remember_action_point_snapshot()
                    break
                else:
                    # [11, 0, 1, 0]
                    continue
            # 或者拥有石油
            # 页面未完全加载时可能为 0 或 1
            # [1, 0, 0, 0]
            if oil > 100:
                self._remember_action_point_snapshot()
                break

    @staticmethod
    def action_point_get_cost(zone, pinned):
        """
        获取进入指定海域所需的行动力消耗。

        Args:
            zone (Zone): 要进入的海域。
            pinned (str): 海域类型。可用类型: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD。

        Returns:
            int: 消耗的行动力。
        """
        if pinned == 'DANGEROUS':
            cost = ACTION_POINTS_COST[zone.hazard_level] * 2
        elif pinned == 'SAFE':
            cost = ACTION_POINTS_COST[zone.hazard_level]
        elif pinned == 'OBSCURE':
            cost = ACTION_POINTS_COST_OBSCURE[zone.hazard_level]
        elif pinned == 'ABYSSAL':
            cost = ACTION_POINTS_COST_ABYSSAL[zone.hazard_level]
        elif pinned == 'STRONGHOLD':
            cost = 200
        else:
            logger.warning(f'[大世界-行动点] 无法获取行动点消耗, 区域={zone}, 固定={pinned}，假设消耗40')
            cost = 40

        if zone.is_port:
            cost = 0

        return cost

    def action_point_get_active_button(self):
        """
        获取当前激活的行动力药剂按钮索引。

        Returns:
            int: 0 到 3。0 为石油，1 为 20 行动力药剂，2 为 50 行动力药剂，3 为 100 行动力药剂。
        """
        for index, item in enumerate(ACTION_POINT_GRID.buttons):
            area = item.area
            color = get_color(self.device.image, area=(area[0], area[3] + 5, area[2], area[3] + 10))
            # 激活的按钮会变蓝
            # 激活: 196, 未激活: 118 ~ 123
            if color[2] > 160:
                return index

        logger.warning('[大世界-行动点] 无法找到活动的行动点箱子按钮')
        return 1

    def action_point_set_button(self, index):
        """
        设置行动力药剂按钮。

        Args:
            index (int): 0 到 3。0 为石油，1 为 20 行动力药剂，2 为 50 行动力药剂，3 为 100 行动力药剂。

        Returns:
            bool: 是否成功。
        """
        for _ in self.loop(timeout=2):
            if self.action_point_get_active_button() == index:
                return True
            else:
                self.device.click(ACTION_POINT_GRID[index, 0])
                self.device.sleep(0.3)
        else:
            logger.warning('[大世界-行动点] 设置行动点按钮超时')
            return False

    def action_point_get_buy_remain(self):
        """
        获取行动力剩余购买次数。

        Returns:
            int | None: 有效剩余购买次数；识别失败时不把未知值当成已买满。

        Pages:
            in: ACTION_POINT_USE
        """
        for _ in self.loop(timeout=1):

            current, _, total = OCR_ACTION_POINT_BUY_REMAIN.ocr(self.device.image)

            # 可能的结果: 0/5, 05
            if total != 5 or not 0 <= current <= total:
                continue
            return current
        else:
            logger.warning('[大世界-行动点] 获取行动点购买剩余超时')

        return None

    def _action_point_purchase_key(self):
        server_now = current_time() - server_time_offset()
        monday = server_now.date() - timedelta(days=server_now.weekday())
        return self._action_point_identity(), monday

    def _action_point_policy_value(self, argument):
        """文件变更时轻量读取购买上限和检查间隔，保留代理参数的优先级。"""
        current = getattr(self.config, argument, 0)
        if (argument in getattr(self.config, 'overridden', {})
                or argument in getattr(self.config, '_scheduler_overrides', {})):
            return current
        name = getattr(self.config, 'config_name', None)
        bound = getattr(self.config, 'bound', None)
        if not isinstance(name, str) or not isinstance(bound, dict):
            return current
        try:
            path = Path(filepath_config(name))
            stamp = path.stat().st_mtime_ns
            policy = self.__dict__.get('_ap_resource_policy')
            if policy is None or policy[:2] != (str(path), stamp):
                data = read_file(str(path))
                values = {}
                for attr in ('OpsiGeneral_BuyActionPointLimit', 'OpsiHazard1Leveling_ActionPointCheckInterval'):
                    group, field = attr.split('_', 1)
                    key = bound.get(attr, f'{group}.{group}.{field}')
                    value = deep_get(data, key, default=getattr(self.config, attr, 0))
                    if type(value) is int and value >= 0 and (attr.endswith('Interval') or value <= 5):
                        values[attr] = value
                self._ap_resource_policy = (str(path), stamp, values)
            policy = self.__dict__.get('_ap_resource_policy')
            return policy[2].get(argument, current) if policy is not None and policy[0] == str(path) else current
        except (OSError, ValueError):
            logger.warning('[大世界-行动点] 无法读取最新行动力策略，沿用当前有效配置')
            return current

    def _action_point_purchase_limit(self):
        """在下一个安全购买点使上限增减生效，实际已购次数保持不变。"""
        return self._action_point_policy_value('OpsiGeneral_BuyActionPointLimit')

    def action_point_buy(self, preserve=1000):
        """
        使用石油购买行动力。

        Args:
            preserve (int): 保留的石油量。

        Returns:
            bool: 是否购买成功。

        Pages:
            in: ACTION_POINT_USE
        """
        buy_limit = self._action_point_purchase_limit()
        if buy_limit <= 0:
            return False
        if self._is_in_month_end_purchase_block_week():
            logger.info('[大世界-行动点] 跳过本周购买行动点，因为是月末封锁周')
            return False
        key = self._action_point_purchase_key()
        cached = self.__dict__.get('_ap_purchase_count')
        if cached is not None and cached[0] == key and cached[1] >= buy_limit:
            logger.info(f'[大世界-行动点] 本周购买缓存命中：已购={cached[1]}，当前上限={buy_limit}')
            return False
        if not self.action_point_set_button(0):
            return False
        current = self.action_point_get_buy_remain()
        if current is None:
            return False
        buy_count = 5 - current
        self._ap_purchase_count = (key, buy_count)
        buy_limit = self._action_point_purchase_limit()
        if buy_count >= buy_limit:
            logger.info('[大世界-行动点] 达到本周购买行动点上限')
            return False
        cost = ACTION_POINTS_BUY[current]
        oil = self._action_point_box[0]
        logger.info(f'[大世界-行动点] 购买行动点将消耗 {cost}, 当前石油: {oil}, 保留: {preserve}')
        if oil >= cost + preserve:
            if key != self._action_point_purchase_key() or self._is_in_month_end_purchase_block_week():
                return False
            try:
                self.action_point_use()
            except Exception:
                self.__dict__.pop('_ap_purchase_count', None)
                self.invalidate_action_point_cache()
                raise
            remaining = self.action_point_get_buy_remain()
            if remaining == current - 1:
                self._ap_purchase_count = (key, 5 - remaining)
            else:
                self.__dict__.pop('_ap_purchase_count', None)
                logger.warning('[大世界-行动点] 购买后次数尚未确认，下次重新读取')
            return True
        else:
            logger.info('[大世界-行动点] 石油不足无法购买')
            return False

    def action_point_quit(self):
        """
        退出行动力弹窗。

        Pages:
            in: ACTION_POINT_USE
            out: page_os
        """
        for _ in self.loop():
            # 结束
            # 有时行动力弹窗没有黑色模糊背景
            # ACTION_POINT_CANCEL 和 OS_CHECK 同时出现
            if not self.appear(ACTION_POINT_CANCEL, offset=(20, 20)):
                if self.appear(OS_CHECK, offset=(20, 20)):
                    break
            # 点击
            if self.appear_then_click(ACTION_POINT_CANCEL, offset=(20, 20), interval=3):
                continue
            # 处理行动力弹窗上方的强制地图事件
            if self.handle_map_event():
                continue

        # 「打开弹窗读行动力 → 取消关闭」是设计内的成对操作，一轮里会被连续调用多次
        # （智能调度决策、短猫前置检查、统计快照），点击记录（最近 15 次）会攒出
        # 两个按钮各 ≥6 次，被「两个按钮交替点击次数过多」规则误判成卡死。
        # 只在弹窗确实关闭后清理：真卡死时上面的循环不会跳出，仍由单按钮 ≥12 次兜底。
        self.device.click_record_remove(ACTION_POINT_REMAIN_OS)
        self.device.click_record_remove(ACTION_POINT_CANCEL)
        # 已正向确认弹窗关闭；下一次有意打开无需继承上一次的3秒重试冷却。
        self.interval_clear(OS_CHECK)

    def handle_action_point(self, zone, pinned, cost=None, keep_current_ap=True, check_rest_ap=False,
                            avoid_ap_overflow=False, *, skip_first_read=False):
        """同一次补充只合并提交一次仪表盘配置，操作后的实际读数仍刷新。"""
        fast = resource_fast_path(self.config)
        previous = self.__dict__.get('_ap_defer_config_update', False)
        self._ap_defer_config_update = fast or previous
        try:
            return self._handle_action_point(
                zone, pinned, cost, keep_current_ap, check_rest_ap, avoid_ap_overflow,
                skip_first_read=skip_first_read,
            )
        finally:
            self._ap_defer_config_update = previous
            if not previous and self.__dict__.pop('_ap_config_dirty', False):
                started = perf_counter()
                self.config.update()
                logger.info(f'[大世界-行动力耗时] 补充后合并配置={perf_counter() - started:.3f}s')

    def _handle_action_point(self, zone, pinned, cost=None, keep_current_ap=True, check_rest_ap=False,
                            avoid_ap_overflow=False, *, skip_first_read=False):
        """
        处理行动力，包括购买和使用药剂。

        Args:
            zone (Zone): 要进入的海域。
            pinned (str): 海域类型。可用类型: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD。
            cost (int): 自定义行动力消耗值。
            keep_current_ap (bool): 是否先检查行动力，避免在不足时使用剩余行动力。
            check_rest_ap (bool): 如果当前行动力与今天可获得的剩余行动力之和超过 200，则跳过 keep_current_ap 检查。
            avoid_ap_overflow (bool): 防溢出模式（侵蚀1练级专用）。
                当前行动力达到 100 即直接开工、不开启行动力箱（100-119 区间
                不再等待自然恢复，也不开 100 箱造成溢出）；低于 100 时开箱后
                达到或超过 200 满值的箱子不开启。
            skip_first_read (bool): 已在同一面板安全读取过行动力时复用首读。
                只省略操作前的重复读取，购买或开箱后的实际读数仍须刷新。

        Returns:
            bool: 是否处理成功。

        Raises:
            ActionPointLimit: 行动力不足时抛出。

        Pages:
            in: ACTION_POINT_USE
        """
        if not self._is_in_action_point():
            return False

        # 行动力药剂有显示动画
        if not skip_first_read:
            self.action_point_safe_get()
        if cost is None:
            cost = self.action_point_get_cost(zone, pinned)
        buy_checked = None

        # 检查剩余行动力
        if check_rest_ap:
            diff = get_server_next_update('00:00') - current_time()
            today_rest = int(diff.total_seconds() // 600)
            if self._action_point_current + today_rest >= 200:
                logger.info('[大世界处理-行动力] 当前行动力与今日可获得的剩余行动力之和超过 200，跳过行动力检查')
                logger.info(f'[大世界-行动点] 当前={self._action_point_current}  今日剩余={today_rest}')
                keep_current_ap = False

        # 先检查行动力
        if keep_current_ap:
            if self._action_point_total <= self.config.OS_ACTION_POINT_PRESERVE:
                logger.info(f'[大世界-行动点] 达到行动点上限, 保留={self.config.OS_ACTION_POINT_PRESERVE}')
                self.action_point_quit()
                raise ActionPointLimit(
                    current=self._action_point_current,
                    total=self._action_point_total,
                    preserve=self.config.OS_ACTION_POINT_PRESERVE,
                )

        for _ in range(12):
            # 拥有足够的行动力
            if self._action_point_current >= cost:
                logger.info('[大世界-行动点] 行动点充足')
                self.action_point_quit()
                return True

            # 防溢出模式下，行动力达到开工线即直接开工，不开启行动力箱。
            # 开工线到 119 区间不再等待自然恢复，也不会开启 100 箱造成溢出。
            if avoid_ap_overflow and self._action_point_current >= ACTION_POINT_AVOID_OVERFLOW_START:
                logger.info('[大世界-行动点] 当前行动力达到100，直接开工不开启行动力箱')
                self.action_point_quit()
                return True

            # 购买行动力
            buy_limit = self._action_point_purchase_limit()
            if buy_limit > 0 and buy_checked != buy_limit:
                if self.action_point_buy(preserve=self.config.OpsiGeneral_OilLimit):
                    # action_point_use 已确认并刷新了购买后的实际行动力。
                    continue
                else:
                    buy_checked = buy_limit

            # 重新检查总行动力是否小于消耗
            # 如果是，则跳过使用药剂
            if self._action_point_total < cost:
                logger.info('[大世界-行动点] 行动点不足')
                self.action_point_quit()
                raise ActionPointLimit(
                    current=self._action_point_current,
                    total=self._action_point_total,
                    cost=cost,
                )

            # 排序行动力药剂
            box = []
            overflow_skipped = False
            for index in [3, 2, 1]:
                if self._action_point_box[index] > 0:
                    # 防溢出：开箱后行动力达到或超过 200 满值的箱子跳过，
                    # 等自然恢复（如当前行动力 100 时也不开 100 箱）
                    if avoid_ap_overflow and self._action_point_current + ACTION_POINT_BOX[index] >= 200:
                        overflow_skipped = True
                        continue
                    if self._action_point_current + ACTION_POINT_BOX[index] >= 200:
                        box.append(index)
                    else:
                        box.insert(0, index)

            # 使用行动力药剂
            if len(box):
                if self._action_point_total > self.config.OS_ACTION_POINT_PRESERVE:
                    self.action_point_set_button(box[0])
                    self.action_point_use()
                    continue
                else:
                    logger.info(f'[大世界-行动点] 达到行动点上限, 保留={self.config.OS_ACTION_POINT_PRESERVE}')
                    self.action_point_quit()
                    raise ActionPointLimit(
                        current=self._action_point_current,
                        total=self._action_point_total,
                        preserve=self.config.OS_ACTION_POINT_PRESERVE,
                    )
            elif overflow_skipped:
                logger.info('[大世界-行动点] 开箱会达到或超出200满值，跳过开箱等待行动力自然恢复')
                self.action_point_quit()
                raise ActionPointLimit(
                    current=self._action_point_current,
                    total=self._action_point_total,
                    cost=cost,
                )
            else:
                logger.info('[大世界-行动点] 没有更多行动点箱子')
                self.action_point_quit()
                raise ActionPointLimit(
                    current=self._action_point_current,
                    total=self._action_point_total,
                    cost=cost,
                )

        logger.warning('[大世界-行动点] 尝试12次后仍无法获取行动点')
        return False

    def action_point_enter(self):
        """
        进入行动力弹窗。

        Pages:
            in: OS_CHECK
            out: ACTION_POINT_USE
        """
        for _ in self.loop():
            if self.appear(ACTION_POINT_USE, offset=(20, 20)):
                break

            if self.appear(OS_CHECK, offset=(20, 20), interval=3):
                self.device.click(ACTION_POINT_REMAIN_OS)
                continue
            if self.handle_map_event():
                # 剧情是透明的，处理剧情时可能检测到 OS_CHECK
                self.interval_reset(OS_CHECK)
                continue
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50)):
                continue

    def action_point_reusable(self, fresh_ap, cost, avoid_ap_overflow=False):
        """判断能否复用刚读到的行动力、跳过 action_point_set 的行动点弹窗。

        仅当复用后与「开弹窗走 handle_action_point」行为完全一致时才返回 True：
        弹窗口径的总行动力高于 OS_ACTION_POINT_PRESERVE（不会触发保留拦截），
        且当前行动力已达到开工线（防溢出模式为
        ACTION_POINT_AVOID_OVERFLOW_START，否则为 cost），弹窗路径也只会
        「行动点充足」直接关闭。不满足时必须照常调用 action_point_set
        ——开行动力箱与石油购买都在那里处理。

        Args:
            fresh_ap (tuple[int, int] | None): 调用方刚读到的
                (弹窗口径总行动力, 当前行动力)。读数与本次调用之间不得有
                任何行动力消耗；为 None 时返回 False。
            cost (int): 目标海域消耗，与 action_point_set 的 cost 相同。
            avoid_ap_overflow (bool): 是否与 action_point_set 一样启用防溢出模式。

        Returns:
            bool: 是否可以跳过弹窗。
        """
        if fresh_ap is None:
            return False
        fresh_total, fresh_current = fresh_ap
        if fresh_total <= self.config.OS_ACTION_POINT_PRESERVE:
            return False
        if avoid_ap_overflow:
            return fresh_current >= ACTION_POINT_AVOID_OVERFLOW_START
        return fresh_current >= cost

    def action_point_set(self, zone=None, pinned=None, cost=None, keep_current_ap=True, check_rest_ap=False,
                         avoid_ap_overflow=False, *, routine=False):
        """
        设置行动力，进入行动力弹窗并处理。

        Args:
            zone (Zone): 要进入的海域。
            pinned (str): 海域类型。可用类型: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD。
            cost (int): 自定义行动力消耗值。
            keep_current_ap (bool): 是否先检查行动力，避免在不足时使用剩余行动力。
            check_rest_ap (bool): 如果当前行动力与今天可获得的剩余行动力之和超过 200，则跳过 keep_current_ap 检查。
            avoid_ap_overflow (bool): 防溢出模式，见 handle_action_point。
            routine (bool): 只有指定的常规练级/调度入口可按间隔复用，入场检查默认强制读取。

        Returns:
            bool: 是否处理成功。

        Raises:
            ActionPointLimit: 行动力不足时抛出。
        """
        if routine:
            fresh_ap = self.action_point_cached_read()
            effective_cost = cost if cost is not None else self.action_point_get_cost(zone, pinned)
            if self.action_point_reusable(fresh_ap, effective_cost, avoid_ap_overflow):
                return True
        self.action_point_enter()
        if not self.handle_action_point(zone, pinned, cost, keep_current_ap, check_rest_ap, avoid_ap_overflow):
            return False

        # 等待行动力弹窗关闭
        for _ in self.loop():
            if self.appear(IN_MAP, offset=(200, 5)):
                break

        return True

    def action_point_check(self, amount):
        """
        检查是否有足够的行动力。

        Args:
            amount (int): 需要检查的行动力数量。

        Returns:
            bool: 是否有足够的行动力。
        """
        self.action_point_enter()
        self.action_point_safe_get()

        enough = self._action_point_total > amount
        if enough:
            logger.info(f'[大世界-行动点] 拥有 {amount} 行动点')
        else:
            logger.info(f'[大世界-行动点] 没有 {amount} 行动点')

        self.action_point_quit()
        for _ in self.loop():
            if self.appear(IN_MAP, offset=(200, 5)):
                break

        return enough
