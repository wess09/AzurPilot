from module.base.timer import Timer
from module.base.utils import area_offset
from module.campaign.assets import *
from module.campaign.campaign_event import CampaignEvent
from module.campaign.campaign_ocr import CampaignOcr
from module.exception import CampaignEnd, CampaignNameError, ScriptEnd
from module.logger import logger
from module.map.assets import WITHDRAW
from module.map.map_operation import MapOperation
from module.ui.assets import CAMPAIGN_CHECK
from module.ui.switch import Switch


class ModeSwitch(Switch):
    def handle_additional(self, main):
        if main.appear(WITHDRAW, offset=(30, 30)):
            logger.warning(f'ModeSwitch: WITHDRAW appears')
            raise CampaignNameError


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
    ENTRANCE = Button(area=(), color=(), button=(), name='default_button')

    def campaign_ensure_chapter(self, chapter, skip_first_screenshot=True):
        """
        确保切换到指定章节。

        Args:
            chapter (int, str): 章节名称，如 7、'd'、'sp'。
            skip_first_screenshot: 是否跳过首次截图。
        """
        index = self._campaign_get_chapter_index(chapter)
        isdigit = is_digit_chapter(chapter)

        # 复用 ui_ensure_index 的逻辑。
        logger.hr("UI ensure index")
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

            logger.attr("Index", current)
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
                logger.warning('Trying to goto EX, but no EX mode switch')
            elif mode == 'normal':
                MODE_SWITCH_1.set('hard', main=self)
            elif mode == 'hard':
                MODE_SWITCH_1.set('normal', main=self)
            else:
                logger.warning(f'Unknown campaign mode: {mode}')
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
                logger.warning(f'Unknown campaign mode: {mode}')

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
            logger.warning(f'Unknown campaign mode: {mode}')

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
            logger.warning(f'Unknown campaign aside: {chapter}')

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
            logger.warning(f'Unknown campaign aside: {chapter}')

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
            logger.info(f'Stage {name} uses entrance {search_name} in UI')

        if self.config.MAP_HAS_MODE_SWITCH:
            for mode_name in self.campaign_get_mode_names(search_name):
                if mode_name in self.stage_entrance:
                    search_name = mode_name

        if search_name not in self.stage_entrance:
            logger.warning(f'Stage not found: {search_name}')
            raise CampaignNameError

        entrance = self.stage_entrance[search_name]
        entrance.name = entrance_name
        return entrance

    def campaign_set_chapter_main(self, chapter, mode='normal'):
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
        if chapter == 'sp':
            self.ui_goto_sp()
            self.campaign_ensure_chapter(chapter)
            return True
        else:
            return False

    def campaign_set_chapter_20241219(self, chapter, stage, mode='combat'):
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
        """
        设置战役章节。

        Args:
            name (str): 战役名称，如 '7-2'、'd3'、'sp3'。
            mode (str): 'normal' 或 'hard'。
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
            logger.warning(f'Unknown campaign chapter: {name}')

    def handle_campaign_ui_additional(self):
        """
        战役 UI 的额外处理。

        Returns:
            bool: 是否已处理。
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
        """
        确保进入指定战役的 UI 界面。

        Args:
            name (str): 战役名称，如 '7-2'、'd3'、'sp3'。
            mode (str): 'normal' 或 'hard'。
            skip_first_screenshot: 是否跳过首次截图。

        Raises:
            ScriptEnd: 重试后仍切换失败时抛出。
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

        logger.warning('战役名称错误')
        raise ScriptEnd('Campaign name error')

    def commission_notice_show_at_campaign(self):
        """
        检查战役界面是否显示委托完成通知。

        Returns:
            bool: 是否有委托已完成。
        """
        return self.appear(CAMPAIGN_CHECK, offset=(20, 20)) and self.appear(COMMISSION_NOTICE_AT_CAMPAIGN)
