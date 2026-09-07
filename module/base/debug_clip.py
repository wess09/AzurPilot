"""侵蚀1漏猫复盘 debug 录屏（真实游戏画面，scrcpy 设备直录，30fps 实时）。

用户要求：录“游戏真实画面”，30fps，**既不加速也不跳帧**。

scrcpy v1.20 的视频流是**不带时间戳的裸 H.264**，若直接 `-c copy` + 固定
`-r 30` 硬摊，源帧率 ≠30 时就会加速/跳帧。因此本模块不这么做，而是：

    裸 H.264 ──ffmpeg 解码──▶ rawvideo 帧 ──python 按墙钟节奏──▶ libx264 30fps mp4

- 解码子进程按“收到即解”把 H.264 变成 rawvideo；
- 我们的主线程**逐帧读取解码输出**，仅在到达 1/30s 的时间点才把该帧交给编码器
  （源高于 30fps 时自然丢帧、源低于 30fps 时用上一帧补齐），从而稳定输出
  30fps、与真实时间同步，不整体加速、不无谓跳帧。
- 整条链通过管道反压自动限速：源 30fps 时一帧不漏。

用法（由侵蚀1战后处理代码驱动）：
    clip = clip_start(self.config)    # 打完开始找事件时打开（提前几秒预录）
    ... 重扫地图 / 处理事件 / 强制移动 ...
    clip_end(keep=bool(事件已解决))    # 事件处理完、进入下一循环前结束

文件输出到 ./log/clips/，一段一个 mp4（默认全部保留、不自动清理）。
限制：ALAS 自身截图方式若正使用 scrcpy，本模块会跳过并告警（同一 abstract
socket 无法并存）。scrcpy/ffmpeg 启动失败会优雅降级为不录，不影响游戏逻辑。
"""

import os
import shutil
import socket
import struct
import subprocess
import threading
import time

from adbutils import AdbError, Network

from module.logger import logger

DEFAULT_OUTPUT_DIR = "./log/clips"
RECORD_FPS = 30
_ACTIVE = None  # 当前活动的录制会话


