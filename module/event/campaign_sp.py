"""活动 SP 关卡执行模块。

执行活动的 SP（Special）关卡，每日限定 1 次。
SP 关卡通常需要完成所有前置关卡后才可解锁，难度较高但奖励丰厚。

流程简单：检查 sp.py 地图文件是否存在 → 执行 1 次 → 延迟到次日。
如果活动没有 SP 关卡或已执行过，自动延迟到次日服务器刷新。

配置路径: Campaign.Name (战役名称)
"""

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
            logger.info(f'[活动-SP] ./campaign/{self.config.Campaign_Event}/sp.py 不存在')
            logger.info(f'此活动无SP，跳过')
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        try:
            super().run(name=self.config.Campaign_Name, folder=self.config.Campaign_Event, total=1)
        except TaskEnd:
            # 捕获任务切换，正常中断
            pass
        except RequestHumanTakeover as error:
            from module.config.recovery import check_error_recovery
            check_error_recovery(self.config, error)
            # 每日 SP 已完成或无法进入，延迟到次日
            logger.info('每日SP已完成或无法进入')
            logger.info('延迟任务到明天')
            self.config.task_delay(server_update=True)
            return

        # 根据执行结果决定后续调度
        if self.run_count > 0:
            # SP 执行成功，延迟到次日服务器刷新
            logger.info(f'已完成, run_count={self.run_count}')
            self.config.task_delay(server_update=True)
        else:
            # SP 未成功执行（可能今日已完成），延迟到次日而非停止
            logger.info('执行失败，可能今天已完成')
            logger.info('延迟任务到明天')
            self.config.task_delay(server_update=True)
