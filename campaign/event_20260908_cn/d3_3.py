"""幽影迷城 D3：仅清除三个塞壬后撤退。"""

from module.logger import logger

from .d3 import Campaign as CampaignBase
from .d3 import Config as ConfigBase


class Config(ConfigBase):
    # 自动搜索会绕过自定义战斗策略，无法保证只打塞壬和三战撤退。
    Campaign_UseAutoSearch = False


class Campaign(CampaignBase):
    # 复用 D3 的完整刷新表：开局两个塞壬，第二战后再刷新一个。
    # 不截断第三战后的普通敌人刷新，否则战斗结算会错误地跳过搜索动画。

    def battle_function(self):
        """按实时位置清除塞壬，避免全清模式或默认策略攻击普通敌人。

        Pages: in: 地图, out: 地图或关卡选择页。

        Returns:
            bool: 是否完成了一场战斗；撤退由 CampaignEnd 结束本轮出击。
        """
        # 战后敌人移动可能抛出 MapEnemyMoved，下一轮仍必须先检查撤退。
        if self.battle_count >= 3:
            logger.info('[D3三战撤退] 已完成三场战斗，撤退')
            self.withdraw()

        if self.siren_count != self.battle_count:
            logger.warning('[D3三战撤退] 战斗计数与塞壬计数不一致，撤退')
            self.withdraw()

        battle_count = self.battle_count
        # 使用识别和移动追踪后的目标，不假定第三个塞壬的刷新坐标。
        self.clear_siren()
        if self.battle_count == battle_count:
            logger.info('[D3三战撤退] 未完成塞壬战斗，重新扫描刷新目标')
            self.full_scan(must_scan=self.map.camera_data)
            self.find_path_initial()
            self.clear_siren()

        if self.battle_count >= 3:
            logger.info('[D3三战撤退] 第三场战斗结束，立即撤退')
            self.withdraw()

        if self.battle_count > battle_count:
            return True

        # 刷新目标仍未识别或不可达时结束本轮，不用普通敌人凑三战。
        logger.warning('[D3三战撤退] 未找到可攻击的塞壬，撤退')
        self.withdraw()
        return False

    @property
    def _map_battle(self):
        """按三场战斗计算出击前的心情消耗。"""
        return 3
