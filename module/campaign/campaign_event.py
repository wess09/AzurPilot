"""战役活动管理模块。

管理活动战役的配置和状态，包括：
- 活动结束时的自动禁用和配置重置
- 低耗活动任务结束时按配置切换主线，或停用并保留活动关卡
- 活动推送通知
- 活动页面的导航检测

支持的活动类型：
- 普通活动（Event）
- 突袭活动（Raid）
- 联动活动（Coalition）
- 作战档案（War Archives）
- 医院活动（Hospital）
- 海上护卫（MaritimeEscort）

继承自 CampaignStatus，提供活动状态检测能力。
"""

import os
import re
from datetime import datetime

from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.config.config_updater import COALITIONS, EVENTS, GEMS_FARMINGS, HOSPITAL, MARITIME_ESCORTS, RAIDS
from module.config.time_source import now as current_time
from module.config.utils import DEFAULT_TIME
from module.logger import logger
from module.notify import handle_notify
from module.ui.assets import BACK_ARROW, CAMPAIGN_MENU_GOTO_EVENT, CAMPAIGN_MENU_NO_EVENT
from module.ui.page import page_campaign_menu, page_coalition, page_event, page_sp
from module.war_archives.assets import WAR_ARCHIVES_CAMPAIGN_CHECK


EVENT_PT_TASKS = EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS + HOSPITAL
LEGACY_EVENT_TIME_LIMIT = datetime(2020, 1, 1, 0, 0)


