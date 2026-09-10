"""验证 debug 录屏的补帧/丢帧节奏、产物校验与录像清理策略。

这些测试不依赖模拟器与真实 ffmpeg：需要子进程的地方用假对象替代，
节奏相关的测试则直接驱动工作线程，验证「源帧率低时补帧、高时丢帧」。
"""

import io
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.base import debug_clip


class _FakeProc:
    """假的 subprocess.Popen，用于验证等待/强杀逻辑。"""

    def __init__(self, exits=True):
        self.exits = exits
        self.terminated = False

    def wait(self, timeout=None):
        if self.exits:
            return 0
        raise subprocess.TimeoutExpired('cmd', timeout)

    def terminate(self):
        self.terminated = True


class _RecordingStdin:
    """记录编码器收到的每一帧，替代 ffmpeg 的 stdin。"""

    def __init__(self):
        self.frames = []
        self.closed = False

    def write(self, data):
        self.frames.append(data)
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class ClipTestCase(unittest.TestCase):
    """提供临时输出目录并隔离模块级缓存的公共基类。"""

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix='debug_clip_test_')
        self._saved_cleanup = debug_clip._LAST_CLEANUP
        # 避免测试过程中真的去扫录像目录
        debug_clip._LAST_CLEANUP = float('inf')

    def tearDown(self):
        debug_clip._LAST_CLEANUP = self._saved_cleanup
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def make_clip(self, fps=30):
        rec = debug_clip._ScrcpyClip(config=None, fps=fps)
        rec.output_dir = self.output_dir
        rec.tmp_path = os.path.join(self.output_dir, '_tmp_eh1_test.mp4')
        rec.dec_log_path = os.path.join(self.output_dir, '_tmp_eh1_test.dec.log')
        rec.enc_log_path = os.path.join(self.output_dir, '_tmp_eh1_test.enc.log')
        return rec


