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
    def test_run_keeps_locked_post_out_of_idle_schedule(self):
        farm = object.__new__(IslandFarm)
        post_ids = [
            *(f'ISLAND_FARM_POST{i}' for i in range(1, 5)),
            *(f'ISLAND_ORCHARD_POST{i}' for i in range(1, 5)),
            'ISLAND_NURSERY_POST1',
            'ISLAND_NURSERY_POST2',
        ]
        farm.posts = {post_id: {'crop': None, 'button': Mock()} for post_id in post_ids}
        farm.farm_positions = 0
        farm.orchard_positions = 0
        farm.nursery_positions = 2
        farm.inventory_counts = {'farm': {}, 'orchard': {}, 'nursery': {}}
        farm._inv_cn = Mock(return_value='')
        farm.ui_ensure = Mock()
        farm.check_inventory_and_prepare_lists = Mock()
        farm.goto_postmanage = Mock()
        farm.post_manage_mode = Mock()
        farm.post_close = Mock()
        farm.post_manage_swipe = Mock()
        farm.post_manage_swipe_until_appear = Mock()
        farm.device = Mock()
        farm.plant_config = {
            'farm': {'default_crop': 'wheat', 'plant_default': 0},
            'orchard': {'default_crop': 'rubber', 'plant_default': 0},
            'nursery': {'default_crop': 'lavender', 'plant_default': 0},
        }
        farm.to_plant_lists = {'farm': [], 'orchard': [], 'nursery': ['lavender']}
        farm.config = Mock()
        farm.decided_lists = Mock(side_effect=lambda *args: args[1] != 'ISLAND_NURSERY_POST2')
        farm._plant_idle_posts = Mock()

        farm.run()

        farm._plant_idle_posts.assert_called_once()
        category, idle_posts, _ = farm._plant_idle_posts.call_args.args
        self.assertEqual(category, 'nursery')
        self.assertEqual([post['post_id'] for post in idle_posts], ['ISLAND_NURSERY_POST1'])

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

        self.assertIsNone(
            farm.post_plant(
                post_button,
                'lavender',
                'nursery',
                'nursery_time_1',
            )
        )

        farm.post_open.assert_called_once_with(post_button)
        farm.device.screenshot.assert_not_called()

    def test_unavailable_post_keeps_crop_for_next_idle_post(self):
        farm = make_farm()
        farm.post_plant = Mock(side_effect=[None, True])
        posts = [
            {'post_id': 'ISLAND_NURSERY_POST1', 'button': Mock(), 'time_var_name': 'nursery_time_0'},
            {'post_id': 'ISLAND_NURSERY_POST2', 'button': Mock(), 'time_var_name': 'nursery_time_1'},
        ]

        farm._plant_idle_posts('nursery', posts, ['lavender'])

        self.assertEqual(farm.post_plant.call_count, 2)
        self.assertEqual(
            [call.args[1] for call in farm.post_plant.call_args_list],
            ['lavender', 'lavender'],
        )
        self.assertNotIn('lavender', farm.to_plant_lists['nursery'])

    def test_failed_crop_advances_to_the_next_crop(self):
        farm = make_farm()
        farm.post_plant = Mock(side_effect=[False, True])
        posts = [
            {'post_id': 'ISLAND_NURSERY_POST1', 'button': Mock(), 'time_var_name': 'nursery_time_0'},
            {'post_id': 'ISLAND_NURSERY_POST2', 'button': Mock(), 'time_var_name': 'nursery_time_1'},
        ]

        farm._plant_idle_posts('nursery', posts, ['lavender', 'strawberry'])

        self.assertEqual(
            [call.args[1] for call in farm.post_plant.call_args_list],
            ['lavender', 'strawberry'],
        )
        self.assertEqual(farm.to_plant_lists['nursery'], ['lavender'])


if __name__ == '__main__':
    unittest.main()
