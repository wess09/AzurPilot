"""飓风与雾霭回廊的跨服导航、关卡接入与上游 SP 模板回归。"""

import importlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from campaign.event_20261022_cn import sp, t1
from module.campaign.campaign_base import CampaignBase
from module.config.config import AzurLaneConfig
from module.template import assets as template_assets


EVENT = 'event_20261022_cn'
ROOT = Path(__file__).resolve().parents[1]


class NavigationConfig(AzurLaneConfig):
    # 只替换导航配置的服务器名，不切换进程内已加载的游戏资源。
    SERVER = 'cn'


def make_campaign(map_module=t1, server='cn'):
    config = NavigationConfig('template')
    config.override(SERVER=server)
    config.merge(map_module.Config())
    campaign = map_module.Campaign(config=config, device=Mock())
    campaign.navigation = Mock()
    for name in ('ui_goto_sp', 'campaign_ensure_mode_20241219',
                 'campaign_ensure_aside_20241219', 'campaign_ensure_chapter'):
        method = Mock()
        campaign.navigation.attach_mock(method, name)
        setattr(campaign, name, method)
    return campaign


class WindFogCorridorTests(unittest.TestCase):
    def test_stage_routes_use_correct_part_on_all_supported_servers(self):
        for server in ('cn', 'en', 'jp', 'tw'):
            for stage, aside in ((1, 'part1'), (2, 'part1'), (3, 'part1'),
                                 (4, 'part2'), (5, 'part2'), (6, 'part2')):
                with self.subTest(server=server, stage=stage):
                    module = importlib.import_module(f'campaign.{EVENT}.t{stage}')
                    campaign = make_campaign(module, server)
                    campaign.campaign_set_chapter(f't{stage}')
                    self.assertEqual(campaign.navigation.mock_calls, [
                        call.ui_goto_sp(),
                        call.campaign_ensure_mode_20241219('combat'),
                        call.campaign_ensure_aside_20241219(aside),
                        call.campaign_ensure_chapter('t'),
                    ])
                    self.assertFalse(campaign.config.MAP_HAS_MODE_SWITCH)
                    self.assertFalse(campaign.config.MAP_CHAPTER_SWITCH_20260326)
                    self.assertEqual(campaign.config.modified, {})
                    campaign.device.click.assert_not_called()

    def test_daily_sp_uses_sp_partition_without_difficulty_switch(self):
        for server in ('cn', 'en', 'jp', 'tw'):
            with self.subTest(server=server):
                campaign = make_campaign(sp, server)
                campaign.campaign_set_chapter('sp')
                self.assertEqual(campaign.navigation.mock_calls, [
                    call.ui_goto_sp(),
                    call.campaign_ensure_mode_20241219('combat'),
                    call.campaign_ensure_aside_20241219('sp'),
                    call.campaign_ensure_chapter('ex_sp'),
                ])
                self.assertTrue(campaign.config.MAP_IS_ONE_TIME_STAGE)
                self.assertFalse(campaign.config.MAP_HAS_MODE_SWITCH)

    def test_other_chapters_delegate_to_shared_navigation(self):
        campaign = make_campaign()
        with patch.object(CampaignBase, 'campaign_set_chapter_20241219', return_value=False) as shared:
            self.assertFalse(campaign.campaign_set_chapter_20241219('main', '1', 'story'))
        shared.assert_called_once_with('main', '1', 'story')
        self.assertEqual(campaign.navigation.mock_calls, [])
        campaign.device.click.assert_not_called()

    def test_sp_siren_template_is_registered_and_decodes(self):
        campaign = make_campaign(sp)
        self.assertFalse(campaign.config.MAP_HAS_MOVABLE_ENEMY)
        self.assertFalse(campaign.config.MAP_HAS_FLEET_STEP)
        self.assertFalse(campaign.config.MAP_SIREN_HAS_BOSS_ICON_SMALL)
        self.assertEqual(campaign.config.MAP_SIREN_TEMPLATE, ['TempestaGhostBoss02'])
        for name in campaign.config.MAP_SIREN_TEMPLATE:
            template = getattr(template_assets, f'TEMPLATE_SIREN_{name}')
            self.assertTrue(template.is_gif)
            self.assertTrue(template.image)
            for frame in template.image:
                self.assertGreater(frame.size, 0)

    def test_registered_event_uses_shared_directory_for_all_four_servers(self):
        args = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))
        for task in ('Event', 'Event2', 'Event3', 'EventA', 'EventB', 'EventC', 'EventD', 'EventSp'):
            for server in ('cn', 'en', 'jp', 'tw'):
                with self.subTest(task=task, server=server):
                    self.assertEqual(args[task]['Campaign']['Event'][f'option_{server}'], [EVENT])

    def test_localized_event_names_survive_config_generation(self):
        for language, expected in (
            ('zh-CN', '飓风与雾霭回廊'),
            ('en-US', 'Tempesta and the Corridor of Fog'),
            ('ja-JP', 'テンペスタと霧靄回廊'),
            ('zh-TW', '飓风与雾霭回廊'),
        ):
            with self.subTest(language=language):
                path = ROOT / f'module/config/i18n/{language}.json'
                translated = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(translated['Campaign']['Event'][EVENT], expected)


if __name__ == '__main__':
    unittest.main()
