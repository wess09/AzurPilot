# 此文件处理大世界（Operation Siren）模式下的行动力（Action Point, AP）管理。
# 包含行动力数值 OCR 识别、药剂（AP Box）库存解析以及自动购买或使用补给的交互逻辑。
from datetime import datetime
from datetime import timedelta

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import *
from module.config.utils import get_server_next_update, server_time_offset
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter
from module.os_handler.assets import *
from module.os_handler.map_event import MapEventHandler
from module.statistics.item import Item, ItemGrid
from module.ui.assets import OS_CHECK
from module.ui.ui import UI
from module.log_res import LogRes

OCR_ACTION_POINT_REMAIN = Digit(ACTION_POINT_REMAIN, letter=(255, 219, 66), name='OCR_ACTION_POINT_REMAIN')
OCR_ACTION_POINT_REMAIN_OS = Digit(ACTION_POINT_REMAIN_OS, letter=(239, 239, 239),
                                   threshold=160, name='OCR_SHOP_YELLOW_COINS_OS')

OCR_OS_ADAPTABILITY = Digit([
    OS_ADAPTABILITY_ATTACK,
    OS_ADAPTABILITY_DURABILITY,
    OS_ADAPTABILITY_RECOVER
], letter=(231, 235, 239), lang="cnocr", name='OCR_OS_ADAPTABILITY')


class ActionPointBuyCounter(DigitCounter):
    def after_process(self, result):
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
        return True


ACTION_POINT_GRID = ButtonGrid(
    origin=(323, 274), delta=(173, 0), button_shape=(115, 115), grid_shape=(4, 1), name='ACTION_POINT_GRID')

class GridSlice:
    """网格切片，用于构建物品网格。"""
    def __init__(self, buttons):
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