def _ffmpeg_path():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class _ScrcpyClip:
    """一个基于 scrcpy 设备视频流的 debug 录屏段。"""

    def __init__(self, config, fps=RECORD_FPS, width=1280, bitrate_scale=1.0):
        self.config = config
        self.fps = fps
        self.width = width
        self.bitrate_scale = bitrate_scale
        self.output_dir = DEFAULT_OUTPUT_DIR
        self.tmp_path = None
        self._core = None
        self.video_socket = None
        self.control_socket = None
        self.server_stream = None
        self.alive = False
        self.resolution = (1280, 720)
        self._dec = None  # ffmpeg: h264 -> rawvideo
        self._enc = None  # ffmpeg: rawvideo -> mp4
        self._socket_thread = None
        self._pace_thread = None
        self._stop = threading.Event()

    # ------------------------------------------------ scrcpy 视频流
    @property
    def _bitrate(self):
        # scrcpy 1.20 超过 20Mbps 会回落，保守限制在 20Mbps 内
        base = max(1, self.width * int(self.width * 9 / 16) * self.fps)
        bitrate = int(base * 0.20 * self.bitrate_scale)
        return max(300_000, min(bitrate, 20_000_000))

    def _open_scrcpy(self):
        from module.device.method.scrcpy.core import ScrcpyCore
        from module.device.method.scrcpy.options import ScrcpyOptions

        core = ScrcpyCore(self.config)
        core.adb_push(self.config.SCRCPY_FILEPATH_LOCAL, self.config.SCRCPY_FILEPATH_REMOTE)

        original_frame_rate = ScrcpyOptions.frame_rate
        try:
            ScrcpyOptions.frame_rate = self.fps
            commands = ScrcpyOptions.command_v120(jar_path=self.config.SCRCPY_FILEPATH_REMOTE)
        finally:
            ScrcpyOptions.frame_rate = original_frame_rate
        # scrcpy-server 1.20 参数位置：max_size、bitrate、max_fps
        commands[6] = str(self.width)
        commands[7] = str(self._bitrate)
        commands[8] = str(self.fps)

        server_stream = core.adb.shell(commands, stream=True)
        server_stream.conn.settimeout(3)

        ret = server_stream.read(10)
        if b"Aborted" in ret:
            raise RuntimeError("scrcpy-server 启动失败：Aborted")
        if ret == b"[server] E":
            ret += self._receive_more(server_stream)
            raise RuntimeError(ret.decode("utf-8", errors="replace"))
        ret += self._receive_more(server_stream)
        if ret:
            logger.info(f"[录屏] scrcpy-server: {ret.strip()}")

        video_socket = self._connect_scrcpy_socket(core)
        if video_socket.recv(1) != b"\x00":
            raise RuntimeError("scrcpy 视频流握手失败")
        control_socket = self._connect_scrcpy_socket(core)
        device_name = video_socket.recv(64).decode("utf-8", errors="replace").rstrip("\x00")
        if device_name:
            logger.attr("[录屏] 设备", device_name)
        resolution = video_socket.recv(4)
        if len(resolution) != 4:
            raise RuntimeError("scrcpy 未返回视频分辨率")
        self.resolution = struct.unpack(">HH", resolution)
        video_socket.settimeout(1)

        self._core = core
        self.server_stream = server_stream
        self.video_socket = video_socket
        self.control_socket = control_socket
        self.alive = True
        logger.attr("[录屏] 分辨率", self.resolution)

    @staticmethod
    def _receive_more(server_stream):
        try:
            return server_stream.conn.recv(4096)
        except Exception:
            return b""

    def _connect_scrcpy_socket(self, core):
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                sock = core.adb.create_connection(Network.LOCAL_ABSTRACT, "scrcpy")
                sock.settimeout(3)
                return sock
            except AdbError:
                time.sleep(0.1)
        raise RuntimeError("连接 scrcpy socket 超时")

    # ------------------------------------------------ 生命周期
    def start(self):
        """启动 scrcpy 流 + 解码/编码管线。成功返回 True。"""
        ffmpeg = _ffmpeg_path()
        if not ffmpeg:
            logger.warning("[录屏] 未找到 ffmpeg，录屏功能不可用")
            return False
        if str(self.config.Emulator_ScreenshotMethod).lower().startswith("scrcpy"):
            logger.warning("[录屏] 截图方式为 scrcpy，无法并存第二条视频流，本次跳过录制")
            return False
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"[录屏] 创建输出目录失败: {e}")
            return False

        try:
            self._open_scrcpy()
        except Exception as e:
            logger.warning(f"[录屏] scrcpy 启动失败，本次不录制: {e}")
            return False

        width, height = self.resolution
        raw_size = width * height * 3  # bgr24
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.tmp_path = os.path.join(self.output_dir, f"_tmp_eh1_{ts}.mp4")

        # 解码：裸 h264 -> rawvideo bgr24（收到即解，不解封包问题）
        dec_cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "h264",
            "-framerate", str(self.fps),
            "-i", "pipe:0",
            "-an",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "pipe:1",
        ]
        # 编码：rawvideo -> libx264 mp4（帧由 python 按 30fps 墙钟喂入）
        enc_cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{width}x{height}",
            "-pix_fmt", "bgr24",
            "-r", str(self.fps),
            "-i", "pipe:0",
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            self.tmp_path,
        ]
        try:
            self._dec = subprocess.Popen(
                dec_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
            self._enc = subprocess.Popen(
                enc_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
        except OSError as e:
            logger.warning(f"[录屏] 启动 ffmpeg 失败: {e}")
            self._close_scrcpy()
            return False

        self._socket_thread = threading.Thread(
            target=self._socket_to_decoder, args=(raw_size,), daemon=True
        )
        self._pace_thread = threading.Thread(
            target=self._pace_loop, args=(raw_size,), daemon=True
        )
        self._socket_thread.start()
        self._pace_thread.start()
        logger.info(f"[录屏] 开始录制（真实画面 {self.fps}fps, {width}x{height}）: {self.tmp_path}")
        return True

    def _socket_to_decoder(self, raw_size):
        """把 scrcpy 裸 H.264 喂给解码器；EOF/停止时关闭解码器输入。"""
        try:
            while not self._stop.is_set() and self.alive:
                try:
                    data = self.video_socket.recv(0x10000)
                except socket.timeout:
                    continue
                except (ConnectionError, OSError):
                    break
                if not data:
                    break
                try:
                    self._dec.stdin.write(data)
                    self._dec.stdin.flush()
                except Exception:
                    break
        finally:
            try:
                self._dec.stdin.close()
            except Exception:
                pass

    def _pace_loop(self, raw_size):
        """逐帧读解码输出，按 1/30s 墙钟把帧交给编码器（补帧/去帧保证 30fps 实时）。"""
        frame_interval = 1.0 / self.fps
        last_frame = None
        next_t = time.perf_counter()
        try:
            while True:
                data = self._read_exact(raw_size)
                if data is None:
                    break
                now = time.perf_counter()
                if not self._stop.is_set() and now < next_t:
                    # 源帧率高于目标，跳过这帧（30fps 采样）
                    continue
                last_frame = data
                if self._stop.is_set():
                    # 收尾阶段：把剩余帧快速写完，不做限速
                    pass
                else:
                    next_t = max(next_t + frame_interval, now - frame_interval)
                try:
                    self._enc.stdin.write(data)
                    self._enc.stdin.flush()
                except Exception:
                    break
        finally:
            if last_frame is not None and not self._stop.is_set():
                pass
            try:
                self._enc.stdin.close()
            except Exception:
                pass

    def _read_exact(self, size):
        """从解码器 stdout 读取一帧 rawvideo，EOF 返回 None。"""
        buf = bytearray(size)
        view = memoryview(buf)
        got = 0
        try:
            while got < size:
                n = self._dec.stdout.readinto(view[got:])
                if n is None or n <= 0:
                    if got == 0:
                        return None
                    break
                got += n
        except Exception:
            return None
        if got == 0:
            return None
        return bytes(buf[:got]) if got == size else None

    def _close_scrcpy(self):
        self.alive = False
        for obj in (self.control_socket, self.video_socket, self.server_stream):
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
        self.control_socket = None
        self.video_socket = None
        self.server_stream = None

    def finalize(self, keep):
        """结束录制，决定保留还是删除。

        Returns:
            str: 保留时返回最终 mp4 路径，丢弃或失败返回 None。
        """
        self._stop.set()
        self._close_scrcpy()
        for th in (self._socket_thread, self._pace_thread):
            if th is not None:
                th.join(timeout=6)

        for proc in (self._dec, self._enc):
            if proc is None:
                continue
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass

        if not keep or not self.tmp_path or not os.path.exists(self.tmp_path):
            if self.tmp_path and os.path.exists(self.tmp_path):
                for _ in range(3):
                    try:
                        os.remove(self.tmp_path)
                        break
                    except OSError:
                        time.sleep(0.2)
            return None

        final_name = f"eh1_clip_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        final_path = os.path.join(self.output_dir, final_name)
        try:
            os.replace(self.tmp_path, final_path)
        except OSError as e:
            logger.warning(f"[录屏] 保存视频失败: {e}")
            try:
                os.remove(self.tmp_path)
            except OSError:
                pass
            return None
        size_mb = os.path.getsize(final_path) / 1024 / 1024
        logger.info(f"[录屏] 已保存: {final_path} ({size_mb:.1f} MB)")
        return final_path


def clip_start(config, fps=RECORD_FPS):
    """打开录屏（线程安全：重复调用返回 None）。

    Args:
        config: 当前运行实例的 AzurLaneConfig（含 serial / scrcpy 路径配置）。

    Returns:
        _ScrcpyClip: 录制句柄；启动失败返回 None。
    """
    global _ACTIVE
    if _ACTIVE is not None:
        return None
    rec = _ScrcpyClip(config, fps=fps)
    if not rec.start():
        return None
    _ACTIVE = rec
    return rec


def clip_end(keep=True):
    """结束当前录屏。

    Args:
        keep (bool): 是否把该段保存为 mp4（无事件轮传 False 会自动丢弃）。

    Returns:
        str: 保留时的视频路径；无录制或已丢弃返回 None。
    """
    global _ACTIVE
    rec = _ACTIVE
    _ACTIVE = None
    if rec is None:
        return None
    return rec.finalize(keep=keep)
