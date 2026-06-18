from module.base.timer import Timer
from module.base.utils import rgb2gray, lower_template_match_similarity
from module.campaign.campaign_ui import CampaignUI
from module.combat.combat import Combat
from module.eventstory.assets import *
from module.handler.login import LoginHandler
from module.logger import logger
from module.ui.page import page_event, page_sp


class EventStory(CampaignUI, Combat, LoginHandler):
    def ui_goto_event_story(self):
        """
        导航至活动剧情入口并获取当前剧情状态。

        Pages:
            page_sp: SP 活动页面（如 event_20251023_cn）
            page_event: 常规活动页面（大多数活动）

        Returns:
            str: 'finish'（已完成）、'story'（有可进入的剧情）、'unknown'（未检测到剧情入口）
        """
        event = self.config.cross_get('Event.Campaign.Event', '')
        if event in [
            'event_20251023_cn',
        ]:
            # SP 活动使用 page_sp 页面
            self.ui_ensure(page_sp)
        else:
            # 大多数活动在 page_event 页面展示
            self.ui_ensure(page_event)
        self.campaign_ensure_mode_20241219('story')

        state = 'unknown'
        for _ in range(3):
            # 等待剧情状态就绪
            timeout = Timer(2, count=6).start()
            for _ in self.loop():
                state = self.get_event_story_state()
                logger.attr('EventStoryState', state)
                if state != 'unknown':
                    break
                if timeout.reached():
                    logger.warning('Wait EventStoryState timeout')
                    break
            if state == 'unknown':
                # 剧情页面被滑动过，找不到剧情入口
                # 通过切换模式重置滑动位置
                self.campaign_ensure_mode_20241219('combat')
                self.campaign_ensure_mode_20241219('story')
                continue
            else:
                break

        return state

    def get_event_20250724_button(self):
        """
        检测炼金术士联动活动的剧情/战斗按钮位置。

        在屏幕中央区域进行模板匹配，匹配成功后将点击点下移至文字区域。

        Returns:
            Button | None: 匹配到的按钮，未匹配到则返回 None
        """
        area = (0, 72, 1280, 560)
        image = self.image_crop(area, copy=False)
        image = rgb2gray(image)
        sim, button = TEMPLATE_ALCHEMIST_STORY.match_result(image)
        if sim >= lower_template_match_similarity(0.85):
            button = button.move(area[:2])
            # 下移点击区域至文字处
            button = button.move((0, 44))
            return button
        sim, button = TEMPLATE_ALCHEMIST_BATTLE.match_result(image)
        if sim >= lower_template_match_similarity(0.85):
            button = button.move(area[:2])
            # 下移点击区域至文字处
            button = button.move((0, 44))
            return button
        return None

    def handle_event_20250724(self, interval=2):
        """
        处理炼金术士联动2活动的剧情按钮弹出。

        该活动中剧情按钮会随机出现在各处，需要持续检测并点击。

        Args:
            interval: 点击间隔（秒），防止重复点击

        Returns:
            bool: 是否点击了按钮
        """
        interval = self.get_interval_timer(TEMPLATE_ALCHEMIST_STORY, interval=interval)
        if not interval.reached():
            return False
        button = self.get_event_20250724_button()
        if button:
            self.device.click(button)
            interval.reset()
            return True
        else:
            return False

    def event_story(self, skip_first_screenshot=True):
        """
        执行活动剧情的截图-检查循环，推进剧情直到结束。

        按优先级处理：战斗检测 > 剧情完成 > 剧情跳过 > 点击推进。
        依次检测首段剧情、末段剧情、中段剧情、战斗中段、炼金术士联动按钮。

        Pages:
            page_event: 活动主页面
            STORY_FIRST: 首段剧情入口
            STORY_MIDDLE: 中段剧情
            STORY_LAST: 末段剧情
            BATTLE_MIDDLE: 战斗中段剧情
            STORY_FINISHED: 剧情已完成标志
            REWARD_GOT: 奖励领取完成

        Args:
            skip_first_screenshot: 是否复用上一状态循环的截图

        Returns:
            str: 'battle'（进入战斗）或 'finish'（剧情结束）
        """
        logger.hr('Event story', level=1)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件检测
            if self.is_combat_executing() or self.is_combat_loading():
                logger.info('run_story end at battle')
                return 'battle'
            if self.match_template_color(STORY_FINISHED, offset=(20, 20), interval=3):
                logger.info('run_story end at STORY_FINISHED')
                return 'finish'
            if self.appear(REWARD_GOT, offset=(50, 30)):
                logger.info('run_story end at REWARD_GOT')
                return 'finish'

            # 剧情跳过处理
            if self.handle_story_skip():
                self.interval_clear([STORY_MIDDLE, BATTLE_MIDDLE])
                continue
            if self.handle_get_items():
                continue

            # 点击推进剧情
            if self.appear_then_click(STORY_FIRST, offset=(20, 20), interval=3):
                self.story_skip_interval_clear()
                self.popup_interval_clear()
                self.device.click_record_clear()
                continue
            if self.match_template_color(STORY_LAST, offset=(20, 20), interval=3):
                self.device.click(STORY_LAST)
                self.story_skip_interval_clear()
                self.popup_interval_clear()
                self.device.click_record_clear()
                continue
            if self.appear_then_click(STORY_MIDDLE, offset=(20, 200), interval=3):
                self.story_skip_interval_clear()
                self.popup_interval_clear()
                self.device.click_record_clear()
                continue
            if self.appear_then_click(BATTLE_MIDDLE, offset=(20, 200), interval=3):
                self.story_skip_interval_clear()
                self.popup_interval_clear()
                self.device.click_record_clear()
                continue
            if self.handle_event_20250724():
                self.story_skip_interval_clear()
                self.popup_interval_clear()
                self.device.click_record_clear()
                continue
            # 深渊秘辛（event_20250814_cn）
            # 全部剧情完成后弹出的 RPG 状态窗口
            if self.appear_then_click(POPUP_RPG_STATUS, offset=(20, 20), interval=3):
                continue

    def run_event_story(self):
        """
        循环执行活动剧情直到全部完成。

        处理流程：导航至剧情入口 -> 执行剧情 -> 战斗时重启游戏跳过（比等待战斗结束更快）
        -> 剧情完成后返回主界面再重新进入以关闭可能残留的奖励弹窗。

        Pages:
            page_event: 活动主页面
            page_main: 游戏主界面
        """
        while 1:
            state = self.ui_goto_event_story()
            if state == 'finish':
                break
            result = self.event_story()
            if result == 'battle':
                # 通过重启游戏跳过活动战斗，比等待战斗结束快得多
                logger.hr('Event Story Battle', level=2)
                self.config.override(Error_HandleError=True)
                self.app_stop()
                self.device.sleep(2)
                self.app_start()
                continue
            if result == 'finish':
                # 剧情结束后返回主界面再进入，以关闭可能残留的 GET_ITEMS 弹窗
                logger.hr('Event story finish', level=2)
                self.ui_goto_main()
                self.ui_goto_event_story()

    def get_event_story_state(self):
        """
        检测当前活动剧情页面的状态。

        依次检查剧情完成标志、奖励领取标志、各段剧情入口按钮，
        并通过点击确认按钮的可交互性。

        Returns:
            str: 'finish'（已完成）、'story'（有可进入的剧情）、
                 'story_alchemist'（炼金术士联动剧情）、'unknown'（未检测到）
        """
        if self.match_template_color(STORY_FINISHED, offset=(20, 20)):
            return 'finish'
        if self.appear(REWARD_GOT, offset=(50, 30)):
            return 'finish'

        if self.appear_then_click(STORY_FIRST, offset=(20, 20)):
            return 'story'
        if self.match_template_color(STORY_LAST, offset=(20, 20)):
            return 'story'
        if self.appear_then_click(STORY_MIDDLE, offset=(20, 200)):
            return 'story'
        if self.appear_then_click(BATTLE_MIDDLE, offset=(20, 200)):
            return 'story'
        if self.get_event_20250724_button():
            return 'story_alchemist'

        return 'unknown'

    def run(self):
        """
        活动剧情任务入口。

        检查当前活动是否支持剧情功能，若支持则执行剧情循环。
        部分活动（如小游戏类）的剧情入口不在常规页面，会直接跳过。

        Pages:
            page_event: 活动主页面
            page_sp: SP 活动页面

        Raises:
            RequestHumanTakeover: 游戏未运行且无法自动启动时
        """
        event = self.config.cross_get('Event.Campaign.Event', '')
        if event in [
            # 该活动的剧情入口在活动小游戏内，不在常规剧情页面
            'event_20260226_cn',
        ]:
            logger.info(f'Current event ({event}) does not have event story, stopped')
            return

        if not self.device.app_is_running():
            logger.warning('Game is not running, start it')
            self.app_start()

        self.run_event_story()


if __name__ == '__main__':
    self = EventStory('alas')
    self.run()
