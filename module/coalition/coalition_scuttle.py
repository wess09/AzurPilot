"""联盟活动沉船刷分模块，专门处理联盟沉船战斗的结算逻辑。
复用公共 C/D 战败结算，显式豁免额外心情并控制战斗结束判定，
并处理沉船专用的结算弹窗与确认操作。"""

from module.coalition.assets import *
from module.coalition.combat import CoalitionCombat
from module.coalition.coalition import Coalition
from module.exception import ScriptEnd, ScriptError
from module.logger import logger


class CoalitionScuttleCombat(CoalitionCombat):
    """联盟沉船复用结算，只豁免额外心情并处理专用确认。"""

    combat_shipwreck_emotion = False
    coalition_result_confirm_buttons = (SCUTTLE_CONFIRM, COALITION_REWARD_CONFIRM)

    def coalition_emotion_reduce(self):
        """牺牲编队整关只扣一次基础心情，单队模式也不按内部战数重复扣减。"""
        return self.battle_count == 0


class CoalitionScuttleRun(Coalition, CoalitionScuttleCombat):
    """联盟沉船主循环，沉船任务进入关卡只扣1次2点心情。"""

    def handle_combat_low_emotion(self):
        """
        重写红脸出击警告弹窗处理。

        沉船任务中牺牲船必然低心情，红脸弹窗出现时点击确认继续出击。
        """
        return self.handle_popup_confirm('IGNORE_LOW_EMOTION')

    def coalition_execute_once(self, event, stage, fleet):
        """执行一次联盟沉船战斗。

        覆盖父类方法，将心情预估从多场战斗改为1场（整个关卡只扣1次2点）。
        联盟沉船虽然内部有多次战斗（1/2/3/4队），但游戏只在整个关卡进入时扣1次心情。

        Args:
            event: 活动名称。
            stage: 关卡名称。
            fleet: 舰队模式。
        """
        self.config.override(
            Campaign_Name=f'{event}_{stage}',
            Campaign_UseAutoSearch=False,
            Fleet_FleetOrder='fleet1_all_fleet2_standby',
        )
        if self.config.Coalition_Fleet == 'single' and self.config.Emotion_Fleet1Control == 'prevent_red_face':
            logger.warning('AL does not allow single coalition with emotion < 30, '
                           'emotion control is forced to prevent_yellow_face')
            self.config.override(Emotion_Fleet1Control='prevent_yellow_face')
        if stage == 'sp' or (event == 'coalition_20261124' and stage == 'ex'):
            self.config.override(Coalition_Fleet='multi')

        # 联盟沉船：整个关卡只扣1次2点心情，不按内部战斗次数预估
        try:
            self.emotion.check_reduce(battle=1)
        except ScriptEnd:
            self.coalition_map_exit(event)
            raise

        if self._coalition_has_oil_icon and self.triggered_stop_condition(oil_check=True, coin_check=True):
            self.coalition_map_exit(event)
            raise ScriptEnd

        self.enter_map(event=event, stage=stage, mode=fleet)
        self.coalition_combat()

    def run(self, event='', mode='', fleet='', total=0):
        """
        运行联盟沉船主循环，仅扣整关基础心情，不扣额外沉船心情。

        SP关卡特殊逻辑：
        - 只有明确 S 评价且没有战败画面才视为通过
        - 其他结果按次数限制继续出击

        Args:
            event (str): 活动名称，为空时从配置读取。
            mode (str): 关卡名称，为空时从配置读取。
            fleet (str): 舰队模式，为空时从配置读取。
            total (int): 总运行次数上限，0 表示不限。
        """
        event = event if event else self.config.Campaign_Event
        mode = mode if mode else self.config.Coalition_Mode
        fleet = fleet if fleet else self.config.Coalition_Fleet
        if not event or not mode or not fleet:
            raise ScriptError(f'CoalitionScuttle arguments unfilled. name={event}, mode={mode}, fleet={fleet}')

        event, mode = self.handle_stage_name(event, mode)
        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount

        while 1:
            # 达到指定运行次数则结束
            if total and self.run_count == total:
                break
            if self.event_time_limit_triggered():
                self.config.task_stop()

            # 日志输出
            logger.hr(f'{event}_{mode}', level=2)
            if self.config.StopCondition_RunCount > 0:
                logger.info(f'剩余次数: {self.config.StopCondition_RunCount}')
            else:
                logger.info(f'计数: {self.run_count}')

            # 无燃油图标时，先在战役菜单检查停止条件
            if not self._coalition_has_oil_icon:
                from module.ui.page import page_campaign_menu
                self.ui_goto(page_campaign_menu)
                if self.triggered_stop_condition(oil_check=True, coin_check=True):
                    break

            # 确保进入联盟页面
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            self.ui_goto_coalition()
            self.disable_event_on_raid()
            self.coalition_ensure_mode(event, 'battle')

            # 检查 PT 和金币停止条件
            if self.triggered_stop_condition(pt_check=True, coin_check=True):
                break

            # 执行战斗
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            try:
                self.coalition_execute_once(event=event, stage=mode, fleet=fleet)
            except ScriptEnd as e:
                logger.hr('脚本结束')
                logger.info(str(e))
                break

            # 战斗结束后更新计数
            self.run_count += 1
            if self.config.StopCondition_RunCount:
                self.config.StopCondition_RunCount -= 1

            # SP关卡仅S评价视为已通过，延迟至服务器刷新
            # A/B/C/D评价均视为未通过，继续出击
            if mode == 'sp' and self.combat_result.rank == 'S' and not self.combat_result.defeated:
                logger.info('SP以S评价通过')
                self.config.task_delay(server_update=True)
                self.config.task_stop()

            # 检查停止条件
            if self.triggered_stop_condition(pt_check=True, coin_check=True):
                break
            # 检查调度器是否切换了任务
            if self.config.task_switched():
                self.config.task_stop()
