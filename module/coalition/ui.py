"""联动活动 UI 处理模块。

提供联动活动的界面交互功能，包括页面检测、难度模式切换、
关卡选择确认、作战编成准备以及返回导航等。定义了
NeoncitySwitch 用于检测带红字提示的特殊状态。
"""

import unicodedata

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.coalition.assets import *
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.exception import CampaignNameError, RequestHumanTakeover, ScriptEnd, ScriptError
from module.logger import logger
from module.ocr.models import OCR_MODEL
from module.ui.assets import BACK_ARROW
from module.ui.page import get_coalition_page
from module.ui.switch import Switch


# 三服共用图像素材，EX 按各服的关卡名和结算文案读取。
VERITAS_EX_TEXT = {
    'cn': ('cnocr', '图书馆', '总得分', '确定'),
    'en': ('ppocr_v6', 'LIBRARY', 'TOTALSCORE', 'CONFIRM'),
    'jp': ('jp', '図書館', '合計スコア', '確定'),
}


class NeoncitySwitch(Switch):
    """霓虹都市联动活动模式切换开关。

    通过检测指定区域的红色文字像素以判断当前模式状态。
    """

    def get(self, main):
        """检测当前开关状态。

        Args:
            main (ModuleBase): 拥有图像检测能力的主运行实例。

        Returns:
            str: 匹配到的状态字符串，未匹配返回 'unknown'。
        """
        # 检查是否包含红字
        for data in self.state_list:
            if main.image_color_count(data['check_button'], color=(123, 41, 41), threshold=30, count=100):
                return data['state']

        return 'unknown'


class HorrorSwitch(Switch):
    """惊悚乐园联动活动模式切换开关。

    支持模式切换过程中的剧情跳过。
    """

    def handle_additional(self, main):
        """处理切换过程中的附加弹窗或剧情跳过。

        Args:
            main (ModuleBase): 主运行实例。

        Returns:
            bool: 是否进行了额外操作。
        """
        if main.handle_story_skip():
            return True
        return super().handle_additional(main)