class ActionPointLimit(Exception):
    """
    行动力不足异常。

    当行动力不足以进入目标海域时抛出。
    """
    def __init__(self, current=None, total=None, cost=None, preserve=None):
        super().__init__()
        self.current = current
        self.total = total
        self.cost = cost
        self.preserve = preserve

    @property
    def delay_minutes(self):
        """
        获取需要延迟的分钟数。

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
    _action_point_box = [0, 0, 0, 0]
    _action_point_current = 0
    _action_point_total = 0

    @staticmethod
    def _is_in_month_end_purchase_block_week():
        """
        判断当前是否处于月末购买封锁周。

        在包含下个服务器月第一天的自然周（周一至周日）内，封锁每周行动力购买。
        进入下个服务器月后，购买将重新可用。

        Returns:
            bool: 是否处于月末封锁周。
        """
        diff = server_time_offset()
        server_now = datetime.now() - diff
        next_month = (server_now.replace(day=28) + timedelta(days=4)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        next_month_start = next_month.replace(day=1)
        current_week_start = server_now.date() - timedelta(days=server_now.weekday())
        next_month_week_start = next_month_start.date() - timedelta(days=next_month_start.weekday())
        return current_week_start == next_month_week_start

    def _is_in_action_point(self):
        return self.appear(ACTION_POINT_USE, offset=(20, 20))

    def is_current_ap_visible(self):
        return self.match_template_color(CURRENT_AP_CHECK, offset=(40, 5), threshold=15)

    def action_point_use(self):
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
        oil = OIL_ITEM.predict(self.device.image, name=False, amount=True)
        items = ACTION_POINT_ITEMS.predict(self.device.image, name=False, amount=True)
        box = [item.amount for item in oil] + [item.amount for item in items]
        current = OCR_ACTION_POINT_REMAIN.ocr(self.device.image)
        total = current
        if self.config.OS_ACTION_POINT_BOX_USE:
            total += np.sum(np.array(box) * tuple(ACTION_POINT_BOX.values()))
        oil = box[0]

        LogRes(self.config).Oil = oil
        logger.info(f'Action points: {current}({total}), oil: {oil}')
        LogRes(self.config).ActionPoint = {'Value': current, 'Total': total}
        self.config.update()
        self._action_point_current = current
        self._action_point_box = box
        self._action_point_total = total
        # 处理超出上限的情况
        if total > 3000:
            self.config.override(OpsiGeneral_DoRandomMapEvent=False)

    def action_point_safe_get(self):
        """
        安全获取行动力信息。

        等待行动力弹窗完全加载，并处理可能的地图事件。
        """
        timeout = Timer(3, count=6).start()
        for _ in self.loop():
            # 结束
            if self.is_current_ap_visible():
                break
            if timeout.reached():
                logger.warning('Get action points timeout, wait is_current_ap_visible timeout')
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
                logger.warning('Get action points timeout')
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
                    break
                else:
                    # [11, 0, 1, 0]
                    continue
            # 或者拥有石油
            # 页面未完全加载时可能为 0 或 1
            # [1, 0, 0, 0]
            if oil > 100:
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
            logger.warning(f'Unable to get AP cost from zone={zone}, pinned={pinned}, assume it costs 40.')
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

        logger.warning('Unable to find an active action point box button')
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
            logger.warning('FSet action point button timeout')
            return False

    def action_point_get_buy_remain(self):
        """
        获取行动力剩余购买次数。

        Returns:
            int: 剩余购买次数。

        Pages:
            in: ACTION_POINT_USE
        """
        current = 0
        for _ in self.loop(timeout=1):

            current, _, total = OCR_ACTION_POINT_BUY_REMAIN.ocr(self.device.image)

            # 可能的结果: 0/5, 05
            if total == 0:
                continue

            break
        else:
            logger.warning('Get action points buy remain timeout')

        return current

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
        self.action_point_set_button(0)
        current = self.action_point_get_buy_remain()
        buy_max = 5  # 当前版本中，玩家每周可购买 5 次行动力
        buy_count = buy_max - current
        buy_limit = self.config.OpsiGeneral_BuyActionPointLimit
        if self._is_in_month_end_purchase_block_week():
            logger.info('Skip buying action points this week because it is the month-end block week')
            return False
        if buy_count >= buy_limit:
            logger.info('Reach the limit to buy action points this week')
            return False
        cost = ACTION_POINTS_BUY[current]
        oil = self._action_point_box[0]
        logger.info(f'Buy action points will cost {cost}, current oil: {oil}, preserve: {preserve}')
        if oil >= cost + preserve:
            self.action_point_use()
            return True
        else:
            logger.info('Not enough oil to buy')
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

    def handle_action_point(self, zone, pinned, cost=None, keep_current_ap=True, check_rest_ap=False):
        """
        处理行动力，包括购买和使用药剂。

        Args:
            zone (Zone): 要进入的海域。
            pinned (str): 海域类型。可用类型: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD。
            cost (int): 自定义行动力消耗值。
            keep_current_ap (bool): 是否先检查行动力，避免在不足时使用剩余行动力。
            check_rest_ap (bool): 如果当前行动力与今天可获得的剩余行动力之和超过 200，则跳过 keep_current_ap 检查。

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
        self.action_point_safe_get()
        if cost is None:
            cost = self.action_point_get_cost(zone, pinned)
        buy_checked = False

        # 检查剩余行动力
        if check_rest_ap:
            diff = get_server_next_update('00:00') - datetime.now()
            today_rest = int(diff.total_seconds() // 600)
            if self._action_point_current + today_rest >= 200:
                logger.info('The sum of the current action points and the rest action points'
                            ' that can be obtained today exceeds 200, skip AP check')
                logger.info(f'Current={self._action_point_current}  Rest={today_rest}')
                keep_current_ap = False

        # 先检查行动力
        if keep_current_ap:
            if self._action_point_total <= self.config.OS_ACTION_POINT_PRESERVE:
                logger.info(f'Reach the limit of action points, preserve={self.config.OS_ACTION_POINT_PRESERVE}')
                self.action_point_quit()
                raise ActionPointLimit(
                    current=self._action_point_current,
                    total=self._action_point_total,
                    preserve=self.config.OS_ACTION_POINT_PRESERVE,
                )

        for _ in range(12):
            # 拥有足够的行动力
            if self._action_point_current >= cost:
                logger.info('Having enough action points')
                self.action_point_quit()
                return True

            # 购买行动力
            if self.config.OpsiGeneral_BuyActionPointLimit > 0 and not buy_checked:
                if self.action_point_buy(preserve=self.config.OpsiGeneral_OilLimit):
                    self.action_point_safe_get()
                    continue
                else:
                    buy_checked = True

            # 重新检查总行动力是否小于消耗
            # 如果是，则跳过使用药剂
            if self._action_point_total < cost:
                logger.info('Not having enough action points')
                self.action_point_quit()
                raise ActionPointLimit(
                    current=self._action_point_current,
                    total=self._action_point_total,
                    cost=cost,
                )

            # 排序行动力药剂
            box = []
            for index in [3, 2, 1]:
                if self._action_point_box[index] > 0:
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
                    logger.info(f'Reach the limit of action points, preserve={self.config.OS_ACTION_POINT_PRESERVE}')
                    self.action_point_quit()
                    raise ActionPointLimit(
                        current=self._action_point_current,
                        total=self._action_point_total,
                        preserve=self.config.OS_ACTION_POINT_PRESERVE,
                    )
            else:
                logger.info('No more action point boxes')
                self.action_point_quit()
                raise ActionPointLimit(
                    current=self._action_point_current,
                    total=self._action_point_total,
                    cost=cost,
                )

        logger.warning('Failed to get action points after 12 trial')
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

    def action_point_set(self, zone=None, pinned=None, cost=None, keep_current_ap=True, check_rest_ap=False):
        """
        设置行动力，进入行动力弹窗并处理。

        Args:
            zone (Zone): 要进入的海域。
            pinned (str): 海域类型。可用类型: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD。
            cost (int): 自定义行动力消耗值。
            keep_current_ap (bool): 是否先检查行动力，避免在不足时使用剩余行动力。
            check_rest_ap (bool): 如果当前行动力与今天可获得的剩余行动力之和超过 200，则跳过 keep_current_ap 检查。

        Returns:
            bool: 是否处理成功。

        Raises:
            ActionPointLimit: 行动力不足时抛出。
        """
        self.action_point_enter()
        if not self.handle_action_point(zone, pinned, cost, keep_current_ap, check_rest_ap):
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
            logger.info(f'Having {amount} action points')
        else:
            logger.info(f'Not having {amount} action points')

        self.action_point_quit()
        for _ in self.loop():
            if self.appear(IN_MAP, offset=(200, 5)):
                break

        return enough
