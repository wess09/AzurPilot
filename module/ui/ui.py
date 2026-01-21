"""
UI交互核心模块
封装游戏界面的页面识别、跳转、按钮点击、弹窗处理等通用UI操作
继承自InfoHandler（基础信息处理类），是自动化脚本的UI交互层核心
"""
# 导入按钮类（定义界面元素的坐标、截图区域、颜色等）
from module.base.button import Button
# 导入装饰器（run_once：确保函数仅执行一次）
from module.base.decorator import run_once
# 导入计时器（控制操作间隔，避免高频点击/检测）
from module.base.timer import Timer
# 导入联合活动相关按钮（霓虹城、DAL活动的退出/舰队准备按钮）
from module.coalition.assets import NEONCITY_FLEET_PREPARATION, NEONCITY_PREPARATION_EXIT, DAL_DIFFICULTY_EXIT
# 导入战斗相关按钮（获取物品、获取新船的弹窗按钮）
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP
# 导入医院活动相关按钮（线索检测、战斗退出）
from module.event_hospital.assets import HOSIPITAL_CLUE_CHECK, HOSPITAL_BATTLE_EXIT
# 导入自定义异常类（游戏未运行、页面未知、请求人工接管）
from module.exception import (GameNotRunningError, GamePageUnknownError,
                              RequestHumanTakeover)
# 导入演习相关按钮（演习准备页面）
from module.exercise.assets import EXERCISE_PREPARATION
# 导入各类弹窗/提示按钮（自动搜索退出、战斗通行证、游戏提示、登录公告等）
from module.handler.assets import (AUTO_SEARCH_MENU_EXIT, BATTLE_PASS_NEW_SEASON, BATTLE_PASS_NOTICE, GAME_TIPS,
                                   LOGIN_ANNOUNCE, LOGIN_ANNOUNCE_2, LOGIN_CHECK, LOGIN_RETURN_SIGN,
                                   MAINTENANCE_ANNOUNCE, MONTHLY_PASS_NOTICE)
# 导入基础信息处理类（UI类的父类，提供基础弹窗处理能力）
from module.handler.info_handler import InfoHandler
# 导入日志工具（输出脚本运行信息，便于调试/监控）
from module.logger import logger
# 导入地图相关按钮（舰队准备、地图准备、撤回等）
from module.map.assets import (FLEET_PREPARATION, MAP_PREPARATION,
                               MAP_PREPARATION_CANCEL, WITHDRAW)
# 导入猫副官相关按钮（猫副官购买弹窗）
from module.meowfficer.assets import MEOWFFICER_BUY
# 导入OCR类（光学字符识别，用于识别界面文字如页码/索引）
from module.ocr.ocr import Ocr
# 导入OS作战相关按钮（自动搜索奖励、兑换检测、重置舰队准备等）
from module.os_handler.assets import (AUTO_SEARCH_REWARD, EXCHANGE_CHECK, RESET_FLEET_PREPARATION, RESET_TICKET_POPUP)
# 导入突袭活动相关所有按钮（通配符导入，简化代码）
from module.raid.assets import *
# 导入UI通用按钮（返回箭头、主页面按钮等）
from module.ui.assets import *
# 导入页面枚举类（定义游戏各页面标识：战役页、活动页、主页面等）
from module.ui.page import Page, page_campaign, page_event, page_main, page_main_white, page_sp
# 导入白色主题UI的按钮（适配不同界面风格）
from module.ui_white.assets import *


