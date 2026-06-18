from module.base.timer import Timer
from module.logger import logger
from module.os_handler.assets import *
from module.os_shop.assets import PORT_SUPPLY_CHECK
from module.os_shop.shop import OSShop
from module.ui.assets import BACK_ARROW

# 碧蓝航线港口有 PORT_GOTO_MISSION、PORT_GOTO_SUPPLY、PORT_GOTO_DOCK
# 红轴港口有 PORT_GOTO_SUPPLY
# 使用 PORT_GOTO_SUPPLY 作为检查器
PORT_CHECK = PORT_GOTO_SUPPLY


class PortHandler(OSShop):
    def port_enter(self):
        """
        进入港口。

        Pages:
            in: IN_MAP
            out: PORT_CHECK
        """
        logger.info('Port enter')
        for _ in self.loop():
            if self.appear(PORT_CHECK, offset=(20, 20)):
                break
            if self.appear_then_click(PORT_ENTER, offset=(20, 20), interval=5):
                continue
            if self.handle_map_event():
                continue
        # 底部按钮有显示动画
        pass  # 已在 ui_click 中确保

    def port_quit(self, skip_first_screenshot=True):
        """
        退出港口。

        Pages:
            in: PORT_CHECK
            out: IN_MAP
        """
        logger.info('Port quit')
        self.ui_back(appear_button=PORT_CHECK, check_button=self.is_in_map,
                     skip_first_screenshot=skip_first_screenshot)
        # 底部按钮有显示动画
        self.wait_os_map_buttons()

    def port_mission_accept(self):
        """
        接受港口中的所有任务。

        自 2022.01.13 起已弃用，任务仅在总览中显示，不再在港口中显示。

        Returns:
            bool: 所有任务已接受或未找到任务时返回 True，无法接受更多任务时返回 False。

        Pages:
            in: PORT_CHECK
            out: PORT_CHECK
        """
        if not self.appear(PORT_MISSION_RED_DOT):
            logger.info('No available missions in this port')
            return True

        self.ui_click(PORT_GOTO_MISSION, appear_button=PORT_CHECK, check_button=PORT_MISSION_CHECK,
                      skip_first_screenshot=True)

        confirm_timer = Timer(1.5, count=3).start()
        success = True
        for _ in self.loop():
            if self.appear_then_click(PORT_MISSION_ACCEPT, offset=(20, 20), interval=0.2):
                confirm_timer.reset()
                continue
            else:
                # 结束
                if confirm_timer.reached():
                    success = True
                    break

            if self.info_bar_count():
                logger.info('Unable to accept missions, because reached the maximum number of missions')
                success = False
                break

        self.ui_back(appear_button=PORT_MISSION_CHECK, check_button=PORT_CHECK, skip_first_screenshot=True)
        return success

    def port_shop_enter(self):
        """
        进入港口商店。

        Pages:
            in: PORT_CHECK
            out: PORT_SUPPLY_CHECK
        """
        self.ui_click(PORT_GOTO_SUPPLY, appear_button=PORT_CHECK, check_button=PORT_SUPPLY_CHECK,
                      skip_first_screenshot=True)
        # 港口物品有显示动画
        self.device.sleep(0.5)
        self.device.screenshot()

    def port_shop_quit(self, skip_first_screenshot=True):
        """
        退出港口商店。

        Pages:
            in: PORT_SUPPLY_CHECK
            out: PORT_CHECK
        """
        logger.info('Port shop quit')
        
        self.interval_clear([PORT_SUPPLY_CHECK, PORT_CHECK, ORDER_CHECK])
        
        # 超时保护：Timer(10, count=30) 限制最多 10 秒 / 30 次 reached() 调用
        timeout = Timer(10, count=30).start()
        order_quit_used = False
        
        while True:
            # 超时保护：同时满足时间超过 10 秒且 reached() 调用超过 30 次
            if timeout.reached():
                logger.warning('port_shop_quit timeout, trying fallback ui_back')
                self.ui_back(appear_button=PORT_SUPPLY_CHECK, check_button=PORT_CHECK, skip_first_screenshot=True)
                break
            
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 成功返回到港口界面
            if self.appear(PORT_CHECK, offset=(20, 20)):
                logger.info('Arrive PORT_CHECK')
                break

            # 意外进入情报界面（作战总览），用 order_quit 正确关闭
            if self.appear(ORDER_CHECK, offset=(20, 20)):
                logger.warning('Unexpected enter order page, executing order_quit')
                self.order_quit()
                order_quit_used = True
                self.interval_clear([PORT_SUPPLY_CHECK, PORT_CHECK, ORDER_CHECK])
                timeout.reset()
                continue

            # 从情报界面退出后可能落在大地图，重新进入港口
            if order_quit_used and self.is_in_map():
                logger.info('On map after order_quit, re-entering port')
                self.port_enter()
                order_quit_used = False
                self.interval_reset(PORT_CHECK)
                continue

            # 正常点击返回箭头
            if self.appear(PORT_SUPPLY_CHECK, offset=(20, 20), interval=3):
                self.device.click(BACK_ARROW)
                self.interval_reset(PORT_SUPPLY_CHECK)
                continue

    def port_dock_repair(self):
        """
        修复所有舰船。

        Pages:
            in: PORT_CHECK
            out: PORT_CHECK
        """
        self.ui_click(PORT_GOTO_DOCK, appear_button=PORT_CHECK, check_button=PORT_DOCK_CHECK,
                      skip_first_screenshot=True)

        repaired = False
        for _ in self.loop():
            # 结束
            if self.info_bar_count():
                break
            if repaired and self.appear(PORT_DOCK_CHECK, offset=(20, 20)):
                break

            # PORT_DOCK_CHECK 是全部修复按钮
            if self.appear_then_click(PORT_DOCK_CHECK, offset=(20, 20), interval=2):
                continue
            if self.handle_popup_confirm('DOCK_REPAIR'):
                repaired = True
                continue

        self.ui_back(appear_button=PORT_DOCK_CHECK, check_button=PORT_CHECK, skip_first_screenshot=True)
