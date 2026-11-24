"""舰船等级检测模块。

通过 OCR 识别战斗画面中各舰船的等级信息。

等级检测的使用场景：
- 等级停止条件：当任一舰船达到目标等级时停止战役
- LV.32 检测：当旗舰达到 32 级时停止（钻石 farming 场景）

等级显示格式为 "LV.XX"，OCR 前需要：
1. 去除 "LV." 前缀，仅保留数字部分
2. 处理低血量时的遮罩效果（颜色偏暗）
3. 处理半透明蓝色背景

等级数据按 6 个位置独立追踪（先锋 3 + 主力 3）。
"""

import module.config.server as server

from module.base.base import ModuleBase
from module.base.button import *
from module.base.decorator import Config
from module.logger import logger
from module.ocr.ocr import Digit

# 白色和遮罩后的参考颜色
COLOR_WHITE = (255, 255, 255)
COLOR_MASKED = (107, 105, 107)


class Level(ModuleBase):
    """舰船等级检测器。

    通过 OCR 读取战斗画面中各位置舰船的等级，并提供等级停止条件判断。

    Attributes:
        _lv (list[int]): 各位置的当前等级，-1 表示未检测。
        _lv_before_battle (list[int]): 战斗前的等级快照，用于检测升级。
    """
    _lv = [-1, -1, -1, -1, -1, -1]
    _lv_before_battle = [-1, -1, -1, -1, -1, -1]

    @property
    def lv(self):
        """获取各位置舰船的等级列表。

        Returns:
            list[int]: 各位置的等级列表，长度为 6。
        """
        return self._lv

    @lv.setter
    def lv(self, value):
        """设置各位置舰船的等级列表。

        Args:
            value (list[int]): 各位置的等级列表。
        """
        self._lv = value

    def lv_reset(self):
        """进入地图后调用此方法重置等级数据。"""
        self._lv = [-1] * 6
        self._lv_before_battle = [-1] * 6

    @Config.when(SERVER='en')
    def _lv_grid(self):
        """获取 EN 服务器下的等级显示按钮网格。

        Returns:
            ButtonGrid: 等级区域按钮网格对象。
        """
        return ButtonGrid(origin=(56, 113), delta=(0, 100), button_shape=(46, 19), grid_shape=(1, 6))

    @Config.when(SERVER='jp')
    def _lv_grid(self):
        """获取 JP 服务器下的等级显示按钮网格。

        Returns:
            ButtonGrid: 等级区域按钮网格对象。
        """
        return ButtonGrid(origin=(34, 125), delta=(0, 100), button_shape=(68, 19), grid_shape=(1, 6))

    @Config.when(SERVER=None)
    def _lv_grid(self):
        """获取默认服务器下的等级显示按钮网格。

        Returns:
            ButtonGrid: 等级区域按钮网格对象。
        """
        return ButtonGrid(origin=(58, 128), delta=(0, 100), button_shape=(46, 19), grid_shape=(1, 6))

    def lv_get(self, after_battle=False):
        """获取各位置舰船的当前等级并执行停止条件检测。

        Args:
            after_battle (bool, optional): 是否在战斗后调用。默认为 False。

        Returns:
            list[int]: 各位置的等级列表。
        """
        if not self.config.StopCondition_ReachLevel and not self.config.STOP_IF_REACH_LV32:
            return [-1] * 6

        self._lv_before_battle = self.lv if after_battle else [-1] * 6

        ocr = LevelOcr(self._lv_grid().buttons, name='LevelOcr')
        self.lv = ocr.ocr(self.device.image)
        logger.attr('等级', ', '.join(str(data) for data in self.lv))

        if after_battle:
            self.lv_triggered()
            self.lv32_triggered()

        return self.lv

    def lv_triggered(self):
        """检测是否有舰船升级并达到设定的目标等级。

        Returns:
            bool: 是否触发了目标等级停止条件。
        """
        limit = self.config.StopCondition_ReachLevel
        if not limit:
            return False

        for i in range(6):
            before, after = self._lv_before_battle[i], self.lv[i]
            if after > before > 0:
                logger.info(f'[等级-检测] 位置 {i} 等级.{before} -> 等级.{after}')
            if after >= limit > before > 0:
                if after - before == 1 or after < 35:
                    logger.info(f'[等级-检测] 位置 {i} 等级.{limit} 已达到')
                    self.config.LV_TRIGGERED = True
                    return True
                else:
                    logger.warning(f'[等级-检测] {before} 和 {after} 之间的等级差距过大。'
                                   f'这不会被视为触发条件')

        return False

    def lv32_triggered(self):
        """检测旗舰是否达到 32 级停止条件。

        Returns:
            bool: 是否触发了 32 级停止条件。
        """
        if not self.config.STOP_IF_REACH_LV32:
            return False

        if self.lv[0] >= 32:
            logger.info('[等级-检测] 位置 0 等级.32 已达到')
            self.config.LV32_TRIGGERED = True
            return True

        return False


