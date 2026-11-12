import base64
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, call

import pytest
from lxml import etree

from module.device.device import Device
from module.device.method.fastinput_ime import FastInputIME
from module.device.method.utils import RETRY_TRIES
from module.exception import EmulatorNotRunningError, GameStuckError, GameTooManyClickError, RequestHumanTakeover


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr('module.device.method.adb.time.sleep', lambda _: None)


@pytest.fixture
def device():
    device = object.__new__(Device)
    device.config = SimpleNamespace(Emulator_ControlMethod='uiautomator2')
    device.sdk_ver = 35
    device._fastinput_ime_prepare_onscreen_keyboard = Mock()
    device.current_ime_adb = Mock(return_value=('stock/.IME', False))
    device.click, device.sleep, device.adb_shell = Mock(), Mock(), Mock(return_value='')
    device.u2 = Mock(info={}, shell=Mock(return_value=SimpleNamespace(exit_code=0, output='')))
    return device


class Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f'unexpected backend access: {name}')


@pytest.mark.parametrize('failures', [1, RETRY_TRIES])
def test_clipboard_preparation_warms_rpc_and_handles_initialization_failure(device, failures):
    initialize = PropertyMock(side_effect=[OSError('cannot connect')] * failures + [{}])
    type(device.u2).info = initialize

    if failures == RETRY_TRIES:
        with pytest.raises(RequestHumanTakeover):
            device.ensure_clipboard_uiautomator2()
    else:
        assert device.ensure_clipboard_uiautomator2() is None
    assert initialize.call_count == min(failures + 1, RETRY_TRIES)


@pytest.mark.parametrize('dump,expected', [
    ('mCurMethodId=stock/.IME\nmInputShown=true', ('stock/.IME', True)),
    ('''mCurrentImeUserId=10
UserId=0
  mSelectedMethodId=stock/.IME
  mInputShown=true
UserId=10
  mSelectedMethodId=work/.IME
  mInputShown=false
''', ('work/.IME', False)),
])
def test_current_ime_uses_selected_current_user_state(dump, expected):
    device = object.__new__(Device)
    device.adb_shell = Mock(return_value=dump)

    assert device.current_ime_adb() == expected


@pytest.mark.parametrize('failures', [0, 1, RETRY_TRIES])
def test_fastinput_replaces_utf8_text_on_each_attempt(device, failures):
    device.current_ime_adb.return_value = (FastInputIME.FASTINPUT_IME, True)
    success = SimpleNamespace(exit_code=0, output='')
    failed = SimpleNamespace(exit_code=1, output='broadcast failed')
    device.u2.shell.side_effect = [success, failed] * failures + [success, success]
    text = '蓝 Aa09+/= "\n'

    if failures == RETRY_TRIES:
        with pytest.raises(RequestHumanTakeover):
            device.input_text_fastinput_ime(text, Mock())
    else:
        assert device.input_text_fastinput_ime(text, Mock()) is None

    commands = [args[0][0] for args in device.u2.shell.call_args_list]
    assert [command[3] for command in commands] == ['ADB_SET_TEXT', 'ADB_EDITOR_CODE'] * min(failures + 1, RETRY_TRIES)
    assert all(base64.b64decode(command[-1]).decode('utf-8') == text for command in commands[::2])
    device.sleep.assert_not_called()


def test_fastinput_setup_failure_does_not_broadcast(device):
    device._set_fastinput_ime = Mock(return_value=False)
    device._enable_fastinput_ime = Mock()
    device._fastinput_ime_log_failure_hint = Mock()
    device.u2 = Forbidden()

    with pytest.raises(RequestHumanTakeover):
        device.input_text_fastinput_ime('code', object())
    assert device._enable_fastinput_ime.call_count == RETRY_TRIES


@pytest.mark.parametrize('sdk,resource_id', [
    (28, 'android:id/switch_widget'), (35, 'com.android.settings:id/switchWidget'),
])
def test_fastinput_settings_handles_both_android_switch_layouts(device, sdk, resource_id):
    def settings(fast_checked, stock_checked, confirm=False):
        root = etree.Element('hierarchy')
        for name, checked in [('FastInputIME', fast_checked), ('StockIME', stock_checked)]:
            row = etree.SubElement(root, 'node')
            etree.SubElement(row, 'node', attrib={'resource-id': 'android:id/title', 'text': name})
            etree.SubElement(row, 'node', attrib={
                'resource-id': resource_id, 'checked': checked, 'enabled': 'true',
            })
        if confirm:
            etree.SubElement(root, 'node', attrib={'resource-id': 'android:id/button1'})
        return root

    frames = iter([
        settings('false', 'true'), settings('true', 'true', confirm=True),
        settings('true', 'true'), settings('true', 'false'),
    ])

    def dump_hierarchy():
        device.hierarchy = next(frames)

    device.sdk_ver = sdk
    device.is_mumu_over_version_400 = False
    device.dump_hierarchy = Mock(side_effect=dump_hierarchy)
    device.stuck_record_clear = Mock()

    device._enable_fastinput_ime()

    assert [args[0][0].attrib['resource-id'] for args in device.click.call_args_list] == [
        resource_id, 'android:id/button1', resource_id,
    ]
    assert device.adb_shell.call_args_list == [
        call(['am', 'start', '-a', 'android.settings.INPUT_METHOD_SETTINGS']),
        call(['input', 'keyevent', '4']),
    ]
    assert device.stuck_record_clear.call_count == 2


