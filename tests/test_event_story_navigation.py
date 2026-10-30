"""用现有按钮资源和内存设备回放活动页到剧情入口的导航。"""

import unittest
from unittest.mock import Mock

import numpy as np

from module.base.utils import load_image
from module.campaign.assets import (
    CHAPTER_20241219_PART1,
    CHAPTER_20241219_PART2,
    SWITCH_20241219_COMBAT,
    SWITCH_20241219_STORY,
)
from module.config.config import AzurLaneConfig
from module.eventstory.assets import STORY_FINISHED, STORY_FIRST
from module.eventstory.eventstory import EventStory
from module.ui.page import Page, page_campaign, page_event, page_sp


class NavigationConfig(AzurLaneConfig):
    # 跨服只验证活动路由；资源统一使用国服原始像素。
    SERVER = 'cn'


def make_runner(event, page=page_sp, part=CHAPTER_20241219_PART1, mode='combat',
                finished=False, server='cn'):
    """合成 1280×720 控件画面，点击后到下一次截图才切换画面。"""
    def frame(*buttons):
        return np.maximum.reduce([load_image(button.file) for button in buttons])

    combat_image = frame(page.check_button, SWITCH_20241219_COMBAT, part)
    story_image = frame(page.check_button, SWITCH_20241219_STORY,
                        STORY_FINISHED if finished else STORY_FIRST)
    image = {
        'combat': combat_image,
        'story': story_image,
        'campaign': frame(page_campaign.check_button),
    }[mode]
    device = Mock(image=image, has_cached_image=True)
    pending = None

    def screenshot():
        nonlocal pending
        if device.screenshot.call_count > 10:
            raise AssertionError('导航未在限定截图次数内到达剧情入口')
        if pending is not None:
            device.image = pending
            pending = None

    def click(button):
        nonlocal pending
        if button.name == 'CAMPAIGN_GOTO_EVENT':
            pending = combat_image
        elif button.name == 'SWITCH_20241219_STORY':
            pending = story_image
        elif button.name != 'STORY_FIRST':
            raise AssertionError(f'出现非预期导航点击：{button.name}')

    device.screenshot.side_effect = screenshot
    device.click.side_effect = click
    config = NavigationConfig('template')
    config.override(SERVER=server)
    config.data['Event'] = {'Campaign': {'Event': event}}
    return EventStory(config=config, device=device)


class EventStoryNavigationTests(unittest.TestCase):
    def tearDown(self):
        # 导航断言失败时也清理共享路径，避免影响后续测试。
        Page.clear_connection()

    def assert_story_navigation(self, runner, expected_clicks):
        self.assertEqual(runner.ui_goto_event_story(), 'story')
        self.assertEqual([call.args[0].name for call in runner.device.click.call_args_list],
                         expected_clicks)
        self.assertEqual(runner.config.modified, {})

    def test_current_event_switches_from_both_parts_on_all_supported_servers(self):
        for server in ('cn', 'en', 'jp', 'tw'):
            for part in (CHAPTER_20241219_PART1, CHAPTER_20241219_PART2):
                with self.subTest(server=server, part=part.name):
                    runner = make_runner('event_20261022_cn', part=part, server=server)
                    self.assert_story_navigation(runner, ['SWITCH_20241219_STORY', 'STORY_FIRST'])
                    runner.device.screenshot.assert_called_once_with()

    def test_current_event_reuses_existing_story_page(self):
        runner = make_runner('event_20261022_cn', mode='story')
        self.assert_story_navigation(runner, ['STORY_FIRST'])
        runner.device.screenshot.assert_not_called()

    def test_current_event_enters_from_main_campaign(self):
        runner = make_runner('event_20261022_cn', mode='campaign')
        self.assert_story_navigation(runner,
                                     ['CAMPAIGN_GOTO_EVENT', 'SWITCH_20241219_STORY', 'STORY_FIRST'])
        self.assertEqual(runner.device.screenshot.call_count, 2)

    def test_previous_sp_event_keeps_its_navigation(self):
        runner = make_runner('event_20251023_cn')
        self.assert_story_navigation(runner, ['SWITCH_20241219_STORY', 'STORY_FIRST'])

    def test_regular_event_keeps_its_navigation(self):
        runner = make_runner('event_20250227_cn', page=page_event)
        self.assert_story_navigation(runner, ['SWITCH_20241219_STORY', 'STORY_FIRST'])

    def test_completed_story_returns_finish_without_clicking(self):
        for event, page in (('event_20261022_cn', page_sp),
                            ('event_20251023_cn', page_sp),
                            ('event_20250227_cn', page_event)):
            with self.subTest(event=event):
                runner = make_runner(event, page=page, mode='story', finished=True)
                self.assertEqual(runner.ui_goto_event_story(), 'finish')
                runner.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
