"""EN Operation Siren: the zone-type dropdown is found in its current bold font.

Fixture: (0, 150, 620, 440) of a live EN 1280x720 screenshot of zone 105 (a Siren stronghold) with
the zone-type dropdown open (Stronghold / Secured / Explorable), pasted back onto a black frame.
The old EN pictures (thin font) score about 0.5 here, so the bot waited for the menu until
GameStuckError.
"""
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

import numpy as np

import module.config.server as server

server.server = 'en'

from module.base.decorator import del_cached_property
from module.base.utils import load_image
from module.os.globe_operation import GlobeOperation, ZONE_SELECT, ZONE_SELECT_EN_BOLD
from module.os.assets import SELECT_DANGEROUS, SELECT_SAFE, SELECT_STRONGHOLD

FIXTURE = Path(__file__).parent / 'fixtures' / 'os_zone_select_en' / 'menu.png'


def reset_buttons():
    """Another test may have loaded the OS buttons for another server; load them again for the current one."""
    for button in ZONE_SELECT:
        for name in button.cached:
            del_cached_property(button, name)
        button.resource_release()


def frame():
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[150:440, 0:620] = load_image(str(FIXTURE))
    return image


def globe(image):
    obj = object.__new__(GlobeOperation)
    obj.device = SimpleNamespace(image=image, stuck_record_add=lambda b: None, click=mock.Mock())
    obj.interval_timer = {}
    obj.config = SimpleNamespace(SERVER='en', BUTTON_OFFSET=30)
    return obj


class ZoneSelectEnTest(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'en'
        reset_buttons()

    def tearDown(self):
        server.server = self._server
        reset_buttons()

    def test_bold_dropdown_found(self):
        g = globe(frame())
        self.assertEqual(g.get_zone_select(), [SELECT_DANGEROUS, SELECT_SAFE, SELECT_STRONGHOLD])
        self.assertTrue(g.is_in_zone_select())

    def test_bold_pictures_only_match_their_own_option(self):
        g = globe(frame())
        self.assertIs(g._zone_select_appear(SELECT_SAFE), ZONE_SELECT_EN_BOLD[SELECT_SAFE])
        self.assertIs(g._zone_select_appear(SELECT_DANGEROUS), ZONE_SELECT_EN_BOLD[SELECT_DANGEROUS])
        self.assertIs(g._zone_select_appear(SELECT_STRONGHOLD), ZONE_SELECT_EN_BOLD[SELECT_STRONGHOLD])

    def test_select_clicks_secured_option(self):
        g = globe(frame())
        pinned = iter([False, True])
        g.loop = lambda *a, **k: iter(range(5))
        with mock.patch.object(GlobeOperation, 'is_zone_pinned', lambda self: next(pinned)):
            g.zone_select_execute(SELECT_SAFE)
        g.device.click.assert_called_once_with(ZONE_SELECT_EN_BOLD[SELECT_SAFE])

    def test_bold_pictures_not_used_on_other_servers(self):
        server.server = 'cn'
        g = globe(frame())
        self.assertEqual(g._zone_select_variants(SELECT_SAFE), [SELECT_SAFE])

    def test_empty_screen_has_no_dropdown(self):
        self.assertEqual(globe(np.zeros((720, 1280, 3), dtype=np.uint8)).get_zone_select(), [])


if __name__ == '__main__':
    unittest.main()
