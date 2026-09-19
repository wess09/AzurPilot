"""模拟器启停并发保护测试。

回归自 2026-09-16 的实机日志：两条恢复线程同时在跑 emulator_start，
一个刚发出启动命令、另一个随即 shutdown，MuMu 窗口永远卡在加载态。
这里锁定三件事：

1. 启停操作互斥——已有操作在跑时，新的启停请求抛 EmulatorOpBusy 且不动手；
2. 锁覆盖操作的**全过程**（含 3 次重试与启动监视），不是只包住发命令；
3. 启动监视超时按 180/300/480 递增，给冷启动留出时间。
"""

import inspect
import json
import threading
import unittest
from unittest.mock import Mock, call, create_autospec, patch

from alas import RESTART_EMULATOR_OP_TIMEOUT, AzurLaneAutoScript
from module.device.env import IS_WINDOWS
from module.exception import EmulatorNotRunningError, EmulatorOpBusy

if IS_WINDOWS:
    from module.device.platform import platform_windows
    from module.device.platform.platform_windows import (
        EMULATOR_START_WATCH_TIMEOUTS,
        MUMU12_DEEP_WAIT_TIMEOUT,
        MUMU12_STOP_WAIT_TIMEOUT,
        PlatformWindows,
    )


# autospec 反射整个 Device 类很慢（约 26 秒），复用同一个实例
_DEVICE_AUTOSPEC = None


def make_platform():
    """构造一个不连接设备、不碰真实模拟器的 PlatformWindows。

    用 __new__ 跳过 __init__（避免 ADB 连接与配置读取），只替换掉真正
    会去操作模拟器的那几个方法。
    """
    platform = PlatformWindows.__new__(PlatformWindows)
    platform.config = Mock()
    platform._emulator_function_wrapper = Mock(return_value=True)
    platform.emulator_start_watch = Mock(return_value=True)
    platform._emulator_stop = Mock()
    platform._emulator_start = Mock()
    return platform


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器平台测试')
class TestEmulatorOpExclusive(unittest.TestCase):
    def tearDown(self):
        # 兜底：任何测试把锁漏掉都会让后续测试全红，这里主动回收
        if PlatformWindows._emulator_op_lock.locked():
            PlatformWindows._emulator_op_lock.release()

    def test_stop_is_skipped_while_another_op_holds_the_lock(self):
        platform = make_platform()
        with PlatformWindows._emulator_op_lock:
            with self.assertRaises(EmulatorOpBusy):
                platform.emulator_stop()

        # 关键：被跳过时不能真的去动模拟器
        platform._emulator_stop.assert_not_called()
        platform._emulator_start.assert_not_called()

    def test_start_is_skipped_while_another_op_holds_the_lock(self):
        platform = make_platform()
        with PlatformWindows._emulator_op_lock:
            with self.assertRaises(EmulatorOpBusy):
                platform.emulator_start()

        platform._emulator_stop.assert_not_called()
        platform._emulator_start.assert_not_called()

    def test_lock_is_released_after_success(self):
        platform = make_platform()
        self.assertTrue(platform.emulator_stop())
        self.assertTrue(platform.emulator_start())

    def test_lock_is_released_when_operation_raises(self):
        platform = make_platform()
        platform._emulator_function_wrapper = Mock(side_effect=RuntimeError('boom'))

        with self.assertRaises(RuntimeError):
            platform.emulator_stop()

        # 异常路径也必须释放，否则后续恢复会被永久跳过
        self.assertTrue(PlatformWindows._emulator_op_lock.acquire(blocking=False))
        PlatformWindows._emulator_op_lock.release()

    def test_lock_is_held_for_the_whole_start_attempt(self):
        """启动监视进行中时，另一个线程不能停模拟器。

        这是本次事故的直接成因：监视（最长数分钟的冷启动等待）期间
        被另一个线程 shutdown 打断。
        """
        platform = make_platform()
        watching = threading.Event()
        release = threading.Event()

        def watch(timeout=None):
            watching.set()
            release.wait(5)
            return True

        platform.emulator_start_watch = watch
        thread = threading.Thread(target=platform.emulator_start)
        thread.start()
        try:
            self.assertTrue(watching.wait(5), '启动监视未进入')
            with self.assertRaises(EmulatorOpBusy):
                platform.emulator_stop()
        finally:
            release.set()
            thread.join(5)

        self.assertFalse(thread.is_alive())

    def test_watch_timeout_follows_the_failure_ladder(self):
        """连续失败越多等得越久，上限 300 秒。

        好设备 60 秒内就能起来，没必要一上来就等几分钟；持续起不来时才逐级放宽。
        """
        cases = [(0, 60), (1, 90), (2, 120), (3, 180), (4, 300), (9, 300)]
        for failures, expected in cases:
            with self.subTest(failures=failures):
                platform = make_platform()
                platform.emulator_start_watch = Mock(return_value=False)

                self.assertFalse(platform.emulator_start(failures=failures))
                platform.emulator_start_watch.assert_called_once_with(timeout=expected)

        self.assertEqual(list(EMULATOR_START_WATCH_TIMEOUTS),
                         sorted(EMULATOR_START_WATCH_TIMEOUTS))

    def test_start_makes_exactly_one_attempt(self):
        """一轮只试一次，重试交给调度器下一轮——不再在一次调用里连试 3 次。"""
        platform = make_platform()
        platform.emulator_start_watch = Mock(return_value=True)

        self.assertTrue(platform.emulator_start())

        platform.emulator_start_watch.assert_called_once()


