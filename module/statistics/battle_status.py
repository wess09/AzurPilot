from module.base.decorator import cached_property
from module.combat.assets import BATTLE_STATUS_S
from module.ocr.ocr import Ocr
from module.statistics.assets import ENEMY_NAME


class BattleStatusStatistics:
    def appear_on(self, image):
        return BATTLE_STATUS_S.appear_on(image)

    @cached_property
    def ocr_object(self):
        return Ocr(ENEMY_NAME, lang='cnocr', threshold=128, name='ENEMY_NAME')

    def stats_battle_status(self, image):
        """从战斗状态截图中识别敌人名称。

        Args:
            image (np.ndarray): 战斗状态截图。

        Returns:
            str: 敌人名称，如 '中型主力舰队'。
        """
        result = self.ocr_object.ocr(image)
        # 删除 OCR 误识别的字符
        for letter in '-一个―~(':
            result = result.replace(letter, '')

        return result
