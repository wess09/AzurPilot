# 基于原版 login.py 增加了智能的游戏重启逻辑
# 用于处理登录流程中的各种弹窗、公告以及在应用崩溃时执行重启恢复操作。
# 最后更新: 2025-08-25 20:41
import numpy as np
from scipy.signal import find_peaks
# 在导入 adbutils 和 uiautomator2 之前修补 pkg_resources
from module.device.pkg_resources import get_distribution
from uiautomator2 import UiObject
from uiautomator2.exceptions import XPathElementNotFoundError
from uiautomator2.xpath import XPath, XPathSelector

_ = get_distribution

import module.config.server as server
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, crop
from module.handler.assets import *
from module.logger import logger
from module.map.assets import *
from module.ui.assets import *
from module.ui.page import page_campaign_menu
from module.ui.ui import UI


class LoginHandler(UI):
    def _handle_app_login(self):
        """
        Pages:
            in: 任意页面
            out: page_main

        Raises:
            GameStuckError: 游戏卡死。
            GameTooManyClickError: 点击次数过多。
            GameNotRunningError: 游戏未运行。
        """
        logger.hr('App login')

        confirm_timer = Timer(1.5, count=4).start()
        orientation_timer = Timer(5)
        login_success = False
        self.device.stuck_record_clear()
        self.device.click_record_clear()

        while 1:
            # 监测设备屏幕旋转
            if not login_success and orientation_timer.reached():
                # 启动应用后屏幕可能会旋转
                self.device.get_orientation()
                orientation_timer.reset()

            self.device.screenshot()

            # 结束条件
            if self.is_in_main():
                if confirm_timer.reached():
                    logger.info('Login to main confirm')
                    break
            else:
                confirm_timer.reset()

            # 登录处理
            if self.match_template_color(LOGIN_CHECK, offset=(30, 30), interval=5):
                self.device.click(LOGIN_CHECK)
                if not login_success:
                    logger.info('Login success')
                    login_success = True
            if self.appear(ANDROID_NO_RESPOND, offset=(30, 30), interval=5):
                logger.warning('Emulator no respond')
                self.device.click_record_add(ANDROID_NO_RESPOND)
                self.device.click_record_check()
                self.device.click(ANDROID_NO_RESPOND, control_check=False)
                continue
            if self.appear_then_click(LOGIN_ANNOUNCE, offset=(30, 30), interval=5):
                continue
            if self.appear_then_click(LOGIN_ANNOUNCE_2, offset=(30, 30), interval=5):
                continue
            if self.appear(EVENT_LIST_CHECK, offset=(30, 30), interval=5):
                self.device.click(BACK_ARROW)
                continue
            # 更新和维护
            if self.appear_then_click(MAINTENANCE_ANNOUNCE, offset=(30, 30), interval=5):
                continue
            if self.appear_then_click(LOGIN_GAME_UPDATE, offset=(30, 30), interval=5):
                continue
            if server.server == 'cn' and not login_success:
                if self.handle_cn_user_agreement():
                    continue
            # 回归玩家
            if self.appear_then_click(LOGIN_RETURN_SIGN, offset=(30, 30), interval=5):
                continue
            if self.appear_then_click(LOGIN_RETURN_INFO, offset=(30, 30), interval=5):
                continue
            # 弹窗处理
            if self.handle_popup_confirm('LOGIN'):
                continue
            if self.handle_urgent_commission():
                continue
            # 主界面弹窗
            if self.ui_page_main_popups(get_ship=login_success):
                return True
            # 始终尝试返回主界面
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30), interval=5):
                continue

        return True

    _user_agreement_timer = Timer(1, count=2)

    def handle_cn_user_agreement(self):
        if not self._user_agreement_timer.reached():
            return False

        right = self.image_color_button(
            area=(640, 360, 1280, 720), color=(78, 189, 234),
            color_threshold=245, encourage=25, name='AGREEMENT_CONFIRM')
        if right is None:
            return False
        # 2026.04.17 不再需要滚动，只需在点击确认前简单滑动
        # 如果屏幕右半部分有蓝色按钮而左半部分没有，则为确认按钮
        # 如果两侧都有，则是中间的登录确认按钮
        left = self.image_color_button(
            area=(0, 360, 640, 720), color=(78, 189, 234),
            color_threshold=245, encourage=25, name='AGREEMENT_CONFIRM')
        if left is None:
            # 用户协议
            # 在屏幕中间某处进行滑动
            box = (350, 230, 920, 430)
            self.device.swipe_vector((0, -150), box, name='AGREEMENT_SCROLL')
            self.device.swipe_vector((0, -150), box, name='AGREEMENT_SCROLL')
            self.device.click(right)
            self._user_agreement_timer.reset()
            return True
        else:
            # 用户登录确认
            self.device.click(right)
            self._user_agreement_timer.reset()
            return True

    def handle_app_login(self):
        """
        处理应用登录流程。

        Returns:
            是否登录成功。

        Raises:
            GameStuckError: 游戏卡死。
            GameTooManyClickError: 点击次数过多。
            GameNotRunningError: 游戏未运行。
        """
        logger.info('handle_app_login')
        self.device.screenshot_interval_set(1.0)
        try:
            self._handle_app_login()
        finally:
            self.device.screenshot_interval_set()

    def app_stop(self):
        logger.hr('App stop')
        self.device.app_stop()

    def app_start(self):
        logger.hr('App start')
        self.device.app_start()
        self.handle_app_login()
        # self.ensure_no_unfinished_campaign()

    # def app_restart(self):
    #     logger.hr('App restart')
    #     self.device.app_stop()
    #     self.device.app_start()
    #     self.handle_app_login()
    #     # self.ensure_no_unfinished_campaign()
    #     self.config.task_delay(server_update=True)

    def app_restart(self):
        logger.hr('App restart')
        # 智能的多次尝试重启逻辑
        RESTART_TRIES = 4
        FIRST_TRY_WAIT_SECONDS = 30
        SUBSEQUENT_TRY_WAIT_SECONDS = 20

        is_restart_success = False

        for i in range(RESTART_TRIES):
            logger.info(f"App restart attempt {i + 1}/{RESTART_TRIES}...")
            self.device.app_stop()
            self.device.sleep(3)
            self.device.app_start()
            wait_seconds = FIRST_TRY_WAIT_SECONDS if i == 0 else SUBSEQUENT_TRY_WAIT_SECONDS
            logger.info(f"Waiting {wait_seconds} seconds for app to launch and stabilize...")
            self.device.sleep(wait_seconds)

            # 验证应用是否已运行
            if self.device.app_is_running():
                logger.info(">>> App started successfully and is running.")
                is_restart_success = True
                break  # 成功启动，跳出循环
            else:
                logger.warning(f"Attempt {i + 1} failed. App is not running after launch (likely crashed).")
                if i < RESTART_TRIES - 1:
                    logger.info("Retrying...")
        
        # 所有尝试均失败则抛出异常
        if not is_restart_success:
            logger.critical(f"重试 {RESTART_TRIES} 次了！还是死活起不来，你的运行环境是碳基生物能搞出来的？")
            from module.exception import RequestHumanTakeover
            raise RequestHumanTakeover("App restart failed repeatedly")
        self.handle_app_login()
        # self.ensure_no_unfinished_campaign()

    def ensure_no_unfinished_campaign(self, confirm_wait=3):
        """
        Pages:
            in: page_main
            out: page_main

        确保没有未完成的战役，如有则撤退。
        """

        def ensure_campaign_retreat():
            if self.appear_then_click(WITHDRAW, offset=(30, 30), interval=5):
                return True
            if self.handle_popup_confirm('WITHDRAW'):
                return True

        def in_campaign():
            return self.appear(CAMPAIGN_CHECK, offset=(30, 30)) \
                   or self.appear(CAMPAIGN_MENU_CHECK, offset=(30, 30)) \
                   or self.appear(EVENT_CHECK, offset=(30, 30)) \
                   or self.appear(SP_CHECK, offset=(30, 30))

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件
            if in_campaign():
                break

            # 点击操作
            if self.ui_main_appear_then_click(page_campaign_menu, interval=3):
                continue
            if ensure_campaign_retreat():
                continue

        self.ui_goto_main()

    def handle_user_agreement(self, xp, hierarchy):
        """
        处理用户协议弹窗（仅限国服）。

        国服客户端存在 bug，用户协议和隐私政策可能在已同意后再次弹出。
        此方法滑动到底部并点击同意按钮。

        Returns:
            是否处理了用户协议弹窗。
        """

        if server.server == 'cn':
            area_wait_results = self.get_for_any_ele([
                XPS('//*[@text="sdk协议"]', xp, hierarchy),
                XPS('//*[@content-desc="sdk协议"]', xp, hierarchy)])
            if area_wait_results is False:
                return False
            agree_wait_results = self.get_for_any_ele([
                XPS('//*[@text="同意"]', xp, hierarchy),
                XPS('//*[@content-desc="同意"]', xp, hierarchy)])
            start_padding_results = self.get_for_any_ele([
                XPS('//*[@text="隐私政策"]', xp, hierarchy), XPS('//*[@content-desc="隐私政策"]', xp, hierarchy),
                XPS('//*[@text="用户协议"]', xp, hierarchy), XPS('//*[@content-desc="用户协议"]', xp, hierarchy)])
            start_margin_results = self.get_for_any_ele([
                XPS('//*[@text="请滑动阅读协议内容"]', xp, hierarchy),
                XPS('//*[@content-desc="请滑动阅读协议内容"]', xp, hierarchy)])

            test_image_original = self.device.image
            image_handle_crop = crop(
                test_image_original, (start_padding_results[2], 0, start_margin_results[2], 720), copy=False)
            # Image.fromarray(image_handle_crop).show()
            sims = color_similarity_2d(image_handle_crop, color=(182, 189, 202))
            points = np.sum(sims >= 255)
            if points == 0:
                return False
            sims_height = np.mean(sims, axis=1)
            # pyplot.plot(sims_height, color='r')
            # pyplot.show()
            peaks, __ = find_peaks(sims_height, height=225)
            if len(peaks) == 2:
                peaks = (peaks[0] + peaks[1]) / 2
            start_pos = [(start_padding_results[2] + start_margin_results[2]) / 2, float(peaks)]
            end_pos = [(start_padding_results[2] + start_margin_results[2]) / 2, area_wait_results[3]]
            logger.info("user agreement position find result: " + ', '.join(f'{pos:.2f}' for pos in start_pos))
            logger.info("user agreement area expect:          " + 'x:963-973, y:259-279')

            self.device.drag(start_pos, end_pos, segments=2, shake=(0, 25), point_random=(0, 0, 0, 0),
                             shake_random=(0, -5, 0, 5))
            AGREE = Button(area=agree_wait_results, color=(), button=agree_wait_results, name='AGREE')
            self.device.click(AGREE)
            return True

    def handle_user_login(self, xp, hierarchy) -> bool:
        """处理用户登录按钮点击。"""
        login_wait_results = self.get_for_any_ele([
            XPS('//*[@text="登录"]', xp, hierarchy),
            XPS('//*[@content-desc="登录"]', xp, hierarchy)])
        if login_wait_results is False:
            return False
        else:
            USER_LOGIN_BTN = Button(area=login_wait_results, color=(), button=login_wait_results, name='USER_LOGIN_BTN')
            self.device.click(USER_LOGIN_BTN)
            return True

    @staticmethod
    def get_for_any_ele(list_u2_path: list) -> bool | tuple:
        """
        从候选 XPath 或 UiObject 列表中查找第一个存在的元素。

        Args:
            list_u2_path: UiObject 或 XPathSelector 的列表，长度 >= 1。

        Returns:
            False 表示未找到元素，tuple 表示找到的元素边界。
        """
        for path in list_u2_path:
            try:
                if isinstance(path, UiObject):
                    if path.exists():
                        return path.bounds()
                    elif not path.exists():
                        continue
                elif isinstance(path, XPathSelector):
                    if path.exists:
                        return path.bounds
                    elif not path.exists:
                        continue
            except XPathElementNotFoundError:
                continue
        return False

    def get_cn_xp_hierarchy(self) -> tuple:
        d = self.device.u2
        xp = XPath(d)
        hierarchy = d.dump_hierarchy()
        return xp, hierarchy


class XPS(XPathSelector):
    def __init__(self, xpath, parent, source):
        super().__init__(parent, xpath, source)