class UI(InfoHandler):
    """
    游戏UI交互核心类，继承自InfoHandler
    核心能力：
    1. 页面识别（判断当前处于哪个游戏页面）
    2. 页面跳转（从任意页面跳转到指定目标页面）
    3. 通用点击逻辑（带重试/确认/容错的按钮点击）
    4. 弹窗统一处理（自动关闭各类干扰弹窗：登录公告、月卡提醒、剧情等）
    5. 特殊场景适配（OS作战、联合活动、突袭活动等）
    """
    # 当前识别到的页面（Page枚举类型）
    ui_current: Page

    def ui_page_appear(self, page, offset=(30, 30), interval=0):
        """
        判断指定页面是否显示在屏幕上（核心页面识别方法）

        Args:
            page (Page): 要检测的页面（如page_main/ page_event）
            offset (tuple): 页面检测区域的偏移容错（避免界面微小偏移导致误判）
            interval (int/float): 检测间隔（秒），避免高频检测

        Returns:
            bool: True（页面存在）/False（页面不存在）
        """
        # 特殊处理主页面：兼容普通主页面和白色主题主页面
        if page == page_main:
            # 先检测白色主题主页面
            if self.appear(page_main_white.check_button, offset=offset, interval=interval):
                return True
            # 再检测普通主页面（缩小偏移容错，提高精准度）
            if self.appear(page_main.check_button, offset=(5, 5), interval=interval):
                return True
            return False
        # 其他页面直接检测对应的检查按钮
        return self.appear(page.check_button, offset=offset, interval=interval)

    def is_in_main(self, offset=(30, 30), interval=0):
        """
        快捷方法：判断是否处于游戏主页面

        Args:
            offset (tuple): 检测偏移容错
            interval (int/float): 检测间隔

        Returns:
            bool: True（在主页面）/False（不在）
        """
        return self.ui_page_appear(page_main, offset=offset, interval=interval)

    def ui_main_appear_then_click(self, page, offset=(30, 30), interval=3):
        """
        在主页面时，点击跳转到指定目标页面

        Args:
            page: 目标页面（如page_campaign/page_event）
            offset (tuple): 主页面检测偏移容错
            interval (int/float): 点击间隔

        Returns:
            bool: True（执行了点击）/False（未点击）
        """
        # 普通主页面 → 点击对应跳转按钮
        if self.appear(page_main.check_button, offset=offset, interval=interval):
            button = page_main.links[page]
            self.device.click(button)
            return True
        # 白色主题主页面 → 点击对应跳转按钮
        if self.appear(page_main_white.check_button, offset=(5, 5), interval=interval):
            button = page_main_white.links[page]
            self.device.click(button)
            return True
        # 未在主页面，返回False
        return False

    def ensure_button_execute(self, button, offset=0):
        """
        检测按钮是否满足执行条件（显示在屏幕上）

        Args:
            button (Button/callable): 要检测的按钮/检测函数
            offset (int/tuple): 检测偏移容错

        Returns:
            bool: True（满足执行条件）/False（不满足）
        """
        # 按钮类型：直接检测是否显示
        if isinstance(button, Button) and self.appear(button, offset=offset):
            return True
        # 可调用对象（如函数）：执行函数并返回结果
        elif callable(button) and button():
            return True
        # 其他情况返回False
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
        通用按钮点击逻辑（带重试、确认、干扰处理）
        核心逻辑：循环检测→满足条件则点击→直到目标状态达成

        Args:
            click_button (Button): 要点击的按钮
            check_button (Button/callable/list): 目标状态检测按钮/函数（点击后要达成的状态）
            appear_button (Button/callable): 点击触发条件（按钮显示时才点击），默认等于click_button
            additional (callable): 额外干扰处理函数（如弹窗处理）
            confirm_wait (int/float): 目标状态确认等待时间（秒）
            offset (tuple): 检测偏移容错
            retry_wait (int/float): 点击重试间隔（秒）
            skip_first_screenshot (bool): 是否跳过首次截图（优化性能）
        """
        logger.hr("UI click")  # 打印分隔线，便于日志阅读
        # 默认点击触发条件为要点击的按钮本身
        if appear_button is None:
            appear_button = click_button

        # 初始化点击计时器（控制重试间隔，避免高频点击）
        click_timer = Timer(retry_wait, count=retry_wait // 0.5)
        # 确认计时器：有额外处理时才启用，避免提前退出
        confirm_wait = confirm_wait if additional is not None else 0
        confirm_timer = Timer(confirm_wait, count=confirm_wait // 0.5).start()

        # 主循环：直到达成目标状态
        while 1:
            # 截图控制：首次跳过（优化性能），后续每次循环截图
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 检测目标状态：达成则退出循环
            if self.ui_process_check_button(check_button, offset=offset):
                if confirm_timer.reached():
                    break
            else:
                # 未达成目标状态，重置确认计时器
                confirm_timer.reset()

            # 满足点击条件则执行点击
            if click_timer.reached():
                # 检测点击触发条件（按钮显示/函数返回True）
                if (isinstance(appear_button, Button) and self.appear(appear_button, offset=offset)) or (
                        callable(appear_button) and appear_button()
                ):
                    self.device.click(click_button)
                    click_timer.reset()
                    continue

            # 处理额外干扰（如弹窗）
            if additional is not None:
                if additional():
                    continue

    def ui_process_check_button(self, check_button, offset=(30, 30)):
        """
        统一处理各类检测按钮/函数的执行逻辑

        Args:
            check_button (Button/callable/list/tuple): 检测目标（按钮/函数/按钮列表）
            offset (tuple): 检测偏移容错

        Returns:
            bool: 检测结果（True/False）
        """
        # 单个按钮：检测是否显示
        if isinstance(check_button, Button):
            return self.appear(check_button, offset=offset)
        # 可调用对象（如函数）：执行并返回结果
        elif callable(check_button):
            return check_button()
        # 按钮列表/元组：任意一个显示则返回True
        elif isinstance(check_button, (list, tuple)):
            for button in check_button:
                if self.appear(button, offset=offset):
                    return True
            return False
        # 其他情况：默认按按钮处理
        else:
            return self.appear(check_button, offset=offset)

    def ui_get_current_page(self, skip_first_screenshot=True):
        """
        识别当前所处的游戏页面（核心页面识别入口）

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            Page: 当前识别到的页面（Page枚举类型）

        Raises:
            GameNotRunningError: 游戏未运行时抛出
            GamePageUnknownError: 无法识别页面时抛出（请求人工接管）
        """
        logger.info("UI get current page")

        # 装饰器确保仅执行一次：检测游戏是否运行
        @run_once
        def app_check():
            if not self.device.app_is_running():
                raise GameNotRunningError("Game not running")

        # 装饰器确保仅执行一次：uiautomator2模式下卸载minicap（避免冲突）
        @run_once
        def minicap_check():
            if self.config.Emulator_ControlMethod == "uiautomator2":
                self.device.uninstall_minicap()

        # 方向检测计时器（定期检测屏幕旋转状态）
        orientation_timer = Timer(5)

        # 超时计时器（10秒未识别到页面则判定为未知页面）
        timeout = Timer(10, count=20).start()
        while 1:
            # 截图控制
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # 超时终止：10秒未识别到页面
            if timeout.reached():
                break

            # 检测已知页面：遍历所有Page枚举，找到匹配的页面
            for page in Page.iter_pages():
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.attr("UI", page.name)
                    self.ui_current = page
                    return page

            # 未知页面但可处理：尝试点击返回主页面按钮
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
            # 处理额外干扰弹窗
            if self.ui_additional():
                timeout.reset()
                continue

            # 检测游戏运行状态/卸载minicap
            app_check()
            minicap_check()
            # 定期检测屏幕旋转状态
            if orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

        # 无法识别页面：输出调试信息并抛出异常
        logger.warning("Unknown ui page")
        logger.attr("EMULATOR__SCREENSHOT_METHOD", self.config.Emulator_ScreenshotMethod)
        logger.attr("EMULATOR__CONTROL_METHOD", self.config.Emulator_ControlMethod)
        logger.attr("SERVER", self.config.SERVER)
        logger.warning("Starting from current page is not supported")
        logger.warning(f"Supported page: {[str(page) for page in Page.iter_pages()]}")
        logger.warning('Supported page: Any page with a "HOME" button on the upper-right')
        logger.critical("Please switch to a supported page before starting Alas")
        raise GamePageUnknownError

    def ui_goto(self, destination, get_ship=True, offset=(30, 30), skip_first_screenshot=True):
        """
        从当前页面跳转到指定目标页面（核心页面跳转逻辑）
        逻辑：逐级返回父页面 → 直到到达目标页面

        Args:
            destination (Page): 目标页面（如page_event/page_campaign）
            get_ship (bool): 是否处理获取新船弹窗（默认True）
            offset (tuple): 页面检测偏移容错
            skip_first_screenshot (bool): 是否跳过首次截图
        """
        # 初始化页面跳转连接（构建页面父子关系）
        Page.init_connection(destination)
        # 清空所有页面检测按钮的间隔（避免检测间隔导致误判）
        self.interval_clear(list(Page.iter_check_buttons()))

        logger.hr(f"UI goto {destination}")
        while 1:
            # 清空主页面按钮的偏移（精准检测）
            GOTO_MAIN.clear_offset()
            # 截图控制
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 终止条件：到达目标页面
            if self.ui_page_appear(page=destination, offset=offset):
                logger.info(f'Page arrive: {destination}')
                break

            # 逐级返回父页面：遍历所有页面，找到当前页面并点击返回父页面的按钮
            clicked = False
            for page in Page.iter_pages():
                if page.parent is None or page.check_button is None:
                    continue
                if self.appear(page.check_button, offset=offset, interval=5):
                    logger.info(f'Page switch: {page} -> {page.parent}')
                    button = page.links[page.parent]
                    self.device.click(button)
                    # 重置按钮点击间隔（避免高频点击）
                    self.ui_button_interval_reset(button)
                    clicked = True
                    break
            if clicked:
                continue

            # 处理跳转过程中的干扰弹窗
            if self.ui_additional(get_ship=get_ship):
                continue

        # 重置页面连接（避免影响后续操作）
        Page.clear_connection()

    def ui_ensure(self, destination, skip_first_screenshot=True):
        """
        确保处于指定目标页面（未在则跳转）

        Args:
            destination (Page): 目标页面
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            bool: True（执行了跳转）/False（已在目标页面）
        """
        logger.hr("UI ensure")
        # 先识别当前页面
        self.ui_get_current_page(skip_first_screenshot=skip_first_screenshot)
        # 已在目标页面：返回False
        if self.ui_current == destination:
            logger.info("Already at %s" % destination)
            return False
        # 未在目标页面：执行跳转并返回True
        else:
            logger.info("Goto %s" % destination)
            self.ui_goto(destination, skip_first_screenshot=True)
            return True

    def ui_goto_main(self):
        """快捷方法：确保跳转到主页面"""
        return self.ui_ensure(destination=page_main)

    def ui_goto_campaign(self):
        """快捷方法：确保跳转到战役页面"""
        return self.ui_ensure(destination=page_campaign)

    def ui_goto_event(self):
        """快捷方法：确保跳转到活动页面"""
        return self.ui_ensure(destination=page_event)

    def ui_goto_sp(self):
        """快捷方法：确保跳转到SP关卡页面"""
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
        确保界面索引/页码切换到指定值（如活动关卡页码、商店页码）
        核心逻辑：OCR识别当前索引 → 计算差值 → 点击上一页/下一页按钮

        Args:
            index (int): 目标索引/页码
            letter (Ocr/callable): OCR识别对象/识别函数（获取当前索引）
            next_button (Button): 下一页按钮
            prev_button (Button): 上一页按钮
            skip_first_screenshot (bool): 是否跳过首次截图
            fast (bool): 是否快速点击（批量点击差值次数，默认True）
            interval (tuple/int/float): 点击间隔（秒）
        """
        logger.hr("UI ensure index")
        # 重试计时器（控制点击间隔）
        retry = Timer(1, count=2)
        while 1:
            # 截图控制
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 获取当前索引：OCR识别/执行识别函数
            if isinstance(letter, Ocr):
                current = letter.ocr(self.device.image)
            else:
                current = letter(self.device.image)

            logger.attr("Index", current)
            # 计算目标与当前索引的差值
            diff = index - current
            # 达成目标索引：退出循环
            if diff == 0:
                break

            # 满足重试间隔：执行点击
            if retry.reached():
                # 差值>0：点击下一页；差值<0：点击上一页
                button = next_button if diff > 0 else prev_button
                if fast:
                    # 快速模式：批量点击差值次数（减少循环）
                    self.device.multi_click(button, n=abs(diff), interval=interval)
                else:
                    # 普通模式：单次点击（索引不连续时使用）
                    self.device.click(button)
                retry.reset()

    def ui_back(self, check_button, appear_button=None, offset=(30, 30), retry_wait=10, skip_first_screenshot=False):
        """
        通用返回逻辑（点击返回箭头，直到到达目标页面）

        Args:
            check_button (Button/callable): 目标页面检测按钮/函数
            appear_button (Button/callable): 返回按钮显示检测
            offset (tuple): 检测偏移容错
            retry_wait (int/float): 重试间隔
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            执行ui_click的返回结果
        """
        return self.ui_click(
            click_button=BACK_ARROW,  # 固定点击返回箭头
            check_button=check_button,  # 目标状态检测
            appear_button=appear_button,  # 点击触发条件
            offset=offset,  # 检测偏移
            retry_wait=retry_wait,  # 重试间隔
            skip_first_screenshot=skip_first_screenshot,  # 截图控制
        )

    # OS作战重置舰队准备的点击计数（防止无限点击）
    _opsi_reset_fleet_preparation_click = 0

    def ui_page_main_popups(self, get_ship=True):
        """
        处理主页面/奖励页面的各类干扰弹窗

        Args:
            get_ship (bool): 是否处理获取新船弹窗（默认True）

        Returns:
            bool: True（处理了弹窗）/False（无弹窗需处理）
        """
        # 公会弹窗：取消
        if self.handle_guild_popup_cancel():
            return True

        # 每日重置相关弹窗：登录公告/奖励/回归签到
        if self.appear_then_click(LOGIN_ANNOUNCE, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(LOGIN_ANNOUNCE_2, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(GET_ITEMS_1, offset=True, interval=3):
            return True
        if self.appear_then_click(GET_ITEMS_2, offset=True, interval=3):
            return True
        # 处理获取新船弹窗（可关闭）
        if get_ship:
            if self.appear_then_click(GET_SHIP, interval=5):
                return True
        if self.appear_then_click(LOGIN_RETURN_SIGN, offset=(30, 30), interval=3):
            return True
        # 活动列表弹窗：返回主页面
        if self.appear(EVENT_LIST_CHECK, offset=(30, 30), interval=5):
            logger.info(f'UI additional: {EVENT_LIST_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        # 月卡即将过期提醒
        if self.appear_then_click(MONTHLY_PASS_NOTICE, offset=(30, 30), interval=3):
            return True
        # 战斗通行证即将过期/未领取奖励提醒
        if self.appear_then_click(BATTLE_PASS_NOTICE, offset=(30, 30), interval=3):
            return True
        # 战斗通行证新赛季弹窗：点击返回箭头关闭
        if self.appear(BATTLE_PASS_NEW_SEASON, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {BATTLE_PASS_NEW_SEASON} -> {BACK_ARROW}')
            self.device.click(BACK_ARROW)
            return True
        # 物品/皮肤过期弹窗
        if self.handle_popup_single(offset=(-6, 48, 54, 88), name='ITEM_EXPIRED'):
            return True
        # 邮箱已满弹窗（白色主题）
        if self.handle_popup_single_white():
            return True
        # 造船坞/meta页面弹窗：返回主页面
        if self.appear(SHIPYARD_CHECK, offset=(30, 30), interval=5):
            logger.info(f'UI additional: {SHIPYARD_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        if self.appear(META_CHECK, offset=(30, 30), interval=5):
            logger.info(f'UI additional: {META_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        # 误点进入玩家信息页面：返回主页面/点击返回箭头
        if self.appear(PLAYER_CHECK, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {PLAYER_CHECK} -> {GOTO_MAIN}')
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
            if self.appear_then_click(BACK_ARROW, offset=(30, 30)):
                return True

        return False

    def ui_page_os_popups(self):
        """
        处理OS作战页面的各类干扰弹窗

        Returns:
            bool: True（处理了弹窗）/False（无弹窗需处理）

        Raises:
            RequestHumanTakeover: 重置舰队准备点击超5次时抛出（请求人工接管）
        """
        # 点击次数超5次：判定为异常，请求人工接管
        if self._opsi_reset_fleet_preparation_click >= 5:
            logger.critical("Failed to confirm OpSi fleets, too many click on RESET_FLEET_PREPARATION")
            logger.critical("Possible reason #1: You haven't set any fleets in operation siren")
            logger.critical(
                "Possible reason #2: Your fleets haven't satisfied the level restrictions in operation siren")
            raise RequestHumanTakeover
        # 重置门票弹窗：点击关闭
        if self.appear_then_click(RESET_TICKET_POPUP, offset=(30, 30), interval=3):
            return True
        # 重置舰队准备弹窗：点击确认，计数+1
        if self.appear_then_click(RESET_FLEET_PREPARATION, offset=(30, 30), interval=3):
            self._opsi_reset_fleet_preparation_click += 1
            self.interval_reset(FLEET_PREPARATION)
            self.interval_reset(RESET_TICKET_POPUP)
            return True
        # 兑换商店弹窗：返回主页面
        if self.appear(EXCHANGE_CHECK, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {EXCHANGE_CHECK} -> {GOTO_MAIN}')
            GOTO_MAIN.clear_offset()
            self.device.click(GOTO_MAIN)
            return True

        return False

    def ui_additional(self, get_ship=True):
        """
        统一处理UI跳转过程中的所有干扰弹窗（核心弹窗处理入口）
        优先级：OS作战弹窗 > 通用确认弹窗 > 主页面弹窗 > 剧情 > 游戏提示 > 其他场景弹窗

        Args:
            get_ship (bool): 是否处理获取新船弹窗（默认True）

        Returns:
            bool: True（处理了弹窗）/False（无弹窗需处理）
        """
        # 1. 处理OS作战弹窗（最高优先级）
        if self.ui_page_os_popups():
            return True

        # 2. 处理通用确认弹窗（如网络断开、研究弹窗）
        if self.handle_popup_confirm("UI_ADDITIONAL"):
            return True
        # 处理紧急委托弹窗
        if self.handle_urgent_commission():
            return True

        # 3. 处理主页面/奖励页面弹窗
        if self.ui_page_main_popups(get_ship=get_ship):
            return True

        # 4. 处理剧情跳过
        if self.handle_story_skip():
            return True

        # 5. 处理游戏提示弹窗（如皮肤功能提示）
        if self.appear(GAME_TIPS, offset=(30, 30), interval=2):
            logger.info(f'UI additional: {GAME_TIPS} -> {GOTO_MAIN}')
            self.device.click(GOTO_MAIN)
            return True

        # 6. 处理宿舍相关弹窗
        if self.appear(DORM_INFO, offset=(30, 30), similarity=0.75, interval=3):
            self.device.click(DORM_INFO)
            return True
        if self.appear_then_click(DORM_FEED_CANCEL, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(DORM_TROPHY_CONFIRM, offset=(30, 30), interval=3):
            return True

        # 7. 处理猫副官相关弹窗
        if self.appear_then_click(MEOWFFICER_INFO, offset=(30, 30), interval=3):
            self.interval_reset(GET_SHIP)
            return True
        if self.appear(MEOWFFICER_BUY, offset=(30, 30), interval=3):
            logger.info(f'UI additional: {MEOWFFICER_BUY} -> {BACK_ARROW}')
            self.device.click(BACK_ARROW)
            self.interval_reset(GET_SHIP)
            return True

        # 8. 处理战役/地图准备弹窗（误点进入时返回）
        if self.appear(MAP_PREPARATION, offset=(30, 30), interval=3) \
                or self.appear(FLEET_PREPARATION, offset=(20, 50), interval=3) \
                or self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=3):
            self.device.click(MAP_PREPARATION_CANCEL)
            return True
        # 处理自动搜索菜单退出
        if self.appear_then_click(AUTO_SEARCH_MENU_EXIT, offset=(200, 30), interval=3):
            return True
        # 处理自动搜索奖励弹窗
        if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
            return True
        # 处理撤回按钮（兼容游戏客户端bug）
        if self.appear(WITHDRAW, offset=(30, 30), interval=3):
            logger.info("WITHDRAW button found, wait until map loaded to prevent bugs in game client")
            self.device.sleep(2)
            self.device.screenshot()
            if self.appear_then_click(WITHDRAW, offset=(30, 30)):
                self.interval_reset(WITHDRAW)
                return True
            else:
                logger.warning("WITHDRAW button does not exist anymore")
                self.interval_reset(WITHDRAW)

        # 9. 处理登录/维护公告弹窗
        if self.appear_then_click(LOGIN_CHECK, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(MAINTENANCE_ANNOUNCE, offset=(30, 30), interval=3):
            return True

        # 10. 处理误点进入演习页面：返回主页面
        if self.appear(EXERCISE_PREPARATION, interval=3):
            logger.info(f'UI additional: {EXERCISE_PREPARATION} -> {GOTO_MAIN}')
            self.device.click(GOTO_MAIN)
            return True

        # 11. 处理联合活动（20251120 DAL）难度选择退出弹窗
        if self.appear_then_click(DAL_DIFFICULTY_EXIT, offset=(20, 20), interval=3):
            return True

        # 12. 处理闲置页面（如奖励页面超时闲置）
        if self.handle_idle_page():
            return True
        # 13. 处理白色主题UI的标签切换弹窗
        if self.appear(MAIN_GOTO_MEMORIES_WHITE, interval=3):
            logger.info(f'UI additional: {MAIN_GOTO_MEMORIES_WHITE} -> {MAIN_TAB_SWITCH_WHITE}')
            self.device.click(MAIN_TAB_SWITCH_WHITE)
            return True

        return False

    def handle_idle_page(self):
        """
        处理游戏闲置页面（如奖励页面超时无操作后的闲置状态）

        Returns:
            bool: True（处理了闲置页面）/False（无闲置页面）
        """
        # 获取闲置页面检测计时器（3秒间隔）
        timer = self.get_interval_timer(IDLE, interval=3)
        if not timer.reached():
            return False
        # 检测各类闲置页面，点击返回主页面按钮
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
        重置指定按钮的点击间隔（避免高频点击导致误操作）
        主要针对易误点的按钮（如猫副官、主页面跳转按钮）

        Args:
            button (Button): 要重置间隔的按钮
        """
        # 猫副官相关按钮：重置获取新船弹窗的检测间隔
        if button == MEOWFFICER_GOTO_DORMMENU:
            self.interval_reset(GET_SHIP)
        if button == DORMMENU_GOTO_DORM:
            self.interval_reset(GET_SHIP)
        if button == DORMMENU_GOTO_MEOWFFICER:
            self.interval_reset(GET_SHIP)
        # 主页面跳转按钮：重置获取新船弹窗的检测间隔
        for switch_button in page_main.links.values():
            if button == switch_button:
                self.interval_reset(GET_SHIP)
        # 奖励页面跳转按钮：重置获取新船弹窗的检测间隔
        if button in [MAIN_GOTO_REWARD, MAIN_GOTO_REWARD_WHITE]:
            self.interval_reset(GET_SHIP)
        # 战术页面跳转按钮：互斥重置间隔
        if button == REWARD_GOTO_TACTICAL:
            self.interval_reset(REWARD_GOTO_TACTICAL_WHITE)
        if button == REWARD_GOTO_TACTICAL_WHITE:
            self.interval_reset(REWARD_GOTO_TACTICAL)
        # 战役页面跳转按钮：重置获取新船/突袭检测间隔
        if button in [MAIN_GOTO_CAMPAIGN, MAIN_GOTO_CAMPAIGN_WHITE]:
            self.interval_reset(GET_SHIP)
            self.interval_reset(RAID_CHECK)
        # 商店补给包按钮：重置兑换检测间隔
        if button == SHOP_GOTO_SUPPLY_PACK:
            self.interval_reset(EXCHANGE_CHECK)
        # RPG活动按钮：重置获取新船检测间隔
        if button in [RPG_GOTO_STAGE, RPG_GOTO_STORY, RPG_LEAVE_CITY]:
            self.interval_timer[GET_SHIP.name] = Timer(5).reset()