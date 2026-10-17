"""紧急委托 / 三油低耗任务：在钻石打捞流程上增加周期出击次数限制。

规则为「每 N 小时最多 M 次」：
- 从首次启用开始，每 N 小时为一个周期；
- 每个周期最多完成 M 次战役运行（异常中断不计）；
- 次数先达到时，等待本周期结束后自动进入下一周期；
- 时间先达到时，下一轮从新周期重新计数；
- N 或 M 为 0 时关闭限制，保持原有行为。
"""

from module.campaign.gems_farming import GemsFarming
from module.campaign.farm_cycle import FarmCycleLimit
from module.logger import logger


class GemsFarmingCycle(GemsFarming):
    """周期出击限制运行器。

    父类提供紧急委托 / 三油低耗的选船、换船、退役和战役运行流程；
    本类只在任务入口和单次战役结束处插入周期次数控制。
    """

    @property
    def cycle_limit(self):
        """惰性创建周期限制对象，确保每个任务实例共享同一份状态。"""
        if not hasattr(self, '_farm_cycle_limit'):
            self._farm_cycle_limit = FarmCycleLimit(self.config)
        return self._farm_cycle_limit

    def run(self, name, folder='campaign_main', mode='normal', total=0):
        """运行当前任务，并在进入战役前处理周期额度。"""
        cycle = self.cycle_limit
        cycle.refresh()
        if cycle.is_blocked:
            logger.hr('触发停止条件: 周期出击次数', level=1)
            cycle.defer()
            return

        return super().run(name=name, folder=folder, mode=mode, total=total)

    def triggered_stop_condition(self, oil_check=True):
        """在父类停止条件之前检查本周期剩余出击次数。"""
        cycle = self.cycle_limit
        cycle.refresh()
        if cycle.is_blocked:
            logger.hr('触发停止条件: 周期出击次数', level=1)
            cycle.defer()
            return True

        return super().triggered_stop_condition(oil_check=oil_check)

    def after_campaign_run(self):
        """每次战役流程正常返回后扣减一周期次数。"""
        super().after_campaign_run()
        self.cycle_limit.consume()
