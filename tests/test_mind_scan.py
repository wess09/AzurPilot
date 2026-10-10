"""心智计算器的三行范围扫描、真实截图和传输层回归。"""
import base64
import io
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageOps
import numpy as np

from module.api.app import create_app
from module.api.config_service import ConfigService
from module.api.mind_calculator_service import MindCalculatorService
from module.api.protocol import ApiError, ConfigChange
from module.runtime.mind_calculator import calculate
from module.runtime.mind_recognition import Card, ScanMerger, ScanPolicy, _match_name, normalize_screenshot, recognize_cards
from tests.test_api import fixture


# 真实截图已遮盖顶部容量，保留船坞标识和三行卡片用于识别回归。
FIXTURES = Path(__file__).parent / 'fixtures'


def cards_for_levels(levels, fleet=0):
    return [Card(93 + col * 165, 65 + row * 227, col,
                 dict(name='拉菲', level=level, rarity='SR', source='', review=True), 6, True, fleet)
            for index, level in enumerate(levels) for row, col in [divmod(index, 7)]]


class RangeTests(unittest.TestCase):
    def test_inclusive_boundaries_exclude_zero_and_outside_levels(self):
        merger = ScanMerger()
        cards = cards_for_levels([118, 115, 115, 90, 89, 0])
        for index, card in enumerate(cards):
            card.ship['name'] = f'舰船{index}'
        merger.slots = [[card, card.y] for card in cards]
        self.assertEqual([ship['level'] for ship in merger.ships(90, 115)], [115, 115, 90])

    def test_later_higher_level_replaces_entire_same_name_record(self):
        merger = ScanMerger()
        cards = cards_for_levels([100, 105, 99])
        cards[1].ship['source'] = '后面的更高等级'
        merger.slots = [[card, card.y] for card in cards]
        self.assertEqual(merger.ships(90, 115), [cards[1].ship])

    def test_pixel_registration_error_does_not_accumulate_duplicate_rows(self):
        merger = ScanMerger()
        image = Image.new('RGB', (1280, 720), (80, 80, 80))
        for page in range(30):
            with patch('module.runtime.mind_recognition.estimate_scroll', return_value=228):
                merger.add(image, cards_for_levels([100] * 21))
        self.assertEqual(len(merger.slots), 7 * 32)
        self.assertEqual(merger.offset, 227 * 29)

    def test_uncertain_level_is_never_written_as_zero(self):
        card = cards_for_levels([89])[0]
        card.level_reliable = False
        merger = ScanMerger(); merger.slots = [[card, card.y]]
        rows = merger.ships(90, 115)
        self.assertEqual(rows, [])
        self.assertEqual(calculate(rows)['mind'], 0)

    def test_name_disagreement_does_not_invalidate_matching_levels(self):
        image = Image.new('RGB', (1280, 720), (80, 80, 80))
        merger = ScanMerger()
        merger.add(image, cards_for_levels([118]))
        retry = cards_for_levels([118])
        retry[0].ship['name'] = '未知舰船'
        merger.add(image, retry)
        self.assertTrue(merger.slots[0][0].level_reliable)
        self.assertIn('跨屏读数不一致', merger.slots[0][0].ship['source'])
        self.assertEqual(merger.ships(90, 115), [])
        retry[0].ship['level'] = 18
        merger.add(image, retry)
        self.assertFalse(merger.slots[0][0].level_reliable)
        self.assertEqual(merger.ships(90, 115), [])

    def test_three_rows_without_minimum_but_with_eligible_ships_continue(self):
        cards = cards_for_levels([115] * 7 + [100] * 7 + [91] * 7)
        policy = ScanPolicy(90, 115, sorted_desc=True)
        self.assertFalse(policy.can_stop(cards, [[card, card.y] for card in cards]))

    def test_complete_three_rows_below_minimum_stop(self):
        cards = cards_for_levels([89] * 7 + [80] * 7 + [70] * 7)
        self.assertTrue(ScanPolicy(90, 115, True).can_stop(cards, [[card, card.y] for card in cards]))

    def test_missing_uncertain_unsorted_and_fleet_priority_cannot_stop(self):
        for kind in ('missing', 'unknown_level', 'unknown_fleet', 'fleet', 'unsorted', 'unconfirmed_sort'):
            with self.subTest(kind=kind):
                current = cards_for_levels([89] * 21)
                policy = ScanPolicy(90, 115, kind != 'unconfirmed_sort')
                if kind == 'missing': current.pop()
                if kind == 'unknown_level': current[0].level_reliable = False
                if kind == 'unknown_fleet': current[0].fleet = -1
                if kind == 'fleet':
                    for card in current: card.fleet = 1
                if kind == 'unsorted': current[1].ship['level'] = 90
                self.assertFalse(policy.can_stop(current, [[card, card.y] for card in current]))
        # 置顶编队的低等级后面接普通高等级是正常游戏排序。
        fleet = cards_for_levels([70] * 21, fleet=1)
        ordinary = cards_for_levels([125] * 21)
        policy = ScanPolicy(90, 115, True)
        self.assertFalse(policy.can_stop(ordinary, [[c, c.y] for c in fleet] + [[c, c.y + 681] for c in ordinary]))
        self.assertTrue(policy.sort_valid)

    def test_name_review_does_not_prevent_confirmed_level_stop(self):
        cards = cards_for_levels([89] * 21)
        cards[0].quality = 2
        self.assertTrue(ScanPolicy(90, 115, True).can_stop(cards, [[card, card.y] for card in cards]))

    def test_range_validation(self):
        for low, high in [(0, 120), (95, 126), (115, 90), (True, 120)]:
            with self.assertRaises(ValueError): ScanPolicy(low, high)

    def test_range_config_defaults_and_api_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            configs = ConfigService(fixture(temp))
            service = MindCalculatorService(configs)
            report = service.report('testpilot')
            self.assertEqual((report['min_level'], report['max_level']), (95, 120))
            configs.patch('testpilot', configs.get('testpilot')['revision'], [
                ConfigChange(path='MindCalculatorScan.MindCalculator.MinLevel', value=90),
                ConfigChange(path='MindCalculatorScan.MindCalculator.MaxLevel', value=115),
            ])
            report = service.report('testpilot')
            self.assertEqual((report['min_level'], report['max_level']), (90, 115))
            with self.assertRaises(ApiError):
                configs.patch('testpilot', configs.get('testpilot')['revision'], [
                    ConfigChange(path='MindCalculatorScan.MindCalculator.MaxLevel', value=126),
                ])