class TestCleanupClips(ClipTestCase):
    def touch(self, name, age_seconds, payload=b'x'):
        path = os.path.join(self.output_dir, name)
        with open(path, 'wb') as f:
            f.write(payload)
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))
        return path

    def test_retention_zero_keeps_clips_forever(self):
        old = self.touch('eh1_clip_20200101_000000.mp4', 400 * 86400)
        self.assertEqual(debug_clip.cleanup_clips(0, self.output_dir), 0)
        self.assertTrue(os.path.exists(old))

    def test_negative_retention_also_keeps_clips(self):
        old = self.touch('eh1_clip_20200101_000000.mp4', 400 * 86400)
        self.assertEqual(debug_clip.cleanup_clips(-1, self.output_dir), 0)
        self.assertTrue(os.path.exists(old))

    def test_removes_clips_older_than_retention(self):
        old = self.touch('eh1_clip_20200101_000000.mp4', 8 * 86400)
        fresh = self.touch('eh1_clip_20260909_000000.mp4', 60)
        self.assertEqual(debug_clip.cleanup_clips(7, self.output_dir), 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_removes_stale_tmp_files_even_when_retention_disabled(self):
        stale = self.touch('_tmp_eh1_20200101_000000.mp4', 2 * 3600)
        fresh = self.touch('_tmp_eh1_20260909_000000.enc.log', 60)
        self.assertEqual(debug_clip.cleanup_clips(0, self.output_dir), 1)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(fresh))

    def test_removes_meowfficer_clips_too(self):
        """短猫相接的录像用 meow_clip_ 前缀，同样要按保留天数清理。"""
        old = self.touch('meow_clip_20200101_000000.mp4', 8 * 86400)
        fresh = self.touch('meow_clip_20260909_000000.mp4', 60)
        self.assertEqual(debug_clip.cleanup_clips(7, self.output_dir), 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_removes_both_tmp_prefixes(self):
        """新前缀与历史遗留的 _tmp_eh1_ 临时文件都要清掉。"""
        legacy = self.touch('_tmp_eh1_20200101_000000.mp4', 2 * 3600)
        current = self.touch('_tmp_clip_20200101_000001.mp4', 2 * 3600)
        self.assertEqual(debug_clip.cleanup_clips(0, self.output_dir), 2)
        self.assertFalse(os.path.exists(legacy))
        self.assertFalse(os.path.exists(current))

    def test_ignores_unrelated_files(self):
        other = self.touch('readme.txt', 400 * 86400)
        self.assertEqual(debug_clip.cleanup_clips(1, self.output_dir), 0)
        self.assertTrue(os.path.exists(other))

    def test_missing_directory_is_safe(self):
        missing = os.path.join(self.output_dir, 'not_created_yet')
        self.assertEqual(debug_clip.cleanup_clips(7, missing), 0)


class TestCleanupClipsIfDue(ClipTestCase):
    def setUp(self):
        super().setUp()
        debug_clip._LAST_CLEANUP = 0.0  # 让首次调用一定执行清理

    def touch_expired_clip(self, name):
        path = os.path.join(self.output_dir, name)
        with open(path, 'wb') as f:
            f.write(b'x')
        mtime = time.time() - 3 * 86400
        os.utime(path, (mtime, mtime))
        return path

    def test_uses_configured_retention_days(self):
        self.touch_expired_clip('eh1_clip_20200101_000000.mp4')
        config = SimpleNamespace(OpsiGeneral_DebugClipRetentionDays=1)
        self.assertEqual(debug_clip.cleanup_clips_if_due(config, self.output_dir), 1)

    def test_second_call_is_throttled(self):
        self.touch_expired_clip('eh1_clip_20200101_000000.mp4')
        config = SimpleNamespace(OpsiGeneral_DebugClipRetentionDays=1)
        self.assertEqual(debug_clip.cleanup_clips_if_due(config, self.output_dir), 1)
        self.touch_expired_clip('eh1_clip_20200102_000000.mp4')
        # 节流期内不再扫描，文件仍然留着
        self.assertEqual(debug_clip.cleanup_clips_if_due(config, self.output_dir), 0)
        self.assertEqual(len(os.listdir(self.output_dir)), 1)

    def test_missing_setting_keeps_everything(self):
        kept = self.touch_expired_clip('eh1_clip_20200101_000000.mp4')
        self.assertEqual(debug_clip.cleanup_clips_if_due(SimpleNamespace(), self.output_dir), 0)
        self.assertTrue(os.path.exists(kept))

    def test_invalid_setting_is_ignored(self):
        kept = self.touch_expired_clip('eh1_clip_20200101_000000.mp4')
        config = SimpleNamespace(OpsiGeneral_DebugClipRetentionDays='abc')
        self.assertEqual(debug_clip.cleanup_clips_if_due(config, self.output_dir), 0)
        self.assertTrue(os.path.exists(kept))


class TestEvenSize(unittest.TestCase):
    def test_even_resolution_unchanged(self):
        self.assertEqual(debug_clip._even_size(1280, 720), (1280, 720))

    def test_odd_edges_rounded_down(self):
        self.assertEqual(debug_clip._even_size(1281, 721), (1280, 720))

    def test_single_odd_edge(self):
        self.assertEqual(debug_clip._even_size(1280, 721), (1280, 720))


class TestFfmpegProbe(unittest.TestCase):
    def setUp(self):
        self._saved = debug_clip._FFMPEG_CACHE
        debug_clip._FFMPEG_CACHE = None

    def tearDown(self):
        debug_clip._FFMPEG_CACHE = self._saved

    def test_rejects_unusable_binary(self):
        self.assertFalse(debug_clip._ffmpeg_works('/definitely/not/a/real/ffmpeg'))
        self.assertFalse(debug_clip._ffmpeg_works(None))
        self.assertFalse(debug_clip._ffmpeg_works(''))

    def test_returns_first_working_candidate(self):
        with patch.object(
            debug_clip, '_ffmpeg_works', side_effect=lambda exe: exe == '/fake/ffmpeg'
        ), patch.object(debug_clip.shutil, 'which', return_value='/fake/ffmpeg'):
            self.assertEqual(debug_clip._ffmpeg_path(), '/fake/ffmpeg')

    def test_returns_none_when_nothing_works(self):
        with patch.object(debug_clip, '_ffmpeg_works', return_value=False), \
                patch.object(debug_clip.shutil, 'which', return_value=None):
            self.assertIsNone(debug_clip._ffmpeg_path())

    def test_probe_result_is_cached(self):
        with patch.object(
            debug_clip, '_ffmpeg_works', side_effect=lambda exe: exe == '/fake/ffmpeg'
        ) as works, patch.object(debug_clip.shutil, 'which', return_value='/fake/ffmpeg'):
            debug_clip._ffmpeg_path()
            first_calls = works.call_count
            debug_clip._ffmpeg_path()
            # 第二次走缓存，不再重复探测子进程
            self.assertEqual(works.call_count, first_calls)


class TestWaitProc(unittest.TestCase):
    def test_normal_exit(self):
        proc = _FakeProc(exits=True)
        self.assertTrue(debug_clip._ScrcpyClip._wait_proc(proc, 1))
        self.assertFalse(proc.terminated)

    def test_timeout_kills_and_reports_failure(self):
        proc = _FakeProc(exits=False)
        self.assertFalse(debug_clip._ScrcpyClip._wait_proc(proc, 0.01))
        self.assertTrue(proc.terminated)

    def test_none_is_ok(self):
        self.assertTrue(debug_clip._ScrcpyClip._wait_proc(None, 1))


class TestReadExact(ClipTestCase):
    def make_reader(self, payload):
        rec = self.make_clip()
        rec._dec = SimpleNamespace(stdout=io.BytesIO(payload))
        return rec

    def test_returns_complete_frame(self):
        rec = self.make_reader(b'a' * 32)
        self.assertEqual(rec._read_exact(32), b'a' * 32)
        self.assertIsNone(rec._error)

    def test_eof_returns_none_without_error(self):
        rec = self.make_reader(b'')
        self.assertIsNone(rec._read_exact(32))
        self.assertIsNone(rec._error)

    def test_partial_frame_returns_none_and_records_reason(self):
        rec = self.make_reader(b'a' * 10)
        self.assertIsNone(rec._read_exact(32))
        self.assertIn('帧中途结束', rec._error)

    def test_keeps_first_error_only(self):
        rec = self.make_reader(b'a' * 10)
        rec._read_exact(32)
        first = rec._error
        rec._set_error('后面的错误')
        self.assertEqual(rec._error, first)


class TestKeepRecord(ClipTestCase):
    def write_tmp(self, payload):
        with open(self.tmp_path, 'wb') as f:
            f.write(payload)

    def setUp(self):
        super().setUp()
        self.rec = self.make_clip()
        self.tmp_path = self.rec.tmp_path

    def test_zero_frames_is_rejected(self):
        self.write_tmp(b'x' * 8000)
        self.rec._frames_written = 0
        self.assertIsNone(self.rec._keep_record(True, 10.0))

    def test_missing_output_file_is_rejected(self):
        self.rec._frames_written = 300
        self.assertIsNone(self.rec._keep_record(True, 10.0))

    def test_tiny_file_is_rejected(self):
        self.write_tmp(b'x' * 100)
        self.rec._frames_written = 300
        self.assertIsNone(self.rec._keep_record(True, 10.0))

    def test_killed_encoder_is_rejected(self):
        self.write_tmp(b'x' * 8000)
        self.rec._frames_written = 300
        self.assertIsNone(self.rec._keep_record(False, 10.0))

    def test_valid_record_is_saved(self):
        self.write_tmp(b'x' * 8000)
        self.rec._frames_written = 300
        path = self.rec._keep_record(True, 10.0)
        self.assertIsNotNone(path)
        self.assertTrue(os.path.basename(path).startswith(debug_clip.CLIP_PREFIX_EH1))
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(self.tmp_path))

    def test_custom_prefix_is_used_for_output_name(self):
        """短猫相接的录像要带自己的前缀，方便和侵蚀一的区分开。"""
        rec = self.make_clip()
        rec.prefix = debug_clip.CLIP_PREFIX_MEOW
        with open(rec.tmp_path, 'wb') as f:
            f.write(b'x' * 8000)
        rec._frames_written = 300
        path = rec._keep_record(True, 10.0)
        self.assertIsNotNone(path)
        self.assertTrue(os.path.basename(path).startswith(debug_clip.CLIP_PREFIX_MEOW))


