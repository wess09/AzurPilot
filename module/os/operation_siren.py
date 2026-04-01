from datetime import datetime, timedelta

from module.config.utils import get_os_next_reset, get_server_last_update
from module.logger import logger
from module.os_handler.assets import TARGET_ENTER, TARGET_ALL_ON, TARGET_RED_DOT
from module.os_handler.target import OSTargetHandler
from module.os.tasks.daily import OpsiDaily
from module.os.tasks.shop import OpsiShop
from module.os.tasks.voucher import OpsiVoucher
from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os.tasks.scheduling import OpsiScheduling
from module.os.tasks.obscure import OpsiObscure
from module.os.tasks.abyssal import OpsiAbyssal
from module.os.tasks.archive import OpsiArchive
from module.os.tasks.stronghold import OpsiStronghold
from module.os.tasks.month_boss import OpsiMonthBoss
from module.os.tasks.explore import OpsiExplore
from module.os.tasks.cross_month import OpsiCrossMonth


class OperationSiren(
    OpsiDaily, OpsiShop, OpsiVoucher, OpsiMeowfficerFarming,
    OpsiHazard1Leveling, OpsiScheduling, OpsiObscure, OpsiAbyssal,
    OpsiArchive, OpsiStronghold, OpsiMonthBoss, OpsiExplore,
    OpsiCrossMonth,
):
    """Operation Siren main class that combines all task modules."""

    def _os_target_enter(self):
        self.os_map_goto_globe(unpin=False)
        self.ui_click(click_button=TARGET_ENTER, check_button=TARGET_ALL_ON,
                      offset=(200, 20), retry_wait=3, skip_first_screenshot=True)

    def _os_target_exit(self):
        self.ui_back(check_button=TARGET_ENTER, appear_button=TARGET_ALL_ON,
                     offset=(200, 20), retry_wait=3, skip_first_screenshot=True)
        self.os_globe_goto_map()

    def os_target_receive(self):
        next_reset = get_os_next_reset()
        now = datetime.now()
        logger.attr('OpsiNextReset', next_reset)
        if next_reset - now < timedelta(days=1):
            logger.error('Only one day to next reset, received loggers may be wasted.'
                         'Running Achievement Collection is undesirable, delayed to next reset.')
        else:
            self.os_map_goto_globe(unpin=False)
            if self.appear(TARGET_RED_DOT):
                self._os_target_enter()
                OSTargetHandler(self.config, self.device).receive_reward()
                self._os_target_exit()
            else:
                logger.info('No reward to receive')
        self.config.OpsiTarget_LastRun = now.replace(microsecond=0)

    def _os_target(self):
        if self.config.OpsiTarget_LastRun > get_server_last_update('00:00'):
            logger.warning('Opsi Safe Achievement search has already been run today, stop')
        else:
            logger.hr('OS target', level=1)
            self._os_target_enter()
            OSTargetHandler(self.config, self.device).run()
            self._os_target_exit()
            self.config.OpsiTarget_LastRun = datetime.now().replace(microsecond=0)

    def server_support_os_target(self):
        return self.config.SERVER in ['cn', 'jp']

    def os_daily(self):
        super().os_daily()
        if self.config.OpsiDaily_CollectTargetReward:
            if self.server_support_os_target():
                self.os_target_receive()
            else:
                logger.info(f'Server {self.config.SERVER} does not support OpsiTarget yet, please contact the developers.')


if __name__ == '__main__':
    self = OperationSiren('alas', task='OpsiMonthBoss')

    from module.os.config import OSConfig
    self.config = self.config.merge(OSConfig())

    self.device.screenshot()
    self.os_init()

    logger.hr("OS clear Month Boss", level=1)
    self.clear_month_boss()
