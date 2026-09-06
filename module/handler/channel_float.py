"""渠道服（4399）启动悬浮球处理。

4399 等渠道服客户端启动后，屏幕左上角（角色名右上方）会出现 SDK 悬浮球。
悬浮球是半透明圆盘，截图里几乎不可见，但顶部带有一圈绿色「○○○」标志，
而黑色标题栏背景不含绿色，因此通过统计绿标像素即可可靠检出。
检出后自动将悬浮球拖拽到屏幕中下，并点击「隐藏悬浮球」对话框的「隐藏」按钮。
"""
import numpy as np

from module.base.base import ModuleBase
from module.base.button import Button
from module.base.utils import crop, get_color
from module.base.timer import Timer
from module.config.deep import deep_get
from module.logger import logger
from module.ui.page import page_main_white

# 悬浮球识别区域：主页面左上角上边沿左半范围（1280x720），
# 绿色「○○○」标志为识别特征；悬浮球需位于等级与名字中间（见 GUI 说明）
CHANNEL_FLOAT_AREA = (0, 0, 640, 50)
# 绿色像素计数阈值：实测有球 443、无球 0，取 20 作为安全阈值
CHANNEL_FLOAT_GREEN_THRESHOLD = 20
# 悬浮球拖拽起点（悬浮球中心）与终点（屏幕中下）
CHANNEL_FLOAT_SWIPE_START = (220, 45)
CHANNEL_FLOAT_SWIPE_END = (640, 620)
CHANNEL_FLOAT_SWIPE_DURATION = 0.6
CHANNEL_FLOAT_MAX_ATTEMPTS = 4
# 「隐藏悬浮球」对话框中的「隐藏」按钮
CHANNEL_FLOAT_HIDE_BUTTON = Button(
    area=(728, 604, 848, 664),
    color=(),
    button=(728, 604, 848, 664),
    name='CHANNEL_FLOAT_HIDE_BUTTON',
)


class ChannelFloatHandler(ModuleBase):
    """检测并处理渠道服启动悬浮球。"""

    def _enabled(self) -> bool:
        """渠道服悬浮球处理是否启用。

        仅当游戏为 4399 渠道服（包名 com.bilibili.blhx.m4399 且服务器为
        cn_channel-*）时，开关 Restart.MoveChannelFloat 才生效；
        其他服务器即使开启开关也不会生效。

        Returns:
            bool: True 表示启用。
        """
        if not bool(deep_get(self.config.data, 'Restart.Restart.MoveChannelFloat', default=False)):
            return False
        package = str(deep_get(self.config.data, 'Alas.Emulator.PackageName', default=''))
        server_name = str(deep_get(self.config.data, 'Alas.Emulator.ServerName', default=''))
        return (package == 'com.bilibili.blhx.m4399'
                and server_name.startswith('cn_channel'))

    def detected(self) -> bool:
        """悬浮球是否出现在屏幕左上角黑条区域。

        悬浮球半透明难以直接模板识别，但其顶部带有绿色「○○○」标志，
        黑色标题栏背景不含绿色像素，通过统计绿色像素数量即可可靠检出。

        Returns:
            bool: True 表示识别到悬浮球。
        """
        image = crop(self.device.image, CHANNEL_FLOAT_AREA, copy=False)
        r = image[:, :, 0].astype(np.int16)
        g = image[:, :, 1].astype(np.int16)
        b = image[:, :, 2].astype(np.int16)
        green = int(np.sum((g > r + 15) & (g > b + 15) & (g > 100)))
        logger.info(f'[渠道悬浮球] 绿色标志像素 {green}')
        return green >= CHANNEL_FLOAT_GREEN_THRESHOLD

    def _dialog_visible(self) -> bool:
        """「隐藏悬浮球」对话框是否已弹出。

        对话框出现时「隐藏」按钮区域为浅色底（接近白色），
        游戏画面中该区域为深色画面，通过平均亮度即可区分。

        Returns:
            bool: True 表示对话框已弹出。
        """
        color = get_color(self.device.image, (728, 604, 848, 664))
        mean = sum(color) / len(color)
        return mean > 150

    def handle_channel_float(self) -> bool:
        """拖拽悬浮球到屏幕中下，并在「隐藏」对话框弹出后点击「隐藏」。

        Returns:
            bool: 固定返回 True，表示已执行处理。
        """
        logger.info('[渠道悬浮球] 拖拽至屏幕中下')
        self.device.swipe(
            CHANNEL_FLOAT_SWIPE_START, CHANNEL_FLOAT_SWIPE_END,
            duration=CHANNEL_FLOAT_SWIPE_DURATION, name='CHANNEL_FLOAT_SWIPE')
        # 等待「隐藏悬浮球」对话框弹出（截图循环，最多等 4 秒）
        dialog_timer = Timer(4)
        while 1:
            self.device.screenshot()
            if self._dialog_visible():
                logger.info('[渠道悬浮球] 点击「隐藏」')
                self.device.click(CHANNEL_FLOAT_HIDE_BUTTON)
                break
            if dialog_timer.reached():
                logger.info('[渠道悬浮球] 未见「隐藏悬浮球」对话框，跳过点击')
                break
        return True

    def run(self) -> bool:
        """任务前的悬浮球检查入口（每个会话仅调用一次）。

        通过绿色标志检测悬浮球；识别到时自动拖拽并点击「隐藏」确认，
        最多尝试 CHANNEL_FLOAT_MAX_ATTEMPTS 次；未识别到悬浮球时不产生
        任何输入操作。

        Returns:
            bool: True 表示本回合检查已消费（无悬浮球或已处理）。
        """
        if not self._enabled():
            return True
        # 仅在主界面检查：游戏重启后需点击进入主界面（调度器登录流程负责），
        # 到达主界面前的回合直接返回 False，等待下一任务回合再试。
        if not self.appear(page_main_white.check_button, offset=(30, 30)):
            logger.info('[渠道悬浮球] 当前不在主界面，等待下一回合')
            return False
        logger.hr('渠道悬浮球检查')
        for _ in range(CHANNEL_FLOAT_MAX_ATTEMPTS):
            self.device.screenshot()
            if not self.detected():
                logger.info('[渠道悬浮球] 未识别到悬浮球，跳过')
                return True
            self.handle_channel_float()
        logger.info('[渠道悬浮球] 多次处理仍未消失，跳过本回合')
        return True
