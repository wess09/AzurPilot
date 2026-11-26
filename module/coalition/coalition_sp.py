"""联动活动 SP 关卡任务模块。

封装联动活动 SP 模式的任务调度逻辑。调用 Coalition 基类
以 SP 难度执行一次战斗，完成后根据执行结果设置下一次
任务延迟或直接停止任务。
"""

from module.coalition.coalition import Coalition
from module.config.config import TaskEnd


class CoalitionSP(Coalition):
    """联合出击 SP 关卡任务处理器。"""

    def run(self, *args, **kwargs):
        """执行 SP 关卡单次挑战任务。

        运行 SP 难度一次，若成功挑战或今日次数已用完则延期至次日，否则停止任务。
        """
        self.sp_attempt_used = False
        try:
            super().run(mode='sp', total=1)
        except TaskEnd:
            # 捕获任务切换信号
            pass
        if self.run_count > 0 or self.sp_attempt_used:
            self.config.task_delay(server_update=True)
        else:
            self.config.task_stop()