def mumu_info(*players):
    """构造 MuMuManager info -v all 的 JSON 输出。"""
    data = {str(i): p for i, p in enumerate(players)}
    return json.dumps(data, ensure_ascii=False)


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器平台测试')
class TestMumu12StateQuery(unittest.TestCase):
    """MuMuManager info 查询：按实例精确判断状态，替代靠进程名猜测。"""

    def make_platform(self, stdout):
        platform = make_platform()
        platform.emulator_instance = Mock()
        platform.emulator_instance.emulator.path = 'F:/mumu/shell/MuMuPlayer.exe'
        platform.emulator_instance.MuMuPlayer12_id = 0
        return platform, patch.object(platform_windows, 'run_mumu_manager', return_value=stdout)

    def test_parses_instance_states(self):
        platform, patched = self.make_platform(
            mumu_info({'is_process_started': True, 'player_state': 'start_finished'}, {'is_process_started': False})
        )
        with patched:
            info = platform._mumu12_instances('F:/mumu/shell/MuMuPlayer.exe')

        self.assertEqual({'0', '1'}, set(info))
        self.assertTrue(info['0']['is_process_started'])
        self.assertFalse(info['1']['is_process_started'])

    def test_returns_none_when_output_is_not_json(self):
        platform, patched = self.make_platform('unknown cmd: info')
        with patched:
            self.assertIsNone(platform._mumu12_instances('F:/mumu/shell/MuMuPlayer.exe'))

    def test_other_instance_running_detects_multi_open(self):
        cases = [
            (mumu_info({'is_process_started': True}, {'is_process_started': False}), False),
            (mumu_info({'is_process_started': True}, {'is_process_started': True}), True),
            (mumu_info({'is_process_started': False}, {'is_process_started': False}), False),
        ]
        for stdout, expected in cases:
            platform, patched = self.make_platform(stdout)
            with patched:
                self.assertIs(expected, platform._mumu12_other_instance_running(
                    'F:/mumu/shell/MuMuPlayer.exe', 0))

    def test_other_instance_running_is_unknown_when_query_fails(self):
        platform, patched = self.make_platform('')
        with patched:
            self.assertIsNone(platform._mumu12_other_instance_running(
                'F:/mumu/shell/MuMuPlayer.exe', 0))

    def test_residue_cleanup_skipped_for_multi_open(self):
        """多开时不按进程名清理，避免误伤其它实例。"""
        platform, patched = self.make_platform(
            mumu_info({'is_process_started': True}, {'is_process_started': True})
        )
        with patched, patch.object(platform_windows.psutil, 'process_iter') as process_iter:
            platform._clean_mumu12_residue('F:/mumu/shell/MuMuPlayer.exe', 0)

        process_iter.assert_not_called()

    def test_residue_cleanup_skipped_when_state_unknown(self):
        """查不到状态时不清理——宁可少清理，不可误杀。"""
        platform, patched = self.make_platform('')
        with patched, patch.object(platform_windows.psutil, 'process_iter') as process_iter:
            platform._clean_mumu12_residue('F:/mumu/shell/MuMuPlayer.exe', 0)

        process_iter.assert_not_called()

    def test_wait_stopped_returns_when_instance_is_down(self):
        platform, patched = self.make_platform(mumu_info({'is_process_started': False}))
        with patched:
            self.assertTrue(platform._mumu12_wait_stopped('F:/mumu/shell/MuMuPlayer.exe', 0))

    def test_wait_stopped_keeps_polling_while_instance_is_up(self):
        """实例还在关闭过程中必须继续等。

        MuMu 的 shutdown 是异步的：命令秒回、实例还要 2~3 秒才停。
        ALAS 原来只盲等 2 秒就 launch，请求会被吞掉（实机复现）。
        """
        platform = make_platform()
        platform.emulator_instance = Mock()
        platform.emulator_instance.MuMuPlayer12_id = 0
        started = mumu_info({'is_process_started': True})
        stopped = mumu_info({'is_process_started': False})
        responses = [started, started, stopped]

        with (
            patch.object(platform_windows, 'run_mumu_manager', side_effect=responses),
            patch.object(platform_windows, 'MUMU12_STATE_POLL_INTERVAL', 0),
        ):
            self.assertTrue(platform._mumu12_wait_stopped('F:/mumu/shell/MuMuPlayer.exe', 0))

    def test_wait_stopped_gives_up_after_timeout(self):
        platform = make_platform()
        with (
            patch.object(platform_windows, 'run_mumu_manager',
                         return_value=mumu_info({'is_process_started': True})),
            patch.object(platform_windows, 'MUMU12_STATE_POLL_INTERVAL', 0),
            patch.object(platform_windows, 'MUMU12_STOP_WAIT_TIMEOUT', 0),
        ):
            self.assertFalse(platform._mumu12_wait_stopped('F:/mumu/shell/MuMuPlayer.exe', 0))

    def test_wait_stopped_falls_back_when_query_unavailable(self):
        """旧版 MuMu 没有 info 子命令时不能卡住，回退到旧的短暂等待。"""
        platform = make_platform()
        with (
            patch.object(platform_windows, 'run_mumu_manager', return_value=''),
            patch.object(platform_windows, 'MUMU12_STATE_POLL_INTERVAL', 0),
        ):
            self.assertTrue(platform._mumu12_wait_stopped('F:/mumu/shell/MuMuPlayer.exe', 0))


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器平台测试')
class TestDeepRestart(unittest.TestCase):
    """深度重启：结束 MuMu 全部进程，仅由「连续重启都失败」触发。

    定位是最後一招逃生口，不是省内存的常规手段——实测普通重启已经会替换
    虚拟机进程，全杀并不更省内存。
    """

    def make_platform(self):
        return make_platform()

    @staticmethod
    def fake_process(name, pid=1234):
        proc = Mock()
        proc.info = {'name': name}
        proc.pid = pid
        return proc

    def test_deep_clean_kills_only_listed_processes(self):
        platform = self.make_platform()
        platform.execute = Mock()
        mumu_player = self.fake_process('MuMuPlayer.exe')
        mumu_vm = self.fake_process('MuMuVMMHeadless.exe')
        unrelated = self.fake_process('notepad.exe')

        with patch.object(platform_windows.psutil, 'process_iter',
                          side_effect=[[mumu_player, mumu_vm, unrelated], []]):
            self.assertTrue(platform._deep_clean_mumu12('F:/mumu/shell/MuMuPlayer.exe'))

        mumu_player.kill.assert_called_once()
        mumu_vm.kill.assert_called_once()
        unrelated.kill.assert_not_called()

    def test_deep_clean_asks_mumu_to_shutdown_all_instances(self):
        platform = self.make_platform()
        platform.execute = Mock()
        with patch.object(platform_windows.psutil, 'process_iter', side_effect=[[], []]):
            platform._deep_clean_mumu12('F:/mumu/shell/MuMuPlayer.exe')

        self.assertTrue(platform.execute.called)
        self.assertIn('control -v all shutdown', platform.execute.call_args.args[0])

    def test_deep_clean_ignores_multi_open(self):
        """多开不阻止深度重启——用户明确选了「一律全杀」。"""
        platform = self.make_platform()
        platform.execute = Mock()
        multi_open = mumu_info({'is_process_started': True}, {'is_process_started': True})

        with (
            patch.object(platform_windows, 'run_mumu_manager', return_value=multi_open) as query,
            patch.object(platform_windows.psutil, 'process_iter', side_effect=[[], []]),
        ):
            platform._deep_clean_mumu12('F:/mumu/shell/MuMuPlayer.exe')

        # 关键：根本没有去查其它实例的状态
        query.assert_not_called()
        self.assertTrue(platform.execute.called)

    def test_deep_clean_gives_up_waiting_after_timeout(self):
        platform = self.make_platform()
        platform.execute = Mock()
        alive = [self.fake_process('MuMuVMMHeadless.exe')]
        with (
            patch.object(platform_windows.psutil, 'process_iter', return_value=alive),
            patch.object(platform_windows, 'MUMU12_DEEP_WAIT_TIMEOUT', 0),
        ):
            self.assertFalse(platform._deep_clean_mumu12('F:/mumu/shell/MuMuPlayer.exe'))

    def test_deep_clean_survives_manager_failure(self):
        """关闭全部实例失败（MuMuManager 不可用）不影响按进程名清理。

        深度重启是最后手段，不能因为其中一步失败就把整个恢复流程打断。
        """
        platform = self.make_platform()
        platform.execute = Mock(side_effect=OSError('MuMuManager missing'))
        mumu_vm = self.fake_process('MuMuVMMHeadless.exe')

        with patch.object(platform_windows.psutil, 'process_iter', side_effect=[[mumu_vm], []]):
            self.assertTrue(platform._deep_clean_mumu12('F:/mumu/shell/MuMuPlayer.exe'))

        mumu_vm.kill.assert_called_once()

    def test_deep_is_ignored_on_non_mumu12(self):
        """非 MuMu12 平台忽略 deep，行为与原来完全一致。"""
        platform = self.make_platform()
        platform.config.EmulatorInfo_Emulator = 'LDPlayer9'
        platform._clean_mumu12_residue = Mock()
        platform._deep_clean_mumu12 = Mock()

        self.assertTrue(platform.emulator_start(deep=True))

        platform._deep_clean_mumu12.assert_not_called()
        platform._clean_mumu12_residue.assert_not_called()

    def test_start_with_deep_uses_deep_clean(self):
        platform = self.make_platform()
        platform.emulator_instance = Mock()
        platform.emulator_instance.emulator.path = 'F:/mumu/shell/MuMuPlayer.exe'
        platform.emulator_instance.MuMuPlayer12_id = 0
        platform.config.EmulatorInfo_Emulator = 'MuMuPlayer12'
        platform._clean_mumu12_residue = Mock()
        platform._deep_clean_mumu12 = Mock()
        platform._mumu12_wait_stopped = Mock()

        self.assertTrue(platform.emulator_start(deep=True))

        platform._deep_clean_mumu12.assert_called_once()
        platform._clean_mumu12_residue.assert_not_called()

    def test_start_without_deep_keeps_old_cleanup(self):
        """默认仍是普通清理——深度重启必须显式开启。"""
        platform = self.make_platform()
        platform.emulator_instance = Mock()
        platform.emulator_instance.emulator.path = 'F:/mumu/shell/MuMuPlayer.exe'
        platform.emulator_instance.MuMuPlayer12_id = 0
        platform.config.EmulatorInfo_Emulator = 'MuMuPlayer12'
        platform._clean_mumu12_residue = Mock()
        platform._deep_clean_mumu12 = Mock()
        platform._mumu12_wait_stopped = Mock()

        self.assertTrue(platform.emulator_start())

        platform._clean_mumu12_residue.assert_called_once()
        platform._deep_clean_mumu12.assert_not_called()


