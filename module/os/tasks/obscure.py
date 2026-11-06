"""大世界隐秘海域任务模块。

执行大世界隐秘海域（Obscure Zone）的清理任务，包括：
- 从仓库获取隐秘海域坐标信息
- 前往目标区域执行自动搜索战斗
- 行动力不足时的保护和延迟处理
- 支持强制运行模式

继承自 CoinTaskMixin 和 OSMap，提供代币保护和地图导航能力，
隐秘海域是大世界主要的代币获取途径之一。
"""

from module.config.utils import get_os_next_reset
from module.logger import logger
from module.os.map import OSMap
from module.os.tasks.scheduling import CoinTaskMixin


OBSCURE_RESUME_KEY = 'OpsiObscure.OpsiObscure.ResumeState'


class OpsiObscure(CoinTaskMixin, OSMap):
    def _save_obscure_resume(self, resumed=False):
        """在操作前保存本海域的续接次数，避免重启后重复获得续接机会。"""
        self.config.cross_set(OBSCURE_RESUME_KEY, dict(
            server=self.config.SERVER,
            reset=get_os_next_reset().isoformat(),
            zone=self.zone.zone_id,
            resumed=resumed,
        ))

    def resume_obscure(self):
        """隐秘海域消失时清除记录；仍在海域时最多续接一次。

        Returns:
            bool: 是否已处理当前隐秘海域。

        Pages:
            in: IN_MAP，已完成海域初始化
            out: IN_MAP，无隐秘海域时保留当前海域，否则返回来源海域
        """
        state = self.config.cross_get(OBSCURE_RESUME_KEY)
        if not self.is_obscure_zone or not self.is_in_special_zone():
            # 重启后可能已经回到来源海域，不能拿旧记录继续点自律或等待退出按钮。
            if state is not None:
                logger.info('[大世界-隐秘海域] 当前隐秘海域已不存在，清除续接记录并继续后续任务')
                self.config.cross_set(OBSCURE_RESUME_KEY, None)
            return False
        same_zone = (
            isinstance(state, dict)
            and state.get('server') == self.config.SERVER
            and state.get('reset') == get_os_next_reset().isoformat()
            and state.get('zone') == self.zone.zone_id
        )
        if not same_zone and self.config.task.command != 'OpsiObscure':
            # 其他任务只接回本功能留下的记录，不能接管手动进入的隐秘/档案海域。
            return False
        if same_zone and state.get('resumed'):
            logger.warning('[大世界-隐秘海域] 已续接过一次，本次正常退出海域')
            self.map_exit()
            self.config.cross_set(OBSCURE_RESUME_KEY, None)
            return True

        # 必须在换队、自律及扫描前落盘；其中任何一步再次卡死都不能重置次数。
        self._save_obscure_resume(resumed=True)
        logger.info('[大世界-隐秘海域] 重启后续接一次自律，完成后续扫描及退出')
        if self.config.task.command == 'OpsiObscure':
            self._finish_obscure(resumed=True)
        else:
            # 智能调度、防溢出或跨月启动时，也读取隐秘海域自己的配置和掉落开关。
            self._run_with_opsi_task_context('OpsiObscure', self._finish_obscure, resumed=True)
        return True

    def _obscure_after_scan(self, drop=None):
        """本轮尚未处理事件时，依次做可选的一次全图扫描和逐队雷达补查。"""
        if self._solved_map_event:
            return
        if self.config.cross_get('OpsiObscure.OpsiObscure.FullScan', default=False):
            # 实验性：隐秘海域全图扫描有概率卡死，默认关闭，只扫一遍。
            logger.warning('[大世界-隐秘海域] 实验性全图扫描，有概率卡死')
            self.map_rescan_once(rescan_mode='full', drop=drop)
        if not self._solved_map_event and self.config.cross_get(
            'OpsiObscure.OpsiObscure.RadarScan', default=False,
        ):
            logger.info('[大世界-隐秘海域] 未处理到事件，切换舰队扫描雷达')
            # 复用短猫的逐队雷达逻辑，但不隐式触发全图扫描或固定坐标巡逻。
            self.clear_question_any_fleet(drop=drop, rescan=False)
            self.fleet_set(self.config.OpsiFleet_Fleet)

    def _finish_obscure(self, resumed=False):
        """完成当前隐秘海域；续接只补自律，不重复执行侦察和潜艇指令。

        Pages:
            in: IN_MAP，隐秘海域
            out: IN_MAP，来源海域
        """
        self.config.override(OpsiGeneral_DoRandomMapEvent=False, HOMO_EDGE_DETECT=False, STORY_OPTION=0)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        with self.config.temporary(_disable_task_switch=True):
            if not resumed:
                self.os_order_execute(
                    recon_scan=True,
                    submarine_call=self.config.OpsiFleet_Submarine)
            self.run_auto_search(rescan='current', exit_map=True, on_map_scanned=self._obscure_after_scan)
            # run_auto_search 已确认退出，之后的维修异常不再属于本隐秘海域。
            self.config.cross_set(OBSCURE_RESUME_KEY, None)
            self.handle_after_auto_search()

    def clear_obscure(self):
        """清理一个隐秘海域。

        从仓库取出隐秘海域坐标，前往目标区域执行自动搜索。
        若没有可执行内容，在代币任务模式下标记无内容并推迟。

        Raises:
            ActionPointLimit: 行动力不足时抛出。

        Pages:
            in: page_os, 大世界地图
            out: page_os, 大世界地图
        """
        logger.hr('大世界-隐秘海域', level=1)
        self.cl1_ap_preserve()
        if self.config.OpsiObscure_ForceRun:
            logger.info('隐秘海域处于强制运行模式')

        result = self.storage_get_next_item('OBSCURE', use_logger=self.config.OpsiGeneral_UseLogger,
                                            skip_obscure_hazard_2=self.config.OpsiObscure_SkipHazard2Obscure)
        if not result:
            if self._handle_coin_task_no_content('隐秘海域', '隐秘海域没有可执行内容'):
                return

        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
        )
        self.zone_init()
        self._save_obscure_resume()
        self._finish_obscure()

    def os_obscure(self):
        """执行大世界隐秘海域任务主流程。

        非强制模式下每次仅清理一个海域以利用指令冷却；强制模式下持续清理。
        """
        while True:
            self.clear_obscure()

            # 非强制模式每次只清一个隐秘海域，保留 os_order_execute 写入的侦查/潜艇冷却。
            if not self.config.OpsiObscure_ForceRun:
                break
            
            self.config.check_task_switch()
            continue
