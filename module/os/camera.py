"""大世界相机控制模块。

管理大世界（Operation Siren）地图的相机移动和视图更新。

大世界的相机系统与主线战役不同：
- 使用 Homography（单应性变换）而非 Perspective（透视检测）
- 固定的存储参数用于网格检测
- 滑动区域和边界与主线战役不同
- 使用 OSGrid 而非 Grid 进行网格检测

继承自 OSMapOperation 和 Camera，组合了大世界地图操作和相机控制能力。
"""

import cv2
import numpy as np

from module.base.button import Button
from module.base.decorator import cached_property
from module.exception import MapDetectionError
from module.logger import logger
from module.map.camera import Camera
from module.map.map_base import location2node, location_ensure
from module.map_detection.os_grid import OSGrid
from module.map_detection.view import View
from module.ocr.ocr import Ocr
from module.os.map_operation import OSMapOperation
from module.os.radar import Radar


# 1280×720 画面中，居中舰队旁边的移动计数。
WALK_COUNTER_AREA = (574, 253, 594, 270)
WALK_COUNTER_MAX_MEAN_DIFFERENCE = 20
OCR_WALK_COUNTER = Ocr(WALK_COUNTER_AREA, name='OS_WALK_COUNTER')


class OSCamera(OSMapOperation, Camera):
    """大世界相机控制器。

    管理大世界地图的相机位置、视图更新和坐标转换。

    Attributes:
        radar (Radner): 雷达对象，用于检测大世界中的目标。
        fleet_current (tuple): 当前舰队位置。
    """
    radar: Radar
    fleet_current: tuple

    def _map_swipe(self, vector, box=(239, 128, 993, 628)):
        """执行地图滑动操作。

        Args:
            vector (tuple[int, int]): 滑动向量 (dx, dy)。
            box (tuple[int, int, int, int]): 滑动安全区域。默认 (239, 128, 993, 628)。

        Returns:
            bool: 滑动操作是否执行成功。
        """
        return super()._map_swipe(vector, box=box)

    def _view_init(self):
        """初始化大世界地图视图对象及单应性变换参数。"""
        if not hasattr(self, 'view'):
            storage = ((10, 7), [(110.307, 103.657), (1012.311, 103.657), (-32.959, 600.567), (1113.057, 600.567)])
            view = View(self.config, mode='os', grid_class=OSGrid)
            view.detector_set_backend('homography')
            view.backend.load_homography(storage=storage)
            self.view = view

    @cached_property
    def radar(self):
        """获取大世界小地图雷达实例。

        Returns:
            Radar: 雷达识别实例。
        """
        return Radar(self.config)

    def predict_radar(self):
        """扫描小地图雷达并将目标合并到地图数据中。"""
        self.radar.predict(self.device.image)
        self.radar.show()

    _walk_counter_image = None

    def walk_counter_changed(self, reset=False):
        """比较移动计数区域，返回变化状态，无可用帧时返回 None。"""
        if reset or self.device.image is None:
            self._walk_counter_image = None
            return None

        image = cv2.cvtColor(self.image_crop(WALK_COUNTER_AREA, copy=False), cv2.COLOR_RGB2GRAY)
        previous = self._walk_counter_image
        if previous is not None:
            difference = cv2.norm(image, previous, cv2.NORM_L1) / image.size
            if difference <= WALK_COUNTER_MAX_MEAN_DIFFERENCE:
                return False

        self._walk_counter_image = image
        return True

    def walk_counter_visible(self):
        """计数区域长时间不变时，确认其中仍可读到数字。"""
        text = OCR_WALK_COUNTER.ocr(self.device.image).strip()
        return text.isascii() and text.isdecimal()

    def grid_is_in_sight(self, grid, camera=None, sight=None):
        """判断指定格子是否在当前相机视野内。

        Args:
            grid: 目标格子或坐标。
            camera: 相机位置，为 None 时使用当前相机位置。
            sight: 视野范围，为 None 时使用地图默认视野。

        Returns:
            bool: 若在视野范围内返回 True，否则返回 False。
        """
        location = location_ensure(grid)
        camera = location_ensure(camera) if camera is not None else self.camera
        if sight is None:
            sight = self.map.camera_sight

        diff = np.array(location) - camera
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
        return x == 0 and y == 0

    # def ensure_edge_insight(self, reverse=False, preset=None, swipe_limit=(4, 3)):
    #     return super().ensure_edge_insight(reverse=reverse, preset=preset, swipe_limit=swipe_limit)
    #
    # def focus_to(self, location, swipe_limit=(4, 3)):
    #     return super().focus_to(location, swipe_limit=swipe_limit)

    def _get_map_outside_button(self):
        """获取地图外的空白点击区域按钮。

        Returns:
            Button: 地图外部可点击区域按钮。
        """
        for _ in range(2):
            if self.view.left_edge:
                edge = self.view.backend.left_edge
                area = (113, 185, edge.get_x(290), 290)
            elif self.view.right_edge:
                edge = self.view.backend.right_edge
                area = (edge.get_x(360), 360, 1280, 560)
            else:
                logger.info('[大世界-相机] 没有左边缘或右边缘')
                self.ensure_edge_insight()
                continue

            button = Button(area=area, color=(), button=area, name='MAP_OUTSIDE')
            return button

    def update_os(self):
        """更新大世界地图视野与格子检测状态。

        类似于 Camera.update()，专用于大世界场景。
        """
        # self.device.screenshot()
        self._view_init()

        try:
            self.view.load(self.device.image)
        except (MapDetectionError, AttributeError, cv2.error) as e:
            logger.warning(e)
            logger.warning('[大世界-相机] 假设摄像机聚焦在格子中心')

            def empty(*args, **kwargs):
                pass

            backup, self.view.backend.load = self.view.backend.load, empty
            self.view.backend.homo_loca = (53, 60)
            self.view.backend.left_edge = False
            self.view.backend.right_edge = False
            self.view.backend.lower_edge = False
            self.view.backend.upper_edge = False
            self.view.load(self.device.image)
            self.view.backend.load = backup

    def convert_radar_to_local(self, location):
        """将雷达相对坐标转换为本地地图视野中的绝对格子对象。

        处理镜头未正对当前舰队的游戏客户端异常。通常情况下大世界相机聚焦于当前舰队，
        对应本地视野中的 (5, 4)。若出现偏差则根据实际舰队位置进行校正。

        Args:
            location (tuple[int, int]): 雷达上的相对坐标 (x, y)。

        Returns:
            OSGrid: self.view 中的对应格子对象。
        """
        location = location_ensure(location)

        fleets = self.view.select(is_current_fleet=True)
        if fleets.count == 1:
            center = fleets[0].location
        elif fleets.count > 1:
            logger.warning(f'[大世界-相机] 雷达转换到本地时发现多个当前舰队: {fleets}')
            fleets = fleets.sort_by_camera_distance(self.view.center_loca)
            center = fleets[0].location
            logger.warning(
                f'假设距离摄像机中心最近的舰队为当前舰队: {location2node(center)}')
        else:
            logger.warning(f'[大世界-相机] 雷达转换到本地时未找到当前舰队, '
                           f'假设摄像机中心为当前舰队: {location2node(self.view.center_loca)}')
            center = self.view.center_loca

        try:
            local = self.view[np.add(location, center)]
        except KeyError:
            logger.warning(f'[大世界-相机] 雷达转换到本地时目标格子不在本地视野中, '
                           f'假设摄像机中心为当前舰队: {location2node(self.view.center_loca)}')
            center = self.view.center_loca
            local = self.view[np.add(location, center)]

        logger.info(
            f'[大世界-相机] 雷达 {location} -> 本地 {location2node(local.location)} '
            f'(舰队={location2node(center)})'
        )
        return local