class NativeLevelTests(unittest.TestCase):
    def test_real_blue_frames_are_not_unknown_fleet_badges(self):
        from module.retire.scanner import FleetScanner
        from module.runtime.mind_recognition import fleet_status
        pixels = np.array(Image.open(FIXTURES / 'mind_fleet_blue.png').convert('RGB'))
        reader = FleetScanner()
        for y in range(0, pixels.shape[0], 45):
            self.assertEqual(fleet_status(pixels[y:y + 45], reader), 0)

    def test_fleet_text_preserves_uncertainty_when_number_is_missing(self):
        from module.retire.scanner import FleetScanner
        from module.runtime.mind_recognition import fleet_status, grid_rows
        from module.retire.dock import CARD_GRIDS
        pixels = np.array(Image.open(FIXTURES / 'mind_dock_fleet_priority.png').convert('RGB'))
        y, x = grid_rows(pixels)[0], round(float(CARD_GRIDS.origin[0]))
        reader = FleetScanner()
        with patch.object(reader, '_match', return_value=0):
            self.assertEqual(fleet_status(pixels[y + 117:y + 162, x:x + 35], reader), -1)

    def test_independent_real_glyphs_never_accept_another_level(self):
        from module.runtime.mind_level import dock_level_reader
        reader = dock_level_reader()
        cases = json.loads((FIXTURES / 'mind_levels.json').read_text(encoding='utf-8'))
        pixels = np.array(Image.open(FIXTURES / 'mind_levels.png'))
        confirmed = 0
        for page, case in enumerate(cases):
            if case['training']:
                continue
            for index, expected in enumerate(case['levels']):
                row, col = divmod(index, 7)
                raw = pixels[(page * 3 + row) * 32:(page * 3 + row + 1) * 32, col * 64:(col + 1) * 64]
                glyphs, _, _ = reader.prepare(raw)
                value = reader.read(glyphs)
                self.assertIn(value, (0, expected), (index, expected, value))
                confirmed += bool(value)
        self.assertGreaterEqual(confirmed, 15)

    def test_blank_level_has_no_digit_identity(self):
        from module.runtime.mind_level import dock_level_reader
        reader = dock_level_reader()
        glyphs, _, _ = reader.prepare(np.full((32, 64, 3), 255, dtype=np.uint8))
        self.assertEqual(glyphs, [])
        self.assertEqual(reader.read(glyphs), 0)

    def test_short_gesture_accounts_for_game_activation_distance(self):
        from module.retire.mind_scan import MindCalculatorScan
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        scanner.config = SimpleNamespace(Emulator_ControlMethod='MaaTouch')
        scanner.device = Mock()
        scanner._drag_rows(13)
        self.assertEqual(scanner.device.drag.call_args.args, ((1170, 470), (1170, 437)))
        self.assertEqual(scanner.device.drag.call_args.kwargs['hold_duration'], .4)


class ScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = Image.open(FIXTURES / 'mind_dock_fleet_priority.png').convert('RGB')
        cls.cards = recognize_cards(cls.image)

    def test_real_three_rows_and_exact_levels(self):
        self.assertEqual([c.ship['level'] for c in self.cards],
                         [120, 110, 110, 110, 105, 105, 105, 105, 100, 100, 100, 100, 99, 99, 97, 84, 79, 76, 71, 70, 70])
        self.assertEqual(len({c.y for c in self.cards}), 3)
        self.assertTrue(all(c.level_reliable for c in self.cards))
        self.assertTrue(all(c.fleet != 0 for c in self.cards))
        self.assertEqual(self.cards[8].ship['name'], '杓鹬.改')
        self.assertEqual(self.cards[13].ship['name'], '阿尔弗雷多·奥里亚尼')
        # 名单、等级和基础稀有度已确认的原始结果直接计费，无需修改核对字段。
        selected = [c.ship for c in self.cards if 90 <= c.ship['level'] <= 115]
        report = calculate(selected)
        self.assertTrue(all(not ship['review'] for ship in selected))
        self.assertEqual(report['included'], len(selected) - 1)
        self.assertEqual(report['excluded'], 1)  # 帕特莉夏为联动舰，保存但不计费。
        self.assertGreater(report['mind'], 0)

    def test_scaled_and_black_border_images_share_layout(self):
        cases = [self.image.resize((1920, 1080)), self.image.resize((960, 540)),
                 ImageOps.expand(self.image, (80, 45, 80, 45)), ImageOps.expand(self.image, (0, 40, 0, 40))]
        expected = [c.ship['level'] for c in self.cards]
        for image in cases:
            with self.subTest(size=image.size):
                normalized = normalize_screenshot(image)
                self.assertEqual(normalized.size, (1280, 720))
                self.assertEqual([c.ship['level'] for c in recognize_cards(normalized)], expected)

    def test_duplicate_names_remain_separate_cards(self):
        cards = recognize_cards(Image.open(FIXTURES / 'mind_dock_duplicates.png'))
        names = [c.ship['name'] for c in cards]
        self.assertEqual(len(cards), 21)
        for name in ['加拉蒂亚', '牙买加', '苏塞克斯', '阳炎']:
            self.assertEqual(names.count(name), 2)

    def test_retries_correct_only_unique_catalog_names(self):
        self.assertEqual(_match_name(['小猎免犬', '小猎兔犬'], 'R')[0]['name'], '小猎兔犬')
        self.assertIsNone(_match_name(['未知的舰船', '完全陌生'], 'SSR')[0])
        self.assertIsNone(_match_name(['皇家方舟·META', '皇家方舟'], 'SSR')[0])
        self.assertIsNone(_match_name(['拉菲', '标枪'], 'SR')[0])

    def test_unknown_name_keeps_review_when_level_is_confirmed(self):
        ocr = Mock()
        ocr.ocr_for_single_lines.side_effect = lambda regions: ['不存在的舰船'] * len(regions)
        cards = recognize_cards(self.image, name_ocr=ocr)
        self.assertTrue(all(card.level_reliable for card in cards))
        self.assertTrue(all(card.ship['review'] for card in cards))
        self.assertEqual(calculate([card.ship for card in cards])['mind'], 0)

    def test_native_name_crops_use_fleet_preprocessing(self):
        from module.ocr.al_ocr import AlOcr, OcrSettings
        from module.runtime.mind_recognition import _name_image, _scanners
        atlas = np.array(Image.open(FIXTURES / 'mind_names.png').convert('RGB'))
        labels = json.loads((FIXTURES / 'mind_names.json').read_text(encoding='utf-8'))
        regions = [atlas[index * 30:(index + 1) * 30] for index in range(len(labels))]
        prepared = [_name_image(region) for region in regions]
        for region, clean in zip(regions, prepared):
            np.testing.assert_array_equal(clean, _scanners()[1].pre_process(region))
            self.assertEqual(clean.shape, (19, 148))
        ocr = AlOcr(name='ppocr_v6', settings=OcrSettings('onnx', 'cpu', False, 'standard'))
        reads = ocr.ocr_for_single_lines(prepared)
        for raw, label in zip(reads, labels):
            self.assertEqual(_match_name([raw], 'SSR')[0]['name'], label['name'], raw)

    def test_verified_name_errors_preserve_second_type_identity(self):
        self.assertEqual(_match_name(['约克城ⅡI'], 'SSR')[0]['name'], '约克城II')
        self.assertEqual(_match_name(['列克星敦ⅡI'], 'SSR')[0]['name'], '列克星敦II')
        self.assertEqual(_match_name(['列克星敦', '列克星敦ⅡI', '列克星敦ⅡI'], 'SSR')[0]['name'], '列克星敦II')
        self.assertIsNone(_match_name(['列克星敦', '列克星敦II'], 'SSR')[0])
        for raw, name in [('酒句', '酒匂'), ('条鱼', '鲦鱼'), ('绦鱼', '鲦鱼'), ('四系乃', '四糸乃'), ('百雪', '白雪')]:
            self.assertEqual(_match_name([raw], 'SSR')[0]['name'], name)

    def test_invalid_images_have_specific_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            service = MindCalculatorService(ConfigService(fixture(temp)))
            def recognize(image):
                stream = io.BytesIO(); image.save(stream, format='PNG')
                return service.recognize('testpilot', 'wrong.png', base64.b64encode(stream.getvalue()).decode())
            for image, message in [(Image.new('RGB', (1280, 720)), '全黑'),
                                   (Image.new('RGB', (1000, 720), 'white'), '16:9'),
                                   (Image.new('RGB', (1280, 720), 'white'), '船坞界面')]:
                with self.subTest(message=message):
                    with self.assertRaises(ApiError) as error:
                        recognize(image)
                    self.assertIn(message, error.exception.message)
            with self.assertRaises(ApiError) as error:
                service.recognize('testpilot', 'broken.png', base64.b64encode(b'not an image').decode())
            self.assertIn('截图识别失败', error.exception.message)


