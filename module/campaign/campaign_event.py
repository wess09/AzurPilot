import re
from datetime import datetime

from module.campaign.campaign_status import CampaignStatus
from module.config.config_updater import COALITIONS, EVENTS, GEMS_FARMINGS, HOSPITAL, MARITIME_ESCORTS, RAIDS
from module.config.utils import DEFAULT_TIME
from module.logger import logger
from module.notify import handle_notify
from module.ui.assets import CAMPAIGN_MENU_NO_EVENT
from module.ui.page import page_campaign_menu, page_coalition, page_event, page_sp
from module.war_archives.assets import WAR_ARCHIVES_CAMPAIGN_CHECK


class CampaignEvent(CampaignStatus):
    def _reset_gems_farming(self, tasks):
        """
        活动结束时将 GemsFarming 重置为 2-4。

        Args:
            tasks (list[str]): 任务名称列表。
        """
        for task in tasks:
            if task not in GEMS_FARMINGS:
                continue
            name = self.config.cross_get(keys=f'{task}.Campaign.Name', default='2-4')
            if not self.stage_is_main(name):
                logger.info(f'Reset GemsFarming to 2-4')
                self.config.cross_set(keys=f'{task}.Campaign.Name', value='2-4')
                self.config.cross_set(keys=f'{task}.Campaign.Event', value='campaign_main')

    def _disable_tasks(self, tasks):
        """
        禁用指定任务列表中的任务。

        Args:
            tasks (list[str]): 任务名称列表。
        """
        with self.config.multi_set():
            # 禁用普通活动任务
            for task in tasks:
                if task in GEMS_FARMINGS:
                    continue
                keys = f'{task}.Scheduler.Enable'
                logger.info(f'Disable task `{task}`')
                self.config.cross_set(keys=keys, value=False)
                keys = f'{task}.Emotion.Fleet1Onsen'
                self.config.cross_set(keys=keys, value=False)
                keys = f'{task}.Emotion.Fleet2Onsen'
                self.config.cross_set(keys=keys, value=False)

            # 重置 GemsFarming
            self._reset_gems_farming(tasks)

            logger.info(f'Reset event time limit')
            self.config.cross_set(keys='EventGeneral.EventGeneral.TimeLimit', value=DEFAULT_TIME)

    def event_pt_limit_triggered(self):
        """
        检查活动 PT 是否达到限制。

        Returns:
            bool: 是否触发 PT 限制。

        Pages:
            in: page_event or page_sp
        """
        # 部分配置可能使用 "100,000" 这种带逗号的格式
        limit = int(
            re.sub(r'[,.\'"，。]', '', str(self.config.EventGeneral_PtLimit))
        )
        tasks = EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS + HOSPITAL
        command = self.config.Scheduler_Command
        if limit <= 0 or command not in tasks:
            self.get_event_pt()
            return False
        if command in GEMS_FARMINGS and self.stage_is_main(self.config.Campaign_Name):
            self.get_event_pt()
            return False

        pt = self.get_event_pt()
        if pt >= limit and limit > 0:
            logger.attr('Event_PT_limit', f'{pt}/{limit}')
            logger.hr(f'Reach event PT limit: {limit}')
            self._disable_tasks(tasks)
            return True
        else:
            return False

    def coin_limit_triggered(self):
        """
        检查金币数量是否达到 StopCondition.CoinLimit 限制。

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
            logger.warning('Coin not found')
            return False

        logger.attr('Coin_limit', f'{coin}/{limit}')
        if coin >= limit:
            logger.hr(f'Reach coin limit: {limit}')
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
        """
        检查活动时间是否达到限制。

        Returns:
            bool: 是否触发时间限制。

        Pages:
            in: page_event or page_sp
        """
        limit = self.config.EventGeneral_TimeLimit
        tasks = EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS + MARITIME_ESCORTS + HOSPITAL
        command = self.config.Scheduler_Command
        if command not in tasks or limit == DEFAULT_TIME:
            return False
        if command in GEMS_FARMINGS and self.stage_is_main(self.config.Campaign_Name):
            return False

        now = datetime.now().replace(microsecond=0)
        logger.attr('Event_time_limit', f'{now} -> {limit}')
        if now > limit:
            logger.hr(f'Reach event time limit: {limit}')
            self._disable_tasks(tasks)
            return True
        else:
            return False

    def triggered_task_balancer(self):
        """
        检查任务均衡器是否触发。

        Returns:
            bool: 是否触发任务切换。

        Pages:
            in: page_event or page_sp
        """
        from module.config.deep import deep_get
        limit = self.config.TaskBalancer_CoinLimit
        coin = deep_get(self.config.data, 'Dashboard.Coin.Value')
        logger.attr('Coin Count', coin)

        # 检查金币
        if coin == 0:
            # 避免 OCR 识别错误/返回零值
            logger.warning('Coin not found')
            return False
        else:
            if self.is_balancer_task():
                if coin < limit:
                    logger.hr('Reach Coin limit')
                    return True
                else:
                    return False
            else:
                return False

    def handle_task_balancer(self):
        if self.config.TaskBalancer_Enable and self.triggered_task_balancer():
            self.config.task_delay(minute=5)
            next_task = self.config.TaskBalancer_TaskCall
            logger.hr(f'TaskBalancer triggered, switching task to {next_task}')
            self.config.task_call(next_task)
            self.config.task_stop()

    def is_event_entrance_available(self):
        """
        检查活动入口是否可用。

        Returns:
            bool: 可用返回 True。

        Raises:
            TaskEnd: 不可用时抛出。
        """
        if self.appear(CAMPAIGN_MENU_NO_EVENT, offset=(20, 20)):
            logger.info('Event unavailable, disable task')
            tasks = EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS + HOSPITAL
            self._disable_tasks(tasks)
            self.config.task_stop()
        else:
            logger.info('Event available')
            return True

    def ui_goto_event(self):
        # 已在 page_event，跳过活动检查。
        if self.ui_get_current_page() == page_event:
            if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
                logger.info('At war archives')
                self.ui_goto_main()
            else:
                logger.info('Already at page_event')
                return True
        self.ui_goto(page_campaign_menu)
        # 检查活动是否可用
        if self.is_event_entrance_available():
            self.ui_goto(page_event)
            return True

    def ui_goto_sp(self):
        # 已在 page_sp，跳过活动检查。
        if self.ui_get_current_page() == page_sp:
            if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
                logger.info('At war archives')
                self.ui_goto_main()
            else:
                logger.info('Already at page_sp')
                return True
        self.ui_goto(page_campaign_menu)
        # 检查活动是否可用
        if self.is_event_entrance_available():
            self.ui_goto(page_sp)
            return True

    def ui_goto_coalition(self):
        # 已在 page_coalition，跳过活动检查。
        if self.ui_get_current_page() == page_coalition:
            logger.info('Already at page_coalition')
            return True
        else:
            self.ui_goto(page_campaign_menu)
            # 检查活动是否可用
            if self.is_event_entrance_available():
                self.ui_goto(page_coalition)
                return True

    def disable_raid_on_event(self):
        """
        进入活动时禁用突袭（或联动）任务，防止用户忘记在突袭结束后手动禁用。
        """
        command = self.config.Scheduler_Command
        if command not in EVENTS + GEMS_FARMINGS:
            return False
        if command in GEMS_FARMINGS and self.stage_is_main(self.config.Campaign_Name):
            return False

        tasks = RAIDS + COALITIONS + MARITIME_ESCORTS
        tasks = [t for t in tasks if self.config.is_task_enabled(t)]
        if tasks:
            logger.info('New event ongoing, disable old raid event tasks')
            self._disable_tasks(tasks)
            return True
        else:
            return False

    def disable_event_on_raid(self):
        """
        进入突袭或联动时禁用活动任务，防止用户忘记在活动结束后手动禁用。
        """
        command = self.config.Scheduler_Command
        if command not in RAIDS + COALITIONS + MARITIME_ESCORTS:
            return False

        events = [t for t in EVENTS if self.config.is_task_enabled(t)]
        gems = [t for t in GEMS_FARMINGS if self.config.is_task_enabled(t)]
        with self.config.multi_set():
            if events:
                logger.info('New raid event ongoing, disable old event tasks')
                self._disable_tasks(events)
            if gems:
                self._reset_gems_farming(gems)
        return events or gems

    @staticmethod
    def stage_is_main(name) -> bool:
        """
        判断给定关卡名称是否为主线关卡。

        Args:
            name (str): 关卡名称，如 `7-2`、`D3`。
        """
        regex_main = re.compile(r'\d{1,2}[-_]\d')
        return bool(regex_main.search(name))
