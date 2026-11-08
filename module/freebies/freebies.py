"""
免费福利（Freebies）任务调度模块。

负责统一调度所有免费福利相关的子模块，按顺序执行：
- 战斗通行证（Battle Pass）奖励收集
- 数据钥匙（Data Key）收集
- 邮件（Mail）奖励领取
- 补给包（Supply Pack）收集

各子模块根据用户配置决定是否执行，全部完成后设置下次运行时间。
"""
from module.base.base import ModuleBase
from module.freebies.battle_pass import BattlePass
from module.freebies.data_key import DataKey
from module.freebies.mail_white import MailWhite
from module.freebies.supply_pack import SupplyPack_250814
from module.logger import logger


class Freebies(ModuleBase):
    """
    免费福利任务总调度器。

    按优先级依次执行战斗通行证、数据钥匙、邮件和补给包的收集。
    每个子模块独立检查用户配置中的开关，决定是否执行。
    全部子模块执行完毕后，通过 `task_delay(server_update=True)` 设置
    下次运行时间为服务器刷新时间。
    """
    def run(self):
        """执行所有已开启的免费福利收集任务。

        依次调用通行证、数据钥匙、邮件以及补给包收集模块，
        完成后将任务延迟至次日服务器刷新。
        """
        if self.config.BattlePass_Collect:
            logger.hr('大月卡', level=1)
            BattlePass(self.config, self.device).run()

        if self.config.DataKey_Collect:
            logger.hr('档案秘钥', level=1)
            DataKey(self.config, self.device).run()

        logger.hr('邮件', level=1)
        MailWhite(self.config, self.device).run()

        if self.config.SupplyPack_Collect:
            logger.hr('优惠礼包', level=1)
            SupplyPack_250814(self.config, self.device).run()

        self.config.task_delay(server_update=True)