class TestDeepFlagPortability(unittest.TestCase):
    """`deep` 必须是调用链上每一层都能接的关键字参数。

    alas.py 调的是 `Device.emulator_start`（转发层），Device 再转发给平台。
    只检查平台层会漏掉转发层——2026-09-17 正是这样漏掉了 Device 一层，
    导致 `TypeError: Device.emulator_start() got an unexpected keyword
    argument 'deep'`，模拟器被关掉后再也起不来，白挂了一晚。
    """

    def test_every_layer_of_the_call_chain_accepts_both_params(self):
        from module.device.device import Device
        from module.device.platform.platform_base import PlatformBase
        from module.device.platform.platform_mac import PlatformMac

        classes = [Device, PlatformBase, PlatformMac]
        if IS_WINDOWS:
            classes.append(PlatformWindows)
        for cls in classes:
            with self.subTest(layer=cls.__name__):
                # inspect.signature 会自动跟随 functools.wraps 的 __wrapped__
                parameters = inspect.signature(cls.emulator_start).parameters
                self.assertIn('deep', parameters)
                self.assertIs(False, parameters['deep'].default)
                self.assertIn('failures', parameters)
                self.assertEqual(0, parameters['failures'].default)


class TestDeepRestartThreshold(unittest.TestCase):
    """EmulatorManagement.DeepRestartAfterFailures 的触发判定。"""

    def make_script(self, threshold, consecutive):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.consecutive_adb_offline = consecutive
        script.config = Mock()
        script.config.EmulatorManagement_DeepRestartAfterFailures = threshold
        return script

    def test_zero_disables_deep_restart(self):
        self.assertFalse(self.make_script(0, 99)._deep_restart_enabled())

    def test_below_threshold_keeps_normal_restart(self):
        self.assertFalse(self.make_script(3, 2)._deep_restart_enabled())

    def test_at_threshold_switches_to_deep_restart(self):
        self.assertTrue(self.make_script(3, 3)._deep_restart_enabled())

    def test_stays_deep_after_threshold(self):
        self.assertTrue(self.make_script(3, 7)._deep_restart_enabled())

    def test_invalid_config_falls_back_to_normal_restart(self):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.consecutive_adb_offline = 99
        script.config = Mock()  # 读出来是 Mock，int() 会抛 TypeError
        self.assertFalse(script._deep_restart_enabled())


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器平台预算测试')
class TestRestartTimeoutBudget(unittest.TestCase):
    def test_outer_timeout_covers_the_whole_platform_budget(self):
        """外层硬超时必须 ≥ 平台层 emulator_start() 的完整预算。

        这是本次事故的核心不变量：只要外层超时短于内层预算，超时就必然发生，
        被放弃的线程会残留下来继续操作模拟器，进而与下一轮恢复互相踩踏。
        平台侧一旦新增耗时步骤（如"等实例真正关闭"），这条断言就会失败，
        提醒同步调大外层超时。
        """
        # 一次 emulator_start 的最坏耗时（取深度重启路径，它最长）：
        #   _emulator_stop(subprocess timeout=30)
        #   + 深度清场（control -v all shutdown ≤60 + 等进程退出 ≤30）
        #   + 等实例真正关闭
        #   + 启动监视（阶梯上限）
        deep_clean_budget = 60 + MUMU12_DEEP_WAIT_TIMEOUT
        platform_budget = (
            30 + deep_clean_budget + MUMU12_STOP_WAIT_TIMEOUT
            + max(EMULATOR_START_WATCH_TIMEOUTS)
        )

        self.assertGreaterEqual(RESTART_EMULATOR_OP_TIMEOUT, platform_budget)


