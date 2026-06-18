from datetime import datetime, timedelta

from module.config.utils import get_server_next_update, get_os_reset_remain, get_os_next_reset
from module.logger import logger
from module.os.map import OSMap
from module.os_shop.assets import OS_SHOP_CHECK


class OpsiShop(OSMap):
    def os_shop(self):
        """
        购买所有港口的补给物资。

        如果黄币或紫币不足，跳过下一个港口的补给购买。

        Pages:
            in: page_os, 大世界地图
            out: page_os, 大世界地图
        """
        logger.hr('OS port daily', level=1)
        today = datetime.now().day
        limit = self.config.OpsiShop_DisableBeforeDate
        if today <= limit:
            logger.info(f'Delay Opsi shop, today\'s date {today} <= limit {limit}')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        if not self.zone.is_azur_port:
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

        self.port_enter()
        self.port_shop_enter()

        if self.appear(OS_SHOP_CHECK):
            not_empty = self.handle_port_supply_buy()
            next_reset = self._os_shop_delay(not_empty)
            logger.info('OS port daily finished, delay to next reset')
            logger.attr('OpsiShopNextReset', next_reset)
        else:
            next_reset = get_os_next_reset()
            logger.warning('There is no shop in the port, skip to the next month.')
            logger.attr('OpsiShopNextReset', next_reset)

        self.port_shop_quit()
        self.port_quit()

        self.config.task_delay(target=next_reset)
        self.config.task_stop()

    def _os_shop_delay(self, not_empty) -> datetime:
        """
        计算大世界商店的延迟时间。

        根据商店是否为空和距月底重置的天数决定下次运行时间。

        Args:
            not_empty (bool): 商店是否非空。

        Returns:
            datetime: 下次商店重置时间。
        """
        next_reset = None

        if not_empty:
            next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
        else:
            remain = get_os_reset_remain()
            next_reset = get_os_next_reset()
            if remain == 0:
                next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
            elif remain < 7:
                next_reset = next_reset - timedelta(days=1)
            else:
                next_reset = (
                    get_server_next_update(self.config.Scheduler_ServerUpdate) +
                    timedelta(days=6)
                )
        return next_reset
