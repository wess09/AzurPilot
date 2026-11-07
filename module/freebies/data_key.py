"""数据密钥收集器，自动收取作战档案中的数据密钥。
通过 OCR 检测密钥数量，判断是否需要收集。
"""

from module.combat.assets import GET_ITEMS_1
from module.freebies.assets import *
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.ui.assets import CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, WAR_ARCHIVES_CHECK
from module.ui.page import page_archives, page_campaign_menu
from module.ui.ui import UI


DATA_KEY = DigitCounter(OCR_DATA_KEY, letter=(255, 247, 247), threshold=64)


class DataKey(UI):
    """作战档案数据钥匙收集器。

    检测作战档案页面中的数据钥匙库存与剩余每日领取数量，自动完成收集。
    """

    def _data_key_collect(self, skip_first_screenshot=True):
        """执行数据钥匙点击领取和弹窗处理循环。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。

        Pages:
            in: page_archives
            out: page_archives, DATA_KEY_COLLECTED
        """
        logger.hr('档案秘钥收集')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(DATA_KEY_COLLECT, offset=(20, 20), interval=3):
                continue
            if self.appear(GET_ITEMS_1, offset=20, interval=3):
                self.device.click(DATA_KEY_COLLECT)
                continue
            if self.handle_popup_confirm('DATA_KEY_LIMIT'):
                # 如果当前为 29/30 说明用户不经常打档案，不必担心损失 1 把钥匙，直接领满即可
                continue
            if self.appear_then_click(CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, offset=(20, 20), interval=3):
                # 偶发误退到 page_campaign_menu 时重新进入
                continue

            # 结束条件
            if self.appear(WAR_ARCHIVES_CHECK, offset=(20, 20)) and self.appear(DATA_KEY_COLLECTED, offset=(20, 20)):
                logger.info('[免费福利-钥匙] 档案秘钥收集完成')
                break

    def data_key_collect(self):
        """
        执行数据钥匙收集。

        Returns:
            bool: 是否执行了收集。

        Pages:
            in: page_archives
        """
        if self.appear(DATA_KEY_COLLECTED, offset=(20, 20)):
            logger.info('[免费福利-钥匙] 档案秘钥已收集')
            return False

        current, remain, total = DATA_KEY.ocr(self.device.image)
        logger.info(f'[免费福利-钥匙] 背包: {current} / {total}, 剩余: {remain}')
        if not self.config.DataKey_ForceCollect and remain <= 0:
            logger.info('[免费福利-钥匙] 没有更多空间存放档案秘钥')
            return False

        self._data_key_collect()
        return True

    def run(self):
        """执行数据钥匙自动收集任务。

        Pages:
            in: 任意页面
            out: page_archives
        """
        self.ui_ensure(page_archives)

        self.data_key_collect()

        # 清除页面检测间隔，使后续 ui_goto() 切换更快
        self.interval_clear([page_archives.check_button, page_campaign_menu.check_button])