class TestDeviceAutoStartBusyHandling(unittest.TestCase):
    """Device 初始化时撞上并发启停：要退化成"模拟器暂不可用"，不能停掉调度器。"""

    def test_busy_becomes_emulator_not_running(self):
        from module.device.device import Device

        with (
            patch('module.device.connection.Connection.__init__',
                  side_effect=EmulatorNotRunningError('offline')),
            patch.object(Device, 'emulator_start', side_effect=EmulatorOpBusy('busy')),
            patch.object(Device, 'emulator_instance', Mock()),
        ):
            # 关键：抛 EmulatorNotRunningError（调度器会安排 Restart 后继续），
            # 而不是 RequestHumanTakeover（那会把整个调度器停掉）
            with self.assertRaises(EmulatorNotRunningError):
                Device(Mock())


class TestRestartEmulatorBusyHandling(unittest.TestCase):
    def setUp(self):
        # _try_restart_emulator 在 stop 与 start 之间有固定等待，且超过阈值时
        # 有最长 300 秒的退避等待。这些测试不验证等待行为，打桩掉以免跑满分钟级。
        patcher = patch('alas.time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_script(self):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.consecutive_adb_offline = 0
        script.config = Mock()
        script.config.Error_AdbOfflineThreshold = 3
        return script

    @staticmethod
    def make_device():
        """用 autospec 而不是裸 Mock：裸 Mock 接受任意参数，会把调用方的
        参数错误（如传了实现不接受的 deep=）悄悄吞掉——2026-09-17 的事故
        正是这样漏过测试的。autospec 会按真实签名校验并抛 TypeError。

        autospec 要反射整个 Device 类，创建一次约 26 秒，因此复用同一个
        实例（每次先 reset 干净）。
        """
        global _DEVICE_AUTOSPEC
        if _DEVICE_AUTOSPEC is None:
            from module.device.device import Device

            _DEVICE_AUTOSPEC = create_autospec(Device, instance=True)
        _DEVICE_AUTOSPEC.reset_mock(return_value=True, side_effect=True)
        return _DEVICE_AUTOSPEC

    def test_gives_up_round_when_stop_is_busy(self):
        """上一轮启动仍在进行时，本轮不能去 stop——那正是打断启动的元凶。"""
        script = self.make_script()
        device = self.make_device()
        device.emulator_stop.side_effect = EmulatorOpBusy('busy')
        script.__dict__['device'] = device

        self.assertFalse(script._try_restart_emulator())
        device.emulator_start.assert_not_called()

    def test_gives_up_round_when_start_is_busy(self):
        script = self.make_script()
        device = self.make_device()
        device.emulator_start.side_effect = EmulatorOpBusy('busy')
        script.__dict__['device'] = device

        self.assertFalse(script._try_restart_emulator())
        device.emulator_stop.assert_called_once()

    def test_returns_true_and_resets_counter_when_restart_succeeds(self):
        script = self.make_script()
        script.consecutive_adb_offline = 2
        script.__dict__['device'] = self.make_device()

        self.assertTrue(script._try_restart_emulator())
        self.assertEqual(0, script.consecutive_adb_offline)

    def test_passes_deep_flag_matching_the_threshold(self):
        """未达阈值时必须以 deep=False 调用——参数名写错会在这里炸出来。"""
        script = self.make_script()
        script.consecutive_adb_offline = 1
        device = self.make_device()
        script.__dict__['device'] = device

        self.assertTrue(script._try_restart_emulator())
        self.assertIs(False, device.emulator_start.call_args.kwargs['deep'])

    def test_passes_deep_true_after_threshold(self):
        script = self.make_script()
        script.consecutive_adb_offline = 5
        script.config.EmulatorManagement_DeepRestartAfterFailures = 3
        device = self.make_device()
        script.__dict__['device'] = device

        self.assertTrue(script._try_restart_emulator())
        self.assertIs(True, device.emulator_start.call_args.kwargs['deep'])

    def test_passes_failure_count_for_the_watch_ladder(self):
        """已连续失败次数要透传给平台，否则等待时间永远停在第一档 60 秒。"""
        script = self.make_script()
        script.consecutive_adb_offline = 4  # 本次调用开头会 +1，故本次之前失败过 4 次
        device = self.make_device()
        script.__dict__['device'] = device

        self.assertTrue(script._try_restart_emulator())
        self.assertEqual(4, device.emulator_start.call_args.kwargs['failures'])


if __name__ == '__main__':
    unittest.main()