class TransportTests(unittest.TestCase):
    def test_actual_server_accepts_large_screenshot_and_rejects_large_regular_request(self):
        """使用 gui 的真实 Uvicorn 配置，不能仅由 TestClient 绕过帧大小检查。"""
        import gui
        import uvicorn
        from websockets.sync.client import connect
        state = SimpleNamespace(deploy_config=SimpleNamespace(WebuiHost='127.0.0.1', WebuiPort=0,
                                                              WebuiSSLKey=None, WebuiSSLCert=None))
        with patch.object(gui, 'State', state), patch('sys.argv', ['gui.py']), \
                patch('deploy.frontend.ensure_frontend'), patch('module.logger.set_file_logger'), \
                patch('module.logger.set_console_logger'), patch('gui._run_uvicorn_server') as run:
            gui.func(None)
        config = run.call_args.args[0]
        self.assertEqual(config.ws_max_size, 8 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as temp, socket.socket() as listener:
            app = create_app(root=fixture(temp), password='', manage_runtime=False, mount_mcp=False)
            listener.bind(('127.0.0.1', 0)); listener.listen()
            config.app, config.factory, config.log_level = app, False, 'error'
            config.loaded = False
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            thread.start()
            try:
                until = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < until:
                    time.sleep(.01)
                self.assertTrue(server.started)
                with connect(f'ws://127.0.0.1:{listener.getsockname()[1]}/api/v1/ws', max_size=8 * 1024 * 1024) as ws:
                    ws.recv(timeout=5)  # 连接握手通知
                    content = base64.b64encode((FIXTURES / 'mind_dock_fleet_priority.png').read_bytes()).decode()
                    self.assertGreater(len(content), 1024 * 1024)
                    ws.send(json.dumps(dict(v=1, type='request', id='dock', method='mind.recognize', params=dict(instance='testpilot', filename='dock.png', content=content))))
                    reply = json.loads(ws.recv(timeout=30))
                    self.assertTrue(reply['ok'], reply)
                    self.assertEqual(len(reply['result']['ships']), 21)
                    ws.send(json.dumps(dict(v=1, type='request', id='oversize', method='mind.report', params=dict(instance='testpilot', junk='x' * (1024 * 1024)))))
                    rejected = json.loads(ws.recv(timeout=5))
                    self.assertEqual(rejected['error']['code'], 'INVALID_REQUEST')
                    # 拒绝普通超大请求后，连接依然可用。
                    ws.send(json.dumps(dict(v=1, type='request', id='alive', method='mind.report', params=dict(instance='testpilot'))))
                    self.assertTrue(json.loads(ws.recv(timeout=5))['ok'])
            finally:
                server.should_exit = True
                thread.join(timeout=10)
            self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
