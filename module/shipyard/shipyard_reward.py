from datetime import datetime

from module.base.timer import Timer
from module.config.utils import get_server_last_update
from module.exception import ScriptError
from module.logger import logger
from module.shipyard.ui import ShipyardUI
from module.ui.page import page_main, page_shipyard

PRBP_BUY_PRIZE = {
    (1, 2):               0,
    (3, 4):               150,
    (5, 6, 7):            300,
    (8, 9, 10):           600,
    (11, 12, 13, 14, 15): 1050,
}
DRBP_BUY_PRIZE = {
    (1, 2):               0,
    (3, 4, 5, 6):         600,
    (7, 8, 9, 10):        1200,
    (11, 12, 13, 14, 15): 3000,
}


class RewardShipyard(ShipyardUI):
    _shipyard_bp_rarity = 'PR'
    _coin_count = 0

    @staticmethod
    def _shipyard_task_enabled(index, count):
        return index > 0 and count > 0

    def _shipyard_get_cost(self, amount, rarity=None):
        """
        根据已购蓝图数量和稀有度计算购买单价。

        Args:
            amount (int): 已购买的蓝图序号
            rarity (str): 稀有度，'DR' 或 'PR'

        Returns:
            int: 购买价格

        Raises:
            ScriptError: 稀有度无效时抛出
        """
        if rarity is None:
            rarity = self._shipyard_bp_rarity

        if rarity == 'PR':
            cost = [v for k, v in PRBP_BUY_PRIZE.items() if amount in k]
            if len(cost):
                return cost[0]
            else:
                return 1500
        elif rarity == 'DR':
            cost = [v for k, v in DRBP_BUY_PRIZE.items() if amount in k]
            if len(cost):
                return cost[0]
            else:
                return 6000
        else:
            raise ScriptError(f'Invalid rarity in _shipyard_get_cost: {rarity}')

    def _shipyard_calculate(self, start, count, pay=False):
        """
        计算当前金币下可购买的最大蓝图数量。

        根据起始位置、剩余数量和金币余额，计算可购买的
        蓝图总数。若 pay 为 True 则扣除对应金币。

        Args:
            start (int): 起始购买序号
            count (int): 剩余待购买总数
            pay (bool): 是否实际扣除金币

        Returns:
            tuple: (下次起始序号, 本次可购买数量)
        """
        if start <= 0 or count <= 0:
            return start, count

        total = 0
        i = start
        for i in range(start, (start + count)):
            cost = self._shipyard_get_cost(i)

            if (total + cost) > self._coin_count:
                if pay:
                    self._coin_count -= total
                else:
                    logger.info(f'Can only buy up to {(i - start)} '
                                f'of the {count} BPs')
                return i, i - start
            total += cost

        if pay:
            self._coin_count -= total
        else:
            logger.info(f'Can buy all {count} BPs')
        return i + 1, count

    def _shipyard_buy_calc(self, start, count):
        """计算可购买数量，不扣除金币。"""
        return self._shipyard_calculate(start, count, pay=False)

    def _shipyard_pay_calc(self, start, count):
        """计算并扣除已购蓝图的金币消耗。"""
        return self._shipyard_calculate(start, count, pay=True)

    def _shipyard_buy(self, count):
        """
        购买指定数量的蓝图。

        支持在 DEV 和 FATE 阶段购买。循环进入购买界面、
        调整数量并确认购买，直到数量用尽或无法继续。

        Args:
            count (int): 待购买总数
        """
        logger.hr('shipyard_buy')
        prev = 1
        start, count = self._shipyard_buy_calc(prev, count)
        while count > 0:
            if not self._shipyard_buy_enter() or \
                    self._shipyard_cannot_strengthen():
                break

            remain = self._shipyard_ensure_index(count)
            if remain is None:
                break

            if self._shipyard_bp_rarity == 'DR':
                self.config.ShipyardDr_LastRun = datetime.now().replace(microsecond=0)
            else:
                self.config.Shipyard_LastRun = datetime.now().replace(microsecond=0)

            self._shipyard_buy_confirm('BP_BUY')

            # 根据实际购买量（remain）扣除金币，同时更新 start
            # 保存到 prev 供下次 _shipyard_pay_calc 使用
            start, _ = self._shipyard_pay_calc(prev, (count - remain))
            prev = start

            start, count = self._shipyard_buy_calc(start, remain)

    def _shipyard_use(self, index):
        """
        使用指定舰船的所有剩余多余蓝图。

        支持在 DEV 和 FATE 阶段使用蓝图。

        Args:
            index (int): 目标舰船索引
        """
        logger.hr('shipyard_use')
        count = self._shipyard_get_bp_count(index)
        while count > 0:
            if not self._shipyard_buy_enter() or \
                    self._shipyard_cannot_strengthen():
                break

            remain = self._shipyard_ensure_index(count)
            if remain is None:
                break
            self._shipyard_buy_confirm('BP_USE')

            count = self._shipyard_get_bp_count(index)

    def shipyard_run(self, series, index, count):
        """
        执行船坞蓝图购买流程。

        Pages: in: page_main, out: page_shipyard

        Args:
            series (int): 科研系列，1-4（部分系列限制为 1-5）
            index (int): 舰船索引，1-6
            count (int): 使用后待购买的数量

        Returns:
            bool: 是否执行了购买流程
        """
        if count <= 0:
            logger.info('Shipyard buy amount is 0, skip')
            return False
        if index <= 0:
            logger.info('Shipyard ship index is 0, skip')
            return False

        # 船坞页面中金币 OCR 困难（文字和数字右对齐导致混淆）
        # 改从主页面获取金币信息
        self.ui_ensure(page_main)
        timeout = Timer(1, count=1).start()
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self._coin_count = self._shipyard_get_coin()

            if self._coin_count > 0:
                break
            if timeout.reached():
                logger.warning('Assumes that OCR_COIN is in the right place')
                break

        self.ui_goto(page_shipyard)
        if not self.shipyard_set_focus(series=series, index=index) \
                or not self._shipyard_buy_enter() \
                or self._shipyard_cannot_strengthen():
            return True

        self._shipyard_use(index=index)
        self._shipyard_buy(count=count)

        return True

    def run(self):
        """
        Pages:
            in: Any page
            out: page_shipyard
        """
        dr_enabled = self._shipyard_task_enabled(
            self.config.ShipyardDr_ShipIndex,
            self.config.ShipyardDr_BuyAmount,
        )
        pr_enabled = self._shipyard_task_enabled(
            self.config.Shipyard_ShipIndex,
            self.config.Shipyard_BuyAmount,
        )
        if not dr_enabled and not pr_enabled:
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        logger.hr('Shipyard DR', level=1)
        logger.attr('ShipyardDr_LastRun', self.config.ShipyardDr_LastRun)
        if not dr_enabled:
            logger.info('Task Shipyard DR is not configured, skip')
        elif self.config.ShipyardDr_LastRun > get_server_last_update('04:00'):
            logger.warning('Task Shipyard DR has already been run today, skip')
        else:
            self._shipyard_bp_rarity = 'DR'
            self.shipyard_run(series=self.config.ShipyardDr_ResearchSeries,
                              index=self.config.ShipyardDr_ShipIndex,
                              count=self.config.ShipyardDr_BuyAmount)

        logger.hr('Shipyard PR', level=1)
        logger.attr('Shipyard_LastRun', self.config.Shipyard_LastRun)
        if not pr_enabled:
            logger.info('Task Shipyard PR is not configured, skip')
        elif self.config.Shipyard_LastRun > get_server_last_update('04:00'):
            logger.warning('Task Shipyard PR has already been run today, stop')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
        else:
            self._shipyard_bp_rarity = 'PR'
            self.shipyard_run(series=self.config.Shipyard_ResearchSeries,
                              index=self.config.Shipyard_ShipIndex,
                              count=self.config.Shipyard_BuyAmount)

        self.config.task_delay(server_update=True)