class TestFinalizeIsSafe(ClipTestCase):
    def test_finalize_never_raises_on_broken_internals(self):
        rec = self.make_clip()
        rec._dec = object()  # 故意塞一个没有 stdin / wait 的对象
        rec._enc = object()
        self.assertIsNone(rec.finalize(keep=False))
        self.assertIsNone(rec.finalize(keep=True))

    def test_finalize_discards_tmp_when_not_kept(self):
        rec = self.make_clip()
        with open(rec.tmp_path, 'wb') as f:
            f.write(b'x' * 8000)
        rec._frames_written = 300
        self.assertIsNone(rec.finalize(keep=False))
        self.assertFalse(os.path.exists(rec.tmp_path))

    def test_finalize_discards_invalid_artifact(self):
        """产物无效（这里模拟 0 帧）时不能留下文件，更不能谎报已保存。"""
        rec = self.make_clip()
        with open(rec.tmp_path, 'wb') as f:
            f.write(b'x' * 8000)
        rec._frames_written = 0
        self.assertIsNone(rec.finalize(keep=True))
        self.assertFalse(os.path.exists(rec.tmp_path))

    def test_finalize_leaves_only_the_mp4_on_success(self):
        """录像成功后目录里只能留下 mp4：ffmpeg 的 stderr 日志必须一并清掉。"""
        rec = self.make_clip()
        with open(rec.tmp_path, 'wb') as f:
            f.write(b'x' * 8000)
        for log_path in (rec.dec_log_path, rec.enc_log_path):
            with open(log_path, 'wb') as f:
                f.write(b'ffmpeg noise')
        rec._frames_written = 300

        path = rec.finalize(keep=True)

        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        for leftover in (rec.tmp_path, rec.dec_log_path, rec.enc_log_path):
            self.assertFalse(os.path.exists(leftover), leftover)


