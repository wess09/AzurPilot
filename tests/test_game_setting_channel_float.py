import unittest
import xml.etree.ElementTree as etree
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call, patch

from module.game_setting.channel_float import (
    ChannelFloatManager,
    update_ysdk_config_xml,
    ysdk_icon_disabled,
)
from module.game_setting.player_prefs import (
    AdbResult,
    PlayerPrefsMetadata,
    PlayerPrefsUnsupported,
    PlayerPrefsWriteError,
)

YSDK_PACKAGE = 'com.tencent.tmgp.bilibili.blhx'
CONFIG = f'/data/user/0/{YSDK_PACKAGE}/shared_prefs/YSDK_CONFIG.xml'
ENABLED = b'''<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="YSDK_ICON_GAME_ACTIVITY">com.manjuu.azurlane.MainActivity</string>
    <string name="YSDK_MSG_BOX_SWITCH">true</string>
    <string name="YSDK_ICON_SWITCH">true</string>
</map>'''


def _entries(content: bytes) -> dict[str | None, etree.Element]:
    return {element.get('name'): element for element in etree.fromstring(content)}


class TestYsdkConfigXml(unittest.TestCase):
    def test_turns_switch_off_and_keeps_other_keys(self):
        updated, changed = update_ysdk_config_xml(ENABLED)
        entries = _entries(updated)

        self.assertTrue(changed)
        self.assertEqual('false', entries['YSDK_ICON_SWITCH'].text)
        self.assertEqual('true', entries['YSDK_MSG_BOX_SWITCH'].text)
        self.assertEqual('com.manjuu.azurlane.MainActivity', entries['YSDK_ICON_GAME_ACTIVITY'].text)
        self.assertTrue(ysdk_icon_disabled(updated))

    def test_adds_missing_switch(self):
        updated, changed = update_ysdk_config_xml(b'<map />')

        self.assertTrue(changed)
        self.assertEqual('string', _entries(updated)['YSDK_ICON_SWITCH'].tag)
        self.assertTrue(ysdk_icon_disabled(updated))

    def test_second_update_is_idempotent(self):
        updated, _ = update_ysdk_config_xml(ENABLED)
        again, changed = update_ysdk_config_xml(updated)

        self.assertFalse(changed)
        self.assertEqual(updated, again)

    def test_rejects_unexpected_xml(self):
        with self.assertRaises(PlayerPrefsUnsupported):
            update_ysdk_config_xml(b'<map><boolean name="YSDK_ICON_SWITCH" value="true" /></map>')
        with self.assertRaises(PlayerPrefsUnsupported):
            update_ysdk_config_xml(b'<set />')
        with self.assertRaises(PlayerPrefsUnsupported):
            update_ysdk_config_xml(b'not xml')


class TestChannelFloatManager(unittest.TestCase):
    METADATA = PlayerPrefsMetadata(uid='10041', gid='10041', mode='660', context='u:object_r:test:s0')

    def _manager(self, package: str = YSDK_PACKAGE) -> ChannelFloatManager:
        manager = ChannelFloatManager(SimpleNamespace(package=package, adb_binary='adb', serial='serial'))
        manager._wait_until_game_stopped = Mock(return_value=True)
        manager._ensure_root = Mock(return_value=True)
        manager._cleanup_stale_transaction_files = Mock()
        manager._ensure_no_atomic_backup = Mock()
        manager._metadata = Mock(return_value=self.METADATA)
        manager._restore_metadata = Mock()
        manager._write_remote_bytes = Mock()
        return manager

    def test_skips_other_packages_without_root(self):
        manager = self._manager('com.bilibili.blhx.m4399')

        self.assertFalse(manager.apply())
        manager._ensure_root.assert_not_called()

    def test_already_locked_does_not_write(self):
        manager = self._manager()
        disabled, _ = update_ysdk_config_xml(ENABLED)
        manager._shell = Mock(side_effect=[
            AdbResult(0, '', ''),
            AdbResult(0, f'----i---------e----- {CONFIG}', ''),
        ])
        manager._read_remote_bytes = Mock(return_value=disabled)

        self.assertTrue(manager._apply_locked())
        manager._write_remote_bytes.assert_not_called()

    def test_missing_config_waits_for_next_start(self):
        manager = self._manager()
        manager._shell = Mock(return_value=AdbResult(1, '', ''))
        manager._read_remote_bytes = Mock()

        self.assertFalse(manager._apply_locked())
        manager._read_remote_bytes.assert_not_called()

    def test_writes_then_locks_file(self):
        manager = self._manager()
        disabled, _ = update_ysdk_config_xml(ENABLED)
        unlocked = AdbResult(0, f'--------------e----- {CONFIG}', '')
        locked = AdbResult(0, f'----i---------e----- {CONFIG}', '')
        ok = AdbResult(0, '', '')
        manager._shell = Mock(side_effect=[ok, unlocked, ok, ok, locked, ok])
        manager._read_remote_bytes = Mock(side_effect=[ENABLED, disabled, disabled])

        with patch('module.game_setting.channel_float.secrets.token_hex', return_value='0' * 16):
            self.assertTrue(manager._apply_locked())

        temporary = f'{CONFIG}.alas-tmp-{"0" * 16}.tmp'
        manager._write_remote_bytes.assert_called_once_with(temporary, disabled, PlayerPrefsWriteError)
        manager._restore_metadata.assert_called_once_with(temporary, self.METADATA)
        self.assertEqual(
            [
                call(['test', '-f', CONFIG], check=False),
                call(['lsattr', CONFIG], check=False),
                call(['mv', temporary, CONFIG], error_type=PlayerPrefsWriteError),
                call(['chattr', '+i', CONFIG], error_type=PlayerPrefsWriteError),
                call(['lsattr', CONFIG], check=False),
                call(['rm', '-f', temporary], check=False),
            ],
            manager._shell.call_args_list,
        )

    def test_unlocks_before_rewriting_locked_file(self):
        manager = self._manager()
        disabled, _ = update_ysdk_config_xml(ENABLED)
        locked = AdbResult(0, f'----i---------e----- {CONFIG}', '')
        ok = AdbResult(0, '', '')
        manager._shell = Mock(side_effect=[ok, locked, ok, ok, ok, locked, ok])
        manager._read_remote_bytes = Mock(side_effect=[ENABLED, disabled, disabled])

        self.assertTrue(manager._apply_locked())
        self.assertEqual(
            call(['chattr', '-i', CONFIG], error_type=PlayerPrefsWriteError),
            manager._shell.call_args_list[2],
        )

    def test_write_failure_is_skipped(self):
        manager = self._manager()
        unlocked = AdbResult(0, f'--------------e----- {CONFIG}', '')
        ok = AdbResult(0, '', '')
        manager._shell = Mock(side_effect=[ok, unlocked, ok])
        manager._read_remote_bytes = Mock(side_effect=[ENABLED, b'<map />'])

        self.assertFalse(manager._apply_locked())
        self.assertEqual(call(['rm', '-f', ANY], check=False), manager._shell.call_args_list[-1])

    def test_apply_restores_root_state(self):
        manager = self._manager()
        manager._apply_locked = Mock(side_effect=PlayerPrefsUnsupported('x'))
        manager._restore_root_state = Mock()

        with patch('module.game_setting.channel_float._device_lock', return_value=nullcontext()):
            self.assertFalse(manager.apply())
        manager._restore_root_state.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
