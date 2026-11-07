"""
月度Boss任务模块。

挑战并击败大世界月度Boss，支持普通和困难两种难度。
战斗前检查适应性数值以选择合适的难度，战斗后在港口修理舰队。
每月重置时自动延迟到新的Boss出现周期。

Classes:
    OpsiMonthBoss: 月度Boss处理器，继承 OSMap。
"""

import numpy as np

from module.config.utils import get_os_next_reset
from module.logger import logger
from module.os.map import OSMap
from module.os_handler.action_point import OCR_OS_ADAPTABILITY
from module.os_handler.assets import OS_MONTHBOSS_NORMAL, OS_MONTHBOSS_HARD


class OpsiMonthBoss(OSMap):
    def get_adaptability(self):
        """识别当前界面的大世界适应性数值。

        Returns:
            tuple[int, int, int]: 攻击、耐久、回复的三项适应性数值。
        """
        adaptability = OCR_OS_ADAPTABILITY.ocr(self.device.image)

        return adaptability

    def clear_month_boss(self):
        """清理大世界月度Boss。

        检查适应性、判断当前 Boss 难度、击败 Boss 并在港口修理舰队。

        Raises:
            ActionPointLimit: 行动力不足。
            TaskEnd: 没有更多月度Boss。

        Pages:
            in: page_os, 大世界任务界面
            out: page_os, 大世界地图
        """
        if self.is_in_opsi_explore():
            logger.info('每月开荒正在运行，停止月度Boss')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        logger.hr("大世界-月度Boss", level=1)
        logger.hr("月度Boss预检查", level=2)
        checkout_offset = self.os_mission_enter(
            skip_siren_mission=self.config.cross_get('OpsiDaily.OpsiDaily.SkipSirenResearchMission'))
        logger.attr('OpsiMonthBoss.模式', self.config.OpsiMonthBoss_Mode)
        if self.appear(OS_MONTHBOSS_NORMAL, offset=checkout_offset):
            logger.attr('月度Boss难度', 'normal')
            is_normal = True
        elif self.appear(OS_MONTHBOSS_HARD, offset=checkout_offset):
            logger.attr('月度Boss难度', 'hard')
            is_normal = False
        else:
            logger.info("未找到普通/困难月度Boss，停止任务")
            self.os_mission_quit()
            self.month_boss_delay(is_normal=False, result=False)
            return True
        self.os_mission_quit()

        if not is_normal and self.config.OpsiMonthBoss_Mode == "normal":
            logger.info("配置为只打普通月度Boss，但当前为困难月度Boss，跳过")
            self.month_boss_delay(is_normal=False, result=True)
            self.config.task_stop()
            return True

        if self.config.OpsiMonthBoss_CheckAdaptability:
            self.os_map_goto_globe(unpin=False)
            adaptability = self.get_adaptability()
            if (np.array(adaptability) < (203, 203, 156)).any():
                logger.info("[大世界-月度Boss] 适应性低于 (203/203/156) 要求，需要变强后再来")
                self.config.task_delay(server_update=True)
                self.config.task_stop()
            # 无需退出，复用当前状态

        # 战斗
        logger.hr("月度Boss前往", level=2)
        with self.config.temporary(_disable_task_switch=True):
            self.globe_goto(154)
            self.go_month_boss_room(is_normal=is_normal)
            result = self.boss_clear(has_fleet_step=True, is_month=True)

            # 战斗结束
            logger.hr("月度Boss维修", level=2)
            self.handle_fleet_repair_by_config(revert=False)
            self.handle_fleet_resolve(revert=False)
            self.month_boss_delay(is_normal=is_normal, result=result)

    def month_boss_delay(self, is_normal=True, result=True):
        """处理月度Boss任务完成或失败后的延迟调度。

        根据难度和清理结果决定延迟到下次月度重置还是稍后重试。

        Args:
            is_normal (bool): True 为普通难度，False 为困难难度。默认 True。
            result (bool): 是否成功击败 Boss。默认 True。
        """
        if is_normal:
            if result:
                if self.config.OpsiMonthBoss_Mode == 'normal_hard':
                    logger.info('普通月度Boss已完成，接下来执行困难月度Boss')
                    self.config.task_stop()
                else:
                    logger.info('普通月度Boss已完成，停止任务')
                    next_reset = get_os_next_reset()
                    self.config.task_delay(target=next_reset)
                    self.config.task_stop()
            else:
                logger.info("无法清理普通月度Boss，稍后重试")
                self.config.opsi_task_delay(recon_scan=False, submarine_call=True, ap_limit=False)
                self.config.task_stop()
        else:
            if result:
                logger.info('困难月度Boss已完成，停止任务')
                next_reset = get_os_next_reset()
                self.config.task_delay(target=next_reset)
                self.config.task_stop()
            else:
                logger.info("无法清理困难月度Boss，明日重试")
                self.config.task_delay(server_update=True)
                self.config.task_stop()
