"""常用候补的选择边界；不连接设备或发送通知。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from module.exception import FleetManagementError
from module.retire.fleet_favourite import FavouriteShips


class FavouriteSelectionTests(unittest.TestCase):
    def test_other_servers_are_rejected_before_any_device_operation(self):
        manager = Mock(config=SimpleNamespace(SERVER='en'))
        with self.assertRaisesRegex(FleetManagementError, '国服'):
            FavouriteShips(manager)
        manager.fleet_enter.assert_not_called()
        manager.prepare_rotation.assert_not_called()

    def finder(self, entries):
        tool = FavouriteShips.__new__(FavouriteShips)
        tool.manager = Mock()
        tool.manager.RESULT_PATH = 'FleetInfo.FleetInfo.Result'
        result = {'main': {'6': [dict(name='其他编队', slot=1)]},
                  'submarine': {'2': [dict(name='潜艇编队', slot=1)]}}
        tool.config = SimpleNamespace(cross_get=lambda *args: result)
        tool._scan = Mock(return_value=entries)
        return tool

    @staticmethod
    def ship(name, **kwargs):
        return dict(name=name, fleet=0, level=80, emotion=150, review=False, busy=False, **kwargs)

    def test_excludes_every_fleet_busy_unknown_duplicate_graduated_and_already_reserved(self):
        entries = [self.ship(name) for name in ('其他编队', '潜艇编队', '同名', '同名', '已毕业', '本轮已选')]
        entries.extend([dict(self.ship('徽标编队'), fleet=5), dict(self.ship('使用中'), busy=True),
                        dict(self.ship('未知心情'), emotion=None), dict(self.ship('低心情'), emotion=2),
                        dict(self.ship('身份未确认'), review=True), self.ship('可选舰船')])
        tool = self.finder(entries)
        selected = tool.find(1, 4, {}, {}, needed=100, reserved=('本轮已选', '已毕业'))
        self.assertEqual('可选舰船', selected['name'])
        self.assertEqual([call(True), call(False)], tool.manager.dock_favourite_set.call_args_list)
        self.assertFalse(tool.manager._level_prepared)
        tool.manager.rotate_slot.assert_not_called()

    def test_no_eligible_common_ship_returns_none_without_selecting_an_assigned_ship(self):
        tool = self.finder([self.ship('其他编队')])
        self.assertIsNone(tool.find(1, 4, {}, {}))
        tool.manager.device.click.assert_not_called()

    def test_level_and_affinity_candidates_are_read_and_graduates_are_skipped(self):
        tool = self.finder([self.ship('已毕业'), self.ship('可选舰船')])
        tool._locate = Mock(return_value=object())
        tool.ui_click = Mock()
        tool.ui_back = Mock()
        tool._profile = Mock(side_effect=[dict(level=120, affinity=100), dict(level=119, affinity=100)])
        observe = Mock()
        selected = tool.find(1, 4, {'level': 120, 'affinity': 100}, {}, observe=observe)
        self.assertEqual('可选舰船', selected['name'])
        self.assertEqual(119, selected['level'])
        self.assertEqual(2, observe.call_count)
        self.assertEqual(2, tool.ui_back.call_count)
        tool.manager.dock_reset.assert_called_once()

    def test_persistently_graduated_ship_is_never_read_or_recruited(self):
        tool = self.finder([self.ship('已毕业')])
        tool._profile = Mock()
        selected = tool.find(1, 4, {'level': 125}, {'已毕业': {'completed_for': {'level': 120}}})
        self.assertIsNone(selected)
        tool._profile.assert_not_called()
