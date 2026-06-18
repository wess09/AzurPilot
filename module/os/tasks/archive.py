
from module.config.utils import get_nearest_weekday_date
from module.logger import logger
from module.os.map import OSMap
from module.shop.shop_voucher import VoucherShop


class OpsiArchive(OSMap):
    def os_archive(self):
        """
        执行大世界作战档案任务。

        完成每日任务中的活跃档案海域，购买下一个可用的日志仪档案，
        循环执行直到耗尽。建议每周运行一次，开发团队会在维护后添加新档案。
        """
        if self.is_in_opsi_explore():
            logger.info('OpsiExplore is under scheduling, stop OpsiArchive')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        shop = VoucherShop(self.config, self.device)
        while True:
            # 防止日志仪被手动购买，先完成已存在的档案海域
            self.os_finish_daily_mission(
                skip_siren_mission=self.config.cross_get('OpsiDaily.OpsiDaily.SkipSirenResearchMission'),
                question=False, rescan=False)

            logger.hr('OS voucher', level=1)
            self._os_voucher_enter()
            bought = shop.run_once()
            self._os_voucher_exit()
            if not bought:
                break

        # 延迟到最近的周三重置
        next_reset = get_nearest_weekday_date(target=2)
        logger.info('All archive zones finished, delay to next reset')
        logger.attr('OpsiNextReset', next_reset)
        self.config.task_delay(target=next_reset)