class TestPaceLoop(ClipTestCase):
    """验证核心节奏：源帧率低时补帧、高时丢帧，输出时长贴近真实时间。"""

    def start_pace(self, fps=30):
        rec = self.make_clip(fps=fps)
        rec._enc = SimpleNamespace(stdin=_RecordingStdin())
        thread = threading.Thread(target=rec._pace_loop, daemon=True)
        thread.start()
        return rec, thread

    def stop_pace(self, rec, thread):
        rec._stop.set()
        thread.join(timeout=3)
        return rec._enc.stdin

    def test_slow_source_is_padded(self):
        """源 10fps 持续 0.6 秒：应补帧到约 18 帧，而不是只写 6 帧。"""
        rec, thread = self.start_pace(fps=30)
        fed = 0
        try:
            for i in range(6):
                try:
                    rec._frames.put_nowait(b'frame-%d' % i)
                except queue.Full:
                    pass
                fed += 1
                time.sleep(0.1)
        finally:
            stdin = self.stop_pace(rec, thread)

        self.assertEqual(fed, 6)
        # 补帧后写入数应远多于源帧数（旧实现只写 6 帧，会导致视频被压缩成 1/3 时长）
        self.assertGreater(len(stdin.frames), 10)
        self.assertTrue(stdin.closed)

    def test_fast_source_is_thinned(self):
        """源 200fps：写入数应受 30fps 节流限制，不能把 60 帧全写进去。"""
        rec, thread = self.start_pace(fps=30)
        try:
            for i in range(60):
                try:
                    rec._frames.put_nowait(b'frame-%d' % i)
                except queue.Full:
                    pass
            time.sleep(0.3)
        finally:
            stdin = self.stop_pace(rec, thread)

        self.assertGreater(len(stdin.frames), 0)
        # 0.3 秒最多约 9~10 帧（30fps），远少于投喂的 60 帧
        self.assertLess(len(stdin.frames), 30)

    def test_written_frames_come_from_source(self):
        """补帧只能复用真实帧，不得写入空帧或垃圾数据。"""
        rec, thread = self.start_pace(fps=30)
        try:
            source = {b'frame-%d' % i for i in range(5)}
            for frame in source:
                try:
                    rec._frames.put_nowait(frame)
                except queue.Full:
                    pass
                time.sleep(0.05)
        finally:
            stdin = self.stop_pace(rec, thread)

        self.assertGreater(len(stdin.frames), 0)
        self.assertTrue(set(stdin.frames).issubset(source))


class TestDrainDecoder(ClipTestCase):
    """收尾时必须把解码器压着的帧补完，否则每段录像都会短一截。"""

    def make_drain_clip(self):
        rec = self.make_clip()
        rec._enc = SimpleNamespace(stdin=_RecordingStdin())
        rec._frames = queue.Queue()  # 放宽容量，方便一次塞入多帧
        return rec

    def test_drains_buffered_frames_until_decoder_done(self):
        rec = self.make_drain_clip()
        for i in range(5):
            rec._frames.put_nowait(b'frame-%d' % i)
        rec._decoder_done.set()
        rec._drain_decoder()
        self.assertEqual(len(rec._enc.stdin.frames), 5)
        self.assertEqual(rec._frames_written, 5)

    def test_stops_at_deadline_when_decoder_never_finishes(self):
        rec = self.make_drain_clip()
        rec._decode_thread = object()  # 让「没有解码线程」的短路不生效
        rec._drain_deadline = time.perf_counter() - 1  # 已经过期
        rec._frames.put_nowait(b'frame-0')
        rec._drain_decoder()
        self.assertEqual(len(rec._enc.stdin.frames), 1)
        self.assertIn('结尾可能缺失', rec._error)

    def test_returns_immediately_without_decode_thread(self):
        rec = self.make_drain_clip()
        rec._drain_deadline = float('inf')
        started = time.perf_counter()
        rec._drain_decoder()
        self.assertLess(time.perf_counter() - started, 0.5)


