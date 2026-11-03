"""每日采集：未能点击出发（体力或资金不足）时不再等待采集完成页面。"""

import unittest
from unittest.mock import Mock, patch

from module.island.island_daily_gather import IslandDailyGather


def make_gather(depart):
    with patch.object(IslandDailyGather, '__init__', lambda self: None):
        gather = IslandDailyGather()
    for name in ('goto_management', 'ui_goto', 'post_manage_mode_collection', '_claim_existing_rewards',
                 '_exit_management', '_handle_collection_complete'):
        setattr(gather, name, Mock())
    gather._handle_target_selection = Mock(return_value=True)
    gather._daily_gather_worker_list = Mock(return_value=[])
    gather._click_plus_and_select_character = Mock(return_value=True)
    gather._click_depart = Mock(return_value=depart)
    return gather


class DailyGatherDepartTest(unittest.TestCase):
    def test_waits_for_complete_after_depart(self):
        gather = make_gather(depart=True)
        gather.dispatch_collection()
        gather._handle_collection_complete.assert_called_once()
        gather._exit_management.assert_called_once()

    def test_skips_wait_when_depart_unavailable(self):
        gather = make_gather(depart=False)
        gather.dispatch_collection()
        gather._handle_collection_complete.assert_not_called()
        gather._exit_management.assert_called_once()


if __name__ == '__main__':
    unittest.main()
