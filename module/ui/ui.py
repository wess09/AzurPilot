from module.base.button import Button
from module.base.decorator import run_once
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP
from module.exception import (GameNotRunningError, GamePageUnknownError,
                              RequestHumanTakeover)
from module.exercise.assets import EXERCISE_PREPARATION
from module.handler.assets import (AUTO_SEARCH_MENU_EXIT, BATTLE_PASS_NEW_SEASON, BATTLE_PASS_NOTICE, GAME_TIPS,
                                   LOGIN_ANNOUNCE, LOGIN_ANNOUNCE_2, LOGIN_CHECK, LOGIN_RETURN_SIGN,
                                   MAINTENANCE_ANNOUNCE, MONTHLY_PASS_NOTICE)
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.assets import (FLEET_PREPARATION, MAP_PREPARATION,
                               MAP_PREPARATION_CANCEL, WITHDRAW)
from module.meowfficer.assets import MEOWFFICER_BUY
from module.ocr.ocr import Ocr
from module.os_handler.assets import (AUTO_SEARCH_REWARD, EXCHANGE_CHECK, RESET_FLEET_PREPARATION, RESET_TICKET_POPUP)
from module.raid.assets import *
from module.ui.assets import *
from module.ui.page import Page, page_academy, page_campaign, page_event, page_main, page_main_white, page_sp
from module.ui_white.assets import *