def test_fastinput_triggers_interface_and_waits_for_ime_before_sending(device):
    device.current_ime_adb.side_effect = [
        ('stock/.IME', False), (FastInputIME.FASTINPUT_IME, False),
        (FastInputIME.FASTINPUT_IME, False), (FastInputIME.FASTINPUT_IME, True),
    ]
    order = Mock()
    for name, method in [('click', device.click), ('ime', device.current_ime_adb),
                         ('select', device.u2.set_fastinput_ime), ('send', device.u2.shell)]:
        order.attach_mock(method, name)

    device.input_text_fastinput_ime('code', object())

    assert [event[0] for event in order.mock_calls] == [
        'click', 'ime', 'select', 'ime', 'click', 'ime', 'ime', 'send', 'send',
    ]
    device.u2.set_fastinput_ime.assert_called_once_with(True)
    assert device.sleep.call_args_list == [call(0.1), call(0.1)]


@pytest.mark.parametrize('error', [GameStuckError, GameTooManyClickError, EmulatorNotRunningError, RequestHumanTakeover])
def test_fastinput_preserves_device_errors_without_retrying_click(device, error):
    device.click.side_effect = error('control failed')

    with pytest.raises(error, match='control failed'):
        device.input_text_fastinput_ime('code', object())

    device.click.assert_called_once()
    device.u2.shell.assert_not_called()


def test_foreground_task_and_activity_share_one_dump(device):
    device.adb_shell.return_value = (
        'mFocusedApp=ActivityRecord{abc u0 com.example/.MainActivity t42}\n'
        'mCurrentFocus=Window{def u0 com.example/.MainActivity}\n'
    )

    assert device._foreground_adb() == (42, 'com.example/com.example.MainActivity')
    device.adb_shell.assert_called_once_with(['dumpsys', 'window'])


def test_clipboard_keeps_game_in_foreground_when_original_activity_is_unknown(device):
    device._foreground_adb = Mock(return_value=(42, None))

    with pytest.raises(RequestHumanTakeover):
        device.get_clipboard_uiautomator2()

    device.adb_shell.assert_not_called()


def test_uiautomator_clipboard_recovers_read_failure_and_restores_each_attempt(device):
    clipboard = PropertyMock(side_effect=[OSError('clipboard read failed'), 'copied text'])
    type(device.u2).clipboard = clipboard
    helper = 'com.github.uiautomator/com.github.uiautomator.MainActivity'
    permission = ('com.android.permissioncontroller/'
                  'com.android.permissioncontroller.permission.ui.GrantPermissionsActivity')
    original = 'com.example/com.example.MainActivity'
    device._foreground_adb = Mock(side_effect=[
        (42, original), (99, permission), (99, helper), (42, original),
        (42, original), (99, helper), (42, original),
    ])

    assert device.get_clipboard_uiautomator2() == 'copied text'

    assert clipboard.call_count == 2
    device.adb_shell.assert_any_call(['input', 'keyevent', 'KEYCODE_BACK'])
    assert device.adb_shell.call_args_list.count(call(['am', 'task', 'focus', '42'], timeout=15)) == 2
    assert device._foreground_adb.call_count == 7


@pytest.mark.parametrize('sdk,ime,value', [
    (28, 'stock/.IME', 'legacy text'), (35, FastInputIME.FASTINPUT_IME, 'copied text'),
    (35, FastInputIME.FASTINPUT_IME, None),
])
def test_clipboard_reads_directly_when_access_is_available(device, sdk, ime, value):
    device.sdk_ver = sdk
    device.current_ime_adb.return_value = (ime, False)
    clipboard = PropertyMock(return_value=value)
    type(device.u2).clipboard = clipboard
    device._foreground_adb = Mock()

    assert device.get_clipboard_uiautomator2() == (value or '')

    clipboard.assert_called_once_with()
    device._foreground_adb.assert_not_called()
    device.sleep.assert_not_called()


def test_restore_failure_retries_saved_activity_without_restarting_clipboard(device, monkeypatch):
    clipboard = PropertyMock(return_value='copied text')
    type(device.u2).clipboard = clipboard
    helper = 'com.github.uiautomator/com.github.uiautomator.MainActivity'
    device._foreground_adb = Mock(side_effect=[(42, 'com.example/.Main'), (99, helper)]
                                            + [(42, 'com.other/.Main')] * RETRY_TRIES)
    monkeypatch.setattr('module.device.method.adb.time.monotonic', Mock(side_effect=[0] + [0, 6] * RETRY_TRIES))

    with pytest.raises(RequestHumanTakeover):
        device.get_clipboard_uiautomator2()

    clipboard.assert_called_once_with()
    assert device.adb_shell.call_args_list.count(call(['am', 'start', '-W', '-n', helper], timeout=15)) == 1
    assert device.adb_shell.call_args_list.count(call(['am', 'task', 'focus', '42'], timeout=15)) == RETRY_TRIES
