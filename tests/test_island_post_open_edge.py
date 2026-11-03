"""岗位按钮停在列表可见区域下沿之下时，先上推列表再点击（啾咖啡岗位 1 的 GameTooManyClickError）。"""

import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.base.button import Button
from module.base.utils import area_offset
from module.island import island as island_module
from module.island.island import Island

POST_AREA = (737, 499, 868, 525)


def make_island(bottoms):
    """bottoms: 每次识别到岗位按钮时其下沿 y；点击岗位后下一轮识别为已打开。"""
    with patch.object(Island, '__init__', lambda self: None):
        island = Island()
    island.device = Mock()
    island.loop = Mock(side_effect=lambda **kwargs: iter([np.zeros((720, 1280, 3), np.uint8)] * 10))
    island.post_manage_up_swipe = Mock()
    post = Button(area=POST_AREA, color=(0, 0, 0), button=POST_AREA, name='POST')
    queue = list(bottoms)
    state = {'opened': False}

    def appear(button, offset=0, **kwargs):
        if button is post and not state['opened']:
            bottom = queue.pop(0) if queue else POST_AREA[3]
            post._button_offset = area_offset(POST_AREA, (0, bottom - POST_AREA[3]))
            return True
        if button is island_module.ISLAND_POST_CHECK:
            return state['opened']
        return False

    def click(button, **kwargs):
        if button is post:
            state['opened'] = True

    island.appear = appear
    island.device.click = Mock(side_effect=click)
    return island, post


class PostOpenEdgeTest(unittest.TestCase):
    def setUp(self):
        self.lock = patch.object(island_module.TEMPLATE_POST_LOCK, 'match', Mock(return_value=False))
        self.lock.start()

    def tearDown(self):
        self.lock.stop()

    def test_nudges_list_before_clicking_edge_post(self):
        island, post = make_island([706, 560])
        self.assertTrue(island.post_open(post))
        island.post_manage_up_swipe.assert_called_once_with(
            706 - island_module.POST_LIST_VISIBLE_BOTTOM + island_module.POST_EDGE_NUDGE_MARGIN)
        island.device.click.assert_called_once()

    def test_clicks_directly_when_post_visible(self):
        island, post = make_island([560])
        self.assertTrue(island.post_open(post))
        island.post_manage_up_swipe.assert_not_called()

    def test_nudge_limit_then_clicks(self):
        island, post = make_island([706] * 10)
        self.assertTrue(island.post_open(post))
        self.assertEqual(island.post_manage_up_swipe.call_count, island_module.POST_EDGE_NUDGE_LIMIT)
        island.device.click.assert_called_once()


if __name__ == '__main__':
    unittest.main()
