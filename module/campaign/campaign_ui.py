"""
战役 UI 导航与章节管理模块。

负责战役界面的 UI 操作，包括：
- 章节切换（数字章节、活动章节、SP 章节）
- 战役模式切换（普通/困难/EX）
- 多版本活动 UI 适配（20241219、20260326 等不同活动 UI 布局）
- 关卡入口获取与章节导航

本模块通过 ModeSwitch 实现战役模式的检测与切换，
通过 CampaignOcr 实现章节索引的 OCR 识别。
"""

from module.base.timer import Timer
from module.base.utils import area_offset
from module.campaign.assets import *
from module.campaign.campaign_event import CampaignEvent
from module.campaign.campaign_ocr import CampaignOcr
from module.exception import CampaignEnd, CampaignNameError, ScriptEnd
from module.logger import logger
from module.map.assets import WITHDRAW, MAP_PREPARATION, MAP_PREPARATION_HARD, FLEET_PREPARATION, MAP_PREPARATION_CANCEL
from module.map.map_operation import MapOperation
from module.ui.assets import CAMPAIGN_CHECK
from module.ui.switch import Switch


class ModeSwitch(Switch):
    """战役模式切换开关。

    扩展 Switch 类，在切换过程中检测 WITHDRAW 按钮出现的异常情况。
    如果在模式切换时意外出现撤退按钮，说明进入了错误的地图状态，
    会抛出 CampaignNameError 进行异常恢复。
    """

    def handle_additional(self, main):
        """处理模式切换过程中的额外异常状态。

        Args:
            main: 当前执行环境对象。

        Raises:
            CampaignNameError: 意外检测到撤退按钮时抛出。
        """
        if main.appear(WITHDRAW, offset=(30, 30)):
            logger.warning(f'模式切换: 出现撤退按钮')
            raise CampaignNameError
        # missing blur background of MAP_PREPARATION on memu player
        # Mode_switch_20241219 and MAP_PREPARARION appears at the same time
        # Campaign preparation
        if main.appear(MAP_PREPARATION, offset=(30, 30), interval=3) \
                or main.appear(MAP_PREPARATION_HARD, offset=(30, 30), interval=3) \
                or main.appear(FLEET_PREPARATION, offset=(20, 50), interval=3):
            main.device.click(MAP_PREPARATION_CANCEL)
            return True


MODE_SWITCH_1 = ModeSwitch('Mode_switch_1', offset=(30, 10))
MODE_SWITCH_1.add_state('normal', SWITCH_1_NORMAL)
MODE_SWITCH_1.add_state('hard', SWITCH_1_HARD)
MODE_SWITCH_2 = ModeSwitch('Mode_switch_2', offset=(30, 10))
MODE_SWITCH_2.add_state('hard', SWITCH_2_HARD)
MODE_SWITCH_2.add_state('ex', SWITCH_2_EX)

# 活动模式切换从 20240725 变更为 20241219
# 20241219 起趋于稳定，因此以该日期命名
MODE_SWITCH_20241219 = ModeSwitch('Mode_switch_20241219', is_selector=True, offset=(30, 30))
MODE_SWITCH_20241219.add_state('combat', SWITCH_20241219_COMBAT)
MODE_SWITCH_20241219.add_state('story', SWITCH_20241219_STORY)
ASIDE_SWITCH_20241219 = ModeSwitch('Aside_switch_20241219', is_selector=True, offset=(20, 20))
ASIDE_SWITCH_20241219.add_state('part1', CHAPTER_20241219_PART1)
ASIDE_SWITCH_20241219.add_state('part2', CHAPTER_20241219_PART2)
ASIDE_SWITCH_20241219.add_state('sp', CHAPTER_20241219_SP)
ASIDE_SWITCH_20241219.add_state('ex', CHAPTER_20241219_EX)
# 缩短 unknown_timer 以加快处理
# 因为游戏 bug 导致战役撤退或完成后侧边指示器可能消失
ASIDE_SWITCH_20241219.set_unknown_timer = Timer(0.6, count=2)

ASIDE_SWITCH_20260326 = ModeSwitch('Aside_switch_20260326', is_selector=True, offset=(30, 30))
ASIDE_SWITCH_20260326.add_state('part1', CHAPTER_20260326_PART1)
ASIDE_SWITCH_20260326.add_state('sp', CHAPTER_20260326_SP)
ASIDE_SWITCH_20260326.set_unknown_timer = Timer(0.6, count=2)


