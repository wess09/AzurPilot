"""大世界目标系统处理器。

管理大世界目标面板的交互，包括目标筛选（全部/未完成）、
目标浏览（上一个/下一个）、奖励领取（单个/全部）以及
目标区域 ID 的 OCR 识别，用于判断海域的目标完成状态。
"""
from module.base.timer import Timer
from module.base.button import *
from module.combat.combat import Combat
from module.logger import logger
from module.ocr.ocr import Digit
from module.os_handler.assets import (
    OCR_TARGET_ZONE_ID, TARGET_ENTER, 
    TARGET_ALL_OFF, TARGET_ALL_ON, TARGET_UNFINISHED_OFF, TARGET_UNFINISHED_ON, 
    TARGET_NEXT_REWARD, TARGET_NEXT_ZONE, TARGET_PREVIOUS_REWARD, TARGET_PREVIOUS_ZONE, 
    TARGET_RECEIVE_ALL, TARGET_RECEIVE_SINGLE, TARGET_RED_DOT
)
from module.os_handler.target_data import DIC_OS_TARGET
from module.ui.switch import Switch
from module.ui.ui import UI


TARGET_SWITCH = Switch('Opsi_Target_switch', is_selector=True)
TARGET_SWITCH.add_state('all', TARGET_ALL_ON)
TARGET_SWITCH.add_state('unfinished', TARGET_UNFINISHED_ON)
ZONE_ID = Digit(OCR_TARGET_ZONE_ID, name='TARGET_ZONE_ID')

class OSTarget:
    """大世界目标数据。"""

    def is_file(self, zone, index):
        """判断指定海域的目标项是否为档案文件类目标。

        Args:
            zone (int): 海域 ID。
            index (int): 目标项索引。

        Returns:
            bool: 是否为文件类目标。
        """
        return not isinstance(DIC_OS_TARGET[zone][index], bool)

    def is_safe(self, zone, index):
        """判断指定海域的目标项是否可在安全海域完成。

        Args:
            zone (int): 海域 ID。
            index (int): 目标项索引。

        Returns:
            bool: 是否可在安全海域完成。
        """
        return DIC_OS_TARGET[zone][index] == True


