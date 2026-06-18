import os

from module.config.config import TaskEnd
from module.event.base import EventBase
from module.exception import RequestHumanTakeover
from module.logger import logger


class CampaignSP(EventBase):
    """活动 SP 关卡的执行器。

    执行单个 SP 关卡（每日限定 1 次），执行完毕或无法进入时延迟到次日服务器刷新。

    Pages:
        in: page_event
        out: page_event
    """

    def run(self, *args, **kwargs):
        """执行活动 SP 关卡流程。

        流程：检查 SP 地图文件是否存在 → 执行 SP 关卡 → 延迟到次日。
        """
        # 检查当前活动是否包含 SP 关卡
        if not os.path.exists(f'./campaign/{self.config.Campaign_Event}/sp.py'):
            logger.info(f'./campaign/{self.config.Campaign_Event}/sp.py not exists')
            logger.info(f'This event do not have SP, skip')
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        try:
            super().run(name=self.config.Campaign_Name, folder=self.config.Campaign_Event, total=1)
        except TaskEnd:
            # 捕获任务切换，正常中断
            pass
        except RequestHumanTakeover:
            # 每日 SP 已完成或无法进入，延迟到次日
            logger.info('Daily SP already completed or unable to enter')
            logger.info('Delaying task to next day')
            self.config.task_delay(server_update=True)
            return

        # 根据执行结果决定后续调度
        if self.run_count > 0:
            # SP 执行成功，延迟到次日服务器刷新
            logger.info(f'SP completed successfully, run_count={self.run_count}')
            self.config.task_delay(server_update=True)
        else:
            # SP 未成功执行（可能今日已完成），延迟到次日而非停止
            logger.info('SP failed to execute, possibly already completed today')
            logger.info('Delaying task to next day')
            self.config.task_delay(server_update=True)
