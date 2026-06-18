from module.shop.assets import *
from module.shop.shop_core import CoreShop_250814
from module.shop.shop_general import GeneralShop_250814
from module.shop.shop_guild import GuildShop_250814
from module.shop.shop_medal import MedalShop2_250814
from module.shop.shop_merit import MeritShop_250814
from module.shop.ui import ShopUI
from module.logger import logger


class RewardShop(ShopUI):
    """奖励商店调度器。

    Pages: in: page_shop
    """

    def run_frequent(self):
        """运行高频商店购买任务。

        Pages: in: page_shop (general shop tab)

        只处理通用商店，用于频繁执行的购买。
        """
        self.ui_goto_shop()
        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_GENERAL, main=self)
        self.shop_tab_250814.set(TAB_GENERAL, main=self)
        if self.config.GeneralShop_Enable:
            GeneralShop_250814(self.config, self.device).run()
        else:
            logger.info('General shop disabled, skip')

        self.config.task_delay(server_update=True)

    def run_once(self):
        """运行一次性商店购买任务。

        Pages: in: page_shop (merit/guild/core/medal tabs)

        依次处理功勋商店、舰队商店、核心商店、勋章商店。
        """
        # 军需商店
        self.ui_goto_shop()
        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_GENERAL, main=self)
        self.shop_tab_250814.set(TAB_MERIT, main=self)
        if self.config.MeritShop_Enable:
            MeritShop_250814(self.config, self.device).run()
        else:
            logger.info('Merit shop disabled, skip')

        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_GENERAL, main=self)
        self.shop_tab_250814.set(TAB_GUILD, main=self)
        if self.config.GuildShop_Enable:
            GuildShop_250814(self.config, self.device).run()
        else:
            logger.info('Guild shop disabled, skip')

        # 核心限定、核心月度、勋章、原型
        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_MONTHLY, main=self)
        self.shop_tab_250814.set(TAB_CORE_MONTHLY, main=self)
        if self.config.CoreShop_Enable:
            CoreShop_250814(self.config, self.device).run()
        else:
            logger.info('Core shop disabled, skip')

        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_MONTHLY, main=self)
        self.shop_tab_250814.set(TAB_MEDAL, main=self)
        if self.config.MedalShop2_Enable:
            MedalShop2_250814(self.config, self.device).run()
        else:
            logger.info('Medal shop disabled, skip')

        self.config.task_delay(server_update=True)


if __name__ == '__main__':
    self = RewardShop('alas')
    self.device.screenshot()
    self.run_once()