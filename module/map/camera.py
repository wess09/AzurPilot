import copy

import numpy as np

from module.base.timer import Timer
from module.base.utils import area_offset
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_1_RYZA
from module.exception import CampaignEnd, GameNotRunningError, MapDetectionError
from module.handler.assets import AUTO_SEARCH_MENU_CONTINUE, GAME_TIPS, GET_MISSION
from module.logger import logger
from module.map.assets import MAP_PREPARATION
from module.map.map_base import CampaignMap, location2node
from module.map.map_operation import MapOperation
from module.map.utils import location_ensure, random_direction
from module.map_detection.grid import Grid
from module.map_detection.utils import area2corner, trapezoid2area
from module.map_detection.view import View
from module.os.assets import GLOBE_GOTO_MAP
from module.os_handler.assets import AUTO_SEARCH_REWARD, GET_ADAPTABILITY, MISSION_CHECK as OPSI_MISSION_CHECK
from module.os_shop.assets import PORT_SUPPLY_CHECK
from module.ui.assets import BACK_ARROW


class Camera(MapOperation):
    view: View
    map: CampaignMap
    camera = (0, 0)
    grid_class = Grid
    _prev_view = None
    _prev_swipe = None

    def _map_swipe(self, vector, box=(123, 159, 1175, 628)):
        """
        Args:
            vector (tuple, np.ndarray): 滑动向量（浮点数）。
            box (tuple): 允许滑动的区域。

        Returns:
            bool: 相机是否移动了。
        """
        vector = np.array(vector)
        name = 'MAP_SWIPE_' + '_'.join([str(int(round(x))) for x in vector])
        if np.any(np.abs(vector) > self.config.MAP_SWIPE_DROP):
            # 地图网格适配
            if self.config.DEVICE_CONTROL_METHOD == 'minitouch':
                distance = self.view.swipe_base * self.config.MAP_SWIPE_MULTIPLY_MINITOUCH
            elif self.config.DEVICE_CONTROL_METHOD == 'MaaTouch':
                distance = self.view.swipe_base * self.config.MAP_SWIPE_MULTIPLY_MAATOUCH
            else:
                distance = self.view.swipe_base * self.config.MAP_SWIPE_MULTIPLY
            # 优化滑动路径
            if self.config.MAP_SWIPE_OPTIMIZE:
                whitelist, blacklist = self.get_swipe_area_opt(vector)
            else:
                whitelist, blacklist = None, None

            vector = distance * vector
            vector = -vector
            self.device.swipe_vector(vector, name=name, box=box, whitelist_area=whitelist, blacklist_area=blacklist)
            # 不知道为什么初始提交中有一个 sleep
            # self.device.sleep(0.3)
            self.update(wait_swipe=True)
            return True
        else:
            # 舍弃滑动
            # self.update(camera=False)
            return False

    def map_swipe(self, vector):
        """使用相对位置滑动到目标格子。
        调用前请先更新相机位置。

        Args:
            vector (tuple): 整数滑动向量。

        Returns:
            bool: 相机是否移动了。
        """
        logger.info('Map swipe: %s' % str(vector))
        self._prev_view = copy.copy(self.view)
        self._prev_swipe = vector
        vector = np.array(vector)
        vector = np.array([0.5, 0.5]) - self.view.center_offset + vector
        return self._map_swipe(vector)

    def focus_to_grid_center(self, tolerance=None):
        """重新聚焦到格子中心。

        Args:
            tolerance (float): 容差值，0 到 0.5。为 None 时使用 MAP_GRID_CENTER_TOLERANCE。

        Returns:
            bool: 地图是否滑动了。
        """
        if not tolerance:
            tolerance = self.config.MAP_GRID_CENTER_TOLERANCE
        if np.any(np.abs(self.view.center_offset - 0.5) > tolerance):
            logger.info('Re-focus to grid center.')
            return self.map_swipe((0, 0))

        return False

    def _view_init(self):
        if not hasattr(self, 'view'):
            self.view = View(self.config, grid_class=self.grid_class)

    def _update_view(self):
        """更新地图视图。
        """
        self._view_init()
        try:
            if not self.is_in_map() \
                    and not self.is_in_strategy_submarine_move() \
                    and not self.is_in_strategy_mob_move() \
                    and not self.is_in_strategy_air_strike():
                logger.warning('Image to detect is not in_map')
                raise MapDetectionError('Image to detect is not in_map')
            self.view.load(self.device.image)
        except MapDetectionError as e:
            if self.info_bar_count():
                logger.warning('Perspective error caused by info bar')
                self.handle_info_bar()
                return False
            elif self.appear(GET_ITEMS_1, offset=5):
                logger.warning('Perspective error caused by get_items')
                # 此处不要使用 handle_mystery()，因为大世界会覆盖它。
                self.device.click(GET_ITEMS_1)
                return False
            elif self.appear(GET_ITEMS_1_RYZA, offset=(-20, -100, 20, 20)):
                logger.warning('Perspective error caused by GET_ITEMS_1_RYZA')
                self.device.click(GET_ITEMS_1_RYZA)
                return False
            elif self.appear(GET_ADAPTABILITY, offset=(20, 20)):
                logger.warning('Perspective error caused by GET_ADAPTABILITY')
                self.device.click(GET_ADAPTABILITY)
                return False
            elif self.handle_story_skip():
                logger.warning('Perspective error caused by story')
                self.ensure_no_story(skip_first_screenshot=False)
                return False
            elif self.appear(GET_MISSION, offset=(20, 20)):
                logger.warning('Perspective error caused by GET_MISSION')
                self.device.click(GET_MISSION)
                return False
            elif self.is_in_stage():
                logger.warning('Image is in stage')
                raise CampaignEnd('Image is in stage')
            elif self.appear(MAP_PREPARATION, offset=(20, 20)):
                logger.warning('Image is in MAP_PREPARATION')
                self.enter_map_cancel()
                raise CampaignEnd('Image is in MAP_PREPARATION')
            elif self.appear(AUTO_SEARCH_MENU_CONTINUE, offset=self._auto_search_menu_offset):
                logger.warning('Image is in auto search menu')
                self.ensure_auto_search_exit()
                raise CampaignEnd('Image is in auto search menu')
            elif self.appear(GLOBE_GOTO_MAP, offset=(20, 20)):
                logger.warning('Image is in OS globe map')
                self.ui_click(GLOBE_GOTO_MAP, check_button=self.is_in_map, offset=(20, 20),
                              retry_wait=3, skip_first_screenshot=True)
                return False
            elif self.appear(AUTO_SEARCH_REWARD, offset=(50, 50)):
                logger.warning('Perspective error caused by AUTO_SEARCH_REWARD')
                if hasattr(self, 'os_auto_search_quit'):
                    self.os_auto_search_quit()
                    return False
                else:
                    logger.warning('Cannot find method os_auto_search_quit(), use ui_click() instead')
                    self.ui_click(AUTO_SEARCH_REWARD, check_button=self.is_in_map, offset=(50, 50),
                                  retry_wait=3, skip_first_screenshot=True)
                    return False
            elif self.appear(OPSI_MISSION_CHECK, offset=(20, 20)):
                logger.warning('Perspective error caused by OPSI_MISSION_CHECK')
                if hasattr(self, 'os_mission_quit'):
                    self.os_mission_quit()
                    return False
                else:
                    logger.warning('Cannot find method os_mission_quit(), use ui_click() instead')
                    self.ui_click(OPSI_MISSION_CHECK, check_button=self.is_in_map, offset=(200, 5),
                                  skip_first_screenshot=True)
                    return False
            elif 'opsi' in self.config.task.command.lower() and self.handle_popup_confirm('OPSI'):
                # 在大世界中始终确认弹窗，与 os_map_goto_globe() 中的弹窗相同
                logger.warning('Perspective error caused by popups')
                return False
            elif self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                logger.warning('Perspective error caused by akashi shop')
                self.device.click(BACK_ARROW)
                return False
            elif self.appear(GAME_TIPS, offset=(20, 20)):
                logger.warning('Perspective error caused by game tips')
                self.device.click(GAME_TIPS)
                return False
            elif 'Camera outside map' in str(e):
                string = str(e)
                logger.warning(string)
                x, y = string.split('=')[1].strip('() ').split(',')
                self._map_swipe((-int(x.strip()), -int(y.strip())))
            # 最后检查游戏是否在运行
            elif not self.device.app_is_running():
                logger.error('Trying to update camera but game died')
                raise GameNotRunningError
            else:
                raise e

        return True

    def _update_view_data(self):
        if self._prev_view is not None and np.linalg.norm(self._prev_swipe) > 0:
            if self.config.MAP_SWIPE_PREDICT:
                swipe = self._prev_view.predict_swipe(
                    self.view,
                    with_current_fleet=self.config.MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET,
                    with_sea_grids=self.config.MAP_SWIPE_PREDICT_WITH_SEA_GRIDS
                )
                if swipe is not None:
                    self._prev_swipe = swipe
            self.camera = tuple(np.add(self.camera, self._prev_swipe))
            self._prev_view = None
            self._prev_swipe = None
            self.show_camera()

        # Set camera position
        if self.view.left_edge:
            x = 0 + self.view.center_loca[0]
        elif self.view.right_edge:
            x = self.map.shape[0] - self.view.shape[0] + self.view.center_loca[0]
        else:
            x = self.camera[0]
        if self.view.upper_edge:
            y = self.map.shape[1] - self.view.shape[1] + self.view.center_loca[1]
        elif self.view.lower_edge:
            y = 0 + self.view.center_loca[1]
        else:
            y = self.camera[1]

        if self.camera != (x, y):
            logger.attr_align('camera_corrected', f'{location2node(self.camera)} -> {location2node((x, y))}')
        self.camera = (x, y)
        self.show_camera()

        self.predict()
        return True

    def update(self, camera=True, wait_swipe=False, allow_error=False):
        """更新地图图像。
        封装原始 update() 方法以处理随机出现的 MapDetectionError，
        该错误通常由网络问题和误点击引起。

        Args:
            camera (bool): 为 True 时更新相机位置和透视数据。
            wait_swipe (bool): 为 True 时等待相机到达格子中心。
            allow_error (bool): 为 True 时遇到检测错误则退出。
        """
        error_confirm = Timer(5, count=10).start()
        swipe_wait_timeout = Timer(0.35, count=1).start()
        # 假设已经滑动过
        swiped = True
        if wait_swipe:
            try:
                prev_center_offset = self._prev_view.center_offset
            except AttributeError:
                logger.warning('Camera.update(wait_swipe=True) but camera has no _prev_view')
                prev_center_offset = None
            logger.attr('prev.center_offset', prev_center_offset)
        else:
            prev_center_offset = None

        def is_grid_center():
            # 是否聚焦在格子中心
            # 参见 focus_to_grid_center
            if np.any(np.abs(self.view.center_offset - 0.5) > self.config.MAP_GRID_CENTER_TOLERANCE):
                return False
            return True

        def is_still_prev():
            # 是否与之前的视图相同
            if prev_center_offset is None:
                return False
            return np.linalg.norm(self.view.center_offset - prev_center_offset) < 0.001

        while 1:
            # Camera.update() 没有 skip_first_screenshot
            # 等待 swipe_wait_timeout 时不设置截图间隔
            if not swipe_wait_timeout.reached():
                self.device._screenshot_interval.clear()
            self.device.screenshot()

            # Update image in view only
            if not camera:
                self.view.update(image=self.device.image)
                return True

            # _update_view()
            try:
                success = self._update_view()
                if not success:
                    continue
                logger.attr('view.center_offset', self.view.center_offset)
                if wait_swipe and not swipe_wait_timeout.reached() and success:
                    # 如果第一张截图仍然是之前的视图
                    # 必须先离开格子中心再重新聚焦
                    if is_still_prev():
                        swiped = False
                    if is_grid_center():
                        if swiped:
                            break
                    else:
                        swiped = True
                    # No error
                    error_confirm.reset()
                    continue
                else:
                    if success:
                        break
                    else:
                        # MapDetectionError 已在 _update_view() 中处理，再次更新
                        error_confirm.reset()
                        continue
            except MapDetectionError:
                if allow_error:
                    break
                elif error_confirm.reached():
                    raise
                else:
                    continue

        # 计算视图数据
        self._update_view_data()

    def predict(self):
        self.view.predict()
        self.view.show()

    def show_camera(self):
        logger.attr_align('Camera', location2node(self.camera))

    def ensure_edge_insight(self, reverse=False, preset=None, swipe_limit=(3, 2), skip_first_update=True):
        """滑动到左下角直到两条边缘可见。
        边缘用于定位相机。

        Args:
            reverse (bool): 是否反向滑动。
            preset (tuple(int)): 手动设置的地图滑动预设。
            swipe_limit (tuple): (x, y)。滑动限制在 (-x, -y, x, y) 范围内。
            skip_first_update (bool): 通常为 True。手动调用 ensure_edge_insight 时使用 False。

        Returns:
            list[tuple]: 滑动记录。
        """
        logger.info(f'Ensure edge in sight.')
        record = []
        x_swipe, y_swipe = np.multiply(swipe_limit, random_direction(self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER))

        while 1:
            if len(record) == 0:
                if not skip_first_update:
                    self.update()
                if preset is not None:
                    self.map_swipe(preset)
                    record.append(preset)

            x = 0 if self.view.left_edge or self.view.right_edge else x_swipe
            y = 0 if self.view.lower_edge or self.view.upper_edge else y_swipe

            if len(record) > 0:
                # 即使两条边缘可见也要滑动，以避免一些尴尬的相机位置。
                self.map_swipe((x, y))

            record.append((x, y))

            if x == 0 and y == 0:
                break

        if reverse:
            logger.info('Reverse swipes.')
            for vector in record[::-1]:
                x, y = vector
                if x != 0 or y != 0:
                    self.map_swipe((-x, -y))

        return record

    def focus_to(self, location, swipe_limit=(4, 3)):
        """将相机聚焦到指定格子。

        Args:
            location: 目标格子坐标。
            swipe_limit (tuple): (x, y)。滑动限制在 (-x, -y, x, y) 范围内。
        """
        location = location_ensure(location)
        logger.info('Focus to: %s' % location2node(location))

        while 1:
            vector = np.array(location) - self.camera
            swipe = tuple(np.min([np.abs(vector), swipe_limit], axis=0) * np.sign(vector))
            has_swiped = self.map_swipe(swipe)

            if not has_swiped:
                break

    def full_scan(self, queue=None, must_scan=None, battle_count=0, mystery_count=0, siren_count=0, carrier_count=0,
                  mode='normal'):
        """扫描整个地图。

        Args:
            queue (SelectedGrids): 需要聚焦的格子。为 None 时使用 map.camera_data。
            must_scan (SelectedGrids): 必须扫描的格子。
            battle_count (int): 战斗计数。
            mystery_count (int): 神秘事件计数。
            siren_count (int): 塞壬计数。
            carrier_count (int): 航母计数。
            mode (str): 扫描模式，如 'init'、'normal'、'carrier'、'movable'。
        """
        logger.info(f'Full scan start, mode={mode}')
        self.map.reset_fleet()

        queue = queue if queue else self.map.camera_data
        if must_scan:
            queue = queue.add(must_scan)

        while len(queue) > 0:
            if self.map.missing_is_none(battle_count, mystery_count, siren_count, carrier_count, mode):
                if must_scan and queue.count != queue.delete(must_scan).count:
                    logger.info('Continue scanning.')
                    pass
                else:
                    logger.info('All spawn found, Early stopped.')
                    break

            queue = queue.sort_by_camera_distance(self.camera)
            self.focus_to(queue[0])
            self.focus_to_grid_center(0.25)
            success = self.map.update(grids=self.view, camera=self.camera, mode=mode)
            if not success:
                self.ensure_edge_insight(skip_first_update=False)
                continue

            queue = queue[1:]

        self.map.missing_predict(battle_count, mystery_count, siren_count, carrier_count, mode)
        self.map.show()

    def in_sight(self, location, sight=None):
        """确保目标位置在相机视野内。

        Args:
            location: 目标位置坐标。
            sight (tuple): 视野范围，如 (-3, -1, 3, 2)。
        """
        location = location_ensure(location)
        logger.info('In sight: %s' % location2node(location))
        if sight is None:
            sight = self.map.camera_sight

        diff = np.array(location) - self.camera
        if diff[1] > sight[3]:
            y = diff[1] - sight[3]
        elif diff[1] < sight[1]:
            y = diff[1] - sight[1]
        else:
            y = 0
        if diff[0] > sight[2]:
            x = diff[0] - sight[2]
        elif diff[0] < sight[0]:
            x = diff[0] - sight[0]
        else:
            x = 0
        self.focus_to((self.camera[0] + x, self.camera[1] + y))

    def convert_global_to_local(self, location):
        """将全局坐标转换为局部坐标。
        如果 self.grids 不包含该位置，则将相机聚焦到该位置后重新转换。

        Args:
            location: self.map 中的格子实例。

        Returns:
            Grid: self.view 中的格子实例。
        """
        location = location_ensure(location)

        local = np.array(location) - self.camera + self.view.center_loca
        logger.info('Global %s (camera=%s) -> Local %s (center=%s)' % (
            location2node(location),
            location2node(self.camera),
            location2node(local),
            location2node(self.view.center_loca)
        ))
        if local in self.view:
            return self.view[local]
        else:
            logger.warning('Convert global to local Failed.')
            self.focus_to(location)
            local = np.array(location) - self.camera + self.view.center_loca
            return self.view[local]

    def convert_local_to_global(self, location):
        """将局部坐标转换为全局坐标。
        如果 self.map 不包含该位置，相机可能有误，修正相机后重新转换。

        Args:
            location: self.view 中的格子实例。

        Returns:
            Grid: self.map 中的格子实例。
        """
        location = location_ensure(location)

        global_ = np.array(location) + self.camera - self.view.center_loca
        logger.info('Global %s (camera=%s) <- Local %s (center=%s)' % (
            location2node(global_),
            location2node(self.camera),
            location2node(location),
            location2node(self.view.center_loca)
        ))

        if global_ in self.map:
            return self.map[global_]
        else:
            logger.warning('Convert local to global Failed.')
            self.ensure_edge_insight(reverse=True)
            global_ = np.array(location) + self.camera - self.view.center_loca
            return self.map[global_]

    def full_scan_find_boss(self):
        logger.info('Full scan find boss.')
        self.map.reset_fleet()

        queue = self.map.select(may_boss=True)
        while len(queue) > 0:
            queue = queue.sort_by_camera_distance(self.camera)
            self.in_sight(queue[0])
            self.predict()
            queue = queue[1:]

            boss = self.map.select(is_boss=True)
            boss = boss.add(self.map.select(may_boss=True, is_enemy=True))
            if boss:
                logger.info(f'Boss found: {boss}')
                self.map.show()
                return True

        logger.warning('No boss found.')
        return False

    def get_swipe_area_opt(self, map_vector):
        """获取 random_rectangle_vector_opted() 的白名单和黑名单。

        Args:
            map_vector: 地图滑动向量。

        Returns:
            list, list: 白名单和黑名单。
        """
        map_vector = np.array(map_vector)

        def local_to_area(local_grid, pad=0):
            result = []
            for local in local_grid:
                # 预测滑动后格子的位置。
                # 滑动应在此结束，以防止将滑动视为点击。
                area = area_offset((0, 0, 1, 1), offset=-map_vector)
                corner = local.grid2screen(area2corner(area))
                area = trapezoid2area(corner, pad=pad)
                result.append(area)
            return result

        def globe_to_local(globe_grids):
            result = []
            for globe in globe_grids:
                location = tuple(np.array(globe.location) - self.camera + self.view.center_loca)
                if location in self.view:
                    local = self.view[location]
                    result.append(local)
            return result

        whitelist = self.map.select(is_land=True) \
            .add(self.map.select(is_current_fleet=True)) \
            .sort_by_camera_distance(self.camera)
        blacklist = self.view.select(is_enemy=True) \
            .add(self.view.select(is_siren=True)) \
            .add(self.view.select(is_boss=True)) \
            .add(self.view.select(is_mystery=True)) \
            .add(self.view.select(is_fleet=True, is_current_fleet=False))

        # self.view.show()
        whitelist = local_to_area(globe_to_local(whitelist), pad=25)
        blacklist = [grid.outer for grid in blacklist] + local_to_area(blacklist, pad=-5)

        return whitelist, blacklist