class CoalitionUI(Combat):
    """联合出击活动界面交互基类。"""

    def in_coalition(self):
        """判断当前是否位于联合出击活动主界面。

        Returns:
            bool: 是否在联合出击主界面。
        """
        # 与突袭活动界面判断一致
        return self.ui_page_appear(get_coalition_page(self.config.Campaign_Event), offset=(20, 20))

    def ui_additional(self, get_ship=True):
        """导航遇到真理学院编队窗口时，先关闭编队再识别活动页。"""
        if (self.config.Campaign_Event == 'coalition_20261124'
                and self.appear(VERITAS_FLEET_PREPARATION, offset=(20, 50))
                and self.appear_then_click(VERITAS_FLEET_CLOSE, offset=(20, 20), interval=3)):
            return True
        return super().ui_additional(get_ship=get_ship)

    def in_coalition_20251120_difficulty_selection(self):
        """判断是否处于 20251120 联动活动的难度选择界面。

        Returns:
            bool: 是否在难度选择弹窗中。
        """
        return self.appear(DAL_DIFFICULTY_EXIT, offset=(20, 20))

    def coalition_ensure_mode(self, event, mode):
        """确保联动活动处于指定的战役模式（剧情模式或战斗模式）。

        Args:
            event (str): 活动标识符。
            mode (str): 目标模式，'story' 或 'battle'。

        Pages:
            in: in_coalition

        Raises:
            ScriptError: 未知活动的模式开关定义。
        """
        if event == 'coalition_20230323':
            mode_switch = Switch('CoalitionMode', offset=(20, 20))
            # 注意按钮状态反转
            # 但 TW 20260703 复刻活动未反转
            if self.config.SERVER == 'tw':
                mode_switch.add_state('story', FROSTFALL_MODE_BATTLE)
                mode_switch.add_state('battle', FROSTFALL_MODE_STORY)
            else:
                mode_switch.add_state('story', FROSTFALL_MODE_STORY)
                mode_switch.add_state('battle', FROSTFALL_MODE_BATTLE)
        elif event == 'coalition_20240627':
            mode_switch = Switch('CoalitionMode', offset=(20, 20))
            mode_switch.add_state('story', ACADEMY_MODE_BATTLE)
            mode_switch.add_state('battle', ACADEMY_MODE_STORY)
        elif event == 'coalition_20250626':
            mode_switch = NeoncitySwitch('CoalitionMode', offset=(20, 20))
            mode_switch.add_state('story', NEONCITY_MODE_STORY)
            mode_switch.add_state('battle', NEONCITY_MODE_BATTLE)
        elif event == 'coalition_20251120':
            logger.info('[联动-UI] 联动活动 coalition_20251120 无模式切换')
            return
        elif event == 'coalition_20260122':
            mode_switch = Switch('CoalitionMode', offset=(20, 20))
            mode_switch.add_state('story', FASHION_MODE_STORY)
            mode_switch.add_state('battle', FASHION_MODE_BATTLE)
        elif event == 'coalition_20260723':
            mode_switch = HorrorSwitch('CoalitionMode', offset=(50, 20))
            mode_switch.add_state('story', HORROR_MODE_STORY)
            mode_switch.add_state('battle', HORROR_MODE_BATTLE)
        elif event == 'coalition_20261124':
            mode_switch = HorrorSwitch('CoalitionMode', is_selector=True, offset=0)
            mode_switch.add_state('story', VERITAS_MODE_STORY)
            mode_switch.add_state('battle', VERITAS_MODE_BATTLE)
        else:
            logger.error(f'[联动-UI] MODE_SWITCH未定义在活动中 {event}')
            raise ScriptError

        if mode == 'story':
            mode_switch.set('story', main=self)
        elif mode == 'battle':
            mode_switch.set('battle', main=self)
        else:
            logger.warning(f'未知的联动战役模式: {mode}')

    def coalition_set_fleet(self, event, mode):
        """设置联动出击队伍模式（单队或多队）。

        Args:
            event (str): 活动标识符。
            mode (str): 队伍模式，'single' 或 'multi'。

        Returns:
            bool: 是否进行了切换点击。

        Pages:
            in: FLEET_PREPARATION

        Raises:
            ScriptError: 未知活动的舰队开关定义。
        """
        fleet_switch = Switch('FleetMode', is_selector=True, offset=0)  # 颜色匹配不设置偏移
        if event == 'coalition_20230323':
            fleet_switch.add_state('single', FROSTFALL_SWITCH_SINGLE)
            fleet_switch.add_state('multi', FROSTFALL_SWITCH_MULTI)
        elif event == 'coalition_20240627':
            fleet_switch.add_state('single', ACADEMY_SWITCH_SINGLE)
            fleet_switch.add_state('multi', ACADEMY_SWITCH_MULTI)
        elif event == 'coalition_20250626':
            fleet_switch.add_state('single', NEONCITY_SWITCH_SINGLE)
            fleet_switch.add_state('multi', NEONCITY_SWITCH_MULTI)
        elif event == 'coalition_20251120':
            fleet_switch.add_state('single', DAL_SWITCH_SINGLE)
            fleet_switch.add_state('multi', DAL_SWITCH_MULTI)
        elif event == 'coalition_20260122':
            fleet_switch.add_state('single', FASHION_SWITCH_SINGLE)
            fleet_switch.add_state('multi', FASHION_SWITCH_MULTI)
        elif event == 'coalition_20260723':
            fleet_switch.add_state('single', HORROR_SWITCH_SINGLE)
            fleet_switch.add_state('multi', HORROR_SWITCH_MULTI)
        elif event == 'coalition_20261124':
            fleet_switch.add_state('single', VERITAS_SWITCH_SINGLE)
            fleet_switch.add_state('multi', VERITAS_SWITCH_MULTI)
        else:
            logger.error(f'[联动-UI] FLEET_SWITCH未定义在活动中 {event}')
            raise ScriptError

        if fleet_switch.get(main=self) == mode:
            return False
        if mode in ('single', 'multi'):
            if event == 'coalition_20261124':
                fleet_switch.click(mode, main=self)
            else:
                fleet_switch.set(mode, main=self)
            return True
        else:
            logger.warning(f'未知的联动舰队模式: {mode}')
            return False

    @staticmethod
    def coalition_get_entrance(event, stage):
        """获取指定活动与关卡的入口按钮。

        Args:
            event (str): 活动标识符。
            stage (str): 关卡名称。

        Returns:
            Button: 关卡入口按钮。

        Raises:
            CampaignNameError: 未匹配到已知关卡。
        """
        dic = {
            # FROSTFALL
            ('coalition_20230323', 'tc1'): FROSTFALL_TC1,
            ('coalition_20230323', 'tc2'): FROSTFALL_TC2,
            ('coalition_20230323', 'tc3'): FROSTFALL_TC3,
            ('coalition_20230323', 'sp'): FROSTFALL_SP,
            ('coalition_20230323', 'ex'): FROSTFALL_EX,
            # ACADEMY
            ('coalition_20240627', 'easy'): ACADEMY_EASY,
            ('coalition_20240627', 'normal'): ACADEMY_NORMAL,
            ('coalition_20240627', 'hard'): ACADEMY_HARD,
            ('coalition_20240627', 'sp'): ACADEMY_SP,
            ('coalition_20240627', 'ex'): ACADEMY_EX,
            # NEONCITY
            ('coalition_20250626', 'easy'): NEONCITY_EASY,
            ('coalition_20250626', 'normal'): NEONCITY_NORMAL,
            ('coalition_20250626', 'hard'): NEONCITY_HARD,
            ('coalition_20250626', 'sp'): NEONCITY_SP,
            ('coalition_20250626', 'ex'): NEONCITY_EX,
            # DAL
            ('coalition_20251120', 'area1-normal'): DAL_AREA1,
            ('coalition_20251120', 'area2-normal'): DAL_AREA2,
            ('coalition_20251120', 'area3-normal'): DAL_AREA3,
            ('coalition_20251120', 'area4-normal'): DAL_AREA4,
            ('coalition_20251120', 'area5-normal'): DAL_AREA5,
            ('coalition_20251120', 'area6-normal'): DAL_AREA6,
            ('coalition_20251120', 'area1-hard'): DAL_AREA1,
            ('coalition_20251120', 'area2-hard'): DAL_AREA2,
            ('coalition_20251120', 'area3-hard'): DAL_AREA3,
            ('coalition_20251120', 'area4-hard'): DAL_AREA4,
            ('coalition_20251120', 'area5-hard'): DAL_AREA5,
            ('coalition_20251120', 'area6-hard'): DAL_AREA6,
            # FASHION
            ('coalition_20260122', 'easy'): FASHION_EASY,
            ('coalition_20260122', 'normal'): FASHION_NORMAL,
            ('coalition_20260122', 'hard'): FASHION_HARD,
            ('coalition_20260122', 'sp'): FASHION_SP,
            ('coalition_20260122', 'ex'): FASHION_EX,
            # HORROR
            ('coalition_20260723', 'easy'): HORROR_EASY,
            ('coalition_20260723', 'normal'): HORROR_NORMAL,
            ('coalition_20260723', 'hard'): HORROR_HARD,
            ('coalition_20260723', 'sp'): HORROR_SP,
            ('coalition_20260723', 'ex'): HORROR_EX,
            # VERITAS
            ('coalition_20261124', 'easy'): VERITAS_EASY,
            ('coalition_20261124', 'normal'): VERITAS_NORMAL,
            ('coalition_20261124', 'hard'): VERITAS_HARD,
            ('coalition_20261124', 'sp'): VERITAS_SP,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError

    def veritas_text_buttons(self, area, labels):
        """将真理学院页面上的指定文字位置转换为点击区域。"""
        model_name, _, _, _ = VERITAS_EX_TEXT[self.config.SERVER]
        ocr = getattr(OCR_MODEL, model_name)
        left, top, _, _ = area
        for text, box, _ in ocr.det(crop(self.device.image, area)):
            label = ''.join(unicodedata.normalize('NFKC', text).split()).upper().replace('.', '')
            if label not in labels:
                continue
            x, y = zip(*box)
            rect = (left + int(min(x)), top + int(min(y)), left + int(max(x)), top + int(max(y)))
            center_x = (rect[0] + rect[2]) // 2
            center_y = (rect[1] + rect[3]) // 2
            # OCR 边框可能包含按钮外沿，点击集中在文字中央。
            click_area = (center_x - 4, center_y - 4, center_x + 4, center_y + 4)
            yield Button(area=rect, color=(), button=click_area, name=label)

    def veritas_ex_entrance(self):
        """定位通关 SP 后显示的图书馆入口。"""
        _, name, _, _ = VERITAS_EX_TEXT[self.config.SERVER]
        labels = (name, f'EX{name}', f'{name}EX')
        buttons = list(self.veritas_text_buttons((0, 106, 1280, 613), (*labels, 'EX')))
        # 优先点击关卡名。只识别出 EX 标志时，该标志也位于关卡入口内。
        matches = [button for button in buttons if button.name in labels] or buttons
        return matches[0] if len(matches) == 1 else None

    def handle_veritas_ex_result(self):
        """识别 EX 总得分页面的确定按钮，返回是否点击。"""
        _, _, score, confirm = VERITAS_EX_TEXT[self.config.SERVER]
        buttons = list(self.veritas_text_buttons((0, 0, 1280, 720), (score, confirm)))
        confirms = [button for button in buttons if button.name == confirm]
        if len(confirms) == 1 and any(button.name == score for button in buttons):
            self.device.click(confirms[0])
            return True
        return False

    @staticmethod
    def coalition_20251120_get_entrance_difficulty(event, stage):
        """获取 20251120 联动活动关卡的难度选择按钮。

        Args:
            event (str): 活动标识符。
            stage (str): 关卡名称。

        Returns:
            Button: 难度选择按钮（普通或困难）。

        Raises:
            CampaignNameError: 未匹配到已知关卡。
        """
        dic = {
            # DAL
            ('coalition_20251120', 'area1-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area2-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area3-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area4-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area5-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area6-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area1-hard'): DAL_HARD,
            ('coalition_20251120', 'area2-hard'): DAL_HARD,
            ('coalition_20251120', 'area3-hard'): DAL_HARD,
            ('coalition_20251120', 'area4-hard'): DAL_HARD,
            ('coalition_20251120', 'area5-hard'): DAL_HARD,
            ('coalition_20251120', 'area6-hard'): DAL_HARD,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError

    @staticmethod
    def coalition_get_battles(event, stage):
        """获取指定联动关卡包含的战斗场次数。

        Args:
            event (str): 活动标识符。
            stage (str): 关卡名称。

        Returns:
            int: 战斗场次数。

        Raises:
            CampaignNameError: 未匹配到已知关卡。
        """
        dic = {
            # FROSTFALL
            ('coalition_20230323', 'tc1'): 1,
            ('coalition_20230323', 'tc2'): 2,
            ('coalition_20230323', 'tc3'): 3,
            ('coalition_20230323', 'sp'): 1,
            ('coalition_20230323', 'ex'): 1,
            # ACADEMY
            ('coalition_20240627', 'easy'): 1,
            ('coalition_20240627', 'normal'): 2,
            ('coalition_20240627', 'hard'): 3,
            ('coalition_20240627', 'sp'): 4,
            ('coalition_20240627', 'ex'): 5,
            # NEONCITY
            ('coalition_20250626', 'easy'): 1,
            ('coalition_20250626', 'normal'): 2,
            ('coalition_20250626', 'hard'): 3,
            ('coalition_20250626', 'sp'): 4,
            ('coalition_20250626', 'ex'): 5,
            # DAL
            ('coalition_20251120', 'area1-normal'): 2,
            ('coalition_20251120', 'area2-normal'): 3,
            ('coalition_20251120', 'area3-normal'): 3,
            ('coalition_20251120', 'area4-normal'): 3,
            ('coalition_20251120', 'area5-normal'): 3,
            ('coalition_20251120', 'area6-normal'): 4,
            ('coalition_20251120', 'area1-hard'): 2,
            ('coalition_20251120', 'area2-hard'): 3,
            ('coalition_20251120', 'area3-hard'): 3,
            ('coalition_20251120', 'area4-hard'): 3,
            ('coalition_20251120', 'area5-hard'): 3,
            ('coalition_20251120', 'area6-hard'): 4,
            # FASHION
            ('coalition_20260122', 'easy'): 1,
            ('coalition_20260122', 'normal'): 2,
            ('coalition_20260122', 'hard'): 3,
            ('coalition_20260122', 'sp'): 4,
            ('coalition_20260122', 'ex'): 5,
            # HORROR
            ('coalition_20260723', 'easy'): 1,
            ('coalition_20260723', 'normal'): 2,
            ('coalition_20260723', 'hard'): 3,
            ('coalition_20260723', 'sp'): 4,
            ('coalition_20260723', 'ex'): 5,
            # VERITAS
            ('coalition_20261124', 'easy'): 1,
            ('coalition_20261124', 'normal'): 2,
            ('coalition_20261124', 'hard'): 3,
            ('coalition_20261124', 'sp'): 4,
            ('coalition_20261124', 'ex'): 5,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError

    @staticmethod
    def coalition_get_fleet_preparation(event):
        """获取指定联动活动出击编队准备按钮。

        Args:
            event (str): 活动标识符。

        Returns:
            Button: 编队准备按钮。

        Raises:
            ScriptError: 未定义活动的编队按钮。
        """
        if event == 'coalition_20230323':
            return FROSTFALL_FLEET_PREPARATION
        elif event == 'coalition_20240627':
            return ACEDEMY_FLEET_PREPARATION
        elif event == 'coalition_20250626':
            return NEONCITY_FLEET_PREPARATION
        elif event == 'coalition_20251120':
            return DAL_FLEET_PREPARATION
        elif event == 'coalition_20260122':
            # FASHION 复用 NEONCITY 资源，整体向 (-12, -12) 偏移
            return NEONCITY_FLEET_PREPARATION
        elif event == 'coalition_20260723':
            return HORROR_FLEET_PREPARATION
        elif event == 'coalition_20261124':
            return VERITAS_FLEET_PREPARATION
        else:
            logger.error(f'[联动-UI] FLEET_PREPARATION未定义在活动中 {event}')
            raise ScriptError

    def handle_fleet_preparation(self, event, stage, mode):
        """处理联动编队界面的舰队检查与单队/多队模式配置。

        Args:
            event (str): 活动标识符。
            stage (str): 关卡名称。
            mode (str): 舰队模式，'single' 或 'multi'。

        Returns:
            bool: 是否进行了点击配置。

        Raises:
            RequestHumanTakeover: 舰队未就绪或旗舰/先锋为空，请求人工介入。
        """
        stage = stage.lower()

        if event == 'coalition_20230323':
            # TC1 和 SP 模式无队伍切换开关
            if stage in ['tc1', 'sp']:
                return False
        if event in [
            'coalition_20240627',
            'coalition_20250626',
            'coalition_20260122',
            'coalition_20260723',
            'coalition_20261124',
        ]:
            # easy 固定单队，SP 和 EX 必须多队
            if stage in ['easy', 'sp', 'ex']:
                return False

        clicked = self.coalition_set_fleet(event, mode)
        if clicked and event == 'coalition_20261124':
            return True

        if self.appear(FLEET_NOT_PREPARED, offset=(20, 20)):
            logger.critical('[联动] 舰队未就绪')
            logger.critical('[联动] 请先就绪舰队')
            raise RequestHumanTakeover
        if self.appear(EMPTY_FLAGSHIP, offset=(20, 20)):
            logger.critical('[联动] 舰队未就绪')
            logger.critical('[联动] 请先就绪舰队')
            raise RequestHumanTakeover
        if self.appear(EMPTY_VANGUARD, offset=(20, 20)):
            logger.critical('[联动] 舰队未就绪')
            logger.critical('[联动] 请先就绪舰队')
            raise RequestHumanTakeover

        return clicked

    def coalition_map_exit(self, event):
        """退出当前关卡编成或准备界面，返回联动主界面。

        Args:
            event (str): 活动标识符。

        Pages:
            in: BATTLE_PREPARATION 或各活动特定的 fleet_preparation
            out: in_coalition
        """
        logger.info('联动地图退出')
        fleet_preparation = self.coalition_get_fleet_preparation(event)
        if event == 'coalition_20261124':
            fleet_exit = VERITAS_FLEET_CLOSE
            fleet_offset = (20, 50)
        else:
            fleet_exit = NEONCITY_PREPARATION_EXIT
            fleet_offset = (20, 20)
        for _ in self.loop():
            if self.in_coalition():
                break
            if self.is_in_main():
                break

            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=3):
                logger.info(f'{BATTLE_PREPARATION} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                continue
            if self.appear(fleet_preparation, offset=fleet_offset, interval=3):
                logger.info(f'{fleet_preparation} -> {fleet_exit}')
                self.device.click(fleet_exit)
                continue
            if event == 'coalition_20251120':
                if self.appear_then_click(DAL_DIFFICULTY_EXIT, offset=(20, 20), interval=3):
                    logger.info(f'{DAL_DIFFICULTY_EXIT} -> {DAL_DIFFICULTY_EXIT}')
                    continue

    def enter_map(self, event, stage, mode):
        """进入指定的联动活动关卡并完成出击前准备。

        Args:
            event (str): 活动标识符，如 'coalition_20230323'。
            stage (str): 关卡名称，如 'TC3'。
            mode (str): 舰队模式，'single' 或 'multi'。

        Pages:
            in: in_coalition
            out: BATTLE_PREPARATION

        Raises:
            RequestHumanTakeover: 进入关卡或准备舰队连续失败超过阈值。
        """
        veritas_ex = event == 'coalition_20261124' and stage.lower() == 'ex'
        button = None if veritas_ex else self.coalition_get_entrance(event, stage)
        if event in ['coalition_20251120']:
            button_difficulty = self.coalition_20251120_get_entrance_difficulty(event, stage)
        else:
            button_difficulty = None
        fleet_preparation = self.coalition_get_fleet_preparation(event)
        campaign_timer = Timer(5)
        campaign_difficulty_timer = Timer(5)
        fleet_timer = Timer(5)
        campaign_click = 0
        campaign_difficulty_click = 0
        fleet_click = 0

        for _ in self.loop():
            # 异常检查
            if campaign_click > 5:
                logger.critical(f"[联动] 无法进入 {button or stage}，尝试次数过多")
                logger.critical("[联动] 可能的原因1: 你还没有通关前置关卡，无法解锁该关卡。")
                raise RequestHumanTakeover
            if campaign_difficulty_click > 5:
                logger.critical(f"[联动] 无法进入 {button_difficulty}，点击次数过多")
                logger.critical("[联动] 可能的原因1: 难度资源的图片不正确。")
                raise RequestHumanTakeover
            if fleet_click > 5 and stage.lower() == 'sp':
                # SP 每天只能出击一次；当天已手动打过时游戏只弹出短暂提示，出击无反应。
                # 视为今日已完成，退出关卡并由 CoalitionSP 推迟到下次服务器刷新，避免重启模拟器循环。
                logger.warning(f"[联动] {button} 出击无反应，视为今日 SP 次数已用完，推迟到下次服务器刷新")
                self.coalition_map_exit(event)
                self.sp_attempt_used = True
                raise ScriptEnd('SP attempt already used today')
            if fleet_click > 5:
                logger.critical(f"[联动] 无法进入 {button}，点击次数过多")
                logger.critical("[联动] 可能的原因1: 你的舰队未达到该关卡的属性要求。")
                logger.critical("[联动] 可能的原因2: 该关卡每天只能进入一次，但这是你第二次尝试进入。")
                raise RequestHumanTakeover

            # 退出条件
            if self.appear(BATTLE_PREPARATION, offset=(20, 20)):
                break

            if self.handle_guild_popup_cancel():
                continue

            # 作战委托进行中，出击会被游戏阻止
            if self.handover_conflict_appear():
                self.handle_handover_conflict()
                continue

            # 进入关卡
            if campaign_timer.reached() and self.in_coalition():
                if veritas_ex:
                    button = self.veritas_ex_entrance()
                if button is not None:
                    self.device.click(button)
                campaign_click += 1
                campaign_timer.reset()
                continue
            if event in ['coalition_20251120']:
                if campaign_difficulty_timer.reached() and self.in_coalition_20251120_difficulty_selection() and button_difficulty:
                    self.device.click(button_difficulty)
                    campaign_difficulty_click += 1
                    campaign_difficulty_timer.reset()
                    continue

            # 舰队准备
            if fleet_timer.reached() and self.appear(fleet_preparation, offset=(20, 50)):
                if self.handle_fleet_preparation(event, stage, mode) and event == 'coalition_20261124':
                    # 切换舰队模式会改变编队内容，先用新截图确认再出击。
                    fleet_timer.reset()
                    continue
                self.device.click(fleet_preparation)
                fleet_click += 1
                fleet_timer.reset()
                campaign_timer.reset()
                continue

            # 自律寻敌确认
            if self.handle_auto_search_continue():
                campaign_timer.reset()
                continue

            # 船坞满退役
            if self.handle_retirement():
                continue

            # 心情低落
            if self.handle_combat_low_emotion():
                continue

            # 紧急委托
            if self.handle_urgent_commission(drop=None):
                continue

            # 剧情跳过
            if self.handle_story_skip():
                campaign_timer.reset()
                continue

            # 自动战斗确认
            if self.handle_combat_automation_confirm():
                continue

            # 2026.01.22 联动活动 FASHION 增加了从上一队加载舰队的弹窗提示
            # 联动活动不允许心情低落战斗，点击任意弹窗确认均属安全操作
            if self.handle_popup_confirm('COALITION'):
                continue