def is_digit_chapter(chapter):
    """
    判断章节是否为数字章节。

    Args:
         chapter (int, str): 章节名称，如 7、'd'、'sp'。

    Returns:
        bool: 是否为数字章节。
    """
    if isinstance(chapter, int):
        return True
    try:
        return chapter[0].isdigit()
    except IndexError:
        return False


class CampaignUI(MapOperation, CampaignEvent, CampaignOcr):
    """战役 UI 导航与管理类。

    提供战役界面的所有 UI 操作能力，包括章节切换、模式切换、
    关卡入口获取等。支持主线战役、活动战役、SP 章节和作战档案
    等多种战役类型。

    通过组合 MapOperation（地图操作）、CampaignEvent（活动检测）
    和 CampaignOcr（章节 OCR 识别）实现完整的战役 UI 管理。

    本类是 CampaignBase 的父类之一，为战役执行提供 UI 层支持。

    Attributes:
        ENTRANCE (Button): 当前关卡的入口按钮，由 ensure_campaign_ui() 设置。
        stage_entrance (dict): 关卡名称到入口按钮的映射字典，
            由 CampaignOcr 的模板匹配生成。
        campaign_chapter (str): 当前章节标识，如 '7'、'd'、'sp'。
    """
    ENTRANCE = Button(area=(), color=(), button=(), name='default_button')

    def campaign_ensure_chapter(self, chapter, skip_first_screenshot=True):
        """确保切换到指定章节。

        Args:
            chapter (int | str): 章节名称，如 7、'd'、'sp'。
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。
        """
        index = self._campaign_get_chapter_index(chapter)
        isdigit = is_digit_chapter(chapter)

        # 复用 ui_ensure_index 的逻辑。
        logger.hr("UI确保索引")
        retry = Timer(1, count=2)
        error_confirm = Timer(0.2, count=0)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_chapter_additional():
                continue

            current = self.get_chapter_index()
            current_isdigit = is_digit_chapter(self.campaign_chapter)

            logger.attr("当前索引", current)
            diff = index - current
            if diff == 0:
                break

            # 查找 D3 时可能误识别为 3-7
            if not (isdigit == current_isdigit):
                continue

            # 14-4 可能因动画缓慢被 OCR 识别为 4-1，需要确认是否确实为 4-1
            if index >= 11 and index % 10 == current:
                error_confirm.start()
                if not error_confirm.reached():
                    continue
            else:
                error_confirm.reset()

            # 切换章节
            if retry.reached():
                button = CHAPTER_NEXT if diff > 0 else CHAPTER_PREV
                self.device.multi_click(button, n=abs(diff), interval=(0.2, 0.3))
                retry.reset()

    def handle_chapter_additional(self):
        """
        章节切换时的额外处理，由 campaign_ensure_chapter() 调用。

        Returns:
            bool: 是否已处理。
        """
        return False

    def campaign_ensure_mode(self, mode='normal'):
        """
        确保切换到指定战役模式。

        Args:
            mode (str): 'normal'、'hard'、'ex'。
        """
        if mode == 'hard':
            self.config.override(Campaign_Mode='hard')

        switch_2 = MODE_SWITCH_2.get(main=self)

        if switch_2 == 'unknown':
            if mode == 'ex':
                logger.warning('尝试前往EX，但无EX模式切换')
            elif mode == 'normal':
                MODE_SWITCH_1.set('hard', main=self)
            elif mode == 'hard':
                MODE_SWITCH_1.set('normal', main=self)
            else:
                logger.warning(f'未知的战役模式: {mode}')
        else:
            if mode == 'ex':
                MODE_SWITCH_2.set('hard', main=self)
            elif mode == 'normal':
                MODE_SWITCH_2.set('ex', main=self)
                MODE_SWITCH_1.set('hard', main=self)
            elif mode == 'hard':
                MODE_SWITCH_2.set('ex', main=self)
                MODE_SWITCH_1.set('normal', main=self)
            else:
                logger.warning(f'未知的战役模式: {mode}')

    def campaign_ensure_mode_20241219(self, mode='combat'):
        """
        确保切换到 20241219 版本的战役模式。

        Args:
            mode (str): 'combat' 或 'story'。
        """
        if mode in ['normal', 'hard', 'ex', 'combat']:
            MODE_SWITCH_20241219.set('combat', main=self)
        elif mode in ['story']:
            MODE_SWITCH_20241219.set('story', main=self)
        else:
            logger.warning(f'未知的战役模式: {mode}')

    def campaign_ensure_aside_20241219(self, chapter):
        """
        确保切换到 20241219 版本的侧边栏标签。

        Args:
            chapter: 'part1'、'part2'、'sp'、'ex'。
        """
        if chapter in ['part1', 'a', 'c', 't']:
            ASIDE_SWITCH_20241219.set('part1', main=self)
        elif chapter in ['part2', 'b', 'd']:
            ASIDE_SWITCH_20241219.set('part2', main=self)
        elif chapter in ['sp', 'ex_sp']:
            ASIDE_SWITCH_20241219.set('sp', main=self)
        elif chapter in ['ex', 'ex_ex']:
            ASIDE_SWITCH_20241219.set('ex', main=self)
        else:
            logger.warning(f'未知的战役侧边栏: {chapter}')

    def campaign_ensure_aside_20260326(self, chapter):
        """
        确保切换到 20260326 版本的侧边栏标签。

        Args:
            chapter: 'part1'、'sp'。
        """
        if chapter in ['part1', 't', 'ht']:
            ASIDE_SWITCH_20260326.set('part1', main=self)
        elif chapter in ['sp', 'ex_sp']:
            ASIDE_SWITCH_20260326.set('sp', main=self)
        else:
            logger.warning(f'未知的战役侧边栏: {chapter}')

    def campaign_get_mode_names(self, name):
        """
        获取关卡在普通和困难模式下的名称。
        t1 -> [t1, ht1]
        ht1 -> [t1, ht1]
        a1 -> [a1, c1]

        Args:
            name (str): 关卡名称。

        Returns:
            list[str]: 普通和困难模式下的关卡名称列表。
        """
        if name.startswith('t'):
            return [f't{name[1:]}', f'ht{name[1:]}']
        if name.startswith('ht'):
            return [f't{name[2:]}', f'ht{name[2:]}']
        if name.startswith('a') or name.startswith('c'):
            return [f'a{name[1:]}', f'c{name[1:]}']
        if name.startswith('b') or name.startswith('d'):
            return [f'b{name[1:]}', f'd{name[1:]}']
        return [name]

    def _campaign_name_is_hard(self, name):
        """
        复用 campaign_get_mode_names() 中的定义判断是否为困难模式。

        Args:
            name: 'a1'、'ht1'、'sp1'。

        Returns:
            bool: 是否为困难模式关卡。
        """
        mode_names = self.campaign_get_mode_names(name)
        if len(mode_names) == 2 and mode_names[1] == name:
            return True
        else:
            return False

    def campaign_get_entrance(self, name):
        """
        获取关卡入口按钮。

        Args:
            name (str): 战役名称，如 '7-2'、'd3'、'sp3'。

        Returns:
            Button: 关卡入口按钮。
        """
        entrance_name = name
        # 特殊情况：d3_3 在 UI 中使用 d3 的入口，但加载 d3_3.py 中不同的战斗逻辑
        search_name = name
        if name == 'd3_3':
            search_name = 'd3'
            logger.info(f'[战役-UI] 关卡 {name} 在UI中使用入口 {search_name}')

        if self.config.MAP_HAS_MODE_SWITCH:
            for mode_name in self.campaign_get_mode_names(search_name):
                if mode_name in self.stage_entrance:
                    search_name = mode_name

        if search_name not in self.stage_entrance:
            logger.warning(f'关卡未找到: {search_name}')
            raise CampaignNameError

        entrance = self.stage_entrance[search_name]
        entrance.name = entrance_name
        return entrance

    def campaign_set_chapter_main(self, chapter, mode='normal'):
        """
        设置主线战役章节。

        导航到主线战役页面，切换到指定章节和模式。

        Args:
            chapter (str): 章节标识，如 '7'、'12'。
            mode (str): 'normal' 或 'hard'。

        Returns:
            bool: True 表示成功设置，False 表示不是主线数字章节。
        """
        if chapter.isdigit():
            self.ui_goto_campaign()
            self.campaign_ensure_mode('normal')
            self.campaign_ensure_chapter(chapter)
            if mode == 'hard':
                self.campaign_ensure_mode('hard')
                # info_bar 可能显示：该地图的困难模式尚未开放。
                # 英文服存在 bug，HM12 显示未开放但实际上可以进入。
                self.handle_info_bar()
                self.campaign_ensure_chapter(chapter)
            return True
        else:
            return False

    def campaign_set_chapter_event(self, chapter, mode='normal'):
        """
        设置活动战役章节。

        导航到活动战役页面，根据章节标识自动切换模式（a/b 为普通，c/d 为困难）。

        Args:
            chapter (str): 章节标识，如 'a'、'b'、'c'、'd'、'sp' 等。
            mode (str): 'normal' 或 'hard'。

        Returns:
            bool: True 表示成功设置，False 表示不是活动章节。
        """
        if chapter in ['a', 'b', 'c', 'd', 'ex_sp', 'as', 'bs', 'cs', 'ds', 't', 'ts', 'tss', 'ht', 'hts']:
            self.ui_goto_event()
            if chapter in ['a', 'b', 'as', 'bs', 't', 'ts', 'tss']:
                self.campaign_ensure_mode('normal')
            elif chapter in ['c', 'd', 'cs', 'ds', 'ht', 'hts']:
                self.campaign_ensure_mode('hard')
            elif chapter == 'ex_sp':
                self.campaign_ensure_mode('ex')
            self.campaign_ensure_chapter(chapter)
            return True
        else:
            return False

    def campaign_set_chapter_sp(self, chapter, mode='normal'):
        """
        设置 SP 章节。

        导航到 SP 页面并切换到 SP 章节。

        Args:
            chapter (str): 章节标识，必须为 'sp'。
            mode (str): 'normal' 或 'hard'（未使用）。

        Returns:
            bool: True 表示成功设置，False 表示不是 SP 章节。
        """
        if chapter == 'sp':
            self.ui_goto_sp()
            self.campaign_ensure_chapter(chapter)
            return True
        else:
            return False

    def campaign_set_chapter_20241219(self, chapter, stage, mode='combat'):
        """
        设置 20241219 版本活动的章节。

        处理 2024 年 12 月起趋于稳定的活动 UI 布局，支持多种侧边栏配置：
        - MAP_CHAPTER_SWITCH_20241219：标准四分区（part1/part2/sp/ex）
        - MAP_CHAPTER_SWITCH_20241219_SP：简化的 SP 布局
        - MAP_CHAPTER_SWITCH_20241219_SPEX：带 EX 的 SP 布局

        Args:
            chapter (str): 章节标识，如 'a'、'b'、'sp'、'ex_sp' 等。
            stage (str): 关卡编号，如 '1'、'2'。
            mode (str): 'combat' 或 'story'。

        Returns:
            bool: True 表示成功设置，False 表示不适用此版本。
        """
        if self.config.MAP_CHAPTER_SWITCH_20241219:
            if self._campaign_name_is_hard(f'{chapter}{stage}'):
                self.config.override(Campaign_Mode='hard')
            # part1、part2、sp、ex
            if mode == 'story':
                self.campaign_ensure_mode_20241219('story')
                return True
            if chapter in ['a', 'c', 't']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20241219('part1')
                self.campaign_ensure_chapter(chapter)
                return True
            if chapter in ['b', 'd', 'ttl']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20241219('part2')
                self.campaign_ensure_chapter(chapter)
                return True
            if chapter in ['ex_sp']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20241219('sp')
                self.campaign_ensure_chapter(chapter)
                return True
            # 部分活动将普通关卡命名为 SP1/SP2...
            # 将其路由到 page_event 并保持默认侧边栏。
            if chapter in ['sp']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_chapter(chapter)
                return True
            if chapter in ['ex_ex']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20241219('ex')
                self.campaign_ensure_chapter(chapter)
                return True
        if self.config.MAP_CHAPTER_SWITCH_20241219_SP:
            if self._campaign_name_is_hard(f'{chapter}{stage}'):
                self.config.override(Campaign_Mode='hard')
            # (空)、normal、sp、(空)
            if chapter in ['sp', 't', 'ht']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                # normal 位于 part2 的位置
                self.campaign_ensure_aside_20241219('part2')
                self.campaign_ensure_chapter(chapter)
                return True
            if chapter in ['ex_sp']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20241219('sp')
                self.campaign_ensure_chapter(chapter)
                return True
        if self.config.MAP_CHAPTER_SWITCH_20241219_SPEX:
            if self._campaign_name_is_hard(f'{chapter}{stage}'):
                self.config.override(Campaign_Mode='hard')
            # normal、sp、ex
            try:
                ASIDE_SWITCH_20241219.offset = area_offset((-20, -20, 20, 20), (0, -37))
                if chapter in ['sp', 't', 'ht']:
                    self.ui_goto_event()
                    self.campaign_ensure_mode_20241219('combat')
                    # normal 位于 part2 的位置
                    self.campaign_ensure_aside_20241219('part2')
                    self.campaign_ensure_chapter(chapter)
                    return True
                if chapter in ['ex_sp']:
                    self.ui_goto_event()
                    self.campaign_ensure_mode_20241219('combat')
                    self.campaign_ensure_aside_20241219('sp')
                    self.campaign_ensure_chapter(chapter)
                    return True
                if chapter in ['ex_sp']:
                    self.ui_goto_event()
                    self.campaign_ensure_mode_20241219('combat')
                    self.campaign_ensure_aside_20241219('sp')
                    self.campaign_ensure_chapter(chapter)
                    return True
            finally:
                ASIDE_SWITCH_20241219.offset = (20, 20)
        return False

    def campaign_set_chapter_20260326(self, chapter, stage, mode='combat'):
        """
        设置 20260326 版本活动的章节。

        处理 2026 年 3 月版本的活动 UI 布局，侧边栏分为 part1 和 sp 两区。

        Args:
            chapter (str): 章节标识，如 't'、'ht'、'ex_sp'。
            stage (str): 关卡编号。
            mode (str): 'combat' 或 'story'。

        Returns:
            bool: True 表示成功设置，False 表示不适用此版本。
        """
        if self.config.MAP_CHAPTER_SWITCH_20260326:
            if self._campaign_name_is_hard(f'{chapter}{stage}'):
                self.config.override(Campaign_Mode='hard')
            if mode == 'story':
                self.campaign_ensure_mode_20241219('story')
                return True
            if chapter in ['t', 'ht']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20260326('part1')
                self.campaign_ensure_chapter(chapter)
                return True
            if chapter in ['ex_sp']:
                self.ui_goto_event()
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_aside_20260326('sp')
                self.campaign_ensure_chapter(chapter)
                return True
        return False

    def campaign_set_chapter(self, name, mode='normal'):
        """设置并切换到目标战役章节。

        按主线、各版本活动、SP 章节的顺序依次尝试切换。

        Args:
            name (str): 战役名称，如 '7-2'、'd3'、'sp3'。
            mode (str): 'normal' 或 'hard'。默认 'normal'。
        """
        # 特殊情况：d3_3 在章节导航中使用 d3
        chapter_name = name
        if name == 'd3_3':
            chapter_name = 'd3'
        
        chapter, stage = self._campaign_separate_name(chapter_name)

        if self.campaign_set_chapter_main(chapter, mode):
            pass
        elif self.campaign_set_chapter_20260326(chapter, stage, mode):
            pass
        elif self.campaign_set_chapter_20241219(chapter, stage, mode):
            pass
        elif self.campaign_set_chapter_event(chapter, mode):
            pass
        elif self.campaign_set_chapter_sp(chapter, mode):
            pass
        else:
            logger.warning(f'[战役-UI] 未知的战役章节: {name}')

    def handle_campaign_ui_additional(self):
        """战役 UI 的额外异常处理。

        若检测到撤退按钮，则等待信息提示条消失后执行撤退。

        Returns:
            bool: 是否进行了额外处理。
        """
        if self.appear(WITHDRAW, offset=(30, 30)):
            # logger.info("发现 WITHDRAW 按钮，等待地图加载完成以防止游戏客户端 bug")
            self.ensure_no_info_bar(timeout=2)
            try:
                self.withdraw()
            except CampaignEnd:
                pass
            return True
        return False

    def ensure_campaign_ui(self, name, mode='normal', skip_first_screenshot=True):
        """确保进入指定战役的 UI 界面并获取关卡入口。

        Args:
            name (str): 战役名称，如 '7-2'、'd3'、'sp3'。
            mode (str): 战役模式，'normal' 或 'hard'。默认 'normal'。
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 成功进入关卡页面并获取到入口按钮时返回 True。

        Raises:
            ScriptEnd: 超时或重试后仍切换失败时抛出。
        """
        timeout = Timer(5, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                break
            try:
                self.campaign_set_chapter(name, mode)
                self.ENTRANCE = self.campaign_get_entrance(name=name)
                return True
            except CampaignNameError:
                pass

            if self.handle_campaign_ui_additional():
                continue

        logger.warning('[战役] 战役名称错误')
        raise ScriptEnd('Campaign name error')

    def commission_notice_show_at_campaign(self):
        """检查战役界面是否显示委托完成通知。

        Returns:
            bool: 是否有委托已完成。
        """
        return self.appear(CAMPAIGN_CHECK, offset=(20, 20)) and self.appear(COMMISSION_NOTICE_AT_CAMPAIGN)
