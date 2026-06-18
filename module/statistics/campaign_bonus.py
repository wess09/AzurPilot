from module.base.button import ButtonGrid
from module.base.utils import *
from module.handler.assets import AUTO_SEARCH_MENU_EXIT
from module.statistics.assets import CAMPAIGN_BONUS, CAMPAIGN_BONUS_SINGLE
from module.statistics.get_items import ITEM_GROUP, GetItemsStatistics
from module.statistics.item import Item
from module.statistics.utils import *


class BonusItem(Item):
    def predict_valid(self):
        return np.mean(rgb2gray(self.image) > 160) > 0.1


class CampaignBonusStatistics(GetItemsStatistics):
    def appear_on(self, image):
        if AUTO_SEARCH_MENU_EXIT.match(image, offset=(200, 20)) \
                and (CAMPAIGN_BONUS.match(image, offset=(200, 500)) \
                or CAMPAIGN_BONUS_SINGLE.match(image, offset=(200, 500))):
            return True

        return False

    def _stats_get_items_load(self, image):
        ITEM_GROUP.item_class = BonusItem
        ITEM_GROUP.similarity = 0.85
        ITEM_GROUP.amount_area = (35, 51, 63, 63)
        origin = area_offset(CAMPAIGN_BONUS.button, offset=(-7, 34))[:2]
        grids = ButtonGrid(origin=origin, button_shape=(64, 64), grid_shape=(7, 2), delta=(72 + 2 / 3, 75))

        reward_bottom = AUTO_SEARCH_MENU_EXIT.button[1]
        grids.buttons = [button for button in grids.buttons if button.area[3] < reward_bottom]
        ITEM_GROUP.grids = grids

    def stats_get_items(self, image, **kwargs):
        """从战役结算截图中提取奖励物品。

        通过金币数量验证截图有效性：金币数量过低或缺失则视为无效截图。

        Args:
            image (np.ndarray): 战役结算截图。

        Returns:
            list[Item]: 奖励物品列表。
        """
        result = super().stats_get_items(image, **kwargs)
        valid = False
        valid_coin = False
        for item in result:
            if item.name == 'Coin':
                valid = True
                if item.amount > 100:
                    valid_coin = True
        if valid and valid_coin:
            return [self.revise_item(item) for item in result]
        elif valid:
            raise ImageError('Campaign bonus image have too low coins, dropped')
        else:
            raise ImageError('Campaign bonus image does not have coins, dropped')

    def revise_item(self, item):
        """修正 OCR 识别错误的物品数量。

        战役奖励芯片掉落 9~30+ 个，但有时 10 被识别为 1。
        舰船数量异常时也会进行修正。

        Args:
            item (Item): 物品实例。

        Returns:
            Item: 修正后的物品实例。
        """
        # 战役奖励芯片掉落 9~30+ 个，但有时 10 被识别为 1
        if item.name == 'Chip' and 0 < item.amount < 4:
            item.amount *= 10

        if 'ship' in item.name:
            if 3 < item.amount < 10:
                item.amount = 1
            elif item.amount >= 10:
                if 0 <= item.amount % 10 <= 3:
                    item.amount %= 10
                else:
                    item.amount //= 10

        return item
