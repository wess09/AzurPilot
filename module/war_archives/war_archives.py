import re

from campaign.campaign_war_archives.campaign_base import CampaignBase
from module.campaign.run import CampaignRun
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.war_archives.assets import (OCR_DATA_KEY_CAMPAIGN,
                                        WAR_ARCHIVES_CAMPAIGN_CHECK)


class OcrDataKey(DigitCounter):
    """作战档案数据密钥计数器 OCR。

    处理数据密钥数量的 OCR 识别，修正常见的识别错误。
    数据密钥格式为 "当前/60"，OCR 可能将 "/60" 误识别为 "60"。
    """

    def after_process(self, result):
        """OCR 后处理，修正数据密钥数量识别错误。

        将 OCR 误识别的 "X60" 格式修正为 "X/60"。
        例如：识别结果 "1560" 会被修正为 "15/60"。

        Args:
            result: OCR 原始识别结果字符串。

        Returns:
            修正后的数据密钥数量字符串。
        """
        result = super().after_process(result)
        result = re.sub(r'(\d{1,2})60$', r'\1/60', result)
        return result


DATA_KEY_CAMPAIGN = OcrDataKey(OCR_DATA_KEY_CAMPAIGN, letter=(255, 247, 247), threshold=64)


class CampaignWarArchives(CampaignRun, CampaignBase):
    def triggered_stop_condition(self, oil_check=True):
        """检查作战档案的停止条件。

        当处于档案战役界面时，通过 OCR 识别剩余数据密钥数量。
        数据密钥用尽时延迟任务到下次服务器重置。

        Pages:
            in: WAR_ARCHIVES_CAMPAIGN_CHECK（档案战役界面）

        Args:
            oil_check: 是否检查燃油停止条件。

        Returns:
            True 表示触发了停止条件，False 表示未触发。
        """
        # 必须在档案战役界面才能进行 OCR 检查
        if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
            # 检查数据密钥是否已用尽
            current, remain, total = DATA_KEY_CAMPAIGN.ocr(self.device.image)
            logger.info(f'Inventory: {current} / {total}, Remain: {current}')
            if remain == total:
                logger.hr('Triggered out of data keys')
                # 仅在数据密钥用尽时才能延迟任务
                self.config.task_delay(server_update=True)
                return True

        # 其他情况，检查通用停止条件
        return super().triggered_stop_condition(oil_check)

    def can_use_auto_search_continue(self):
        """判断是否可使用自动搜索续战。

        自动搜索菜单具有模糊背景，会遮挡 DATA_KEY_CAMPAIGN 的 OCR 区域，
        因此作战档案中禁用自动搜索续战功能。

        Returns:
            始终返回 False，不支持自动搜索续战。
        """
        return False

    def run(self, name=None, folder='campaign_main', mode='normal', total=0):
        """执行作战档案战役。

        强制启用数据密钥使用，然后调用父类战役运行逻辑。
        作战档案必须使用数据密钥才能进入。

        Pages:
            in: page_archives（作战档案选择界面）
            out: page_main（主界面，任务完成后）

        Args:
            name: 战役名称，如 'war_archives_20190321_en'。
            folder: 战役文件夹路径，默认 'campaign_main'。
            mode: 战役模式，'normal' 或 'hard'。
            total: 总运行次数，0 表示无限。
        """
        self.config.override(USE_DATA_KEY=True)
        super().run(name, folder, mode, total)
