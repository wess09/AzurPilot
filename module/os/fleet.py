# 此文件专门负责大世界（Operation Siren）模式下的舰队基础控制。
# 涵盖了大世界特有的移动逻辑、血量检测、港口定位以及根据战斗状态切换编队的底层指令。
import re

import inflection
import numpy as np

# 此文件专门负责大世界（Operation Siren）模式下的舰队基础控制。
# 涵盖了大世界特有的移动逻辑、血量检测、港口定位以及根据战斗状态切换编队的底层指令。
from module.base.button import Button, ButtonGrid
from module.base.filter import Filter
from module.base.timer import Timer
from module.base.utils import point_limit
from module.config.utils import dict_to_kv
from module.exception import MapWalkError
from module.handler.assets import MAINTENANCE_ANNOUNCE
from module.logger import logger
from module.map.fleet import Fleet
from module.map.map_grids import SelectedGrids
from module.map.utils import location_ensure
from module.map_detection.utils import area2corner, corner2inner
from module.ocr.ocr import Ocr
from module.os.assets import FLEET_EMP_DEBUFF, MAP_EXIT, MAP_GOTO_GLOBE, STRONGHOLD_PERCENTAGE, TEMPLATE_EMPTY_HP
from module.os.camera import OSCamera
from module.os.map_base import OSCampaignMap
from module.os_ash.ash import OSAsh
from module.os_combat.combat import Combat
from module.os_combat.assets import SIREN_PREPARATION
from module.combat.assets import BATTLE_PREPARATION
from module.os_handler.assets import AUTO_SEARCH_REWARD, CLICK_SAFE_AREA, IN_MAP, PORT_ENTER, TEMPLATE_STORAGE_SHIP_EMPTY
from module.os_shop.assets import PORT_SUPPLY_CHECK
from module.ui.assets import BACK_ARROW

FLEET_FILTER = Filter(regex=re.compile(r'fleet-?(\d)'), attr=('fleet',), preset=('callsubmarine',))


def limit_walk(location, step=3):
    x, y = location
    if abs(x) > 0:
        x = min(abs(x), step - abs(y)) * x // abs(x)
    return x, y


class BossFleet:
    def __init__(self, fleet_index):
        self.fleet_index = fleet_index
        self.fleet = str(fleet_index)
        self.standby_loca = (0, 0)

    def __str__(self):
        return f'Fleet-{self.fleet}'

    __repr__ = __str__

    def __eq__(self, other):
        return str(self) == str(other)


class PercentageOcr(Ocr):
    def __init__(self, *args, **kwargs):
        kwargs['lang'] = 'azur_lane'
        super().__init__(*args, **kwargs)

    def pre_process(self, image):
        image = super().pre_process(image)
        image = np.pad(image, ((2, 2), (0, 0)), mode='constant', constant_values=255)
        return image


FLEET_LOW_RESOLVE = Button(
    area=(294, 76, 339, 121), color=(255, 44, 33), button=(294, 76, 339, 121),
    name='FLEET_LOW_RESOLVE')


