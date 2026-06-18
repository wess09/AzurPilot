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
        """判断是否为文件类目标。"""
        return not isinstance(DIC_OS_TARGET[zone][index], bool)

    def is_safe(self, zone, index):
        """判断是否为安全目标。"""
        return DIC_OS_TARGET[zone][index] == True

class OSTargetHandler(OSTarget, Combat, UI):
    def _receive_reward_all(self, skip_first_screenshot=True):
        """
        领取所有目标奖励（如果有两个或更多）。

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
                
            # End
            if not self.image_color_count(TARGET_RECEIVE_ALL, color=(230, 187, 67), threshold=220, count=400):
                if confirm_timer.reached():
                    break

        return received
    
    def find_unreceived_zone(self, skip_first_screenshot=True):
        """
        切换到有奖励的海域（如果只有一个需要领取）。

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
        """
        领取单个目标奖励。

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

            # End
            if not self.image_color_count(TARGET_RECEIVE_SINGLE, color=(76, 117, 184), threshold=220, count=400):
                if confirm_timer.reached():
                    break
        
        return received

    def receive_reward(self):
        """
        领取目标奖励。

        Returns:
            bool: 是否领取成功。
        """
        logger.hr('OS Achievement Reward Receive', level=2)
        TARGET_SWITCH.set('all', main=self)
        received = False
        if self.appear(TARGET_RECEIVE_ALL):
            received = self._receive_reward_all()
        elif self.find_unreceived_zone():
            received = self._receive_reward_single()
        if received:
            logger.info(f'Opsi achievement reward collection received')
        else:
            logger.info(f'No Opsi achievement reward available')
        return received
    
    def _is_finished(self, area):
        return self.image_color_count(area, color=(255, 239, 156), threshold=221, count=100)
    
    def _star_grid(self):
        return ButtonGrid(
            origin=(665, 405),
            delta=(32, 41),
            button_shape=(32, 30),
            grid_shape=(1, 5)
        )
    
    def scan_current_zone(self):
        """
        扫描当前海域信息。

        Returns:
            zone_id: 海域 ID。
            finished: 完成状态列表。
        """
        zone_id = ZONE_ID.ocr(self.device.image)
        finished = [self._is_finished(button.area) for button in self._star_grid().buttons]
        logger.info(f'Zone {zone_id} target progress: {str(finished)}')
        return zone_id, finished

    def find_unfinished_safe_star_zone(self, skip_first_screenshot=True):
        """
        通过搜索未完成的海域，查找有未完成安全星标的海域。

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
                            logger.info(f'No. {index+1} of Zone {zone_id} is a file target, skipped.')
                            continue
                        elif self.is_safe(zone_id, index):
                            logger.info(f'No. {index+1} of Zone {zone_id} is safe for MeowfficerFarming.')
                            return zone_id
                        else:
                            logger.info(f"No. {index+1} of Zone {zone_id} can only be done in danger zone, skipped.")
                            continue
            if self.appear(TARGET_NEXT_ZONE):
                self.device.click(TARGET_NEXT_ZONE)
                # 可能点击超过 15 次
                self.device.click_record.pop()
                info_timer.reset()
                continue
            else:
                logger.info(f'All remaining stars can only be finished in danger zone.')
                return 0

    def run(self):
        TARGET_SWITCH.set('unfinished', main=self)
        zone = self.find_unfinished_safe_star_zone()
        with self.config.multi_set():
            if zone == 0:
                logger.info('Disable Safe Target Farming')
                self.config.OpsiTarget_TargetZone = 0
                self.config.OpsiTarget_TargetFarming = False
            else:
                logger.info(f'Successfully found safe target zone, zone_id={zone}')
                self.config.OpsiTarget_TargetZone = zone
        TARGET_SWITCH.set('all', main=self)
            
