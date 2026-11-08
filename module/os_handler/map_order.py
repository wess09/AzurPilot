"""大世界地图指令处理器。

管理大世界地图中的指令操作（如进入海域、移动舰队等），
继承地图操作、行动力处理器和地图事件处理器。提供指令
面板的进入/退出检测、海域颜色分析以判断海域状态等。
"""
import numpy as np

from module.base.timer import Timer
from module.base.utils import color_similarity_2d
from module.logger import logger
from module.map.assets import MAP_CAT_ATTACK
from module.map.map_operation import MapOperation
from module.os.globe_zone import ZoneManager
from module.os_handler.action_point import ActionPointHandler
from module.os_handler.assets import *
from module.os_handler.map_event import MapEventHandler


class MapOrderHandler(MapOperation, ActionPointHandler, MapEventHandler, ZoneManager):
    """大世界地图指令处理器，管理大世界地图中的指令面板操作。"""

    def is_in_map_order(self):
        """
        判断当前是否处于地图指令面板中。

        Returns:
            bool: 处于地图指令面板返回 True。
        """
        return self.appear(ORDER_CHECK, offset=(20, 20))

    def order_enter(self):
        """
        打开大世界地图指令面板。

        Pages:
            in: is_in_map
            out: is_in_map_order
        """
        logger.info('进入指令')
        for _ in self.loop():
            # 结束
            if self.is_in_map_order():
                break

            if self.is_in_map():
                if self.appear_then_click(ORDER_ENTER, offset=(20, 20), interval=2):
                    continue
            # 游戏偶尔出现上一次通关弹窗 AUTO_SEARCH_REWARD 延迟弹出的 Bug
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
            # 若玩家未正确配置游戏设置，跳过 TB 引导
            if self.handle_map_event():
                continue

    def order_quit(self):
        """
        退出大世界地图指令面板，返回地图。

        Pages:
            in: is_in_map_order
            out: is_in_map
        """
        logger.info('退出指令')
        self.ui_click(ORDER_CHECK, appear_button=self.is_in_map_order, check_button=self.is_in_map,
                      skip_first_screenshot=True)

    def order_execute(self, button):
        """
        执行指定的地图指令按钮。

        Args:
            button (Button): 导航指令面板中的功能按钮。

        Returns:
            bool: 是否成功执行该指令。

        Pages:
            in: is_in_map
            out: is_in_map
        """
        logger.hr(button)
        self.order_enter()

        missing_timer = Timer(1, count=3).start()
        confirm_timer = Timer(1.2, count=4).start()
        assume_zone = self.name_to_zone(11)

        for _ in self.loop():
            # 结束
            if self.is_in_map():
                if confirm_timer.reached():
                    return True
            else:
                confirm_timer.reset()

            if self.is_in_map_order() and not self.appear(button):
                if missing_timer.reached():
                    logger.info(f'[大世界处理-指令] 地图指令不可用: {button}')
                    self.order_quit()
                    return False
            else:
                missing_timer.reset()

            if self.appear_then_click(button, interval=3):
                continue
            if self.handle_popup_confirm(button.name):
                continue
            if self.handle_map_event():
                continue
            if self.handle_map_cat_attack():
                continue
            if self.handle_action_point(zone=assume_zone, pinned='OBSCURE'):
                # 点击行动力取消后，游戏会关闭指令面板而非停留在原处，
                # 因此需要重新进入指令面板并重新执行指令。
                self.order_enter()
                confirm_timer.reset()
                missing_timer.reset()
                continue

    def wait_until_order_finished(self):
        """等待地图指令（如潜艇支援打击）执行动画播放完毕。"""
        for _ in self.loop():
            # 结束
            if self.is_in_map() and self.appear(ORDER_ENTER, offset=(20, 20)):
                break

            if self.handle_map_event():
                continue
            if self.handle_map_cat_attack():
                continue

    def os_order_execute(self, recon_scan=True, submarine_call=True):
        """
        执行大世界导航指令（侦察扫描与潜艇支援）。

        侦察扫描冷却时间为 30 分钟，潜艇支援冷却时间为 60 分钟。
        处于冷却期内调用会额外消耗行动力（侦察最多 10 点，潜艇最多 39 点）。

        Args:
            recon_scan (bool): 是否执行侦察扫描。
            submarine_call (bool): 是否呼叫潜艇支援。

        Pages:
            in: is_in_map
            out: is_in_map
        """
        # backup = self.config.cover(OS_ACTION_POINT_PRESERVE=0, OS_ACTION_POINT_BOX_USE=True)

        if recon_scan:
            recon_scan = self.order_execute(ORDER_SCAN)
        if submarine_call:
            submarine_call = self.order_execute(ORDER_SUBMARINE)
            if submarine_call:
                self.wait_until_order_finished()

        self.config.opsi_task_delay(recon_scan=recon_scan, submarine_call=submarine_call)

        # backup.recover()

    def handle_map_cat_attack(self):
        """
        点击安全区域跳过指挥猫打击动画。

        在大世界中覆盖该方法，因为标准按钮位置与大世界海域退出按钮重叠。

        Returns:
            bool: 是否检测到并跳过了指挥猫打击。
        """
        if not self.map_cat_attack_timer.reached():
            return False
        if np.sum(color_similarity_2d(self.image_crop(MAP_CAT_ATTACK, copy=False), (255, 231, 123)) > 221) > 100:
            logger.info('跳过地图指挥喵攻击')
            self.device.click(CLICK_SAFE_AREA)
            self.map_cat_attack_timer.reset()
            return True

        return False
