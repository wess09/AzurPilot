"""国际服新版白色弹窗的粗体「Confirm」：旧细体模板认不出，邮件领取会一直卡在弹窗上。

夹具 en_popup_no_mail.png：国际服 2026-11-05 邮件领取时的「No mail found meeting these conditions.」弹窗。
"""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.handler import info_handler
from module.handler.info_handler import InfoHandler

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/en_popup_no_mail.png'


def template_score(asset, image, offset=30):
    """在资源区域附近匹配模板，返回最高相似度（与 Button.match 的取法一致）。"""
    full = cv2.imread(str(asset))
    ys, xs = np.where(full.max(axis=2) > 0)
    x1, y1, x2, y2 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    search = image[y1 - offset:y2 + offset, x1 - offset:x2 + offset]
    return cv2.matchTemplate(search, full[y1:y2, x1:x2], cv2.TM_CCOEFF_NORMED).max()


class BoldConfirmTemplateTest(unittest.TestCase):
    def test_bold_template_matches_new_popup(self):
        image = cv2.imread(str(FIXTURE))
        self.assertGreater(template_score(ROOT / 'assets/en/ui_white/POPUP_CONFIRM_WHITE_BOLD.png', image), 0.95)
        # 旧的细体模板在新弹窗上低于识别阈值，这就是卡住的原因
        self.assertLess(template_score(ROOT / 'assets/en/ui_white/POPUP_CONFIRM_WHITE.png', image), 0.85)


class HandlePopupConfirmTest(unittest.TestCase):
    def test_bold_confirm_is_clicked(self):
        with patch.object(InfoHandler, '__init__', lambda self: None):
            handler = InfoHandler()
        handler.device = Mock()
        bold = info_handler.POPUP_CONFIRM_WHITE_BOLD
        handler.appear = Mock(side_effect=lambda button, **kwargs: button is bold)
        self.assertTrue(handler.handle_popup_confirm('MAIL_CLAIM'))
        handler.device.click.assert_called_once_with(bold)
        self.assertEqual(bold.name, 'POPUP_CONFIRM_WHITE_BOLD')

    def test_nothing_clicked_without_popup(self):
        with patch.object(InfoHandler, '__init__', lambda self: None):
            handler = InfoHandler()
        handler.device = Mock()
        handler.appear = Mock(return_value=False)
        self.assertFalse(handler.handle_popup_confirm('MAIL_CLAIM'))
        handler.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
