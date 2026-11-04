"""农田锁定岗位不应被当作空闲岗位重复尝试播种。"""

import unittest
from unittest.mock import Mock

import module.config.server as server

server.server = 'cn'

from module.island.island_farm import IslandFarm


def make_farm():
    farm = object.__new__(IslandFarm)
    farm.device = Mock()
    farm.post_close = Mock()
    farm.post_get_and_close = Mock()
    farm.posts = {'ISLAND_NURSERY_POST2': {'crop': 'lavender'}}
    farm.to_plant_lists = {'nursery': ['lavender']}
    farm.time_vars = {'nursery': [None, 'stale-time']}
    return farm


class IslandFarmLockedPostTests(unittest.TestCase):
    def test_locked_post_is_not_added_to_idle_state(self):
        farm = make_farm()
        farm.post_open = Mock(return_value=False)
        post_button = Mock()

        self.assertFalse(
            farm.decided_lists(
                post_button,
                'ISLAND_NURSERY_POST2',
                'nursery',
                'nursery_time_1',
            )
        )

        farm.post_open.assert_called_once_with(post_button)
        self.assertIsNone(farm.posts['ISLAND_NURSERY_POST2']['crop'])
        self.assertIsNone(farm.time_vars['nursery'][1])
        farm.device.screenshot.assert_not_called()
        farm.post_get_and_close.assert_not_called()

    def test_locked_post_between_scan_and_plant_does_not_continue_dispatch(self):
        farm = make_farm()
        farm.post_open = Mock(return_value=False)
        post_button = Mock()

        self.assertFalse(
            farm.post_plant(
                post_button,
                'lavender',
                'nursery',
                'nursery_time_1',
            )
        )

        farm.post_open.assert_called_once_with(post_button)
        farm.device.screenshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
