import module.config.server as server

from module.base.base import ModuleBase
from module.base.button import *
from module.base.decorator import Config
from module.logger import logger
from module.ocr.ocr import Digit

COLOR_WHITE = (255, 255, 255)
COLOR_MASKED = (107, 105, 107)


class Level(ModuleBase):
    _lv = [-1, -1, -1, -1, -1, -1]
    _lv_before_battle = [-1, -1, -1, -1, -1, -1]

    @property
    def lv(self):
        """
        Returns:
            list[int]: 各位置的等级列表。
        """
        return self._lv

    @lv.setter
    def lv(self, value):
        """
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
        return ButtonGrid(origin=(56, 113), delta=(0, 100), button_shape=(46, 19), grid_shape=(1, 6))

    @Config.when(SERVER='jp')
    def _lv_grid(self):
        return ButtonGrid(origin=(34, 128), delta=(0, 100), button_shape=(68, 19), grid_shape=(1, 6))

    @Config.when(SERVER=None)
    def _lv_grid(self):
        return ButtonGrid(origin=(58, 128), delta=(0, 100), button_shape=(46, 19), grid_shape=(1, 6))

    def lv_get(self, after_battle=False):
        """获取各位置的等级。

        Args:
            after_battle (bool): 是否在战斗后调用。

        Returns:
            list[int]: 各位置的等级列表。
        """
        if not self.config.StopCondition_ReachLevel and not self.config.STOP_IF_REACH_LV32:
            return [-1] * 6

        self._lv_before_battle = self.lv if after_battle else [-1] * 6

        ocr = LevelOcr(self._lv_grid().buttons, name='LevelOcr')
        self.lv = ocr.ocr(self.device.image)
        logger.attr('LEVEL', ', '.join(str(data) for data in self.lv))

        if after_battle:
            self.lv_triggered()
            self.lv32_triggered()

        return self.lv

    def lv_triggered(self):
        limit = self.config.StopCondition_ReachLevel
        if not limit:
            return False

        for i in range(6):
            before, after = self._lv_before_battle[i], self.lv[i]
            if after > before > 0:
                logger.info(f'Position {i} LV.{before} -> LV.{after}')
            if after >= limit > before > 0:
                if after - before == 1 or after < 35:
                    logger.info(f'Position {i} LV.{limit} Reached')
                    self.config.LV_TRIGGERED = True
                    return True
                else:
                    logger.warning(f'Level gap between {before} and {after} is too large. '
                                   f'This will not be considered as a trigger')

        return False

    def lv32_triggered(self):
        if not self.config.STOP_IF_REACH_LV32:
            return False

        if self.lv[0] >= 32:
            logger.info(f'Position 0 LV.32 Reached')
            self.config.LV32_TRIGGERED = True
            return True

        return False


class LevelOcr(Digit):
    def pre_process(self, image):
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
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')

        # 不记录修正日志，因为等级通常为空
        # 如: [23, 0, 0, 100, 0, 0]
        result = int(result) if result else 0

        return result
