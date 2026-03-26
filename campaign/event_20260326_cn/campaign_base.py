from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.ui.page import page_event
from module.logger import logger


class CampaignBase(CampaignBase_):

    def handle_exp_info(self):

        if self.appear(page_event):
            return False
        return super().handle_exp_info()

    def campaign_set_chapter_20241219(self, chapter, stage, mode='combat'):

        if self.config.MAP_CHAPTER_SWITCH_20241219:
            # 处理 T 系列普通关卡
            if chapter == 't':
                self.ui_goto_sp()
                self.campaign_ensure_mode_20241219('combat')
                if stage in ['1', '2', '3']:
                    self.campaign_ensure_aside_20241219('part1')
                else:
                    logger.warning(f'[Event20260326] Stage {chapter}{stage} 不在可识别关卡列表中')
                self.campaign_ensure_chapter(chapter)
                return True

            # 处理 HT 系列困难关卡
            if chapter == 'ht':
                self.ui_goto_sp()
                self.campaign_ensure_mode_20241219('combat')
                if stage in ['1', '2', '3']:
                    self.campaign_ensure_aside_20241219('part2')
                else:
                    logger.warning(f'[Event20260326] Stage {chapter}{stage} 不在可识别关卡列表中')
                self.campaign_ensure_chapter(chapter)
                return True

            # 处理 SP/EX 特殊关卡
            if chapter == 'ex_sp':
                self.ui_goto_sp()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20241219('sp')
                self.campaign_ensure_chapter(chapter)
                return True

        return super().campaign_set_chapter_20241219(chapter, stage, mode)