class CampaignEvent(CampaignStatus):
    """战役活动管理器。

    处理活动的生命周期管理，包括活动检测、禁用、配置重置和通知。
    """
    def _disable_tasks(self, tasks):
        """
        禁用活动任务；低耗任务按各自配置切换主线或停止。

        Args:
            tasks (list[str]): 任务名称列表。
        """
        with self.config.multi_set():
            for task in tasks:
                if task in GEMS_FARMINGS:
                    # 原本就在刷主线的任务不受活动收尾影响。
                    name = self.config.cross_get(keys=f'{task}.Campaign.Name', default='2-4')
                    if self.stage_is_main(name):
                        continue
                    stage = str(self.config.cross_get(
                        keys=f'{task}.GemsFarming.EventFallbackStage', default='2-4')).strip().lower()
                    match = re.fullmatch(r'(?:campaign_)?([1-9]\d?)[-_]([1-4])', stage)
                    if match and os.path.isfile(
                            f'./campaign/campaign_main/campaign_{match[1]}_{match[2]}.py'):
                        stage = f'{match[1]}-{match[2]}'
                        logger.info(f'[活动战役] 将 `{task}` 切换到主线 {stage}')
                        self.config.cross_set(keys=f'{task}.Campaign.Name', value=stage)
                        self.config.cross_set(keys=f'{task}.Campaign.Event', value='campaign_main')
                        # 保留启用状态和调度时间，不重新启用用户已关闭的任务。
                        continue
                    if stage != '0':
                        logger.warning(f'[活动战役] `{task}` 的后续关卡无效: {stage}，停止任务')
                keys = f'{task}.Scheduler.Enable'
                logger.info(f'[活动战役] 禁用任务 `{task}`')
                self.config.cross_set(keys=keys, value=False)
                keys = f'{task}.Emotion.Fleet1Onsen'
                self.config.cross_set(keys=keys, value=False)
                keys = f'{task}.Emotion.Fleet2Onsen'
                self.config.cross_set(keys=keys, value=False)

            logger.info(f'[活动战役] 重置活动时间限制')
            self.config.cross_set(keys='EventGeneral.EventGeneral.TimeLimit', value=DEFAULT_TIME)

    def get_event_pt_limit(self):
        """返回当前任务适用的 PT 上限。

        不适用时返回 0，不读取游戏画面。

        Returns:
            int: PT 上限数值，不限制时返回 0。
        """
        # 部分配置可能使用 "100,000" 这种带逗号的格式
        limit = int(
            re.sub(r'[,.\'"，。]', '', str(self.config.EventGeneral_PtLimit))
        )
        command = self.config.Scheduler_Command
        if command not in EVENT_PT_TASKS:
            return 0
        if command in GEMS_FARMINGS and self.stage_is_main(self.config.Campaign_Name):
            return 0
        return limit

    def event_pt_limit_triggered(self):
        """检查活动 PT 是否达到限制。

        Returns:
            bool: 是否触发 PT 限制。

        Pages:
            in: page_event or page_sp
        """
        limit = self.get_event_pt_limit()
        command = self.config.Scheduler_Command
        # 主线打捞任务在普通战役页（page_campaign），该页右上角区域并不显示活动 PT。
        # 直接跳过 PT 读取与上限判断，避免把页面其他数字误读成 PT（例如读成 1）。
        if command in GEMS_FARMINGS and self.stage_is_main(self.config.Campaign_Name):
            return False
        if limit <= 0:
            self.get_event_pt()
            return False

        pt = self.get_event_pt()
        if pt >= limit and limit > 0:
            logger.attr('活动PT限制', f'{pt}/{limit}')
            logger.hr(f'达到活动PT上限: {limit}')
            self._disable_tasks(EVENT_PT_TASKS)
            return True
        else:
            return False

    def coin_limit_triggered(self):
        """检查金币数量是否达到 StopCondition.CoinLimit 限制。

        Returns:
            bool: 是否触发金币限制。
        """
        limit = int(
            re.sub(r'[,.\'"，。]', '', str(self.config.StopCondition_CoinLimit))
        )
        if limit <= 0:
            return False

        coin = self.get_coin()
        if coin == 0:
            # 避免 OCR 识别错误/返回零值
            logger.warning('[活动战役] 未找到物资')
            return False

        logger.attr('物资限制', f'{coin}/{limit}')
        if coin >= limit:
            logger.hr(f'达到物资上限: {limit}')
            self.config.task_delay(minute=(120, 240))
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"AzurPilot <{self.config.config_name}> campaign delayed",
                content=f"<{self.config.config_name}> {self.config.Campaign_Name} reached coin limit"
            )
            return True
        else:
            return False

    def event_time_limit_triggered(self):
        """检查活动时间是否达到限制。

        Returns:
            bool: 是否触发时间限制。

        Pages:
            in: page_event or page_sp
        """
        limit = self.config.EventGeneral_TimeLimit
        tasks = EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS + MARITIME_ESCORTS + HOSPITAL
        command = self.config.Scheduler_Command
        # 2020-01-01 曾是配置界面生成的“不限制”默认值；全局默认时间改为
        # 2023-01-01 后，存量配置仍需按不限制处理，避免启动活动任务即被停用。
        if command not in tasks or limit in (DEFAULT_TIME, LEGACY_EVENT_TIME_LIMIT):
            return False
        if command in GEMS_FARMINGS and self.stage_is_main(self.config.Campaign_Name):
            return False

        now = current_time().replace(microsecond=0)
        logger.attr('活动时间限制', f'{now} -> {limit}')
        if now > limit:
            logger.hr(f'达到活动时间限制: {limit}')
            self._disable_tasks(tasks)
            return True
        else:
            return False

    def triggered_task_balancer(self):
        """检查任务均衡器是否触发。

        Returns:
            bool: 是否触发任务切换。

        Pages:
            in: page_event or page_sp
        """
        from module.config.deep import deep_get
        limit = self.config.TaskBalancer_CoinLimit
        coin = deep_get(self.config.data, 'Dashboard.Coin.Value')
        logger.attr('物资数量', coin)

        # 检查金币
        if coin == 0:
            # 避免 OCR 识别错误/返回零值
            logger.warning('[活动战役] 未找到物资')
            return False
        else:
            if self.is_balancer_task():
                if coin < limit:
                    logger.hr('达到物资上限')
                    return True
                else:
                    return False
            else:
                return False

    def handle_task_balancer(self):
        """处理任务均衡器逻辑。

        若已启用且触发条件满足，则延迟当前任务并调度目标任务。
        """
        if self.config.TaskBalancer_Enable and self.triggered_task_balancer():
            self.config.task_delay(minute=5)
            next_task = self.config.TaskBalancer_TaskCall
            logger.hr(f'任务均衡器触发，切换任务到 {next_task}')
            self.config.task_call(next_task)
            self.config.task_stop()

    def is_event_entrance_available(self):
        """检查活动入口是否可用。

        Returns:
            bool: 可用返回 True。
        """
        if self.appear(CAMPAIGN_MENU_NO_EVENT, offset=(20, 20)):
            logger.info('[活动战役] 活动不可用，禁用任务')
            tasks = EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS + HOSPITAL
            self._disable_tasks(tasks)
            self.config.task_stop()
        else:
            logger.info('[活动战役] 活动可用')
            return True

    @staticmethod
    def _campaign_banner_success_pages(destination):
        """
        横幅导航的成功页面。

        剧情活动的 EVENT 与 SP 是同一活动 UI 的不同分页，
        进入其中任一页都视为到达活动，后续由章节切换处理。
        """
        if destination in (page_event, page_sp):
            return (page_event, page_sp)
        return (destination,)

    @classmethod
    def _campaign_banner_wrong_pages(cls, destination):
        """
        与目标共用出击菜单横幅、但不是目标活动的页面。

        2026.02.12 后突袭入口迁到出击菜单，与剧情/联动/医院/RPG
        共用 CAMPAIGN_MENU_GOTO_EVENT。横幅当前展示哪一个，点进去就是哪一个。
        """
        success = set(cls._campaign_banner_success_pages(destination))
        pages = []
        for page, button in page_campaign_menu.links.items():
            if button == CAMPAIGN_MENU_GOTO_EVENT and page not in success:
                pages.append(page)
        return pages

    def _ui_goto_campaign_banner_page(self, destination, skip_first_screenshot=True):
        """
        从出击菜单活动横幅进入指定活动页。

        若横幅当前是突袭等非目标活动，点进去会触发
        CAMPAIGN_MENU_GOTO_EVENT 与 BACK_ARROW 交替点击。
        此时返回出击菜单并滑动横幅，再尝试进入。

        Args:
            destination: 目标页面，如 page_event、page_sp、page_coalition。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否到达目标活动。

        Pages:
            in: page_campaign_menu
            out: destination
        """
        success_pages = self._campaign_banner_success_pages(destination)
        wrong_pages = self._campaign_banner_wrong_pages(destination)
        pending_swipe = False
        swipe_count = 0
        timeout = Timer(40, count=80).start()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            for page in success_pages:
                if page.check_button and self.ui_page_appear(page, offset=(30, 30)):
                    logger.info(f'[活动战役] 到达页面: {page}')
                    return True

            if timeout.reached():
                logger.warning('[活动战役] 从出击菜单进入活动超时')
                return False

            # 点进了突袭/联动等错误活动，返回后准备切横幅
            wrong_hit = False
            for page in wrong_pages:
                if page.check_button is None:
                    continue
                if self.appear(page.check_button, offset=(30, 30)):
                    logger.info(f'[活动战役] 横幅进入了 {page}，返回出击菜单')
                    pending_swipe = True
                    wrong_hit = True
                    back = page.links.get(page_campaign_menu, BACK_ARROW)
                    if self.appear_then_click(back, offset=(30, 30), interval=2):
                        timeout.reset()
                    break
            if wrong_hit:
                continue

            # 出击菜单：先滑动横幅，再点击进入
            if self.appear(page_campaign_menu.check_button, offset=(30, 30)):
                if pending_swipe:
                    if swipe_count >= 4:
                        logger.warning('[活动战役] 滑动出击菜单横幅后仍未到达目标活动')
                        return False
                    logger.info('[活动战役] 滑动出击菜单活动横幅')
                    self.device.swipe_vector(
                        (-350, 0),
                        box=CAMPAIGN_MENU_GOTO_EVENT.button,
                        name='CAMPAIGN_MENU_EVENT_BANNER',
                    )
                    swipe_count += 1
                    pending_swipe = False
                    timeout.reset()
                    continue
                if self.appear_then_click(CAMPAIGN_MENU_GOTO_EVENT, offset=(30, 30), interval=3):
                    timeout.reset()
                    continue

            if self.ui_additional():
                timeout.reset()
                continue

    def _ui_goto_event_from_menu(self, destination):
        """
        先到出击菜单，确认活动入口可用，再经横幅进入目标活动。

        Args:
            destination: page_event / page_sp / page_coalition。

        Returns:
            bool: 是否到达目标活动。
        """
        self.ui_goto(page_campaign_menu)
        if not self.is_event_entrance_available():
            return False
        if self._ui_goto_campaign_banner_page(destination):
            return True
        logger.error('[活动战役] 无法从出击菜单进入目标活动，横幅可能被突袭占用')
        self.config.task_delay(minute=30)
        self.config.task_stop()

    def ui_goto_event(self):
        """导航至活动主页面。

        Returns:
            bool: 成功到达返回 True。

        Pages:
            in: 任意页面
            out: page_event
        """
        # 已在剧情活动 UI（含 SP 分页），跳过活动检查。
        current = self.ui_get_current_page()
        if current in (page_event, page_sp):
            if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
                logger.info('[活动战役] 在作战档案')
                self.ui_goto_main()
            else:
                logger.info('[活动战役] 已在活动页面')
                return True
        return self._ui_goto_event_from_menu(page_event)

    def ui_goto_sp(self):
        """导航至 SP 活动页面。

        Returns:
            bool: 成功到达返回 True。

        Pages:
            in: 任意页面
            out: page_sp
        """
        # 已在剧情活动 UI（含 EVENT 分页），跳过活动检查。
        current = self.ui_get_current_page()
        if current in (page_event, page_sp):
            if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
                logger.info('[活动战役] 在作战档案')
                self.ui_goto_main()
            else:
                logger.info('[活动战役] 已在SP页面')
                return True
        return self._ui_goto_event_from_menu(page_sp)

    def ui_goto_coalition(self):
        """导航至联动作战页面。

        Returns:
            bool: 成功到达返回 True。

        Pages:
            in: 任意页面
            out: page_coalition
        """
        # 已在 page_coalition，跳过活动检查。
        if self.ui_get_current_page() == page_coalition:
            logger.info('[活动战役] 已在联动页面')
            return True
        return self._ui_goto_event_from_menu(page_coalition)

    def disable_raid_on_event(self):
        """进入活动时禁用突袭（或联动）任务，防止用户忘记在突袭结束后手动禁用。

        Returns:
            bool: 是否禁用了突袭任务。
        """
        command = self.config.Scheduler_Command
        if command not in EVENTS + GEMS_FARMINGS:
            return False
        if command in GEMS_FARMINGS and self.stage_is_main(self.config.Campaign_Name):
            return False

        tasks = RAIDS + COALITIONS + MARITIME_ESCORTS
        tasks = [t for t in tasks if self.config.is_task_enabled(t)]
        if tasks:
            logger.info('[活动战役] 新活动进行中，禁用旧突袭活动任务')
            self._disable_tasks(tasks)
            return True
        else:
            return False

    def disable_event_on_raid(self):
        """进入突袭或联动时禁用活动任务，防止用户忘记在活动结束后手动禁用。

        Returns:
            bool: 是否禁用了活动任务。
        """
        command = self.config.Scheduler_Command
        if command not in RAIDS + COALITIONS + MARITIME_ESCORTS:
            return False

        events = [t for t in EVENTS if self.config.is_task_enabled(t)]
        gems = [t for t in GEMS_FARMINGS if self.config.is_task_enabled(t)
                and not self.stage_is_main(self.config.cross_get(keys=f'{t}.Campaign.Name', default='2-4'))]
        if events or gems:
            logger.info('[活动战役] 新突袭活动进行中，禁用旧活动任务')
            self._disable_tasks(events + gems)
        return bool(events or gems)

    @staticmethod
    def stage_is_main(name) -> bool:
        """判断给定关卡名称是否为主线关卡。

        Args:
            name (str): 关卡名称，如 `7-2`、`D3`。

        Returns:
            bool: 若为主线关卡返回 True，否则返回 False。
        """
        regex_main = re.compile(r'^(?:campaign_)?\d{1,2}[-_]\d')
        return bool(regex_main.match(str(name).strip().lower()))
