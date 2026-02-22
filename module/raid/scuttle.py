from module.combat.assets import OPTS_INFO_D, BATTLE_STATUS_D, EXP_INFO_D, BATTLE_STATUS_C, EXP_INFO_C
from module.exception import ScriptError, CampaignEnd
from module.logger import logger
from module.raid.assets import RAID_FLEET_PREPARATION, RAID_FLEET_VANGUARD, RAID_FLEET_FLAGSHIP
from module.raid.combat import RaidCombat
from module.raid.raid import raid_entrance
from module.raid.run import RaidRun
from module.retire.assets import DOCK_CHECK
from module.retire.dock import Dock
from module.retire.scanner import ShipScanner
from module.ui.page import page_raid, page_rpg_stage


class RaidScuttleCombat(RaidCombat):
    triggered_normal_end = False

    def handle_battle_status(self, drop=None):
        """
        Args:
            drop (DropImage):

        Returns:
            bool:
        """
        if self.is_combat_executing():
            return False
        if self.appear(BATTLE_STATUS_D, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_D)
            return True
        if self.appear(OPTS_INFO_D, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(OPTS_INFO_D)
            return True
        if super().handle_battle_status(drop=drop):
            logger.warning("Triggered normal end")
            self.triggered_normal_end = True
            return True

        return False

    def handle_exp_info(self):
        """
        Returns:
            bool:
        """
        if self.is_combat_executing():
            return False
        if self.appear_then_click(EXP_INFO_D):
            self.device.sleep((0.25, 0.5))
            return True
        if super().handle_exp_info():
            return True

        return False


class RaidScuttleRun(RaidRun, RaidScuttleCombat, Dock):
    @property
    def change_vanguard(self):
        return 'vanguard' in self.config.RaidScuttle_Sacrifice

    @property
    def change_flagship(self):
        return 'flagship' in self.config.RaidScuttle_Sacrifice

    def triggered_stop_condition(self, oil_check=False, pt_check=False, coin_check=False):
        if self.triggered_normal_end:
            return True
        if super().triggered_stop_condition(oil_check, pt_check, coin_check):
            return True

        return False

    def raid_enter_preparation(self, mode, raid, skip_first_screenshot=True):
        """
        Args:
            mode:
            raid:
            skip_first_screenshot:

        Pages:
            in: page_raid
            out: BATTLE_PREPARATION
        """
        # UI ensure
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        if not self.is_raid_rpg():
            self.ui_ensure(page_raid)
        else:
            self.ui_ensure(page_rpg_stage)
            self.raid_rpg_swipe()
        entrance = raid_entrance(raid=raid, mode=mode)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(entrance, offset=(10, 10), interval=5):
                self.device.click(entrance)
                continue

            # End
            if self.appear_then_click(RAID_FLEET_PREPARATION, offset=(20, 20), interval=5):
                break

    def get_common_rarity_ship(self, index='all'):
        self.dock_favourite_set(False, wait_loading=False)
        self.dock_sort_method_dsc_set(False, wait_loading=False)
        self.dock_filter_set(
            index=index, rarity='common', extra='enhanceable', sort='total'
        )

        logger.hr('FINDING SHIP')

        scanner = ShipScanner(level=(1, 31), fleet=0, status='free')
        scanner.disable('rarity')

        return scanner.scan(self.device.image)

    def vanguard_change(self):
        logger.hr('Change vanguard', level=2)
        for _ in self.loop():
            if self.appear(DOCK_CHECK, offset=(20, 20)):
                break
            if self.appear(RAID_FLEET_PREPARATION, offset=(20, 20)):
                self.device.click(RAID_FLEET_VANGUARD)
                continue

        ship = self.get_common_rarity_ship(index='vanguard')
        if ship:
            self._ship_change_confirm(min(ship, key=lambda s: (s.level, -s.emotion)).button)
            logger.info('Change vanguard success')
            return True
        else:
            logger.info('Change vanguard failed, no vanguard in common rarity.')
            self._dock_reset()
            self.ui_back(check_button=RAID_FLEET_PREPARATION)
            return False

    def flagship_change(self):
        logger.hr('Change flagship', level=2)
        for _ in self.loop():
            if self.appear(DOCK_CHECK, offset=(20, 20)):
                break
            if self.appear(RAID_FLEET_PREPARATION, offset=(20, 20)):
                self.device.click(RAID_FLEET_FLAGSHIP)
                continue

        ship = self.get_common_rarity_ship(index='main')
        if ship:
            self._ship_change_confirm(min(ship, key=lambda s: (s.level, -s.emotion)).button)
            logger.info('Change flagship success')
            return True
        else:
            logger.info('Change flagship failed, no flagship in common rarity.')
            self._dock_reset()
            self.ui_back(check_button=RAID_FLEET_PREPARATION)
            return False

    def run(self, name='', mode='', total=0):
        """
        Args:
            name (str): Raid name, such as 'raid_20200624'
            mode (str): Raid mode, such as 'hard', 'normal', 'easy'
            total (int): Total run count
        """
        name = name if name else self.config.Campaign_Event
        mode = mode if mode else self.config.Raid_Mode
        if not name or not mode:
            raise ScriptError(f'RaidRun arguments unfilled. name={name}, mode={mode}')

        while 1:
            super().run(name=name, mode=mode, total=total)

            # End
            if self.triggered_normal_end:
                self.raid_enter_preparation(mode=mode, raid=name, skip_first_screenshot=False)
                success = True
                if self.change_vanguard:
                    success = self.vanguard_change()
                if self.change_flagship:
                    success = success and self.flagship_change()

                self.enter_map_cancel(skip_first_screenshot=False)
                self.triggered_normal_end = False

                # Scheduler
                if self.config.task_switched():
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_stop()
                elif not success:
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_delay(minute=30)
                    self.config.task_stop()
            else:
                break
