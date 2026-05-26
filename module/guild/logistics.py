import re

from module.base.button import ButtonGrid
from module.base.decorator import Config, cached_property
from module.base.filter import Filter
from module.base.timer import Timer
from module.base.utils import *
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
GUILD_SUPPLY_MAX_RETRY = 2
GUILD_EXCHANGE_BUG_RETRY = 5


class ExchangeLimitOcr(Digit):
    def pre_process(self, image):
        """
        Args:
            image (np.ndarray): Shape (height, width, channel)

        Returns:
            np.ndarray: Shape (width, height)
        """
        return 255 - color_mapping(rgb2gray(image), max_multiply=2.5)


GUILD_EXCHANGE_LIMIT = ExchangeLimitOcr(OCR_GUILD_EXCHANGE_LIMIT, threshold=64)


class GuildLogistics(GuildBase):
    _guild_logistics_mission_finished = False

    @cached_property
    def exchange_items(self):
        item_grid = ItemGrid(
            EXCHANGE_GRIDS, {}, template_area=(40, 21, 89, 70), amount_area=(60, 71, 91, 92))
        item_grid.load_template_folder('./assets/stats_basic')
        return item_grid

    def _is_in_guild_logistics(self):
        """
        Color sample the GUILD_LOGISTICS_ENSURE_CHECK
        to determine whether is currently
        visible or not

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        # Axis (181, 97, 99) and Azur (148, 178, 255)
        return bool(
            self.image_color_count(
                GUILD_LOGISTICS_ENSURE_CHECK,
                color=(181, 97, 99),
                threshold=221,
                count=400,
            )
            or self.image_color_count(
                GUILD_LOGISTICS_ENSURE_CHECK,
                color=(148, 178, 255),
                threshold=221,
                count=400,
            )
        )

    def _guild_logistics_ensure(self, skip_first_screenshot=True):
        """
        Ensure guild logistics is loaded
        After entering guild logistics, background loaded first, then St.Louis / Leipzig, then guild logistics

        Args:
            skip_first_screenshot (bool):
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._is_in_guild_logistics():
                break

    @Config.when(SERVER='en')
    def _guild_logistics_mission_available(self):
        """
        Color sample the GUILD_MISSION area to determine
        whether the button is enabled, mission already
        in progress, or no more missions can be accepted

        Used at least twice, 'Collect' and 'Accept'

        Returns:
            bool: If button active

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        r, g, b = get_color(self.device.image, GUILD_MISSION.area)
        if g > max(r, b) - 10:
            # Green tick at the bottom right corner if guild mission finished
            logger.info('Guild mission has finished this week')
            self._guild_logistics_mission_finished = True
            return False
        # 0/300 in EN is bold and pure white, and Collect rewards is blue white, so reverse the if condition
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=235, count=100):

            logger.info('Guild mission button inactive')
            return False
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=180, count=50):
            # white pixels less than 50, but has blue-white pixels
            logger.info('Guild mission button active')
            return True
        else:
            # No guild mission counter
            logger.info('No guild mission found, mission of this week may not started')
            return False
            # if self.image_color_count(GUILD_MISSION_CHOOSE, color=(255, 255, 255), threshold=221, count=100):
            #     # Guild mission choose available if user is guild master
            #     logger.info('Guild mission choose found')
            #     return True
            # else:
            #     logger.info('Guild mission choose not found')
            #     return False

    @Config.when(SERVER='jp')
    def _guild_logistics_mission_available(self):
        """
        Color sample the GUILD_MISSION area to determine
        whether the button is enabled, mission already
        in progress, or no more missions can be accepted

        Used at least twice, 'Collect' and 'Accept'

        Returns:
            bool: If button active

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        r, g, b = get_color(self.device.image, GUILD_MISSION.area)
        if g > max(r, b) - 10:
            # Green tick at the bottom right corner if guild mission finished
            logger.info('Guild mission has finished this week')
            self._guild_logistics_mission_finished = True
            return False
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=254, count=50):
            # 0/300 in JP is (255, 255, 255)
            logger.info('Guild mission button inactive')
            return False
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=180, count=400):
            # (255, 255, 255) less than 50, but has many blue-white pixels
            logger.info('Guild mission button active')
            return True
        elif not self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=180, count=50):
            # No guild mission counter
            logger.info('No guild mission found, mission of this week may not started')
            # Guild mission choose in JP server disabled until we get the screenshot.
            return False
            # if self.image_color_count(GUILD_MISSION_CHOOSE, color=(255, 255, 255), threshold=221, count=100):
            #     # Guild mission choose available if user is guild master
            #     logger.info('Guild mission choose found')
            #     return True
            # else:
            #     logger.info('Guild mission choose not found')
            #     return False
        else:
            logger.info('Unknown guild mission condition. Skipped.')
            return False

    @Config.when(SERVER=None)
    def _guild_logistics_mission_available(self):
        """
        Color sample the GUILD_MISSION area to determine
        whether the button is enabled, mission already
        in progress, or no more missions can be accepted

        Used at least twice, 'Collect' and 'Accept'

        Returns:
            bool: If button active

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        r, g, b = get_color(self.device.image, GUILD_MISSION.area)
        if g > max(r, b) - 10:
            # Green tick at the bottom right corner if guild mission finished
            logger.info('Guild mission has finished this week')
            self._guild_logistics_mission_finished = True
            return False
        elif self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=180, count=400):
            # Unfinished mission accept/collect range from about 240 to 322
            logger.info('Guild mission button active')
            return True
        elif not self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=180, count=50):
            # No guild mission counter
            logger.info('No guild mission found, mission of this week may not started')
            return False
            # if self.image_color_count(GUILD_MISSION_CHOOSE, color=(255, 255, 255), threshold=221, count=100):
            #     # Guild mission choose available if user is guild master
            #     logger.info('Guild mission choose found')
            #     return True
            # else:
            #     logger.info('Guild mission choose not found')
            #     return False
        else:
            logger.info('Guild mission button inactive')
            return False

    def _guild_logistics_supply_available(self):
        """
        Color sample the GUILD_SUPPLY area to determine
        whether the button is enabled or disabled

        mode determines

        Returns:
            bool: If button active

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        color = get_color(self.device.image, GUILD_SUPPLY.area)
        # Active button has white letters, inactive button have gray letters
        if np.max(color) > np.mean(color) + 25:
            # For members, click to receive supply
            # For leaders, click to buy supply and receive supply
            logger.info('Guild supply button active')
            return True
        else:
            logger.info('Guild supply button inactive')
            return False

    def _handle_guild_fleet_mission_start(self):
        """
        Select new weekly fleet mission.
        Current account must be a guild master or officer.

        Returns:
            bool: If clicked
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
        """
        Mark guild supply as checked and clear pending click state.

        Args:
            state (dict): Supply check state.
        """
        state['checked'] = True
        state['clicked'] = False

    def _guild_logistics_supply_handle(self, state, click_interval, result_timer):
        """
        Handle guild supply receive retry flow.

        Args:
            state (dict): Supply check state.
            click_interval (Timer): Click interval control.
            result_timer (Timer): Result wait control.

        Returns:
            bool: If handled and loop should continue.
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

        if state['click_count'] >= GUILD_SUPPLY_MAX_RETRY:
            logger.warning('Guild supply remains available after retries, skip supply this time')
            self._guild_logistics_supply_check_finished(state)
            return False

        if click_interval.reached():
            self.device.click(GUILD_SUPPLY)
            click_interval.reset()
            state['click_count'] += 1
            result_timer.reset()
        return True

    def _guild_logistics_exchange_bug_check(self, exchange_count):
        """
        Check in-game refresh bug after repeated exchange attempts.

        Args:
            exchange_count (int): Exchange click count in current run.
        """
        if exchange_count < GUILD_EXCHANGE_BUG_RETRY:
            return

        # If you run AL across days, then do guild exchange.
        # There will show an error, said time is not up.
        # Restart the game can't fix the problem.
        # To fix this, you have to enter guild logistics once, then restart.
        # If exchange for 5 times, this bug is considered to be triggered.
        logger.warning(
            'Unable to do guild exchange, probably because the timer in game was bugged')
        raise GameBugError('Triggered guild logistics refresh bug')

    def _guild_logistics_timer_reset(self, confirm_timer, exchange_interval=None):
        """
        Reset logistics stable and exchange timers.

        Args:
            confirm_timer (Timer): Stable state timer.
            exchange_interval (Timer): Exchange retry timer.
        """
        confirm_timer.reset()
        if exchange_interval is not None:
            exchange_interval.reset()

    def _guild_logistics_popup_handle(self, supply_state, confirm_timer, exchange_interval):
        """
        Handle logistics popups and reward receive pages.

        Args:
            supply_state (dict): Supply check state.
            confirm_timer (Timer): Stable state timer.
            exchange_interval (Timer): Exchange retry timer.

        Returns:
            bool: If handled and loop should continue.
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

    def _guild_logistics_mission_handle(self, mission_checked, click_interval):
        """
        Handle guild mission collect or accept action.

        Args:
            mission_checked (bool): If mission has been checked.
            click_interval (Timer): Click interval control.

        Returns:
            tuple[bool, bool]: New checked state and whether loop should continue.
        """
        if mission_checked:
            return True, False

        if not self._guild_logistics_mission_available():
            return True, False

        if click_interval.reached():
            self.device.click(GUILD_MISSION)
            click_interval.reset()
        return False, True

    def _guild_logistics_exchange_handle(self, exchange_checked, exchange_count, exchange_interval):
        """
        Handle guild exchange action.

        Args:
            exchange_checked (bool): If exchange has been checked.
            exchange_count (int): Exchange click count in current run.
            exchange_interval (Timer): Exchange retry timer.

        Returns:
            tuple[bool, int, bool]: New checked state, exchange count, and whether loop should continue.
        """
        if exchange_checked or not exchange_interval.reached():
            return exchange_checked, exchange_count, False

        if not self._guild_exchange():
            return True, exchange_count, False

        exchange_interval.reset()
        return False, exchange_count + 1, True

    def _guild_logistics_collect(self, skip_first_screenshot=True):
        """
        Execute collect/accept screen transitions within
        logistics

        Args:
            skip_first_screenshot (bool):

        Returns:
            bool: If all guild logistics are check, no need to check them today.

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        logger.hr('Guild logistics')
        logger.attr('Guild master/official', self.config.GuildLogistics_SelectNewMission)
        confirm_timer = Timer(1.5, count=3).start()
        exchange_interval = Timer(1.5, count=3)
        click_interval = Timer(0.5, count=1)
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
                continue

            if self._is_in_guild_logistics():
                if self._guild_logistics_supply_handle(supply_state, click_interval, supply_result_timer):
                    self._guild_logistics_timer_reset(confirm_timer)
                    continue
                mission_checked, handled = self._guild_logistics_mission_handle(mission_checked, click_interval)
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
                confirm_timer.reset()

        logger.info(f"supply_checked: {supply_state['checked']}, mission_checked: {mission_checked}, "
                    f'exchange_checked: {exchange_checked}, mission_finished: {self._guild_logistics_mission_finished}')
        # Azur Lane receives new guild missions now
        # No longer consider `self._guild_logistics_mission_finished` as a check
        return all([supply_state['checked'], mission_checked, exchange_checked])

    def _guild_exchange_scan(self):
        """
        Image scan of available options.
        Not exchangeable items are tagged enough=False.

        Returns:
            list[Item]:

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        # Scan the available exchange items that are selectable
        items = self.exchange_items.predict(self.device.image, name=True, amount=False)

        # Loop EXCHANGE_GRIDS to detect for red text in bottom right area
        # indicating player lacks inventory for that item
        for item, button in zip(items, EXCHANGE_GRIDS.buttons):
            area = area_offset((35, 64, 83, 83), button.area[:2])
            item.enough = not self.image_color_count(area, color=(255, 93, 90), threshold=221, count=20)

        text = [str(item.name) if item.enough else f'{item.name} (not enough)' for item in items]
        logger.info(f'Exchange items: {", ".join(text)}')
        return items

    def _guild_exchange(self):
        """
        Performs sift check and executes the applicable
        exchanges, number performed based on limit
        If unable to exchange at all, loop terminates
        prematurely

        Returns:
            bool: If clicked.

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        if GUILD_EXCHANGE_LIMIT.ocr(self.device.image) <= 0:
            return False

        items = self._guild_exchange_scan()
        EXCHANGE_FILTER.load(self.config.GuildLogistics_ExchangeFilter)
        selected = EXCHANGE_FILTER.apply(items, func=lambda item: item.enough)
        logger.attr('Exchange_sort', ' > '.join([str(item.name) for item in selected]))

        if len(selected):
            button = EXCHANGE_BUTTONS.buttons[items.index(selected[0])]
            # Just bored click, will retry in self._guild_logistics_collect
            self.device.click(button)
            return True
        else:
            logger.warning('No guild exchange items satisfy current filter, or not having enough resources')
            return False

    def guild_logistics(self):
        """
        Execute all actions in logistics

        Returns:
            bool: If all guild logistics are check, no need to check them today.

        Pages:
            in: page_guild
            out: page_guild, GUILD_LOGISTICS
        """
        logger.hr('Guild logistics', level=1)
        self.guild_side_navbar_ensure(bottom=3)
        self._guild_logistics_ensure()

        result = self._guild_logistics_collect()
        logger.info(f'Guild logistics run success: {result}')
        return result