class UI(InfoHandler):
    ui_current: Page

    def ui_page_appear(self, page, offset=(30, 30), interval=0):
        """
        检测指定页面是否出现在屏幕上。

        Args:
            page (Page): 要检测的页面。
            offset: 匹配偏移量。
            interval: 检测间隔。
        """
        if page == page_main:
            if self.appear(page_main_white.check_button, offset=offset, interval=interval):
                return True
            if self.appear(page_main.check_button, offset=(5, 5), interval=interval):
                return True
            return False
        # 英文本地化导致学院标题字体宽度变化，需要额外检查其他按钮
        if self.config.SERVER == 'en' and page == page_academy:
            if self.appear(ACADEMY_GOTO_MUNITIONS, offset=offset, interval=interval):
                return True
        return self.appear(page.check_button, offset=offset, interval=interval)

    def is_in_main(self, offset=(30, 30), interval=0):
        return self.ui_page_appear(page_main, offset=offset, interval=interval)

    def ui_main_appear_then_click(self, page, offset=(30, 30), interval=3):
        """
        检测主界面是否出现，若出现则点击前往目标页面的按钮。

        Args:
            page: 目标页面。
            offset: 匹配偏移量。
            interval: 检测间隔。

        Returns:
            bool: 是否点击了按钮。
        """
        if self.appear(page_main.check_button, offset=offset, interval=interval):
            button = page_main.links[page]
            self.device.click(button)
            return True
        if self.appear(page_main_white.check_button, offset=(5, 5), interval=interval):
            button = page_main_white.links[page]
            self.device.click(button)
            return True
        return False

    def ensure_button_execute(self, button, offset=0):
        if isinstance(button, Button) and self.appear(button, offset=offset):
            return True
        elif callable(button) and button():
            return True
        else:
            return False

    def ui_click(
            self,
            click_button,
            check_button,
            appear_button=None,
            additional=None,
            confirm_wait=1,
            offset=(30, 30),
            retry_wait=10,
            skip_first_screenshot=False,
    ):
        """
        点击按钮并等待目标画面出现。

        Args:
            click_button (Button): 要点击的按钮。
            check_button (Button, callable): 用于确认页面已切换的检测按钮或回调。
            appear_button (Button, callable): 点击前需先出现的按钮，默认为 click_button。
            additional (callable): 额外的弹窗处理回调。
            confirm_wait (int, float): 确认等待时间（秒）。
            offset (bool, int, tuple): 匹配偏移量。
            retry_wait (int, float): 重试等待时间（秒）。
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        logger.hr("UI click")
        if appear_button is None:
            appear_button = click_button

        click_timer = Timer(retry_wait, count=retry_wait // 0.5)
        confirm_wait = confirm_wait if additional is not None else 0
        confirm_timer = Timer(confirm_wait, count=confirm_wait // 0.5).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_process_check_button(check_button, offset=offset):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

            if click_timer.reached():
                if (isinstance(appear_button, Button) and self.appear(appear_button, offset=offset)) or (
                        callable(appear_button) and appear_button()
                ):
                    self.device.click(click_button)
                    click_timer.reset()
                    continue

            if additional is not None:
                if additional():
                    continue

    def ui_process_check_button(self, check_button, offset=(30, 30)):
        """
        处理检测按钮，支持 Button、callable、列表或元组等多种类型。

        Args:
            check_button (Button, callable, list[Button], tuple[Button]): 检测按钮或回调。
            offset: 匹配偏移量。

        Returns:
            bool: 是否检测到目标。
        """
        if isinstance(check_button, Button):
            return self.appear(check_button, offset=offset)
        elif callable(check_button):
            return check_button()
        elif isinstance(check_button, (list, tuple)):
            for button in check_button:
                if self.appear(button, offset=offset):
                    return True
            return False
        else:
            return self.appear(check_button, offset=offset)

    def ui_get_current_page(self, skip_first_screenshot=True):
        """
        获取当前所在的 UI 页面。

        Args:
            skip_first_screenshot: 是否跳过首次截图。

        Returns:
            Page: 当前页面对象。
        """
        logger.info("UI get current page")

        @run_once
        def app_check():
            if not self.device.app_is_running():
                raise GameNotRunningError("Game not running")

        @run_once
        def minicap_check():
            if self.config.Emulator_ControlMethod == "uiautomator2":
                self.device.uninstall_minicap()

        orientation_timer = Timer(5)

        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # 超时退出
            if timeout.reached():
                break

            # 已知页面检测
            for page in Page.iter_pages():
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.attr("UI", page.name)
                    self.ui_current = page
                    return page

            # 未知页面但可以处理
            logger.info("Unknown ui page")
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.appear_then_click(GOTO_MAIN_WHITE, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.appear_then_click(RPG_HOME, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.ui_additional():
                timeout.reset()
                continue

            app_check()
            minicap_check()
            # 持续检查屏幕旋转
            if orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

        # 未知页面，需要手动切换
        logger.warning("Unknown ui page")
        logger.attr("EMULATOR__SCREENSHOT_METHOD", self.config.Emulator_ScreenshotMethod)
        logger.attr("EMULATOR__CONTROL_METHOD", self.config.Emulator_ControlMethod)
        logger.attr("SERVER", self.config.SERVER)
        logger.warning("Starting from current page is not supported")
        logger.warning(f"Supported page: {[str(page) for page in Page.iter_pages()]}")
        logger.warning('Supported page: Any page with a "HOME" button on the upper-right')
        logger.critical("杂鱼大叔~ 这么大个人了连主界面都进不去吗？噗噗，简直像个迷路的小宝宝❤")
        logger.critical("听好了，笨蛋大叔：要么滚去正常的界面启动，"
                        "要么找个带『一键回港』按钮的界面再求我。你要是连这都找不到，建议直接把号删了止损。")
        logger.critical("看懂了吗？废材？不要再浪费我的算力了，赶紧去改！")
        
        # 未知页面自动重启
        logger.warning("Unknown page detected, try to restart game")
        from module.handler.login import LoginHandler
        login_handler = LoginHandler(config=self.config, device=self.device)
        login_handler.device.app_stop()
        while login_handler.device.app_is_running():
            self.device.sleep(0.5)
        login_handler.device.app_start()
        login_handler.handle_app_login()
        return self.ui_get_current_page(skip_first_screenshot=True)

    def ui_goto(self, destination, get_ship=True, offset=(30, 30), skip_first_screenshot=True):
        """
        导航到目标页面，使用 A* 寻路算法找到最短路径。

        Args:
            destination (Page): 目标页面。
            get_ship: 是否处理获得舰船的弹窗。
            offset: 匹配偏移量。
            skip_first_screenshot: 是否跳过首次截图。
        """
        # 初始化页面连接
        Page.init_connection(destination)
        self.interval_clear(list(Page.iter_check_buttons()))

        logger.hr(f"UI goto {destination}")
        while 1:
            GOTO_MAIN.clear_offset()
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 到达目标页面
            if self.ui_page_appear(page=destination, offset=offset):
                logger.info(f'Page arrive: {destination}')
                break

            # 其他页面：按 A* 路径点击导航
            clicked = False
            for page in Page.iter_pages():
                if page.parent is None or page.check_button is None:
                    continue
                if self.appear(page.check_button, offset=offset, interval=5):
                    logger.info(f'Page switch: {page} -> {page.parent}')
                    button = page.links[page.parent]
                    self.device.click(button)
                    self.ui_button_interval_reset(button)
                    clicked = True
                    break
            if clicked:
                continue

            # 处理额外弹窗
            if self.ui_additional(get_ship=get_ship):
                continue

        # 重置页面连接
        Page.clear_connection()

    def ui_ensure(self, destination, skip_first_screenshot=True):
        """
        确保当前在目标页面，若不在则导航过去。

        Args:
            destination (Page): 目标页面。
            skip_first_screenshot: 是否跳过首次截图。

        Returns:
            bool: 是否发生了页面切换。
        """
        logger.hr("UI ensure")
        self.ui_get_current_page(skip_first_screenshot=skip_first_screenshot)
        if self.ui_current == destination:
            logger.info("Already at %s" % destination)
            return False
        else:
            logger.info("Goto %s" % destination)
            self.ui_goto(destination, skip_first_screenshot=True)
            return True

    def ui_goto_main(self):
        return self.ui_ensure(destination=page_main)

    def ui_goto_campaign(self):
        return self.ui_ensure(destination=page_campaign)

    def ui_goto_event(self):
        return self.ui_ensure(destination=page_event)

    def ui_goto_sp(self):
        return self.ui_ensure(destination=page_sp)

    def ui_ensure_index(
            self,
            index,
            letter,
            next_button,
            prev_button,
            skip_first_screenshot=False,
            fast=True,
            interval=(0.2, 0.3),
    ):
        """
        确保翻页到指定索引位置，通过 OCR 识别当前页码并点击翻页按钮。

        Args:
            index (int): 目标索引。
            letter (Ocr, callable): OCR 识别器或回调函数。
            next_button (Button): 下一页按钮。
            prev_button (Button): 上一页按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。
            fast (bool): 默认为 True。当索引不连续时设为 False。
            interval (tuple, int, float): 两次点击之间的间隔（秒）。
        """
        logger.hr("UI ensure index")
        retry = Timer(1, count=2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if isinstance(letter, Ocr):
                current = letter.ocr(self.device.image)
            else:
                current = letter(self.device.image)

            logger.attr("Index", current)
            diff = index - current
            if diff == 0:
                break

            if retry.reached():
                button = next_button if diff > 0 else prev_button
                if fast:
                    self.device.multi_click(button, n=abs(diff), interval=interval)
                else:
                    self.device.click(button)
                retry.reset()

    def ui_back(self, check_button, appear_button=None, offset=(30, 30), retry_wait=10, skip_first_screenshot=False):
        return self.ui_click(
            click_button=BACK_ARROW,
            check_button=check_button,
            appear_button=appear_button,
            offset=offset,
            retry_wait=retry_wait,
            skip_first_screenshot=skip_first_screenshot,
        )

    _opsi_reset_fleet_preparation_click = 0

    def ui_page_main_popups(self, get_ship=True):
        """
        处理主界面和奖励页面出现的弹窗。

        Args:
            get_ship: 是否处理获得舰船的弹窗。
        """
        # 大舰队弹窗
        if self.handle_guild_popup_cancel():
            return True

        # 每日重置公告
        if self.appear_then_click(LOGIN_ANNOUNCE, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(LOGIN_ANNOUNCE_2, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(GET_ITEMS_1, offset=True, interval=3):
            return True
        if self.appear_then_click(GET_ITEMS_2, offset=True, interval=3):
            return True
        if get_ship:
            if self.appear_then_click(GET_SHIP, interval=5):
                return True
        if self.appear_then_click(LOGIN_RETURN_SIGN, offset=(30, 30), interval=3):
            return True
        if self.appear(EVENT_LIST_CHECK, offset=(30, 30), interval=5):
            logger.info(f'UI additional: {EVENT_LIST_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        # 月卡即将到期
        if self.appear_then_click(MONTHLY_PASS_NOTICE, offset=(30, 30), interval=3):
            return True
        # 通行券即将到期且玩家有未领取的通行券奖励
        if self.appear_then_click(BATTLE_PASS_NOTICE, offset=(30, 30), interval=3):
            return True
        # 购买通行券的广告弹窗
        # 2024.12.19，主界面的 PURCHASE_POPUP 变为 BATTLE_PASS_NEW_SEASON
        # if self.appear_then_click(PURCHASE_POPUP, offset=(44, -77, 84, -37), interval=3):
        #     return True
        # 通行券新赛季通知弹窗
        if self.appear(BATTLE_PASS_NEW_SEASON, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {BATTLE_PASS_NEW_SEASON} -> {BACK_ARROW}')
            self.device.click(BACK_ARROW)
            return True
        # 物品过期 offset=(37, 72)，皮肤过期 offset=(24, 68)
        if self.handle_popup_single(offset=(-6, 48, 54, 88), name='ITEM_EXPIRED'):
            return True
        # 邮箱已满弹窗
        if self.handle_popup_single_white():
            return True
        # 从确认点击误入的页面
        if self.appear(SHIPYARD_CHECK, offset=(30, 30), interval=5):
            logger.info(f'UI additional: {SHIPYARD_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        if self.appear(META_CHECK, offset=(30, 30), interval=5):
            logger.info(f'UI additional: {META_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        # 误点击
        if self.appear(PLAYER_CHECK, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {PLAYER_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
            if self.appear_then_click(BACK_ARROW, offset=(30, 30)):
                return True

        return False

    def ui_page_os_popups(self):
        """
        处理大世界页面出现的弹窗。
        """
        # 大世界重置流程：
        # - 大世界已重置，handle_story_skip() 点击确认
        # - RESET_TICKET_POPUP 弹窗
        # - 是否打开兑换商店？handle_popup_confirm() 点击确认
        # - EXCHANGE_CHECK 页面，点击返回箭头
        if self._opsi_reset_fleet_preparation_click >= 5:
            logger.critical("无法确认大世界出击舰队，大叔你还点？是在玩打地鼠吗？真是逊毙了！")
            logger.critical("哎呀呀，大叔是眼花了还是没长脑子？ #1: 建议检查您是否在大世界中设置了舰队")
            logger.critical("笨——蛋——大叔！ #2: 建议检查您的舰队准入门槛（等级限制）")
            raise RequestHumanTakeover
        if self.appear_then_click(RESET_TICKET_POPUP, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(RESET_FLEET_PREPARATION, offset=(30, 30), interval=3):
            self._opsi_reset_fleet_preparation_click += 1
            self.interval_reset(FLEET_PREPARATION)
            self.interval_reset(RESET_TICKET_POPUP)
            return True
        if self.appear(EXCHANGE_CHECK, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {EXCHANGE_CHECK} -> {GOTO_MAIN}')
            GOTO_MAIN.clear_offset()
            self.device.click(GOTO_MAIN)
            return True

        return False

    def ui_additional(self, get_ship=True):
        """
        处理 UI 切换过程中出现的各种弹窗。

        Args:
            get_ship: 是否处理获得舰船的弹窗。
        """
        # 大世界页面弹窗
        # 包含 popup_confirm 变体，必须优先处理
        if self.ui_page_os_popups():
            return True

        # 科研弹窗、断线重连弹窗
        if self.handle_popup_confirm("UI_ADDITIONAL"):
            return True
        if self.handle_urgent_commission():
            return True

        # 主界面和奖励页面弹窗
        # 仅在非岛屿页面时处理，避免岛屿页面的 UI 元素被误检测为 GET_SHIP/GET_ITEMS
        # 例如岛屿管理界面的邮箱按钮与 GET_SHIP 检测区域 (1104,610,1110,630) 重叠
        if not (hasattr(self, 'ui_current') and self.ui_current and 'island' in self.ui_current.name):
            if self.ui_page_main_popups(get_ship=get_ship):
                return True

        # 剧情跳过
        if self.handle_story_skip():
            return True

        # 游戏提示
        # 度假村的活动委托提示
        # 2025.05.29 进入船坞时出现的皮肤功能提示
        if self.appear(GAME_TIPS, offset=(30, 30), interval=2):
            logger.info(f'UI additional: {GAME_TIPS} -> {GOTO_MAIN}')
            self.device.click(GOTO_MAIN)
            return True

        # 后宅弹窗
        if self.appear(DORM_INFO, offset=(30, 30), similarity=0.75, interval=3):
            self.device.click(DORM_INFO)
            return True
        if self.appear_then_click(DORM_FEED_CANCEL, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(DORM_TROPHY_CONFIRM, offset=(30, 30), interval=3):
            return True

        # 指挥喵弹窗
        if self.appear_then_click(MEOWFFICER_INFO, offset=(30, 30), interval=3):
            self.interval_reset(GET_SHIP)
            return True
        if self.appear(MEOWFFICER_BUY, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {MEOWFFICER_BUY} -> {BACK_ARROW}')
            self.device.click(BACK_ARROW)
            self.interval_reset(GET_SHIP)
            return True

        # 战役准备界面
        if self.appear(MAP_PREPARATION, offset=(30, 30), interval=3) \
                or self.appear(FLEET_PREPARATION, offset=(20, 50), interval=3) \
                or self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=3):
            self.device.click(MAP_PREPARATION_CANCEL)
            return True
        if self.appear_then_click(AUTO_SEARCH_MENU_EXIT, offset=(200, 30), interval=3):
            return True
        if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
            return True
        if self.appear(WITHDRAW, offset=(30, 30), interval=3):
            # 此处等待是为了处理 2022-04-07 游戏更新后的客户端 bug
            # 复现步骤（100% 成功）：
            # - 进入任意关卡，如 12-4
            # - 停止并重启游戏
            # - 运行 Alas 的 Main 任务
            # - Alas 切换到 page_campaign 并从已有关卡撤退
            # - 游戏客户端在 page_campaign W12 界面卡死，点击屏幕无响应
            # - 再次重启游戏客户端可修复此问题
            logger.info("WITHDRAW button found, wait until map loaded to prevent bugs in game client")
            self.device.sleep(2)
            self.device.screenshot()
            if self.appear_then_click(WITHDRAW, offset=(30, 30)):
                self.interval_reset(WITHDRAW)
                return True
            else:
                logger.warning("WITHDRAW button does not exist anymore")
                self.interval_reset(WITHDRAW)

        # 登录相关
        if self.appear_then_click(LOGIN_CHECK, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(MAINTENANCE_ANNOUNCE, offset=(30, 30), interval=3):
            return True

        # 误点击
        if self.appear(EXERCISE_PREPARATION, interval=3):
            logger.info(f'UI additional: {EXERCISE_PREPARATION} -> {GOTO_MAIN}')
            self.device.click(GOTO_MAIN)
            return True

        # RPG 活动 (raid_20240328)
        # if self.appear_then_click(RPG_STATUS_POPUP, offset=(30, 30), interval=3):
        #     return True
        # 医院活动 (20250327)
        # if self.appear_then_click(HOSIPITAL_CLUE_CHECK, offset=(20, 20), interval=2):
        #     return True
        # if self.appear_then_click(HOSPITAL_BATTLE_EXIT, offset=(20, 20), interval=2):
        #     return True
        # 霓虹都市 (coalition_20250626)
        # 时尚联动 (coalition_20260122) 复用 NEONCITY
        # if self.appear(NEONCITY_FLEET_PREPARATION, offset=(20, 20), interval=3):
        #     logger.info(f'{NEONCITY_FLEET_PREPARATION} -> {NEONCITY_PREPARATION_EXIT}')
        #     self.device.click(NEONCITY_PREPARATION_EXIT)
        #     return True
        # DATE A LANE (coalition_20251120)
        # if self.appear_then_click(DAL_DIFFICULTY_EXIT, offset=(20, 20), interval=3):
        #     return True

        # 空闲页面
        if self.handle_idle_page():
            return True
        # 白色主题 UI 切换，无偏移量仅颜色匹配
        if self.appear(MAIN_GOTO_MEMORIES_WHITE, interval=3):
            logger.info(f'UI additional: {MAIN_GOTO_MEMORIES_WHITE} -> {MAIN_TAB_SWITCH_WHITE}')
            self.device.click(MAIN_TAB_SWITCH_WHITE)
            return True

        return False

    def handle_idle_page(self):
        """
        处理空闲页面（如待机动画），点击回到主界面。

        Returns:
            bool: 是否处理了空闲页面。
        """
        timer = self.get_interval_timer(IDLE, interval=3)
        if not timer.reached():
            return False
        if IDLE.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f'UI additional: {IDLE} -> {REWARD_GOTO_MAIN}')
            self.device.click(REWARD_GOTO_MAIN)
            timer.reset()
            return True
        if IDLE_2.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f'UI additional: {IDLE_2} -> {REWARD_GOTO_MAIN}')
            self.device.click(REWARD_GOTO_MAIN)
            timer.reset()
            return True
        if IDLE_3.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f'UI additional: {IDLE_3} -> {REWARD_GOTO_MAIN}')
            self.device.click(REWARD_GOTO_MAIN)
            timer.reset()
            return True
        return False

    def ui_button_interval_reset(self, button):
        """
        重置某些按钮的检测间隔，防止误点击。

        Args:
            button (Button): 刚点击过的按钮。
        """
        if button == MEOWFFICER_GOTO_DORMMENU:
            self.interval_reset(GET_SHIP)
        if button == DORMMENU_GOTO_DORM:
            self.interval_reset(GET_SHIP)
        if button == DORMMENU_GOTO_MEOWFFICER:
            self.interval_reset(GET_SHIP)
        for switch_button in page_main.links.values():
            if button == switch_button:
                self.interval_reset(GET_SHIP)
        if button in [MAIN_GOTO_REWARD, MAIN_GOTO_REWARD_WHITE]:
            self.interval_reset(GET_SHIP)
        if button == REWARD_GOTO_TACTICAL:
            self.interval_reset(REWARD_GOTO_TACTICAL_WHITE)
        if button == REWARD_GOTO_TACTICAL_WHITE:
            self.interval_reset(REWARD_GOTO_TACTICAL)
        if button in [MAIN_GOTO_CAMPAIGN, MAIN_GOTO_CAMPAIGN_WHITE]:
            self.interval_reset(GET_SHIP)
            # 信浓活动与突袭有相同的标题
            self.interval_reset(RAID_CHECK)
        if button == SHOP_GOTO_SUPPLY_PACK:
            self.interval_reset(EXCHANGE_CHECK)
        if button in [RPG_GOTO_STAGE, RPG_GOTO_STORY, RPG_LEAVE_CITY]:
            self.interval_timer[GET_SHIP.name] = Timer(5).reset()