class LevelOcr(Digit):
    """舰船等级数字 OCR 识别器。"""

    def pre_process(self, image):
        """图像预处理：去除低血量暗色遮罩与半透明蓝色背景，并截除 'LV.' 前缀。

        Args:
            image (np.ndarray): 待处理的原始区域图像。

        Returns:
            np.ndarray: 处理后的二值化或灰度图像。
        """
        # 检查红色通道最大值以判断图像是否被遮罩。
        # 被遮罩时红色通道最大值不超过 COLOR_MASKED[0]=107。
        # 先裁剪再检查，去除"需要修理"图标同时保留字符 'V' 的上半部分。
        max_red = image[:8, :, 0].max()
        if max_red <= COLOR_MASKED[0]:
            # 低血量舰船的遮罩将 COLOR_WHITE=(255, 255, 255) 变为 COLOR_MASKED=(107, 105, 107)
            # 通过乘以标量将所有通道恢复。
            scalar = np.mean(COLOR_WHITE) / np.mean(COLOR_MASKED)
            image = cv2.addWeighted(image, scalar, image, 0, 0)

        # 转灰度前处理字符的蓝色背景。
        # 背景是半透明的，将 (0, 0, 0) 变为 (33, 65, 115)，(255, 255, 255) 变为 (107, 138, 189)。
        # 使用中点 (70, 102, 152)。
        bg = (70, 102, 152)
        # BT.601 亮度转换
        luma_trans = (0.299, 0.587, 0.114)
        luma_bg = np.dot(bg, luma_trans)
        image = cv2.subtract(image, bg).dot(luma_trans).round().astype(np.uint8)
        image = cv2.subtract(255, cv2.multiply(image, 255 / (255 - luma_bg)))
        # 找到 'L' 以去除 'LV.' 前缀。如果未找到 'L' 则返回空图像。
        if server.server != 'jp':
            letter_l = np.nonzero(image[9:15, :].max(axis=0) < 127)[0]
            if len(letter_l):
                first_digit = letter_l[0] + 17
                if first_digit + 3 < 46:  # LV_GRID_MAIN.button_shape[0] = 46
                    return image[:, first_digit:]
        else:
            letter_l = np.nonzero(image[5:11, :].max(axis=0) < 63)[0]
            if len(letter_l):
                first_digit = letter_l[0] + 23  # 船坞中最大尺寸，海域网格中最小尺寸
                if first_digit + 3 < 70:  # LV_GRID_MAIN.button_shape[0] = 46
                    image = image[:, first_digit:]
                    image = cv2.copyMakeBorder(image, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))
                    return image
        return np.array([[255]], dtype=np.uint8)

    def after_process(self, result):
        """后处理识别结果，纠正常见字符混淆并转换为整数。

        Args:
            result (str): OCR 原始识别文本。

        Returns:
            int: 解析出的等级数字，解析失败或为空时返回 0。
        """
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')

        # 不记录修正日志，因为等级通常为空
        # 如: [23, 0, 0, 100, 0, 0]
        result = int(result) if result else 0

        return result
