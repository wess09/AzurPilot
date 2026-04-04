import numpy as np

from campaign.campaign_main.campaign_15_base import MASK_MAP_UI_W15
from module.base.timer import Timer
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.logger import logger
from module.map.assets import FLEET_SUPPORT_EMPTY
from module.map.map_base import CampaignMap as CampaignMap_
from module.map.map_grids import SelectedGrids
from module.map.utils import location_ensure
from module.map_detection.grid import GridInfo
from module.map_detection.utils_assets import ASSETS


class CampaignMap(CampaignMap_):
    def update(self, grids, camera, mode='normal'):
        """
        Args:
            grids:
            camera (tuple):
            mode (str): Scan mode, such as 'init', 'normal', 'carrier', 'movable'
        """
        offset = np.array(camera) - np.array(grids.center_loca)

        for grid in grids.grids.values():
            loca = tuple(offset + grid.location)
            if loca in self.grids:
                if self.ignore_prediction_match(globe=loca, local=grid):
                    continue
                self.grids[loca].merge(grid, mode=mode)
        if mode == 'init':
            self.fixup_submarine_fleet()
        return True


class Config:
    # Ambushes can be avoid by having more DDs.
    MAP_WALK_TURNING_OPTIMIZE = False
    MAP_HAS_MYSTERY = False

    # HOMO_CANNY_THRESHOLD = (50, 100)
    # MAP_SWIPE_MULTIPLY = (0.993, 1.011)
    # MAP_SWIPE_MULTIPLY_MINITOUCH = (0.960, 0.978)
    # MAP_SWIPE_MULTIPLY_MAATOUCH = (0.932, 0.949)
    MAP_SWIPE_MULTIPLY = (1.391, 1.417)
    MAP_SWIPE_MULTIPLY_MINITOUCH = (1.345, 1.370)
    MAP_SWIPE_MULTIPLY_MAATOUCH = (1.306, 1.329)


class CampaignBase(CampaignBase_):
    ENEMY_FILTER = '1L > 1M > 1E > 2L > 3L > 2M > 2E > 1C > 2C > 3M > 3E > 3C'
    has_support_fleet = True
    destroyed_land_base = []

    def map_init(self, map_):
        if self.config.MAP_HAS_SUBMARINE_SUPPORT and self.has_support_fleet:
            logger.hr(f'{self.FUNCTION_NAME_BASE}SUBMARINE', level=2)
            self.combat(balance_hp=False, emotion_reduce=False, save_get_items=False)
        super().map_init(map_)

    def map_data_init(self, map_):
        super().map_data_init(map_)
        self.destroyed_land_base = []
        # Patch ui_mask, get rid of supporting fleet
        _ = ASSETS.ui_mask
        ASSETS.ui_mask = MASK_MAP_UI_W15.image

    def can_use_auto_search_continue(self):
        return False

    def fleet_preparation(self, skip_first_screenshot=True):
        if self.appear(FLEET_SUPPORT_EMPTY, offset=(5, 5)):
            self.has_support_fleet = False
        logger.attr('Has support fleet', self.has_support_fleet)
        return super().fleet_preparation(skip_first_screenshot=skip_first_screenshot)

    def strategy_set_execute(self, formation=None, sub_view=None, sub_hunt=None):
        super().strategy_set_execute(
            formation=formation,
            sub_view=sub_view,
            sub_hunt=sub_hunt,
        )
        logger.attr("Map has air strike", self.strategy_has_air_strike())

    def _map_swipe(self, vector, box=(239, 159, 1175, 628)):
        # Left border to 239, avoid swiping on support fleet
        return super()._map_swipe(vector, box=box)

    def air_attackable(self, location):
        """
        Check if air attack can be used at location.
        This requires that:
            1. location grid is in the map (not exceeding the boundaries)
            2. location is not a land grid
        
        Args:
            location (tuple): Location of air attack.
        
        Returns:
            bool: if attackable.
        """
        location = location_ensure(location)
        attackable = True

        try:
            logger.info(f'location: {self.map[location]}')
        except KeyError as e:
            logger.exception(f'Given coordinates are outside the map.')
            raise e

        if self.map[location].is_land:
            logger.error(f'{self.map[location]} is a land grid.')
            attackable = False

        if not attackable:
            logger.error(f'Cannot air attack at {self.map[location]}.')

        return attackable

    def _air_attack(self, location):
        """
        Select the location for air attack.

        Args: 
            location (tuple, str, GridInfo): Location of air attack.
        
        Returns:
            bool: If selected.
        
        Pages:
            in: AIR_STRIKE_CONFIRM
            out: AIR_STRIKE_CONFIRM
        """
        location = location_ensure(location)

        self.in_sight(location)
        grid = self.convert_global_to_local(location)
        grid.__str__ = location

        logger.info('Select mob to move')
        skip_first_screenshot = True
        interval = Timer(2, count=4)
        clicked_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            if self.is_in_strategy_mob_move():
                self.view.update(image=self.device.image)
            # temporary method to end
            if clicked_count >= 1:
                break
            # Click
            if interval.reached() and self.is_in_strategy_air_strike():
                self.device.click(grid)
                clicked_count += 1
                interval.reset()
                continue

    def air_attack(self, location):
        """
        Open strategy, use air attack at location, close strategy.

        Args:
            location (tuple, str, GridInfo): Location of air attack.
            
        Returns:
            bool: If attacked

        Pages:
            in: IN_MAP
            out: IN_MAP
        """
        if not self.air_attackable(location):
            return False

        self.strategy_open()
        if not self.strategy_has_air_strike():
            logger.warning(f'No remain air attack trials, will abandon attacking')
            self.strategy_close()
            return False
        self.strategy_air_strike_enter()
        self._air_attack(location)
        self.strategy_air_strike_confirm()
        self.strategy_close(skip_first_screenshot=False)
        return True

    def destroy_land_base(self, land_base_grid, goto_grid, attack_grid):
        """
        Args:
            land_base_grid (GridInfo): location of land base
            goto_grid (GridInfo): location for current fleet to go to
            attack_grid (GridInfo): location to use air attack

        Returns:
            bool: False
        """
        if land_base_grid in self.destroyed_land_base:
            logger.info(f'Land base {land_base_grid} already destroyed')
        elif goto_grid.is_accessible:
            logger.info(f'Destroy land base on {land_base_grid}')
            self.goto(goto_grid, turning_optimize=self.config.MAP_WALK_TURNING_OPTIMIZE)
            if self.air_attack(attack_grid):
                self.destroyed_land_base.append(land_base_grid)
        else:
            logger.info(f'Land base {land_base_grid} not accessible, will check in next battle')

        return False
