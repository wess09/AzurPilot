from datetime import timedelta

from module.config.time_source import now as current_time

from module.base.timer import Timer
from module.island.island import Island
from module.island.assets import *
from module.island_daily_interact.assets import *
from module.base.utils import crop
from module.handler.assets import STORY_SKIP_3
from module.logger import logger
from module.ui.assets import ISLAND_PHONE_CHECK, ISLAND_CHECK
from module.ui.page import page_island, page_island_map, page_island_phone


DEVELOPMENT_PLAN_TASK_LIST_AREA = (179, 124, 280, 690)


class IslandDailyInteract(Island):
    """每日与每周互动任务：摸猫、JUU速运、商区外送服务、每周照相。"""

    def run(self):
        """执行启用的岛屿低频互动任务。"""
        logger.hr('Island Daily Interact Run', level=1)
        self.ui_ensure(page_island)

        all_done = True
        self.pet_cat()
        all_done = self.juu_express() and all_done
        all_done = self.business_delivery() and all_done
        if self.config.IslandDailyInteract_WeeklyPhoto:
            all_done = self.weekly_photo() and all_done

        if all_done:
            self._delay_to_next_day()
            logger.info('[岛屿-每日周任务] 岛屿每日互动执行完成')
        else:
            logger.warning('[岛屿-每日周任务] 岛屿每日互动部分任务失败，60分钟后重试')
            self.config.task_delay(minute=60)

    def pet_cat(self):
        """
        执行晨露农场摸猫。

        Pages:
            in: 任意页面
            out: page_island 或奖励关闭后的当前页面
        """
        from module.island_daily_interact.assets import PET_CAT_FARM_INTERACT

        logger.hr('Pet Cat', level=2)
        if not self.island_map_goto('farm'):
            logger.warning('[岛屿-每日周任务] 前往晨露农场失败，跳过摸猫任务')
            return False
        self.move_for_morningdew_farm()

        if self._click_optional_interact(PET_CAT_FARM_INTERACT, '摸猫互动'):
            self._handle_island_reward_optional()
        else:
            logger.info('[岛屿-每日周任务] 未检测到摸猫互动按钮，跳过')

        self._click_safe_area_twice()

    def juu_express(self):
        """
        执行 JUU 速运任务。

        Pages:
            in: 任意页面
            out: page_island
        """
        from module.island_daily_interact.assets import (
            DEVELOPMENT_PLAN_DAILY_TAB,
            DEVELOPMENT_PLAN_DAILY_TAB_CHECK,
            TEMPLATE_JUU_EXPRESS_TASK_ICON,
        )

        logger.hr('JUU Express', level=2)
        if not self._detect_development_plan_template_task(
                task_template=TEMPLATE_JUU_EXPRESS_TASK_ICON,
                tab_button=DEVELOPMENT_PLAN_DAILY_TAB,
                tab_check=DEVELOPMENT_PLAN_DAILY_TAB_CHECK,
                tab_label='每日计划',
                label='JUU速运'):
            logger.info('[岛屿-每日周任务] 未检测到或已完成 JUU 速运任务，跳过')
            self._back_to_island_phone_from_development_plan()
            return True
        if not self._back_to_island_phone_from_development_plan():
            return False

        completed = True
        for name, destination, move_method, interact_button, complete_button in self._juu_express_steps():
            if not self.juu_express_location_flow(
                    name=name,
                    destination=destination,
                    move_method=move_method,
                    interact_button=interact_button,
                    complete_button=complete_button):
                logger.warning(f'[岛屿-每日周任务] JUU速运地点交互失败，终止后续流程: {name}')
                completed = False
                break

        self._handle_island_reward_optional()
        self._click_safe_area_twice()
        self.ui_goto(page_island, get_ship=False)
        return completed

    def business_delivery(self):
        """
        执行商区外送服务任务。

        Pages:
            in: 任意页面
            out: page_island
        """
        from module.island_daily_interact.assets import (
            DEVELOPMENT_PLAN_DAILY_TAB,
            DEVELOPMENT_PLAN_DAILY_TAB_CHECK,
            TEMPLATE_BUSINESS_DELIVERY_TASK_ICON,
        )

        logger.hr('Business Delivery', level=2)
        if not self._detect_development_plan_template_task(
                task_template=TEMPLATE_BUSINESS_DELIVERY_TASK_ICON,
                tab_button=DEVELOPMENT_PLAN_DAILY_TAB,
                tab_check=DEVELOPMENT_PLAN_DAILY_TAB_CHECK,
                tab_label='每日计划',
                label='商区外送服务'):
            logger.info('[岛屿-每日周任务] 未检测到或已完成商区外送服务任务，跳过')
            self._back_to_island_phone_from_development_plan()
            return True
        if not self._back_to_island_phone_from_development_plan():
            return False

        completed = True
        for name, destination, move_method, interact_button, complete_button in self._business_delivery_steps():
            if not self.delivery_location_flow(
                    task_label='商区外送服务',
                    name=name,
                    destination=destination,
                    move_method=move_method,
                    interact_button=interact_button,
                    complete_button=complete_button):
                logger.warning(f'[岛屿-每日周任务] 商区外送服务地点交互失败，终止后续流程: {name}')
                completed = False
                break

        self._handle_island_reward_optional()
        self._click_safe_area_twice()
        self.ui_goto(page_island, get_ship=False)
        return completed

    def weekly_photo(self):
        """
        执行每周照相任务，直到开发计划中不再出现任务图标。

        Pages:
            in: 任意页面
            out: page_island_phone 或 page_island
        """
        from module.island_daily_interact.assets import (
            DEVELOPMENT_PLAN_WEEKLY_TAB,
            DEVELOPMENT_PLAN_WEEKLY_TAB_CHECK,
            TEMPLATE_WEEKLY_PHOTO_TASK_ICON,
            WEEKLY_PHOTO_TASK_CHECK,
        )

        logger.hr('Weekly Photo', level=2)
        completed = True
        while 1:
            if not self._start_development_plan_template_task(
                    task_template=TEMPLATE_WEEKLY_PHOTO_TASK_ICON,
                    task_check=WEEKLY_PHOTO_TASK_CHECK,
                    tab_button=DEVELOPMENT_PLAN_WEEKLY_TAB,
                    tab_check=DEVELOPMENT_PLAN_WEEKLY_TAB_CHECK,
                    tab_label='每周计划',
                    label='每周照相任务'):
                logger.info('[岛屿-每日周任务] 未检测到或已完成每周照相任务，结束循环')
                self._back_to_island_phone_from_development_plan()
                break

            if not self._run_weekly_photo_once():
                logger.warning('[岛屿-每日周任务] 每周照相任务单轮流程未完整完成，结束循环')
                completed = False
                break

            if not self._back_to_island_phone():
                completed = False
                break

        return completed

    def delivery_location_flow(self, task_label, name, destination, move_method, interact_button, complete_button):
        """
        单个外送类任务地点的通用交付流程。

        Args:
            task_label: 日志中的任务名称。
            name: 日志中的地点名称。
            destination: island_map_goto() 的目的地。
            move_method: 目的地内移动路线函数。
            interact_button: 当前地点交互按钮。
            complete_button: 当前地点已完成图标。

        Returns:
            bool: 是否完成该地点交付。
        """
        logger.hr(f'{task_label} - {name}', level=3)
        for attempt in range(2):
            logger.info(f'[岛屿-每日周任务] 前往{name}，第{attempt + 1}次尝试')
            if not self.island_map_goto(destination):
                logger.warning(f'[岛屿-每日周任务] 前往{name}失败')
                continue
            move_method()

            interact_status = self._click_optional_interact_or_complete(
                    interact_button=interact_button,
                    complete_button=complete_button,
                    label=f'{name}交付互动')
            if interact_status == 'clicked':
                self.handle_island_story_skip_safely()
                return True
            if interact_status == 'complete':
                return True

            logger.warning(f'[岛屿-每日周任务] 未检测到{name}交付互动按钮')

        return False

    def juu_express_location_flow(self, name, destination, move_method, interact_button, complete_button):
        """单个 JUU 速运地点的通用交付流程。"""
        return self.delivery_location_flow(
            task_label='JUU速运',
            name=name,
            destination=destination,
            move_method=move_method,
            interact_button=interact_button,
            complete_button=complete_button,
        )

    def move_for_lakeniya(self):
        """繁荫农圃拉科尼娅移动路线。"""
        self.island_up(2000)
        self.island_right(1800)
        self.island_up(500)

    def move_for_luxi(self):
        """繁荫农圃露西移动路线。"""
        self.island_left(800)
        self.island_up(5500)
        self.island_left(1000)
        self.island_up(3700)

    def move_for_aobulaien(self):
        """栖风原野奥布莱恩移动路线。"""
        self.island_right(4600)
        self.island_up(5100)
        self.island_right(1100)

    def move_for_qiaoan(self):
        """栖风原野乔安移动路线。"""
        self.island_right(6000)
        self.island_down(3000)
        self.island_right(2300)

    def move_for_morningdew_farm(self):
        """晨露农场摸猫移动路线。"""
        self.island_left(500)
        self.island_down(200)

    def move_for_hemo(self):
        """晨露农场赫莫移动路线。"""
        self.island_left(600)
        self.island_up(2000)
        self.island_left(800)

    def move_for_meili(self):
        """晨露农场梅莉移动路线。"""
        self.island_right(1800)
        self.island_down(600)

    def move_for_aolipike(self):
        """晨露农场奥利匹克移动路线。"""
        self.island_left(500)
        self.island_down(1500)
        self.island_left(1700)
        self.island_down(1900)

    def move_for_amoma(self):
        """港口商区阿莫玛移动路线。"""
        self.island_up(1500)
        self.island_left(400)

    def move_for_pateli(self):
        """港口帕特莉移动路线。"""
        self.island_left(2200)
        self.device.click(ISLAND_JUMP)
        self.island_left(1200)
        self.island_up(500)

    def move_for_bulaimei(self):
        """港口布莱梅移动路线（需跳转到啾咖啡餐厅）。"""
        self.island_up(2600)
        self.device.click(ROUTE_TWO_OPTION_COMPLETE)
        for _ in self.loop(timeout=12, skip_first=False):
            self.device.sleep(2)
            if self.appear(ISLAND_CHECK):
                break
        self.island_left(600)

    def move_for_lisha(self):
        """集会岛莉莎移动路线。"""
        self.island_up(3000)
        self.island_left(2000)
        self.island_up(5500)
        self.island_right(300)
        self.island_up(2200)
        self.island_left(1100)

    def handle_island_story_skip_safely(self):
        """
        安全处理岛屿互动后的剧情跳过。

        Returns:
            bool: 是否检测到返回状态或执行过跳过处理。
        """
        handled = False
        for _ in self.loop(timeout=20, skip_first=False):
            if self._appear_story_skip_luma(interval=2):
                self.device.click(AIR_DROP_SKIP)
                handled = True
                continue

            in_island = self.ui_page_appear(page_island)
            in_island_map = self.ui_page_appear(page_island_map)
            if in_island or in_island_map:
                return handled

            if self.appear(ISLAND_PHONE_CHECK):
                logger.warning('[岛屿-每日周任务] 跳过期间检测到岛屿手机页面，停止继续点击跳过')
                self.ui_goto(page_island, get_ship=False)
                return handled

            if self._handle_island_reward_once():
                handled = True
                continue

        logger.warning('[岛屿-每日周任务] 剧情跳过等待超时')
        return handled

    def _appear_story_skip_luma(self, interval=0):
        """岛屿对话左上角菜单易受场景光照染色，使用亮度匹配复用 STORY_SKIP_3。"""
        self.device.stuck_record_add(STORY_SKIP_3)
        if interval:
            timer = self.interval_timer.get(STORY_SKIP_3.name)
            if timer is None or timer.limit != interval:
                self.interval_timer[STORY_SKIP_3.name] = Timer(interval)
                timer = self.interval_timer[STORY_SKIP_3.name]
            if not timer.reached():
                return False

        appear = STORY_SKIP_3.match_luma(self.device.image, offset=(20, 20), similarity=0.85)
        if appear and interval:
            timer.reset()
        return appear

    def _juu_express_steps(self):
        # 其余 2 个 JUU 速运按钮暂缺，后续补图后再补回。
        return [
            ('港口的帕特莉', 'port', self.move_for_pateli, JUU_EXPRESS_PATELI_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            ('栖风原野的奥布莱恩', 'mine_forest', self.move_for_aobulaien, JUU_EXPRESS_AOBULAIEN_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            ('晨露农场的梅莉', 'farm', self.move_for_meili, JUU_EXPRESS_MEILI_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            ('集会岛的莉莎', 'assembly', self.move_for_lisha, JUU_EXPRESS_LISHA_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            # 缺图：繁荫农圃的拉科尼娅
            # ('繁荫农圃的拉科尼娅', 'nursery', self.move_for_lakeniya, JUU_EXPRESS_LAKENIYA_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
            ('栖风原野的乔安', 'mine_forest', self.move_for_qiaoan, JUU_EXPRESS_QIAOAN_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            # 缺图：晨露农场的奥利匹克
            # ('晨露农场的奥利匹克', 'farm', self.move_for_aolipike, JUU_EXPRESS_AOLIPIKE_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            ('港口商区的阿莫玛', 'port_business', self.move_for_amoma, JUU_EXPRESS_AMOMA_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
            ('繁荫农圃的露西', 'nursery', self.move_for_luxi, JUU_EXPRESS_LUXI_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
        ]

    def _business_delivery_steps(self):
        return [
            ('港口商区的阿莫玛', 'port_business', self.move_for_amoma, BUSINESS_DELIVERY_AMOMA_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
            ('栖风原野的奥布莱恩', 'mine_forest', self.move_for_aobulaien, BUSINESS_DELIVERY_TWO_OPTION_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            ('集会岛的莉莎', 'assembly', self.move_for_lisha, BUSINESS_DELIVERY_TWO_OPTION_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            ('繁荫农圃的拉科尼娅', 'nursery', self.move_for_lakeniya, BUSINESS_DELIVERY_THREE_OPTION_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
            ('繁荫农圃的露西', 'nursery', self.move_for_luxi, BUSINESS_DELIVERY_THREE_OPTION_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
            ('港口的帕特莉', 'port', self.move_for_pateli, BUSINESS_DELIVERY_TWO_OPTION_INTERACT, ROUTE_TWO_OPTION_COMPLETE),
            ('啾咖啡餐厅的布莱梅', 'port', self.move_for_bulaimei, BUSINESS_DELIVERY_THREE_OPTION_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
            ('晨露农场的赫莫', 'farm', self.move_for_hemo, BUSINESS_DELIVERY_THREE_OPTION_INTERACT, ROUTE_THREE_OPTION_COMPLETE),
        ]

    def _enter_development_plan(self):
        """
        从岛屿手机页面进入开发计划页面。

        Pages:
            in: page_island_phone
            out: ISLAND_DEVELOPMENT_PLAN_CHECK
        """
        from module.island_daily_interact.assets import ISLAND_DEVELOPMENT_PLAN_CHECK, ISLAND_PHONE_DEVELOPMENT_PLAN

        self.ui_goto(page_island_phone, get_ship=False)
        for _ in self.loop(timeout=15):
            if self.appear(ISLAND_DEVELOPMENT_PLAN_CHECK):
                return True
            if self.appear_then_click(ISLAND_PHONE_DEVELOPMENT_PLAN, interval=2):
                continue
            if self._handle_island_reward_once():
                continue

        logger.warning('[岛屿-每日周任务] 进入开发计划页面超时')
        return False

    def _start_development_plan_template_task(self, task_template, task_check, tab_button, tab_check, tab_label, label):
        """
        进入开发计划页面后先切换到目标页签，再通过模板搜索启动指定任务。

        Args:
            task_template: 开发计划任务列表中的任务图标模板。
            task_check: 点击任务图标后的确认按钮。
            tab_button: 目标页签的切换按钮。
            tab_check: 目标页签切换后的激活检测按钮。
            tab_label: 目标页签日志名称。
            label: 日志名称。

        Returns:
            bool: 是否需要继续执行任务流程。
        """
        if not self._enter_development_plan():
            return False

        if not self._switch_development_plan_tab(tab_button=tab_button, tab_check=tab_check, label=tab_label):
            return False

        self.device.screenshot()
        task_button = self._match_development_plan_task_template(task_template)
        if task_button is None:
            return False

        logger.info(f'[岛屿-每日周任务] 检测到{label}，点击任务图标')
        self.device.click(task_button)
        for _ in self.loop(timeout=8):
            if self.appear_then_click(task_check, offset=(20, 20), interval=2):
                logger.info(f'[岛屿-每日周任务] {label}确认成功')
                return True
            if self._handle_island_reward_once():
                continue

        logger.warning(f'[岛屿-每日周任务] {label}确认按钮等待超时')
        return False

    def _detect_development_plan_template_task(self, task_template, tab_button, tab_check, tab_label, label):
        """
        进入开发计划页面后只检测指定任务图标，不点击任务确认按钮。

        Args:
            task_template: 开发计划任务列表中的任务图标模板。
            tab_button: 目标页签的切换按钮。
            tab_check: 目标页签切换后的激活检测按钮。
            tab_label: 目标页签日志名称。
            label: 日志名称。

        Returns:
            bool: 是否检测到目标任务图标。
        """
        if not self._enter_development_plan():
            return False

        if not self._switch_development_plan_tab(tab_button=tab_button, tab_check=tab_check, label=tab_label):
            return False

        self.device.screenshot()
        if self._match_development_plan_task_template(task_template) is None:
            return False

        logger.info(f'[岛屿-每日周任务] 检测到{label}任务图标')
        return True

    def _switch_development_plan_tab(self, tab_button, tab_check, label):
        """切换到开发计划目标页签，并确认页签已激活。"""
        logger.info(f'[岛屿-每日周任务] 切换到{label}页签')
        for _ in self.loop(timeout=12):
            if self.appear(tab_check):
                logger.info(f'[岛屿-每日周任务] {label}页签已激活')
                return True
            if self.appear_then_click(tab_button, interval=2):
                continue
            if self._handle_island_reward_once():
                continue

        logger.warning(f'[岛屿-每日周任务] 切换到{label}页签超时')
        return False

    def _match_development_plan_task_template(self, task_template):
        """在开发计划任务列表区域内匹配任务图标模板。"""
        region = crop(self.device.image, DEVELOPMENT_PLAN_TASK_LIST_AREA, copy=False)
        matches = task_template.match_multi(
            region,
            similarity=0.85,
            threshold=5,
            name='DEVELOPMENT_PLAN_TASK_TEMPLATE',
        )
        if not matches:
            return None

        matches.sort(key=lambda button: (button.area[1], button.area[0]))
        return matches[0].move(DEVELOPMENT_PLAN_TASK_LIST_AREA[:2])

    def _run_weekly_photo_once(self):
        from module.island_daily_interact.assets import (
            WEEKLY_PHOTO_CAMERA,
            WEEKLY_PHOTO_IDLE,
        )

        for index in range(3):
            logger.info(f'[岛屿-每日周任务] 每周照相第{index + 1}轮')
            self._click_weekly_photo_button(WEEKLY_PHOTO_CAMERA, '照相按钮')
            self._click_weekly_photo_button(WEEKLY_PHOTO_IDLE, '空闲按钮')

        for _ in self.loop(timeout=12):
            if self._handle_island_reward_once():
                continue
            if self.appear_then_click(ISLAND_BACK, interval=2):
                return True

        logger.warning('[岛屿-每日周任务] 每周照相通用奖励或返回按钮等待超时')
        return False

    def _click_weekly_photo_button(self, button, label):
        """每周照相页面按钮位置固定，直接点击，不做出现检测。"""
        self.device.screenshot()
        logger.info(f'[岛屿-每日周任务] 点击{label}')
        self.device.click(button)

    def _click_optional_interact(self, button, label, timeout=8):
        for _ in self.loop(timeout=timeout):
            if self.appear_then_click(button, interval=2):
                logger.info(f'[岛屿-每日周任务] 点击{label}')
                return True
            if self._handle_island_reward_once():
                continue

        return False

    def _click_optional_interact_or_complete(self, interact_button, complete_button, label, timeout=8):
        for _ in self.loop(timeout=timeout):
            if self.appear_then_click(interact_button, interval=2):
                logger.info(f'[岛屿-每日周任务] 点击{label}')
                return 'clicked'
            if self.appear(complete_button, offset=(20, 20)):
                logger.info(f'[岛屿-每日周任务] {label}已完成，进入下一步')
                return 'complete'
            if self._handle_island_reward_once():
                continue

        return 'missing'

    def _handle_island_reward_optional(self, timeout=6):
        handled = False
        for _ in self.loop(timeout=timeout):
            if self._handle_island_reward_once():
                handled = True
                continue
        return handled

    def _handle_island_reward_once(self):
        if self.appear(GET_ITEMS_ISLAND, offset=(20, 20)):
            logger.info('[岛屿-每日周任务] 检测到岛屿奖励页面，点击安全区域关闭')
            self.device.click(ISLAND_CLICK_SAFE_AREA)
            return True
        if self.appear(ISLAND_GET, offset=(20, 20)):
            logger.info('[岛屿-每日周任务] 检测到岛屿领取页面，点击安全区域关闭')
            self.device.click(ISLAND_CLICK_SAFE_AREA)
            return True
        return False

    def _click_safe_area_twice(self):
        for _ in range(2):
            self.device.screenshot()
            self.device.click(ISLAND_CLICK_SAFE_AREA)

    def _back_to_island_phone_from_development_plan(self):
        logger.info('[岛屿-每日周任务] 退出开发计划页面')
        for _ in self.loop(timeout=8):
            if self.appear(ISLAND_PHONE_CHECK):
                return True
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self._handle_island_reward_once():
                continue
        logger.warning('[岛屿-每日周任务] 退出开发计划页面超时')
        return False

    def _back_to_island_phone(self):
        logger.info('[岛屿-每日周任务] 返回岛屿手机页面')
        for _ in self.loop(timeout=20):
            if self.appear(ISLAND_PHONE_CHECK):
                return True
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self._handle_island_reward_once():
                continue
        logger.warning('[岛屿-每日周任务] 返回岛屿手机页面超时')
        return False

    def _delay_to_next_day(self):
        target = current_time().replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= current_time():
            target += timedelta(days=1)
        self.config.task_delay(target=target)
        logger.info(f'[岛屿-每日周任务] 下次岛屿每日互动运行时间: {target}')