class OSFleet(OSCamera, Combat, Fleet, OSAsh):
    def _goto(self, location, expected=''):
        super()._goto(location, expected)
        self.predict_radar()
        self.map.show()

        if self.handle_ash_beacon_attack():
            # 余烬攻击后，摄像机重新聚焦到当前舰队。
            self.camera = location
            self.update()

    def map_data_init(self, map_=None):
        """
        创建新的地图对象，使用当前海域的形状。
        """
        map_ = OSCampaignMap()
        map_.shape = self.zone.shape
        super().map_data_init(map_)

    def map_control_init(self):
        """
        移除不存在的元素（如策略、回合等）。
        """
        # self.handle_strategy(index=1 if not self.fleets_reversed() else 2)
        self.update()
        # if self.handle_fleet_reverse():
        #     self.handle_strategy(index=1)
        self.hp_reset()
        self.hp_get()
        self.lv_reset()
        self.lv_get()
        self.ensure_edge_insight(preset=self.map.in_map_swipe_preset_data, swipe_limit=(6, 5))
        # self.full_scan(must_scan=self.map.camera_data_spawn_point)
        # self.find_current_fleet()
        # self.find_path_initial()
        # self.map.show_cost()
        # self.round_reset()
        # self.round_battle()

    def find_current_fleet(self):
        self.fleet_1 = self.camera

    @property
    def _walk_sight(self):
        sight = (-4, -1, 3, 2)
        return sight

    _os_map_event_handled = False

    def ambush_color_initial(self):
        self._os_map_event_handled = False

    def handle_ambush(self):
        """
        将地图事件视为伏击，触发行走重试。
        """
        if self.handle_map_get_items():
            self._os_map_event_handled = True
            self.device.sleep(0.3)
            self.device.screenshot()
            return True
        elif self.handle_map_event():
            self.ensure_no_map_event()
            self._os_map_event_handled = True
            return True
        else:
            return False

    def handle_mystery(self, button=None):
        """
        处理伏击后，如果舰队已到达则视为神秘格子，否则仅视为伏击。
        """
        if self._os_map_event_handled and button.predict_fleet() and button.predict_current_fleet():
            return 'get_item'
        else:
            return False

    @staticmethod
    def _get_goto_expected(grid):
        """
        获取 _goto() 中使用的 `expected` 参数值。
        """
        if grid.is_enemy:
            return 'combat'
        elif grid.is_resource or grid.is_meowfficer or grid.is_exclamation:
            return 'mystery'
        else:
            return ''

    def _hp_grid(self):
        hp_grid = super()._hp_grid()

        # 六个血条的位置，根据各服务器的 OS 布局
        if self.config.SERVER == 'en':
            hp_grid = ButtonGrid(origin=(35, 205), delta=(0, 100), button_shape=(66, 3), grid_shape=(1, 6))
        elif self.config.SERVER == 'jp':
            pass
        else:
            pass

        return hp_grid

    def _storage_hp_grid(self):
        return ButtonGrid(origin=(185, 553), delta=(166, 0), button_shape=(99, 4), grid_shape=(6, 1))

    def hp_retreat_triggered(self):
        return False

    need_repair = [False, False, False, False, False, False]

    def hp_get(self):
        """
        计算当前血量，同时检测扳手图标（舰船已阵亡，需要修理）。
        """
        super().hp_get()
        if self.config.OpsiHazard1Leveling_SkipHpCheck:
            self.need_repair = [False, False, False, False, False, False]
            return

        ship_icon = self._hp_grid().crop((0, -67, 67, 0))
        need_repair = [TEMPLATE_EMPTY_HP.match(self.image_crop(button, copy=False)) for button in ship_icon.buttons]
        self.need_repair = need_repair
        logger.attr('Repair icon', need_repair)

        if any(need_repair):
            for index, repair in enumerate(need_repair):
                if repair:
                    self._hp_has_ship[self.fleet_current_index][index] = True
                    self._hp[self.fleet_current_index][index] = 0

            logger.attr('HP', ' '.join(
                [str(int(data * 100)).rjust(3) + '%' if use else '____'
                 for data, use in zip(self.hp, self.hp_has_ship, strict=False)]))

        return self.hp

    def _storage_hp_get(self):
        super().hp_get()
        ship_icon = self._hp_grid().crop((-29, -165, 106, -30))
        has_ship = [not TEMPLATE_STORAGE_SHIP_EMPTY.match(
                    self.image_crop(button, copy=False), similarity=0.5) for button in ship_icon.buttons]
        need_repair = [not repair for repair in self.hp_has_ship]
        for index, repair in enumerate(need_repair):
            if repair:
                self._hp[self.fleet_current_index][index] = 0
        for index, ship in enumerate(has_ship):
            self._hp_has_ship[self.fleet_current_index][index] = ship
        self.need_repair = [all(repair) for repair in zip(need_repair, has_ship, strict=False)]
        logger.attr('Repair icon', self.need_repair)
        logger.attr('HP', ' '.join(
            [str(int(data * 100)).rjust(3) + '%' if use else '____'
            for data, use in zip(self.hp, self.hp_has_ship, strict=False)]))

    def storage_hp_get(self):
        """
        在 STORAGE_CHECK 页面计算当前血量，同时检测扳手图标（舰船已阵亡，需要修理）。
        """
        origin = (self._hp_grid, self.COLOR_HP_RED)
        self._hp_grid = self._storage_hp_grid
        self.COLOR_HP_RED = (236, 0, 0)
        try:
            self._storage_hp_get()
        finally:
            self._hp_grid = origin[0]
            self.COLOR_HP_RED = origin[1]
        return self.hp

    def lv_get(self, after_battle=False):
        pass

    def fleet_low_resolve_appear(self):
        """
        检测当前舰队是否有低士气减益效果。
        """
        return self.image_color_count(
            FLEET_LOW_RESOLVE, color=FLEET_LOW_RESOLVE.color, threshold=221, count=250)

    def get_sea_grids(self):
        """
        获取当前视野中的海洋格子。

        Returns:
            SelectedGrids: 海洋格子集合，按与摄像机距离排序。
        """
        sea = []
        for local in self.view:
            if not local.predict_sea() or local.predict_current_fleet():
                continue
            # local = np.array(location) - self.camera + self.view.center_loca
            location = np.array(local.location) + self.camera - self.view.center_loca
            location = tuple(location.tolist())
            if location == self.fleet_current or location not in self.map:
                continue
            sea.append(self.map[location])

        if len(self.fleet_current):
            center = self.fleet_current
        else:
            center = self.camera
        return SelectedGrids(sea).sort_by_camera_distance(center)

    def wait_until_camera_stable(self, skip_first_screenshot=True):
        """
        等待 homo_loca 稳定。DETECTION_BACKEND 必须为 'homography'。
        """
        logger.hr('Wait until camera stable')
        record = None
        confirm_timer = Timer(0.6, count=2).start()
        for _ in self.loop(skip_first=skip_first_screenshot):
            self.update_os()
            current = self.view.backend.homo_loca
            logger.attr('homo_loca', current)
            if record is None or (current is not None and np.linalg.norm(np.subtract(current, record)) < 3):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

            record = current

        logger.info('Camera stabled')

    def wait_until_walk_stable(self, confirm_timer=None, skip_first_screenshot=False, walk_out_of_step=True, drop=None):
        """
        等待 homo_loca 稳定。DETECTION_BACKEND 必须为 'homography'。

        Args:
            confirm_timer (Timer): 确认计时器。
            skip_first_screenshot (bool): 是否跳过第一次截图。
            walk_out_of_step (bool): 是否捕获 walk_out_of_step 错误。
                默认为 True，深渊海域中使用 False。
            drop (DropImage): 掉落记录对象。

        Returns:
            str: 舰队途中遇到的事件，如 'event'、'search'、'akashi'、'combat'，
                或其组合如 'event_akashi'、'event_combat'，无事件时返回空字符串 ''。

        Raises:
            MapWalkError: 无法到达目标格子时抛出。
        """
        logger.hr('Wait until walk stable')
        record = None
        enemy_searching_appear = False
        self.device.screenshot_interval_set(0.35)
        if confirm_timer is None:
            confirm_timer = Timer(0.8, count=2)
        result = set()
        # 记录剧情历史以清除点击记录
        clicked_story = False
        clicked_story_count = 0

        confirm_timer.reset()

        def abyssal_expected_end():
            # 添加 handle_map_event() 因为 OSCombat.combat_status() 会移除 get_items
            if self.handle_map_event(drop=drop):
                return False
            return self.is_in_map()

        for _ in self.loop(skip_first=skip_first_screenshot):
            # 地图事件
            event = self.handle_map_event(drop=drop)
            if event:
                confirm_timer.reset()
                result.add('event')
                if event == 'story_skip':
                    clicked_story = True
                    clicked_story_count += 1
                    # 清除点击记录，避免塞壬扫描装置中超过 6 个选项导致的 GameTooManyClickError
                    # 塞壬扫描装置中提交物品的流程为
                    # STORY_OPTION_2_OF_3 -> POPUP_CONFIRM_STORY_SKIP
                    # 两个操作都返回 'story_skip' 事件
                    # 连续 2 次 story_skip 表示提交了塞壬扫描装置
                    if clicked_story_count >= 11:
                        logger.info('Continuous options in story')
                        self.device.click_record_clear()
                        clicked_story_count = 0
                elif event == 'map_get_items':
                    # story_skip -> map_get_items 表示收到了深渊进度奖励
                    if clicked_story:
                        logger.info('Got items from story')
                        self.device.click_record_clear()
                        clicked_story = False
                    clicked_story_count = 0
                else:
                    # 处理了其他事件，清除历史记录
                    clicked_story = False
                    clicked_story_count = 0
                continue
            if self.handle_retirement():
                confirm_timer.reset()
                continue
            if self.handle_walk_out_of_step():
                if walk_out_of_step:
                    raise MapWalkError('walk_out_of_step')
                else:
                    continue
            if self.handle_popup_confirm('WALK_UNTIL_STABLE'):
                confirm_timer.reset()
                continue
            if self.handle_manjuu():
                confirm_timer.reset()
                continue

            # 意外点击
            if self.is_in_globe():
                self.os_globe_goto_map()
                confirm_timer.reset()
                continue
            if self.is_in_storage():
                self.storage_quit()
                confirm_timer.reset()
                continue
            if self.is_in_os_mission():
                self.os_mission_quit()
                confirm_timer.reset()
                continue
            if self.handle_os_game_tips():
                confirm_timer.reset()
                continue
            if self.is_in_map_order():
                self.order_quit()
                confirm_timer.reset()
                continue

            # 战斗
            if self.combat_appear():
                # 使用 ui_back() 进行测试，因为每月深渊日志太少。
                # self.ui_back(check_button=self.is_in_map)
                self.combat(expected_end=abyssal_expected_end, fleet_index=self.fleet_show_index, save_get_items=drop)
                confirm_timer.reset()
                result.add('event')
                continue

            # 明石商店
            if self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                self.interval_clear(PORT_SUPPLY_CHECK)
                self.handle_akashi_supply_buy(CLICK_SAFE_AREA)
                confirm_timer.reset()
                result.add('akashi')
                continue

            # 游戏 bug：上一个已清理海域的 AUTO_SEARCH_REWARD 弹窗
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                confirm_timer.reset()
                continue

            # 敌人搜索
            if not enemy_searching_appear and self.enemy_searching_appear():
                enemy_searching_appear = True
                confirm_timer.reset()
                continue
            else:
                if enemy_searching_appear:
                    self.handle_enemy_flashing()
                    self.device.sleep(0.3)
                    logger.info('Enemy searching appeared.')
                    enemy_searching_appear = False
                    confirm_timer.reset()
                    result.add('search')
                if self.is_in_map():
                    self.enemy_searching_color_initial()

            # 到达检测
            # 检查颜色，因为解锁时屏幕会变黑。
            # 直接使用 IN_MAP，本质上是 `self.is_in_map() and IN_MAP.match_template_color()`
            if self.match_template_color(IN_MAP, offset=(200, 5), threshold=50):
                self.update_os()
                current = self.view.backend.homo_loca
                logger.attr('homo_loca', current)
                # 已知最大距离为 4.48px，homo_loca 在 (56, 60) 和 (52, 58) 之间
                if record is None or (current is not None and np.linalg.norm(np.subtract(current, record)) < 5.5):
                    if confirm_timer.reached():
                        break
                else:
                    confirm_timer.reset()
                record = current
            else:
                confirm_timer.reset()

        result = '_'.join(result)
        logger.info(f'Walk stabled, result: {result}')
        self.device.screenshot_interval_set()
        return result

    def port_goto(self, allow_port_arrive=True):
        """
        简单的港口导航实现，通过雷达搜索港口。

        在大世界中，舰队移动时摄像机始终跟随，会干扰 `self.goto()`。
        多数情况下使用自律寻敌清理地图，经典方法已弃用。
        但仍需要将舰队移向港口，此方法用于该场景。

        Raises:
            MapWalkError: 无法到达目标格子时抛出。
                可能点击了陆地、港口中心或舰队自身。
        """
        confirm_timer = Timer(3, count=6).start()
        while 1:
            # 计算目的地
            grid = self.radar.port_predict(self.device.image)
            logger.info(f'Port route at {grid}')
            if grid is None:
                self.device.screenshot()
                continue

            radar_arrive = np.linalg.norm(grid) == 0
            port_arrive = self.appear(PORT_ENTER, offset=(20, 20))
            if allow_port_arrive and port_arrive:
                logger.info('Arrive port (port_arrive)')
                break
            elif allow_port_arrive and (not port_arrive and radar_arrive):
                if confirm_timer.reached():
                    logger.warning('Arrive port on radar but port entrance not appear')
                    raise MapWalkError
                else:
                    logger.info('Arrive port on radar but port entrance not appear, confirming')
                    self.device.screenshot()
                    continue
            elif not allow_port_arrive and radar_arrive:
                logger.info('Arrive port (radar_arrive)')
                break
            else:
                confirm_timer.reset()

            # 更新本地视野
            self.update_os()
            self.predict()

            # 点击路径点
            grid = point_limit(grid, area=(-4, -2, 3, 2))
            grid = self.convert_radar_to_local(grid)
            self.device.click(grid)

            # 等待到达
            self.wait_until_walk_stable()

    def fleet_set(self, index=1, skip_first_screenshot=True):
        """
        Args:
            index (int): Target fleet_current_index
            skip_first_screenshot (bool):

        Returns:
            bool: If switched.
        """
        logger.hr(f'Fleet set to {index}')
        if self.fleet_selector.ensure_to_be(index):
            self.wait_until_camera_stable()
            return True
        else:
            return False

    def storage_fleet_set(self, index=1, skip_first_screenshot=True):
        """
        Args:
            index (int): Target fleet_current_index
            skip_first_screenshot (bool):

        Returns:
            bool: If switched.
        """
        logger.hr(f'Fleet set to {index}')
        return self.storage_fleet_selector.ensure_to_be(index)

    def parse_fleet_filter(self):
        """
        Returns:
            list: List of BossFleet or str. Such as [Fleet-4, 'CallSubmarine', Fleet-2, Fleet-3, Fleet-1].
        """
        FLEET_FILTER.load(self.config.OpsiFleetFilter_Filter)
        fleets = FLEET_FILTER.apply([BossFleet(f) for f in [1, 2, 3, 4]])

        # 设置待命位置
        standby_list = [(-1, -1), (0, -1), (1, -1)]
        index = 0
        for fleet in fleets:
            if isinstance(fleet, BossFleet) and index < len(standby_list):
                fleet.standby_loca = standby_list[index]
                index += 1

        return fleets

    def relative_goto(self, has_fleet_step=False, near_by=False, relative_position=(0, 0), index=0, **kwargs):
        logger.hr('Relative goto')
        logger.info(f'Relative goto, {dict_to_kv(kwargs)}')

        # 更新本地视野
        # 不截图，复用旧截图
        self.update_os()
        self.predict()
        self.predict_radar()

        # 计算目的地
        grids = self.radar.select(**kwargs)
        if near_by:
            grids = grids.sort_by_camera_distance((0, 0))
        if grids:
            # 点击路径点
            grid = np.add(location_ensure(grids[index]), relative_position)

            grid = point_limit(grid, area=(-4, -2, 3, 2))
            if has_fleet_step:
                grid = limit_walk(grid)
            grid = self.convert_radar_to_local(grid)
            self.device.click(grid)
        else:
            logger.info('No position to goto, stop')

        # 等待到达
        # 使用新截图
        self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4), walk_out_of_step=False)

    def go_month_boss_room(self, is_normal=True):
        logger.hr('Goto room entrance')
        logger.info(f'Goto room entrance, is_normal={is_normal}')
        while 1:
            if self.appear(MAP_EXIT, offset=(20, 20)):
                break

            # 入口下方 2 格
            self.relative_goto(has_fleet_step=True, near_by=True, relative_position=(3, -2), is_port=True)

            self.update_os()
            self.predict()
            self.predict_radar()
            grid = self.radar.select(is_port=True).first_or_none()
            if grid is not None and grid.location == (-3, 2):
                logger.info('At room entrance')
                break

        logger.hr('Enter room entrance')
        while 1:
            if self.appear(MAP_EXIT, offset=(20, 20)):
                logger.info('Entered boss room')
                break

            if is_normal:
                self.relative_goto(has_fleet_step=True, near_by=True, is_exclamation=True)
            else:
                if self.radar.select(is_exclamation=True).count:
                    logger.warning('Trying to enter month boss hard mode but is_exclamation exists')
                    self.relative_goto(has_fleet_step=True, near_by=True, is_exclamation=True)
                else:
                    self.relative_goto(has_fleet_step=True, near_by=True, is_question=True)

    def question_goto(self, has_fleet_step=False):
        logger.hr('Question goto')
        while 1:
            # 游戏 bug：上一个已清理海域的 AUTO_SEARCH_REWARD 弹窗
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                self.device.screenshot()
                continue

            # 更新本地视野
            # 不截图，复用旧截图
            self.update_os()
            self.predict()
            self.predict_radar()

            # 计算目的地
            grids = self.radar.select(is_question=True)
            if grids:
                # 点击路径点
                grid = location_ensure(grids[0])
                grid = point_limit(grid, area=(-4, -2, 3, 2))
                if has_fleet_step:
                    grid = limit_walk(grid)
                grid = self.convert_radar_to_local(grid)
                self.device.click(grid)
            else:
                logger.info('No question mark to goto, stop')
                break

            # 等待到达
            # 使用新截图
            self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4), walk_out_of_step=False)

    def month_boss_goto_additional(self, location=(0, 0), has_fleet_step=False, drop=None):
        self.update_os()
        self.predict()
        self.predict_radar()

        # 计算目的地
        grids = self.radar.select(is_question=True)
        if grids:
            # 点击路径点
            grid = np.add(location_ensure(grids[0]), location)
            # 使用问号的相对位置来定位 Boss 区域入口
            grid = np.add(grid, (1, -6))
            grid = point_limit(grid, area=(-4, -2, 3, 2))
            if has_fleet_step:
                grid = limit_walk(grid)
            if grid == (0, 0):
                logger.info(f'Arrive destination: boss {location}')
            grid = self.convert_radar_to_local(grid)
            self.device.click(grid)
        else:
            logger.info('No boss to goto, stop')
        self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4), walk_out_of_step=False, drop=drop)

    def boss_goto(self, location=(0, 0), has_fleet_step=False, drop=None, is_month=False):
        logger.hr('BOSS goto')

        if is_month:
            self.month_boss_goto_additional(location=location, has_fleet_step=has_fleet_step, drop=drop)

        while 1:
            # 更新本地视野
            # 不截图，复用旧截图
            self.update_os()
            self.predict()
            self.predict_radar()

            # 计算目的地
            grids = self.radar.select(is_enemy=True)
            if grids:
                # 点击路径点
                grid = np.add(location_ensure(grids[0]), location)
                grid = point_limit(grid, area=(-4, -2, 3, 2))
                if has_fleet_step:
                    grid = limit_walk(grid)
                if grid == (0, 0):
                    logger.info(f'Arrive destination: boss {location}')
                    break
                grid = self.convert_radar_to_local(grid)
                self.device.click(grid)
            else:
                logger.info('No boss to goto, stop')
                break

            # 等待到达
            # 使用新截图
            self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4), walk_out_of_step=False, drop=drop)

    def get_boss_leave_button(self):
        for grid in self.view:
            if grid.predict_current_fleet():
                return None

        grids = [grid for grid in self.view if grid.predict_caught_by_siren()]
        if len(grids) == 1:
            center = grids[0]
        elif len(grids) > 1:
            logger.warning(f'Found multiple fleets in boss ({grids}), use the center one')
            center = SelectedGrids(grids).sort_by_camera_distance(self.view.center_loca)[0]
        else:
            logger.warning('No fleet in boss, use camera center instead')
            center = self.view[self.view.center_loca]

        logger.info(f'Fleet in boss: {center}')
        # 中心格子左侧半个格子。
        area = corner2inner(center.grid2screen(area2corner((1, 0.25, 1.5, 0.75))))
        button = Button(area=area, color=(), button=area, name='BOSS_LEAVE')
        return button

    def boss_leave(self):
        """
        离开 Boss 区域。

        Pages:
            in: is_in_map() 或 combat_appear()
            out: is_in_map(), 舰队不在 Boss 区域中。
        """
        logger.hr('BOSS leave')
        # 更新本地视野
        self.update_os()
        self.predict()

        click_timer = Timer(3)
        pause_interval = Timer(0.5, count=1)
        for _ in self.loop():
            # 结束条件
            if self.is_in_map():
                self.predict_radar()
                if self.radar.select(is_enemy=True):
                    logger.info('Fleet left boss, boss found')
                    break

            # 意外重新进入 Boss
            if pause_interval.reached():
                if self.appear(BATTLE_PREPARATION):
                    logger.info(f'{BATTLE_PREPARATION} -> {BACK_ARROW}')
                    self.device.click(BACK_ARROW)
                    pause_interval.reset()
                    continue
                if self.appear(SIREN_PREPARATION, offset=(20, 20)):
                    logger.info(f'{SIREN_PREPARATION} -> {BACK_ARROW}')
                    self.device.click(BACK_ARROW)
                    pause_interval.reset()
                    continue
                pause = self.is_combat_executing()
                if pause:
                    self.device.click(pause)
                    self.interval_reset(MAINTENANCE_ANNOUNCE)
                    pause_interval.reset()
                    continue
            if self.handle_combat_quit():
                self.interval_reset(MAINTENANCE_ANNOUNCE)
                pause_interval.reset()
                continue
            if self.handle_combat_quit_reconfirm():
                self.interval_reset(MAINTENANCE_ANNOUNCE)
                pause_interval.reset()
                continue

            # 点击离开按钮
            if self.is_in_map() and click_timer.reached():
                button = self.get_boss_leave_button()
                if button is not None:
                    self.device.click(button)
                    click_timer.reset()
                    continue
                else:
                    logger.info('Fleet left boss, current fleet found')
                    break

    def boss_clear(self, has_fleet_step=True, is_month=False, allow_submarine_call=True):
        """
        所有舰队轮流攻击 Boss。

        Args:
            has_fleet_step (bool): 是否限制舰队移动步数。
            is_month (bool): 是否为月度 Boss。
            allow_submarine_call (bool): 是否允许呼叫潜艇。

        Returns:
            bool: 是否成功击败 Boss。

        Pages:
            in: 塞壬日志（深渊），Boss 已出现。
            out: 成功时为危险或安全海域；失败时仍在深渊中。
        """
        logger.hr(f'BOSS clear', level=1)

        fleets = self.parse_fleet_filter()
        with self.stat.new(
                genre=inflection.underscore(self.config.task.command),
                method=self.config.DropRecord_OpsiRecord
        ) as drop:
            for fleet in fleets:
                logger.hr(f'Turn: {fleet}', level=2)
                if not isinstance(fleet, BossFleet):
                    if allow_submarine_call:
                        self.os_order_execute(recon_scan=False, submarine_call=True)
                    else:
                        logger.info(f'Skip fleet-filter order `{fleet}` in abyssal')
                    continue

                # 切换舰队
                if self.fleet_set(fleet.fleet_index):
                    pass
                else:
                    # 如果舰队不存在则重新聚焦摄像机
                    others = [f for f in fleets if isinstance(f, BossFleet) and f != fleet]
                    if len(others):
                        other: BossFleet = others[0]
                        self.fleet_set(other.fleet_index)
                        self.fleet_set(fleet.fleet_index)
                    else:
                        logger.warning(f'No other fleets from {fleets}, skip refocus')
                        pass

                # 检查舰队
                self.handle_os_map_fleet_lock(enable=False)
                if self.fleet_low_resolve_appear():
                    logger.warning('Skip using current fleet because of the low resolve debuff')
                    self.boss_goto(location=fleet.standby_loca, has_fleet_step=has_fleet_step, drop=drop,
                                   is_month=is_month)
                    continue

                # 确保 Boss 出现
                if is_month:
                    while not self.radar.select(is_enemy=True):
                        self.relative_goto(has_fleet_step=True, is_question=True, relative_position=(1, -6), index=0)
                        try:
                            self.relative_goto(has_fleet_step=True, is_question=True, index=1)
                        except IndexError:
                            self.relative_goto(has_fleet_step=True, is_question=True, relative_position=(1, -7),
                                               index=0)

                # 攻击
                self.boss_goto(location=(0, 0), has_fleet_step=has_fleet_step, drop=drop, is_month=is_month)

                # 结束条件
                self.predict_radar()
                if self.radar.select(is_question=True):
                    logger.info('BOSS clear')
                    if drop.count:
                        drop.add(self.device.image)
                    self.map_exit()
                    return True

                # 待命
                self.boss_leave()
                if fleet.standby_loca != (0, 0):
                    self.boss_goto(location=fleet.standby_loca, has_fleet_step=has_fleet_step, drop=drop)
                else:
                    if drop.count:
                        drop.add(self.device.image)
                    break

        logger.critical('无法击败boss，舰队已耗尽')
        return False

    def run_abyssal(self):
        """
        处理双重确认并攻击深渊（塞壬日志）Boss。
        即使舰队筛选器包含 `CallSubmarine` 条目，深渊也不会使用潜艇命令。

        Returns:
            bool: 是否成功击败 Boss。

        Pages:
            in: 塞壬日志（深渊）。
            out: 成功时为危险或安全海域；失败时仍在深渊中。
        """
        self.handle_os_map_fleet_lock(enable=False)

        def is_at_front(grid):
            # 格子位置通常为 (0, -2)
            x, y = grid.location
            return (abs(x) <= abs(y)) and (y < 0)

        while 1:
            self.device.screenshot()
            self.question_goto(has_fleet_step=True)

            if self.radar.select(is_enemy=True).filter(is_at_front):
                logger.info('Found boss at front')
                break
            else:
                logger.info('No boss at front, retry question_goto')
                continue

        result = self.boss_clear(has_fleet_step=True, allow_submarine_call=False)
        return result

    def get_stronghold_percentage(self):
        """
        获取塞壬要塞的清理进度。

        Returns:
            str: 通常为 ['100', '80', '60', '40', '20', '0'] 之一。
        """
        ocr = PercentageOcr(STRONGHOLD_PERCENTAGE, letter=(255, 255, 255), threshold=128, name='STRONGHOLD_PERCENTAGE')
        result = ocr.ocr(self.device.image)
        result = result.rstrip('7Kk')
        for starter in ['100', '80', '60', '40', '20', '0']:
            if result.startswith(starter):
                result = starter
                logger.attr('STRONGHOLD_PERCENTAGE', result)
                return result

        logger.warning(f'Unexpected STRONGHOLD_PERCENTAGE: {result}')
        return result

    def get_second_fleet(self):
        """
        获取第二支舰队，用于解锁需要 2 支舰队的机关。

        Returns:
            int: 第二支舰队的索引。
        """
        current = self.fleet_selector.get()
        if current == 1:
            second = 2
        else:
            second = 1
        logger.attr('Second_fleet', second)
        return second

    @staticmethod
    def fleet_walk_limit(outside, step=3):
        if np.linalg.norm(outside) <= 3:
            return outside
        if step == 1:
            grids = np.array([
                (0, -1), (0, 1), (-1, 0), (1, 0),
            ])
        else:
            grids = np.array([
                (0, -3), (0, 3), (-3, 0), (3, 0),
                (2, -2), (2, 2), (-2, 2), (-2, -2),
            ])
        degree = np.sum(grids * outside, axis=1) / np.linalg.norm(grids, axis=1) / np.linalg.norm(outside)
        return grids[np.argmax(degree)]

    _nearest_object_click_timer = Timer(2)

    def click_nearest_object(self):
        if not self._nearest_object_click_timer.reached():
            return False
        if not self.appear(MAP_GOTO_GLOBE, offset=(200, 20)):
            return False
        if self.appear(PORT_ENTER, offset=(20, 20)):
            return False

        self.update_os()
        self.view.predict()
        self.radar.predict(self.device.image)
        self.radar.show()
        nearest = self.radar.nearest_object()
        if nearest is None:
            self._nearest_object_click_timer.reset()
            return False

        step = 1 if self.appear(FLEET_EMP_DEBUFF, offset=(50, 20)) else 3
        nearest = self.fleet_walk_limit(nearest.location, step=step)
        try:
            nearest = self.convert_radar_to_local(nearest)
        except KeyError:
            logger.info('Radar grid not on local map')
            self._nearest_object_click_timer.reset()
            return False
        self.device.click(nearest)
        self._nearest_object_click_timer.reset()
