import re

from module.base.timer import Timer
from module.campaign.campaign_event import CampaignEvent
from module.coalition.assets import *
from module.coalition.combat import CoalitionCombat
from module.exception import ScriptEnd, ScriptError
from module.logger import logger
from module.ocr.ocr import Digit
from module.log_res.log_res import LogRes
from module.ui.assets import BACK_ARROW
from module.ui.page import page_campaign_menu


class AcademyPtOcr(Digit):
    """学园活动 PT 专用 OCR，识别形如 '累计: 840' 的文本。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alphabet += ':'

    def after_process(self, result):
        """从冒号后提取数字部分。

        输入示例: '累计: 840' -> 提取 '840'
        """
        logger.attr(self.name, result)
        try:
            result = result.rsplit(':')[1]
        except IndexError:
            pass
        return super().after_process(result)


class DALPtOcr(Digit):
    """DAL 活动 PT 专用 OCR，识别形如 'X9100' 的文本。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alphabet += 'X'

    def after_process(self, result):
        """从 X 字符后提取数字部分。

        输入示例: 'X9100' -> 提取 '9100'
        """
        logger.attr(self.name, result)
        try:
            result = result.rsplit('X')[1]
        except IndexError:
            pass
        return super().after_process(result)


class Coalition(CoalitionCombat, CampaignEvent):
    run_count: int
    run_limit: int

    def get_event_pt(self):
        """识别当前活动的 PT 数值。

        根据不同活动选择对应的 OCR 对象和参数，从截图中读取 PT 值。
        999999 视为默认值，需等待画面刷新后重试。

        Returns:
            int: PT 数值，识别失败返回 0。
        """
        event = self.config.Campaign_Event
        if event == 'coalition_20230323':
            ocr = Digit(FROSTFALL_OCR_PT, name='OCR_PT', letter=(198, 158, 82), threshold=128)
        elif event == 'coalition_20240627':
            ocr = AcademyPtOcr(ACADEMY_PT_OCR, name='OCR_PT', letter=(255, 255, 255), threshold=128)
        elif event == 'coalition_20250626':
            # 使用通用 OCR 模型
            ocr = Digit(NEONCITY_PT_OCR, name='OCR_PT', lang='cnocr', letter=(208, 208, 208), threshold=128)
        elif event == 'coalition_20251120':
            ocr = DALPtOcr(DAL_PT_OCR, name='OCR_PT', letter=(255, 213, 69), threshold=128)
        elif event == 'coalition_20260122':
            ocr = Digit(FASHION_PT_OCR, name='OCR_PT', letter=(41, 40, 40), threshold=128)
        else:
            logger.error(f'ocr object is not defined in event {event}')
            raise ScriptError

        pt = 0
        for _ in self.loop(timeout=1.5):
            pt = ocr.ocr(self.device.image)
            # 999999 是默认占位值，等待画面刷新
            if pt not in [999999]:
                break
        else:
            logger.warning('Wait PT timeout, assume it is')
        LogRes(self.config).Pt = pt
        self.config.update()
        return pt

    def check_oil(self):
        """检查燃油是否低于限制值。

        部分联动活动不显示燃油图标，此时跳过检查。
        首次检测到燃油不足时，等待画面稳定后二次确认。

        Returns:
            bool: 燃油不足返回 True，否则返回 False。
        """
        # 无燃油图标的联动活动跳过检查
        if not self._coalition_has_oil_icon:
            logger.info('Coalition event has no oil icon, skip oil check')
            return False

        limit = max(500, self.config.StopCondition_OilLimit)
        if not (self.get_oil() < limit):
            return False

        # 等待 OCR 数值稳定后再确认一次
        timeout = Timer(1, count=2).start()
        while True:
            self.device.screenshot()
            if self.appear(BACK_ARROW, offset=(5, 2)):
                break
            if timeout.reached():
                logger.warning('Assumes that OCR_OIL is stable')
                break
        if self.get_oil() < limit:
            return True
        else:
            return False

    @property
    def _coalition_has_oil_icon(self):
        """当前联动活动是否在 UI 上显示燃油图标。

        部分活动出于 UI 设计考虑移除了燃油显示。
        参见: https://github.com/LmeSzinc/AzurLaneAutoScript/issues/5214
        """
        if self.config.Campaign_Event == 'coalition_20260122':
            return False
        return True

    def triggered_stop_condition(self, oil_check=False, pt_check=False, coin_check=False):
        """检查是否触发停止条件。

        依次检查：运行次数上限、燃油不足、活动 PT 上限、金币上限、任务均衡器。

        Args:
            oil_check: 是否检查燃油限制。
            pt_check: 是否检查活动 PT 限制。
            coin_check: 是否检查金币限制。

        Returns:
            bool: 触发了停止条件返回 True。
        """
        # 运行次数上限
        if self.run_limit and self.config.StopCondition_RunCount <= 0:
            logger.hr('Triggered stop condition: Run count')
            self.config.StopCondition_RunCount = 0
            self.config.Scheduler_Enable = False
            return True
        # 燃油限制
        if oil_check:
            # 检查 ui_current 是否存在，避免属性异常
            ui_is_campaign_menu = hasattr(self, 'ui_current') and self.ui_current == page_campaign_menu
            if (self._coalition_has_oil_icon or ui_is_campaign_menu) and self.check_oil():
                logger.hr('Triggered stop condition: Oil limit')
                self.config.task_delay(minute=(120, 240))
                return True
        # 活动 PT 限制
        if pt_check:
            if self.event_pt_limit_triggered():
                logger.hr('Triggered stop condition: Event PT limit')
                return True
        # 金币限制
        if coin_check and self.coin_limit_triggered():
            logger.hr('Triggered stop condition: Coin limit')
            return True
        # 任务均衡器
        if self.run_count >= 1:
            if self.config.TaskBalancer_Enable and self.triggered_task_balancer():
                logger.hr('Triggered stop condition: Coin limit')
                self.handle_task_balancer()
                return True

        return False

    def coalition_execute_once(self, event, stage, fleet):
        """执行一次联动战斗。

        覆盖战役配置，处理情绪管理，检测停止条件后进入战斗。
        SP 关卡强制使用多舰队；单舰队模式下情绪控制不低于黄脸。

        Args:
            event: 活动名称，如 'coalition_20230323'。
            stage: 关卡名称，如 'a1'、'sp'。
            fleet: 舰队模式，如 'single'、'multi'。

        Pages:
            in: in_coalition
            out: in_coalition
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
        if stage == 'sp':
            # SP 关卡需要多舰队
            self.config.override(
                Coalition_Fleet='multi',
            )
        try:
            self.emotion.check_reduce(battle=self.coalition_get_battles(event, stage))
        except ScriptEnd:
            self.coalition_map_exit(event)
            raise

        if self._coalition_has_oil_icon and self.triggered_stop_condition(oil_check=True, coin_check=True):
            self.coalition_map_exit(event)
            raise ScriptEnd

        self.enter_map(event=event, stage=stage, mode=fleet)
        self.coalition_combat()

    @staticmethod
    def handle_stage_name(event, stage):
        """标准化活动名称和关卡名称。

        去除空白字符并转小写。霜落活动额外去除连字符。

        Args:
            event: 活动名称。
            stage: 关卡名称。

        Returns:
            tuple: (event, stage) 标准化后的名称。
        """
        stage = re.sub('[ \t\n]', '', str(stage)).lower()
        if event == 'coalition_20230323':
            stage = stage.replace('-', '')

        return event, stage

    def run(self, event='', mode='', fleet='', total=0):
        """联动活动主循环。

        从配置读取活动、关卡、舰队参数，循环执行战斗直到触发停止条件。
        无燃油图标的活动需先跳转到战役菜单检查停止条件再进入联动页面。

        Args:
            event: 活动名称，为空时从配置读取。
            mode: 关卡名称，为空时从配置读取。
            fleet: 舰队模式，为空时从配置读取。
            total: 总运行次数上限，0 表示不限。

        Raises:
            ScriptError: 参数未填写。
            ScriptEnd: 触发停止条件或脚本正常结束。
        """
        event = event if event else self.config.Campaign_Event
        mode = mode if mode else self.config.Coalition_Mode
        fleet = fleet if fleet else self.config.Coalition_Fleet
        if not event or not mode or not fleet:
            raise ScriptError(f'Coalition arguments unfilled. name={event}, mode={mode}, fleet={fleet}')

        event, mode = self.handle_stage_name(event, mode)
        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount
        while 1:
            # 达到总次数上限
            if total and self.run_count == total:
                break
            if self.event_time_limit_triggered():
                self.config.task_stop()

            # 日志输出当前关卡和剩余次数
            logger.hr(f'{event}_{mode}', level=2)
            if self.config.StopCondition_RunCount > 0:
                logger.info(f'Count remain: {self.config.StopCondition_RunCount}')
            else:
                logger.info(f'Count: {self.run_count}')

            # 无燃油图标时，先在战役菜单检查停止条件
            if not self._coalition_has_oil_icon:
                self.ui_goto(page_campaign_menu)
                if self.triggered_stop_condition(oil_check=True, coin_check=True):
                    break
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
                logger.hr('Script end')
                logger.info(str(e))
                break

            # 战斗后更新计数
            self.run_count += 1
            if self.config.StopCondition_RunCount:
                self.config.StopCondition_RunCount -= 1
            # 再次检查停止条件
            if self.triggered_stop_condition(pt_check=True, coin_check=True):
                break
            # 任务调度器检查
            if self.config.task_switched():
                self.config.task_stop()


if __name__ == '__main__':
    self = Coalition('alas5', task='Coalition')
    self.device.screenshot()
    self.get_event_pt()