class TestClipSession(unittest.TestCase):
    def setUp(self):
        self._saved = debug_clip._ACTIVE
        debug_clip._ACTIVE = None

    def tearDown(self):
        debug_clip._ACTIVE = self._saved

    def test_stale_session_is_finalized_before_restart(self):
        stale = SimpleNamespace(finalize=lambda keep: '/stale.mp4')
        debug_clip._ACTIVE = stale
        with patch.object(debug_clip, '_ScrcpyClip') as clip_cls:
            clip_cls.return_value.start.return_value = False
            self.assertIsNone(debug_clip.clip_start(config=None))
        # 旧会话被收尾、_ACTIVE 被清空，不会永久泄漏导致之后再也录不了
        self.assertIsNone(debug_clip._ACTIVE)

    def test_clip_end_clears_active_even_if_finalize_raises(self):
        def boom(keep):
            raise RuntimeError('finalize exploded')

        debug_clip._ACTIVE = SimpleNamespace(finalize=boom)
        self.assertIsNone(debug_clip.clip_end(keep=True))
        self.assertIsNone(debug_clip._ACTIVE)

    def test_clip_end_without_session_returns_none(self):
        self.assertIsNone(debug_clip.clip_end(keep=True))


class TestClipRecordingContext(unittest.TestCase):
    """clip_recording 是各任务接入录像的统一入口（短猫相接有 4 处调用）。"""

    def test_disabled_does_not_start_or_save(self):
        with patch.object(debug_clip, 'clip_start') as start, \
                patch.object(debug_clip, 'clip_end') as end:
            with debug_clip.clip_recording(config='cfg', enabled=False) as clip:
                self.assertIsNone(clip)
        start.assert_not_called()
        end.assert_not_called()

    def test_enabled_starts_with_prefix_and_saves(self):
        handle = object()
        with patch.object(debug_clip, 'clip_start', return_value=handle) as start, \
                patch.object(debug_clip, 'clip_end') as end:
            with debug_clip.clip_recording(
                config='cfg', enabled=True, prefix=debug_clip.CLIP_PREFIX_MEOW
            ) as clip:
                self.assertIs(clip, handle)
        start.assert_called_once_with('cfg', prefix=debug_clip.CLIP_PREFIX_MEOW)
        end.assert_called_once_with(keep=True)

    def test_saves_even_when_body_raises(self):
        with patch.object(debug_clip, 'clip_start', return_value=object()), \
                patch.object(debug_clip, 'clip_end') as end:
            with self.assertRaises(ValueError):
                with debug_clip.clip_recording(config='cfg', enabled=True):
                    raise ValueError('boom')
        end.assert_called_once_with(keep=True)

    def test_start_failure_is_not_fatal(self):
        """scrcpy/ffmpeg 起不来时录像优雅降级，不影响任务本身。"""
        with patch.object(debug_clip, 'clip_start', return_value=None), \
                patch.object(debug_clip, 'clip_end') as end:
            with debug_clip.clip_recording(config='cfg', enabled=True) as clip:
                self.assertIsNone(clip)
        end.assert_not_called()


class TestMeowfficerClipWiring(unittest.TestCase):
    """短猫相接的录像上下文必须读对配置键、用对自己的文件名前缀。"""

    def make_fake_task(self, enabled):
        from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming

        fake = SimpleNamespace(
            config=SimpleNamespace(OpsiMeowfficerFarming_DebugClip=enabled)
        )
        return OpsiMeowfficerFarming._meow_debug_clip(fake)

    def test_disabled_switch_yields_no_clip(self):
        with self.make_fake_task(False) as clip:
            self.assertIsNone(clip)

    def test_enabled_switch_starts_clip_with_meow_prefix(self):
        handle = object()
        with patch.object(debug_clip, 'clip_start', return_value=handle) as start, \
                patch.object(debug_clip, 'clip_end') as end:
            with self.make_fake_task(True) as clip:
                self.assertIs(clip, handle)
        self.assertEqual(start.call_args.kwargs['prefix'], debug_clip.CLIP_PREFIX_MEOW)
        end.assert_called_once_with(keep=True)


if __name__ == '__main__':
    unittest.main()
