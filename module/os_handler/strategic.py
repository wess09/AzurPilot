"""大世界战略搜索处理器。

管理大世界战略搜索（Strategic Search）功能的交互流程。
提供战略搜索面板的进入、标签页切换（已净化/未净化）、
搜索选项勾选、确认弹窗处理以及滚动条控制等操作。
"""
from module.base.utils import get_color
from module.logger import logger
from module.os_handler.assets import *
from module.os_handler.map_event import MapEventHandler
from module.ui.scroll import Scroll

STRATEGIC_SEARCH_SCROLL = Scroll(STRATEGIC_SEARCH_SCROLL_AREA, color=(247, 211, 66), name='STRATEGIC_SEARCH_SCROLL')


class StrategicSearchHandler(MapEventHandler):
    def strategy_search_enter(self):
        logger.info('[大世界-策略] 进入策略搜索')
        self.interval_clear(STRATEGIC_SEARCH_MAP_OPTION_OFF)
        for _ in self.loop():
            # End
            if self.appear(STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20)):
                return True

            if self.handle_map_event():
                continue
            if self.appear(AUTO_SEARCH_REWARD, offset=(50, 50)):
                continue
            if self.match_template_color(STRATEGIC_SEARCH_MAP_OPTION_OFF, offset=(20, 20), interval=2):
                self.device.click(STRATEGIC_SEARCH_MAP_OPTION_OFF)
                continue

    def strategic_search_set_tab(self):
        logger.info('[大世界-策略] 设置策略搜索标签')
        for _ in self.loop():
            if get_color(self.device.image, STRATEGIC_SEARCH_TAB_SECURED.area)[2] <= 150:
                self.device.click(STRATEGIC_SEARCH_TAB_SECURED)
                continue
            if get_color(self.device.image, STRATEGIC_SEARCH_TAB_SECURED.area)[2] > 150:
                break

    def _strategy_search_scroll_appear(self):
        """
        检查策略搜索界面的滚动条是否仍然存在。

        Returns:
            bool: 滚动条存在返回 True，已消失返回 False。
        """
        for _ in self.loop(timeout=2):
            if STRATEGIC_SEARCH_SCROLL.appear(main=self):
                return True
            else:
                logger.warning('[大世界-策略] 策略搜索滚动条消失')
        else:
            logger.warning('[大世界-策略] 策略搜索滚动条消失确认')
            return False

    def _strategy_option_selected(self, button):
        """
        检查指定选项按钮是否处于已勾选激活状态。

        Args:
            button: 选项按钮资源。

        Returns:
            bool: 按钮被选中返回 True。
        """
        return self.image_color_count(button.button, color=(156, 255, 82), count=30)

    def strategic_search_set_option(self):
        """
        配置策略搜索选项（重复区域模式、遭遇商人停止、遭遇装置停止、自动提交任务等）。

        Returns:
            bool: 配置是否成功，若因未知原因弹窗意外关闭则返回 False。
        """
        logger.info('[大世界-策略] 设置策略搜索选项')
        is_jp = self.config.SERVER == 'jp'
        if is_jp:
            # 日服选项文本换行：先确保区域模式与商人选项在同一个可见范围。
            STRATEGIC_SEARCH_SCROLL.drag_threshold = 0.01
            STRATEGIC_SEARCH_SCROLL.set(0.17, main=self, random_range=(-0.01, 0.01), distance_check=False)
            if not self._strategy_search_scroll_appear():
                return False

        for _ in self.loop():
            if is_jp:
                if not self.appear(STRATEGIC_SEARCH_MERCHANT_CHECK, offset=(20, 100)):
                    continue
                for button in (STRATEGIC_SEARCH_ZONEMODE_REPEAT, STRATEGIC_SEARCH_ZONEMODE_RANDOM,
                               STRATEGIC_SEARCH_MERCHANT_STOP, STRATEGIC_SEARCH_MERCHANT_CONTINUE):
                    button.load_offset(STRATEGIC_SEARCH_MERCHANT_CHECK)

            if self._strategy_option_selected(STRATEGIC_SEARCH_ZONEMODE_REPEAT) \
                    and self._strategy_option_selected(STRATEGIC_SEARCH_MERCHANT_STOP):
                logger.attr('区域模式', '重复')
                logger.attr('遭遇商人', '停止')
                break
            if self._strategy_option_selected(STRATEGIC_SEARCH_ZONEMODE_RANDOM):
                logger.attr('区域模式', '随机')
                self.device.click(STRATEGIC_SEARCH_ZONEMODE_REPEAT)
                continue
            if self._strategy_option_selected(STRATEGIC_SEARCH_MERCHANT_CONTINUE):
                logger.attr('遭遇商人', '继续')
                self.device.click(STRATEGIC_SEARCH_MERCHANT_STOP)
                continue

        STRATEGIC_SEARCH_SCROLL.drag_threshold = 0.1
        STRATEGIC_SEARCH_SCROLL.set(0.5, main=self)
        if not self._strategy_search_scroll_appear():
            return False

        for _ in self.loop():
            self.appear(STRATEGIC_SEARCH_DEVICE_CHECK, offset=(20, 200), similarity=0.7)
            STRATEGIC_SEARCH_DEVICE_STOP.load_offset(STRATEGIC_SEARCH_DEVICE_CHECK)
            STRATEGIC_SEARCH_DEVICE_CONTINUE.load_offset(STRATEGIC_SEARCH_DEVICE_CHECK)

            if self._strategy_option_selected(STRATEGIC_SEARCH_DEVICE_STOP):
                logger.attr('遭遇装置', '停止')
                break
            if self._strategy_option_selected(STRATEGIC_SEARCH_DEVICE_CONTINUE):
                logger.attr('遭遇装置', '继续')
                self.device.click(STRATEGIC_SEARCH_DEVICE_STOP)
                continue

        STRATEGIC_SEARCH_SCROLL.drag_threshold = 0.05
        STRATEGIC_SEARCH_SCROLL.edge_add = (0.5, 0.8)
        STRATEGIC_SEARCH_SCROLL.set_bottom(main=self)
        if not self._strategy_search_scroll_appear():
            return False

        for _ in self.loop():
            self.appear(STRATEGIC_SEARCH_SUBMIT_CHECK, offset=(20, 20), similarity=0.7)
            STRATEGIC_SEARCH_SUBMIT_OFF.load_offset(STRATEGIC_SEARCH_SUBMIT_CHECK)
            STRATEGIC_SEARCH_SUBMIT_ON.load_offset(STRATEGIC_SEARCH_SUBMIT_CHECK)

            if self._strategy_option_selected(STRATEGIC_SEARCH_SUBMIT_ON):
                logger.attr('自动提交', '开启')
                break
            if self._strategy_option_selected(STRATEGIC_SEARCH_SUBMIT_OFF):
                logger.attr('自动提交', '关闭')
                self.device.click(STRATEGIC_SEARCH_SUBMIT_ON)
                continue

        return True

    def strategic_search_confirm(self):
        """确认并开始执行策略搜索。"""
        logger.info('[大世界-策略] 策略搜索确认')
        confirmed = False
        for _ in self.loop():
            if self.appear(STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20)) \
                    and self.handle_popup_confirm(offset=(30, 30), name='STRATEGIC_SEARCH'):
                confirmed = True
                continue
            # 计划作战确认后可能继续弹出指挥喵召回等确认框，处理后等待新截图。
            if confirmed and self.handle_popup_confirm(offset=(30, 30), name='STRATEGIC_SEARCH_MEOWFFICER'):
                continue
            if self.is_in_map():
                return True

    def strategic_search_start(self, skip_first_screenshot=True):
        """
        启动大世界连续策略搜索。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否启动成功。

        Pages:
            in: IN_MAP
            out: IN_MAP（策略搜索已在运行中）
        """
        logger.hr('策略搜索开始')
        # 快速模式（侵蚀1练级·跳过计划作战滑动检查）：面板会保留上一次的
        # 选项配置，循环刷取时每次重新滑动检查各选项属于重复动作，直接确认开始。
        skip_check = self.config.cross_get(
            'OpsiHazard1Leveling.OpsiHazard1Leveling.SkipStrategicSearchCheck', False,
        )
        if skip_check:
            logger.info('[大世界-策略] 已开启快速模式，跳过计划作战面板选项检查')
        for _ in range(3):
            self.strategy_search_enter()
            self.strategic_search_set_tab()
            if not skip_check:
                success = self.strategic_search_set_option()
                if not success:
                    continue
            if self.strategic_search_confirm():
                return True

        logger.warning('[大世界-策略] 策略搜索启动失败')
        return False
