"""联动活动（Coalition Event）执行模块。

自动执行碧蓝航线的联动活动战斗。联动活动是一种特殊的限时活动，
通常分为多个难度（Easy/Normal/Hard 或 TC1/TC2/TC3），部分活动有 SP 关卡。

本模块的核心功能：
- 活动 PT（点数）识别：不同活动使用不同的 OCR 策略和参数
- 燃油检查：部分活动 UI 不显示燃油图标，需跳过检查
- 关卡标准化：兼容旧配置中的 TC-1/2/3 难度名
- 停止条件管理：运行次数、燃油、PT、金币、任务均衡器
- 情绪管理：单舰队模式下强制防止黄脸

支持的联动活动包括霜落（Frostfall）、学园、约会大作战（DAL）、
霓虹都市、时尚、恐怖故事等。

配置路径: Campaign.Event (活动名称), Coalition.Mode (关卡难度),
         Coalition.Fleet (舰队模式)
"""

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

        Args:
            result (str): 原始识别字符串。

        Returns:
            int: 提取的数字结果。
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

        Args:
            result (str): 原始识别字符串。

        Returns:
            int: 提取的数字结果。
        """
        logger.attr(self.name, result)
        try:
            result = result.rsplit('X')[1]
        except IndexError:
            pass
        return super().after_process(result)


class Coalition(CoalitionCombat, CampaignEvent):
    """联动活动战役执行器。

    继承自 CoalitionCombat（联动战斗逻辑）和 CampaignEvent（活动战役基础），
    负责联动活动的完整自动化流程：
    1. 从配置读取活动名称、关卡难度和舰队模式
    2. 标准化关卡名称（兼容旧配置格式）
    3. 循环执行战斗，每次检查停止条件
    4. 识别活动 PT 值用于进度追踪
    5. 处理无燃油图标的特殊活动 UI

    Attributes:
        run_count: 当前已执行的战斗次数。
        run_limit: 配置的运行次数上限。
    """

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
        elif event == 'coalition_20260723':
            threshold = 256 if self.config.SERVER == 'en' else 221
            ocr = Digit(HORROR_PT_OCR, name='OCR_PT', lang='cnocr', letter=(228, 230, 237), threshold=threshold)
        elif event == 'coalition_20261124':
            ocr = Digit(VERITAS_PT_OCR, name='OCR_PT', letter=(192, 208, 227), threshold=192)
        else:
            logger.error(f'[联动] 活动 {event} 未定义OCR对象')
            raise ScriptError

        pt = 0
        for _ in self.loop(timeout=1.5):
            pt = ocr.ocr(self.device.image)
            # 999999 是默认占位值，等待画面刷新
            if pt not in [999999]:
                break
        else:
            logger.warning('等待PT超时，假设已达到')
        LogRes(self.config).record('Pt', pt, observed=pt != 999999 and bool(getattr(ocr, 'last_valid', False)))
        self.config.update()
        return pt

    def check_oil(self):
        """检查燃油是否低于限制值。

        真理学院在战役菜单读取燃油，其他活动沿用已有的燃油图标判断。
        首次检测到燃油不足时，等待画面稳定后二次确认。

        Returns:
            bool: 燃油不足返回 True，否则返回 False。
        """
        # 真理学院作战页没有燃油数字，确认回到战役菜单后才读取。
        if not self._coalition_has_oil_icon:
            if (self.config.Campaign_Event != 'coalition_20261124'
                    or not self.ui_page_appear(page_campaign_menu)):
                logger.info('联动活动无石油图标，跳过石油检查')
                return False

        limit = max(self.config.StopCondition_OilLimitHardFloor, self.config.StopCondition_OilLimit)
        if not (self.get_oil() < limit):
            return False

        # 等待 OCR 数值稳定后再确认一次
        timeout = Timer(1, count=2).start()
        while True:
            self.device.screenshot()
            if self.appear(BACK_ARROW, offset=(5, 2)):
                break
            if timeout.reached():
                logger.warning('假设OCR_OIL稳定')
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
        if self.config.Campaign_Event in [
            'coalition_20260122',
            'coalition_20260723',
            'coalition_20261124',
        ]:
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
            logger.hr('触发停止条件: 运行次数')
            self.config.StopCondition_RunCount = 0
            self.config.Scheduler_Enable = False
            return True
        # 燃油限制
        if oil_check:
            # 检查 ui_current 是否存在，避免属性异常
            ui_is_campaign_menu = hasattr(self, 'ui_current') and self.ui_current == page_campaign_menu
            if (self._coalition_has_oil_icon or ui_is_campaign_menu
                    or self.config.Campaign_Event == 'coalition_20261124') and self.check_oil():
                logger.hr('触发停止条件: 石油上限')
                self.config.task_delay(minute=(120, 240))
                return True
        # 活动 PT 限制
        if pt_check:
            if self.event_pt_limit_triggered():
                logger.hr('触发停止条件: 活动PT上限')
                return True
        # 金币限制
        if coin_check and self.coin_limit_triggered():
            logger.hr('触发停止条件: 物资上限')
            return True
        # 任务均衡器
        if self.run_count >= 1:
            if self.config.TaskBalancer_Enable and self.triggered_task_balancer():
                logger.hr('触发停止条件: 物资上限')
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
            logger.warning('[联动] 不允许单舰队联动心情低于30，强制切换为防止黄脸模式')
            self.config.override(Emotion_Fleet1Control='prevent_yellow_face')
        if stage == 'sp' or (event == 'coalition_20261124' and stage == 'ex'):
            # SP 和真理学院的 EX 关卡需要多舰队。
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

        去除空白字符并转小写。霜落活动使用内部 TC 编号；
        其他活动兼容旧配置中的 TC-1/2/3 难度名。

        Args:
            event: 活动名称。
            stage: 关卡名称。

        Returns:
            tuple: (event, stage) 标准化后的名称。
        """
        stage = re.sub('[ \t\n]', '', str(stage)).lower()
        if event == 'coalition_20230323':
            stage = stage.replace('-', '')
            stage = {
                'easy': 'tc1',
                'normal': 'tc2',
                'hard': 'tc3',
            }.get(stage, stage)
        else:
            converted = {
                'tc1': 'easy',
                'tc2': 'normal',
                'tc3': 'hard',
            }.get(stage.replace('-', ''), stage)
            if converted != stage:
                logger.warning(f'转换旧版联动关卡: {stage} -> {converted}')
                stage = converted

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
                logger.info(f'剩余次数: {self.config.StopCondition_RunCount}')
            else:
                logger.info(f'计数: {self.run_count}')

            # 无燃油图标时，先在战役菜单检查停止条件
            if not self._coalition_has_oil_icon:
                self.ui_ensure(page_campaign_menu)
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
                logger.hr('脚本结束')
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