class OSTargetHandler(OSTarget, Combat, UI):
    """大世界目标面板处理器。"""

    def _receive_reward_all(self, skip_first_screenshot=True):
        """领取所有目标奖励（如果有两个或更多）。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否领取成功。
        """
        confirm_timer = Timer(1, count=3).start()
        received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(TARGET_RECEIVE_ALL, offset=(10, 10), interval=3):
                confirm_timer.reset()
                continue
            if self.handle_popup_confirm('RECEIVE_ALL'):
                confirm_timer.reset()
                continue
            if self.handle_get_items():
                received = True
                confirm_timer.reset()
                continue
                
            # 结束
            if not self.image_color_count(TARGET_RECEIVE_ALL, color=(230, 187, 67), threshold=35, count=400):
                if confirm_timer.reached():
                    break

        return received
    
    def find_unreceived_zone(self, skip_first_screenshot=True):
        """切换到有奖励待领取的单项海域。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否找到。
        """
        # 确保在所有海域列表中
        TARGET_SWITCH.set('all', main=self)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束
            if self.appear(TARGET_RECEIVE_SINGLE):
                return True

            if not self.appear(TARGET_PREVIOUS_REWARD) and not self.appear(TARGET_NEXT_REWARD):
                return False

            if self.appear_then_click(TARGET_NEXT_REWARD, offset=(10, 10), interval=2):
                continue
            if self.appear_then_click(TARGET_PREVIOUS_REWARD, offset=(10, 10), interval=2):
                continue
                     
    def _receive_reward_single(self, skip_first_screenshot=True):
        """领取单个目标奖励。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否领取成功。
        """
        confirm_timer = Timer(1, count=3).start()
        received = False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            
            if self.handle_get_items():
                received = True
                confirm_timer.reset()
                continue
            if self.appear_then_click(TARGET_RECEIVE_SINGLE, offset=(10, 10), interval=3):
                confirm_timer.reset()
                continue

            # 结束
            if not self.image_color_count(TARGET_RECEIVE_SINGLE, color=(76, 117, 184), threshold=35, count=400):
                if confirm_timer.reached():
                    break
        
        return received

    def receive_reward(self):
        """领取目标奖励。

        Returns:
            bool: 是否领取成功。
        """
        logger.hr('大世界目标奖励领取', level=2)
        TARGET_SWITCH.set('all', main=self)
        received = False
        if self.appear(TARGET_RECEIVE_ALL):
            received = self._receive_reward_all()
        elif self.find_unreceived_zone():
            received = self._receive_reward_single()
        if received:
            logger.info(f'大世界目标奖励已领取')
        else:
            logger.info(f'无大世界目标奖励可用')
        return received
    
    def _is_finished(self, area):
        """检查指定星星区域是否已完成（亮黄色）。

        Args:
            area (tuple): 检查区域。

        Returns:
            bool: 是否已完成。
        """
        return self.image_color_count(area, color=(255, 239, 156), threshold=34, count=100)
    
    def _star_grid(self):
        """获取目标面板的五颗星按钮网格。

        Returns:
            ButtonGrid: 五颗星按钮网格。
        """
        return ButtonGrid(
            origin=(665, 405),
            delta=(32, 41),
            button_shape=(32, 30),
            grid_shape=(1, 5)
        )
    
    def scan_current_zone(self):
        """扫描当前海域的目标完成信息。

        Returns:
            tuple[int, list[bool]]: (海域 ID, 5 个星标项的完成状态列表)。
        """
        zone_id = ZONE_ID.ocr(self.device.image)
        finished = [self._is_finished(button.area) for button in self._star_grid().buttons]
        logger.info(f'[大世界处理-目标] 海域 {zone_id} 目标进度: {str(finished)}')
        return zone_id, finished

    def find_unfinished_safe_star_zone(self, skip_first_screenshot=True):
        """通过搜索未完成的海域，查找有未完成安全星标的海域。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            int: 有未完成安全星标的海域 ID，如果不存在则返回 0。
        """
        last_zone = self.config.OpsiTarget_TargetZone
        info_timer = Timer(1)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not info_timer.reached():
                continue

            zone_id, finished = self.scan_current_zone()

            if zone_id >= last_zone:
                for index in range(1, 5):
                    if not finished[index]:
                        if self.is_file(zone_id, index):
                            logger.info(f'[大世界处理-目标] 区域 {zone_id} 第 {index+1} 项是档案目标，跳过')
                            continue
                        elif self.is_safe(zone_id, index):
                            logger.info(f'[大世界处理-目标] 区域 {zone_id} 第 {index+1} 项可在安全海域完成，适合指挥喵搜寻')
                            return zone_id
                        else:
                            logger.info(f"[大世界处理-目标] 区域 {zone_id} 第 {index+1} 项只能在危险区域完成，跳过")
                            continue
            if self.appear(TARGET_NEXT_ZONE):
                self.device.click(TARGET_NEXT_ZONE)
                # 可能点击超过 15 次
                self.device.click_record.pop()
                info_timer.reset()
                continue
            else:
                logger.info(f'所有剩余星星只能在危险区域完成。')
                return 0

    def run(self):
        """执行目标扫描与配置更新主逻辑。"""
        TARGET_SWITCH.set('unfinished', main=self)
        zone = self.find_unfinished_safe_star_zone()
        with self.config.multi_set():
            if zone == 0:
                logger.info('禁用安全目标刷取')
                self.config.OpsiTarget_TargetZone = 0
                self.config.OpsiTarget_TargetFarming = False
            else:
                logger.info(f'成功找到安全目标区域, zone_id={zone}')
                self.config.OpsiTarget_TargetZone = zone
        TARGET_SWITCH.set('all', main=self)
            
