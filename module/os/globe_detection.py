"""
大世界全球地图检测模块。

负责全球地图 (Globe Map) 的图像检测和定位，通过单应性变换和
模板匹配确定当前摄像机在全球地图中的位置。

主要类:
    GlobeDetection: 全球地图检测器，通过模板匹配定位当前摄像机位置。

检测流程:
    1. 加载预处理好的全球地图边界图像 (GLOBE_MAP)。
    2. 对游戏截图进行透视变换和边界提取。
    3. 将提取的边界与全球地图进行模板匹配 (cv2.matchTemplate)。
    4. 根据匹配结果计算摄像机在全球地图坐标系中的位置。

坐标系:
    globe 坐标系: 全球地图的二维坐标系，原点为地图左上角，
        范围约为 (0, 0) 到 GLOBE_MAP_SHAPE (2570, 1696)。
    screen 坐标系: 1280x720 的屏幕像素坐标系。
    homo_center: 单应性变换后的屏幕中心在全球地图坐标系中的位置。
"""
import time

from module.base.utils import *
from module.config.config import AzurLaneConfig
from module.logger import logger
from module.map_detection.homography import Homography
from module.map_detection.perspective import Perspective
from module.map_detection.utils import *

GLOBE_MAP = './assets/map_detection/os_globe_map.png'
GLOBE_MAP_SHAPE = (2570, 1696)


class GlobeDetection:
    """全球地图检测器。

    通过单应性变换和模板匹配，在大世界模式下确定当前摄像机
    在全球地图中的位置。支持屏幕坐标与全球地图坐标的双向转换。

    Examples:
        globe = GlobeDetection(AzurLaneConfig('template'))
        globe.load(image)

    Logs:
                  globe_center: (1305, 325)
        0.062s      similarity: 0.354

    Attributes:
        globe (np.ndarray): 预处理后的全球地图边界图像。
        homo_center (tuple[int, int]): 屏幕中心在全球地图坐标系中的位置。
        center_loca (tuple[float, float]): 当前摄像机在全球地图坐标系中的位置。
        config (AzurLaneConfig): 配置对象。
        perspective (Perspective): 透视检测器。
        homography (Homography): 单应性变换器。
    """
    globe = None
    homo_center: tuple
    center_loca: tuple

    def __init__(self, config):
        """初始化全球地图检测器。

        Args:
            config (AzurLaneConfig): 配置对象，包含全球地图检测相关参数。
        """
        self.config = config
        self.perspective = Perspective(config)
        self.homography = Homography(config)
        self._globe_map_loaded = False

    def load_globe_map(self):
        """加载全球地图资源和单应性变换矩阵。

        必须在进行任何全球地图操作前调用。仅首次调用时实际加载，
        后续调用直接返回 False。

        Returns:
            bool: 首次加载成功返回 True，已加载返回 False。
        """
        if self._globe_map_loaded:
            return False

        logger.info('[大世界-检测] 加载大世界地图')

        # Load GLOBE_MAP
        image = load_image(GLOBE_MAP)
        image = self.find_peaks(image, para=self.config.OS_GLOBE_FIND_PEAKS_PARAMETERS)
        pad = self.config.OS_GLOBE_IMAGE_PAD
        image = np.pad(image, ((pad, pad), (pad, pad)), mode='constant', constant_values=0)
        image = image.astype(np.uint8)
        image = cv2.resize(image, None, fx=self.config.OS_GLOBE_IMAGE_RESIZE, fy=self.config.OS_GLOBE_IMAGE_RESIZE)
        self.globe = image

        # Load homography
        backup = self.config.temporary(
            HOMO_STORAGE=self.config.OS_GLOBE_HOMO_STORAGE, DETECTING_AREA=self.config.OS_GLOBE_DETECTING_AREA)
        self.homography.find_homography(*self.config.HOMO_STORAGE, overflow=False)
        self.homo_center = self.screen2globe([self.config.SCREEN_CENTER])[0].astype(int)
        backup.recover()

        self._globe_map_loaded = True
        return True

    def screen2globe(self, points):
        """将屏幕坐标转换为全球地图坐标。

        Args:
            points (np.ndarray): 屏幕坐标点数组。

        Returns:
            np.ndarray: 对应的全球地图坐标点数组。
        """
        return perspective_transform(points, data=self.homography.homo_data)

    def globe2screen(self, points):
        """将全球地图坐标转换为屏幕坐标。

        Args:
            points (np.ndarray): 全球地图坐标点数组。

        Returns:
            np.ndarray: 对应的屏幕坐标点数组。
        """
        return perspective_transform(points, data=self.homography.homo_invt)

    def find_peaks(self, image, para):
        """提取图像中的海域边缘峰值特征。

        Args:
            image (np.ndarray): 输入图像数据。
            para (dict): 传递给 scipy.signal.find_peaks 的参数字典。

        Returns:
            np.ndarray: 单色边界图像，边缘为白色，其余为黑色。
        """
        r, g, b = cv2.split(image)
        # b = cv2.add(cv2.multiply(g, 0.6), cv2.multiply(b, 0.4))
        # image = cv2.subtract(b, r)
        cv2.convertScaleAbs(g, alpha=0.6, dst=g)
        cv2.convertScaleAbs(b, alpha=0.4, dst=b)
        cv2.add(g, b, dst=b)
        cv2.subtract(b, r, dst=b)
        image = b

        hori = self.perspective.find_peaks(image, is_horizontal=True, param=para, mask=None)
        vert = self.perspective.find_peaks(image, is_horizontal=False, param=para, mask=None)
        image = cv2.bitwise_or(hori, vert)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cv2.dilate(image, kernel, dst=image)

        return image

    def perspective_transform(self, image):
        """对截图执行透视校正变换，消除俯视透视畸变。

        Args:
            image (np.ndarray): 带有透视效果的原始截图。

        Returns:
            np.ndarray: 校正为正视平面的 2D 地图图像。
        """
        image = cv2.warpPerspective(image, self.homography.homo_data, self.homography.homo_size)
        return image

    def load(self, image):
        """从截图中检测当前摄像机在全球地图中的位置。

        对截图进行透视变换和边界提取后，与预加载的全球地图进行模板匹配，
        计算当前摄像机位置并存储到 self.center_loca。

        Args:
            image (np.ndarray): 当前游戏截图（1280x720）。

        Logs:
            globe_center: 摄像机在全球地图坐标系中的位置。
            similarity: 模板匹配相似度（低于 0.1 时发出警告）。
        """
        self.load_globe_map()
        start_time = time.time()

        local = self.find_peaks(self.perspective_transform(image), para=self.config.OS_LOCAL_FIND_PEAKS_PARAMETERS)
        local = local.astype(np.uint8)
        local = cv2.resize(local, None, fx=self.config.OS_GLOBE_IMAGE_RESIZE, fy=self.config.OS_GLOBE_IMAGE_RESIZE)

        result = cv2.matchTemplate(self.globe, local, cv2.TM_CCOEFF_NORMED)
        _, similarity, _, loca = cv2.minMaxLoc(result)
        loca = np.array(loca) / self.config.OS_GLOBE_IMAGE_RESIZE
        loca = tuple(self.homo_center + loca - self.config.OS_GLOBE_IMAGE_PAD)
        self.center_loca = loca

        time_cost = round(time.time() - start_time, 3)
        logger.attr_align('全球地图中心', loca)
        logger.attr_align('相似度', float2str(similarity), front=float2str(time_cost) + 's')
        if similarity < 0.1:
            logger.warning('[大世界-检测] 匹配大世界地图时相似度过低')
