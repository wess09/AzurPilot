"""装备码跨任务交接、配置保护与卸装失败的回归。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

import yaml

from module.campaign.gems_farming import GemsEquipmentHandler
from module.equipment.assets import EQUIPMENT_CODE_EXPORT
from module.equipment.equipment_code import EMPTY_CODE, EquipmentCodeHandler
from module.exception import RequestHumanTakeover


# 仅用于无设备的流程测试，不代表实际游戏装备。
CV_CODE = 'MTExLzIyMi8zMzMvMC8wXDA='
DD_CODE = 'NDQ0LzU1NS82NjYvMC8wXDA='


def handler_with_store(store, ship='bogue'):
    handler = object.__new__(GemsEquipmentHandler)
    handler.config = SimpleNamespace(
        task=SimpleNamespace(command='ThreeOilLowCost'), Emulator_ControlMethod='minitouch',
        cross_get=lambda keys: store['raw'],
        cross_set=lambda keys, value: store.update(raw=value),
    )
    handler._code_enter = Mock()
    handler.current_ship = Mock(return_value=ship)
    handler._code_export = Mock(return_value=CV_CODE)
    handler._code_apply = Mock(return_value=True)
    return handler


def export_handler(*attempts):
    handler = object.__new__(EquipmentCodeHandler)
    handler.device = Mock()
    handler.loop = Mock(side_effect=[range(len(info_bars)) for info_bars in attempts])
    handler.info_bar_count = Mock(side_effect=[value for info_bars in attempts for value in info_bars])
    handler.appear_then_click = Mock(return_value=True)
    handler._clipboard_adb = Mock(return_value=None)
    return handler


class EquipmentTransferTests(unittest.TestCase):
    def test_saved_bogue_survives_task_recreation_and_equips_unconfigured_ranger(self):
        store = {'raw': 'bogue: null\nranger: null'}
        first = handler_with_store(store)
        self.assertTrue(first.code_clear())
        self.assertTrue(first.code_apply())
        # 与实际日志一致：切换任务后重新创建处理器，内存缓存已不存在。
        resumed = handler_with_store(store)
        self.assertIsNone(resumed.last_code)
        self.assertTrue(resumed.code_clear())
        resumed._code_export.assert_not_called()
        resumed.current_ship.return_value = 'ranger'
        self.assertTrue(resumed.code_apply())
        resumed._code_apply.assert_called_with(code=CV_CODE)
        self.assertIsNone(resumed.last_code)

    def test_each_clear_replaces_cache_and_target_scheme_has_priority(self):
        store = {'raw': yaml.safe_dump({'bogue': CV_CODE, 'ranger': DD_CODE, 'DD': DD_CODE})}
        handler = handler_with_store(store)
        handler.last_code = DD_CODE
        self.assertTrue(handler.code_clear())
        self.assertEqual(handler.last_code, CV_CODE)
        self.assertTrue(handler.code_apply(name='ranger'))
        handler._code_apply.assert_called_with(code=DD_CODE)
        self.assertIsNone(handler.last_code)
        self.assertTrue(handler.code_clear(name='DD'))
        self.assertEqual(handler.last_code, DD_CODE)

    def test_failed_clear_and_unsupported_control_discard_previous_cache(self):
        for supported in (True, False):
            handler = handler_with_store({'raw': yaml.safe_dump({'bogue': CV_CODE})})
            handler.last_code = DD_CODE
            handler.equipment_code_supported = Mock(return_value=supported)
            handler._code_apply.return_value = False
            self.assertFalse(handler.code_clear())
            self.assertIsNone(handler.last_code)
            if not supported:
                handler._code_enter.assert_not_called()

    def test_missing_or_invalid_export_never_clears_equipment(self):
        for value in (None, '', '   ', 123, [], 'invalid'):
            with self.subTest(value=value):
                handler = handler_with_store({'raw': ''})
                handler.last_code = DD_CODE
                handler._code_export.return_value = value
                self.assertFalse(handler.code_clear())
                handler._code_apply.assert_not_called()
                self.assertIsNone(handler.last_code)

    def test_save_failure_leaves_equipment_and_store_untouched(self):
        store = {'raw': 'ranger: null'}
        handler = handler_with_store(store)
        handler.config.cross_set = Mock(side_effect=OSError('只读文件系统'))
        self.assertFalse(handler.code_clear())
        handler._code_apply.assert_not_called()
        self.assertEqual(store['raw'], 'ranger: null')
        self.assertIsNone(handler.last_code)

    def test_invalid_yaml_or_document_shape_never_overwrites_other_schemes(self):
        for raw in ('bogue: [', 'bogue: ' + CV_CODE + '\n---\n- broken', '42', '[1, 2]'):
            with self.subTest(raw=raw):
                store = {'raw': raw}
                handler = handler_with_store(store)
                with self.assertRaises(RequestHumanTakeover):
                    handler.code_clear()
                handler._code_apply.assert_not_called()
                handler._code_export.assert_not_called()
                self.assertEqual(store['raw'], raw)

    def test_missing_blank_and_invalid_target_codes_use_current_transfer_only(self):
        for value in (None, '', '  ', 123, [], {}, 'invalid'):
            with self.subTest(value=value):
                handler = handler_with_store({'raw': yaml.safe_dump({'bogue': CV_CODE, 'ranger': value})})
                self.assertTrue(handler.code_clear())
                self.assertTrue(handler.code_apply(name='ranger'))
                handler._code_apply.assert_called_with(code=CV_CODE)
                handler._code_apply.reset_mock()
                self.assertFalse(handler.code_apply(name='ranger'))
                handler._code_apply.assert_not_called()

    def test_successful_export_preserves_other_configured_schemes(self):
        store = {'raw': yaml.safe_dump({'DD': DD_CODE, 'bogue': None})}
        handler = handler_with_store(store)
        self.assertTrue(handler.code_clear())
        self.assertEqual(yaml.safe_load(store['raw']), {'DD': DD_CODE, 'bogue': CV_CODE})

    def test_explicit_empty_code_remains_valid(self):
        handler = handler_with_store({'raw': yaml.safe_dump({'bogue': EMPTY_CODE})})
        self.assertTrue(handler.code_clear())
        self.assertTrue(handler.code_apply())
        handler._code_apply.assert_called_with(code=EMPTY_CODE)

    def test_export_timeout_does_not_reuse_clipboard(self):
        for bars, clicked in (((0, 0), True), ((0, 1), False), ((1, 1), True)):
            with self.subTest(bars=bars, clicked=clicked):
                handler = export_handler(bars)
                handler.appear_then_click.return_value = clicked
                self.assertIsNone(handler._code_export())
                handler._clipboard_adb.assert_not_called()
                handler.device.ensure_clipboard_uiautomator2.assert_not_called()
                if bars == (1, 1):
                    handler.appear_then_click.assert_not_called()

    def test_adb_export_succeeds_even_when_uiautomator2_is_unavailable(self):
        handler = export_handler((1, 0, 1))
        handler._clipboard_adb.return_value = DD_CODE
        handler.device.ensure_clipboard_uiautomator2.side_effect = RequestHumanTakeover
        order = Mock()
        order.attach_mock(handler.appear_then_click, 'copy')
        order.attach_mock(handler.info_bar_count, 'notice')
        order.attach_mock(handler._clipboard_adb, 'read_adb')

        self.assertEqual(handler._code_export(), DD_CODE)
        self.assertEqual(order.mock_calls, [
            call.notice(), call.notice(), call.copy(EQUIPMENT_CODE_EXPORT, offset=(5, 5), interval=3),
            call.notice(), call.read_adb(),
        ])
        handler.device.ensure_clipboard_uiautomator2.assert_not_called()
        handler.device.get_clipboard_uiautomator2.assert_not_called()

    def test_export_fallback_prepares_and_confirms_fresh_copy_before_reading(self):
        handler = export_handler((0, 1), (1, 0, 1))
        handler.device.get_clipboard_uiautomator2.return_value = CV_CODE
        order = Mock()
        order.attach_mock(handler.appear_then_click, 'copy')
        order.attach_mock(handler._clipboard_adb, 'read_adb')
        order.attach_mock(handler.device.ensure_clipboard_uiautomator2, 'prepare')
        order.attach_mock(handler.device.get_clipboard_uiautomator2, 'read_uiautomator')
        order.attach_mock(handler.device.stuck_record_clear, 'reset')

        self.assertEqual(handler._code_export(), CV_CODE)
        copy = call.copy(EQUIPMENT_CODE_EXPORT, offset=(5, 5), interval=3)
        self.assertEqual(order.mock_calls, [
            copy, call.read_adb(), call.prepare(), copy, call.read_uiautomator(), call.reset(),
        ])
        self.assertEqual(handler.loop.call_args_list, [call(timeout=10, skip_first=False)] * 2)

    def test_fallback_export_does_not_read_if_only_old_notice_is_visible(self):
        handler = export_handler((0, 1), (1, 1))
        self.assertIsNone(handler._code_export())
        handler._clipboard_adb.assert_called_once()
        handler.device.ensure_clipboard_uiautomator2.assert_called_once()
        handler.appear_then_click.assert_called_once()
        handler.device.get_clipboard_uiautomator2.assert_not_called()

    def test_invalid_fallback_clipboard_protects_equipment(self):
        for clipboard in ('', 'bad-code'):
            with self.subTest(clipboard=clipboard):
                handler = export_handler((0, 1), (0, 1))
                handler.config = SimpleNamespace(
                    Emulator_ControlMethod='MaaTouch', EquipmentCode_ExportToConfig=True, EquipmentCode_Config='',
                )
                handler.last_code = DD_CODE
                handler.device.get_clipboard_uiautomator2.return_value = clipboard
                handler._code_enter = Mock()
                handler.set_code = Mock()
                handler._code_apply = Mock()

                self.assertFalse(handler.code_clear(name='bogue'))
                self.assertIsNone(handler.last_code)
                handler.set_code.assert_not_called()
                handler._code_apply.assert_not_called()

    def test_export_preserves_device_takeover(self):
        for operation in ('ensure_clipboard_uiautomator2', 'get_clipboard_uiautomator2'):
            with self.subTest(operation=operation):
                handler = export_handler((0, 1), (0, 1))
                getattr(handler.device, operation).side_effect = RequestHumanTakeover
                with self.assertRaises(RequestHumanTakeover):
                    handler._code_export()

    def test_generic_clear_without_export_keeps_original_behavior(self):
        handler = object.__new__(EquipmentCodeHandler)
        handler.config = SimpleNamespace(Emulator_ControlMethod='minitouch', EquipmentCode_ExportToConfig=False)
        handler._code_enter = Mock()
        handler.current_ship = Mock(return_value='DD')
        handler._code_export = Mock()
        handler._code_apply = Mock(return_value=True)
        handler.last_code = CV_CODE
        self.assertTrue(handler.code_clear())
        handler._code_export.assert_not_called()
        self.assertIsNone(handler.last_code)


if __name__ == '__main__':
    unittest.main()
