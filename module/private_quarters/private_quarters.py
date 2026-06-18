import module.config.server as server
from module.base.timer import Timer
from module.logger import logger
from module.private_quarters.assets import *
from module.private_quarters.interact import PQInteract
from module.private_quarters.shop import PQShop
from module.ui.page import page_private_quarters, page_dormmenu


class PrivateQuarters(PQInteract, PQShop):
    def _pq_get_daily_count(self, retry=3):
        """
        获取每日互动剩余次数，带重试缓冲。

        高性能 PC 上初始截图可能模糊或滞后，
        因此通过有限次数的重读来确保结果准确。

        Args:
            retry (int): 最大重试次数

        Returns:
            int: 剩余互动次数，0 表示已耗尽

        Pages:
            in: 私人宿舍主页
        """
        count = self.status_get_daily_count()
        get_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：成功获取非零次数，或重试耗尽确认为零
            if count != 0 or retry == 0:
                return count

            # 计时器到期，重新读取每日次数
            if get_timer.reached():
                count = self.status_get_daily_count()
                get_timer.reset()
                retry -= 1

    def _pq_shop_enter(self):
        """
        进入私人宿舍商店并导航到天狼星礼物标签页。

        Pages:
            in: 私人宿舍主页
            out: 私人宿舍商店 - 天狼星 - 礼物
        """
        # 进入商店
        self.ui_click(
            click_button=PRIVATE_QUARTERS_SHOP_ENTER,
            check_button=PRIVATE_QUARTERS_SHOP_CHECK,
            appear_button=page_private_quarters.check_button,
            offset=(20, 20),
            skip_first_screenshot=True
        )

        # 切换到天狼星分区
        self.shop_left_navbar_ensure(2)

        # 切换到礼物标签
        self.shop_bottom_navbar_ensure(2)

    def _pq_shop_exit(self):
        """
        退出私人宿舍商店，返回私人宿舍主页。

        Pages:
            in: 私人宿舍商店
            out: 私人宿舍主页
        """
        self.ui_click(
            click_button=PRIVATE_QUARTERS_SHOP_BACK,
            check_button=page_private_quarters.check_button,
            appear_button=PRIVATE_QUARTERS_SHOP_CHECK,
            offset=(20, 20),
            skip_first_screenshot=True
        )

    def pq_shop_weekly_items(self):
        """
        购买商店每周物品。

        玫瑰需要 24000+ 金币，蛋糕需要 210+ 钻石，
        余额不足时跳过等待次日。

        Pages:
            in: 私人宿舍主页
            out: 私人宿舍主页
        """
        logger.hr(f'Get Weekly Items', level=2)

        # 进入商店
        self._pq_shop_enter()

        # 执行购买
        self.shop_buy()

        # 退出商店
        self._pq_shop_exit()

    def pq_execute_interact(self, target_ship):
        """
        执行与目标舰娘的互动流程。

        校验目标合法性后，进入房间并执行互动序列。

        Args:
            target_ship (str): 目标舰娘名称（小写，如 'sirius'）

        Pages:
            in: 私人宿舍主页
            out: 私人宿舍主页
        """
        # 校验目标是否可选
        target_title = target_ship.title().replace('_', ' ')
        if target_ship not in self.available_targets:
            logger.error(f'Unsupported target ship: {target_title}, cannot continue subtask')
            return

        # 进入目标房间，最多重试 3 次
        if not self.pq_goto_room(target_ship, retry=3):
            return

        # 执行互动流程
        self.pq_interact()

    def pq_run(self, buy_roses, buy_cake, target_interact, target_ship):
        """
        执行私人宿舍日常流程。

        包括购买每周商品（玫瑰/蛋糕）和与目标舰娘互动。

        Args:
            buy_roses (bool): 是否购买每周玫瑰
            buy_cake (bool): 是否购买每周蛋糕
            target_interact (bool): 是否执行舰娘互动
            target_ship (str): 目标舰娘名称

        Pages:
            in: 私人宿舍主页
            out: 私人宿舍主页
        """
        logger.hr(f'Private Quarters Run', level=1)
        target_title = target_ship.title().replace('_', ' ')
        logger.info(f'Task configured for Buy_Roses={buy_roses}, '
                    f'Buy_Cake={buy_cake}, '
                    f'Interact_ShipGirl={target_interact}, '
                    f'Target_ShipGirl={target_title}')

        # 进入商店购买每周物品
        if self.shop_filter:
            if server.server not in ['tw']:
                self.pq_shop_weekly_items()
            else:
                logger.info(f'Private Quarters shop not supported for {server.server} server.')

        # 执行舰娘互动
        if target_interact:
            # 获取每日剩余次数，为 0 则退出
            count = self._pq_get_daily_count(retry=3)
            if count == 0:
                logger.info('Daily intimacy count exhausted, exit subtask')
                return
            if server.server in ['tw'] and target_ship in ['taihou']:
                logger.info(f'Target ship:{target_ship} not supported for {server.server} server.')
                return
            # 执行互动
            self.pq_execute_interact(target_ship)

    def run(self):
        """
        私人宿舍任务入口。

        从任意页面导航到宿舍菜单，进入私人宿舍执行日常流程。

        Pages:
            in: 任意页面
            out: page_main，可能有 info_bar
        """
        
        self.ui_ensure(page_dormmenu)
        self.ui_goto(page_private_quarters, get_ship=False)
        self.handle_info_bar()
        self.pq_run(
            buy_roses=self.config.PrivateQuarters_BuyRoses,
            buy_cake=self.config.PrivateQuarters_BuyCake,
            target_interact=self.config.PrivateQuarters_TargetInteract,
            target_ship=self.config.PrivateQuarters_TargetShip
        )
        if server.server in ['tw']:
            logger.info(f'Private Quarters task not presently supported for {server.server} server.')
            logger.info('If want to address, review necessary assets, replace, update above condition, and test')

        self.config.task_delay(server_update=True)
