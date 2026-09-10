"""大世界战后 debug 录屏（真实游戏画面，scrcpy 设备直录，30fps 实时）。

当前由侵蚀1练级与短猫相接两个任务使用，各自有独立的开关，共用同一套录制实现
和同一份保留天数设置。

用户要求：录「游戏真实画面」，30fps，**既不加速也不跳帧**。

scrcpy v1.20 的视频流是**不带时间戳的裸 H.264**，直接 `-c copy` + 固定 `-r 30`
会在源帧率 ≠30 时加速或跳帧。因此本模块采用「解码 → 定时补帧 → 编码」三段式：

    裸 H.264 ──ffmpeg 解码──▶ rawvideo 帧 ──按 1/30s 墙钟投喂──▶ libx264 30fps mp4

三个线程各司其职：

- `_socket_to_decoder`：把 scrcpy 的 H.264 字节流喂给解码器；
- `_decode_loop`：把解码出的 rawvideo 帧塞进「只留最新一帧」的队列；
- `_pace_loop`：每 1/30s 醒来一次，队列里有新帧就用新帧，没有就**复用上一帧**。

由此得到两条保证：源帧率高于 30fps 时自动丢帧（取到的总是最新帧），源帧率低于
30fps 时自动补帧（复用上一帧）。播放速度因此恒等于真实速度——scrcpy 只在屏幕内容
变化时产帧，游戏加载/静止期间帧率会掉到很低，补帧是「不加速」的关键。早期版本
缺了这一步，低帧率片段会被压缩成原时长的 1/N。

关于总时长：ffmpeg 的 H.264 解码器有固定的起播预读（实测约 19 帧，probesize /
analyzeduration / threads 都压不下去），这段帧要等收到 EOF 才会吐出来。因此
`_pace_loop` 退出前会先 `_drain_decoder()` 把它们补进结尾。即便如此，视频仍会比
真实时间短「预读帧数 ÷ 源帧率」秒：源 30fps 时约 0.6 秒（6%），60fps 时约 0.3 秒。
源帧率越低这段越长（5fps 时可达 4 秒），但 scrcpy 在实战画面下不会掉到那么低。
偏差超过 20% 时 `_keep_record` 会打 warning，不会静默。

用法（由各任务的战后处理代码驱动，推荐用上下文管理器）：

    with clip_recording(self.config, self.config.OpsiMeowfficerFarming_DebugClip,
                        prefix=CLIP_PREFIX_MEOW):
        ... 重扫地图 / 处理事件 / 强制移动 ...

进入 with 时开录，退出时（含异常路径）保存。每一轮都保留，不管这一轮有没有
遇到事件，方便逐轮回看实际过程。也可手动 `clip_start()` / `clip_end(keep=...)`
控制得更细，`keep=False` 用于调用方确实想丢弃某一段的场景。

文件输出到 `./log/clips/`，一段一个 mp4，文件名前缀区分任务
（`eh1_clip_*` = 侵蚀1、`meow_clip_*` = 短猫相接），按 `OpsiGeneral` 里的
`DebugClipRetentionDays` 保留天数自动清理（0 表示永久保留）。产物无效时
**不会**留下文件，也不会谎报「已保存」。

文件输出到 `./log/clips/`，一段一个 mp4，按 `DebugClipRetentionDays` 保留天数自动
清理（0 表示永久保留）。产物无效时**不会**留下文件，也不会谎报「已保存」。

限制：ALAS 自身截图方式若正使用 scrcpy，本模块会跳过并告警（同一 abstract
socket 无法并存）。scrcpy/ffmpeg 启动失败会优雅降级为不录，不影响游戏逻辑。
"""

import contextlib
import os
import queue
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
# 录像文件名前缀，用于区分是哪个任务录的
CLIP_PREFIX_EH1 = "eh1_clip_"  # 侵蚀1练级
CLIP_PREFIX_MEOW = "meow_clip_"  # 短猫相接（耄耋相接）
CLIP_PREFIXES = (CLIP_PREFIX_EH1, CLIP_PREFIX_MEOW)
# 录制中途的临时文件前缀；保留旧前缀以便清理历史残留
TMP_PREFIX = "_tmp_clip_"
TMP_PREFIXES = (TMP_PREFIX, "_tmp_eh1_")
# 产物小于此字节数视为无效（正常 720p 首帧就在 10KB 以上）
MIN_VALID_BYTES = 4096
# 编码落后超过该秒数就不再追赶，直接重新对齐（否则会陷入无休止追赶）
MAX_LAG = 1.0
# 收尾时等待解码器吐出剩余帧的上限（秒）。ffmpeg 解码器有固定的起播缓冲，
# 通常十几帧；超过这个时间就放弃，避免卡住游戏主流程。
DRAIN_TIMEOUT = 5.0
# 线程退出 / 子进程退出的等待上限（秒）
JOIN_TIMEOUT = 8
DECODER_EXIT_TIMEOUT = 5
# 编码器要写完 moov atom 才能得到可播放的 mp4，给的时间要宽裕
ENCODER_EXIT_TIMEOUT = 15
# 残留临时文件的保留秒数（进程被强杀时留下的）
TMP_MAX_AGE = 3600
# 清理节流：两次扫描目录至少间隔这么久
CLEANUP_INTERVAL = 3600

_ACTIVE = None  # 当前活动的录制会话
_FFMPEG_CACHE = None  # ffmpeg 探测结果缓存，None 表示尚未探测
_LAST_CLEANUP = 0.0  # 上次清理录像目录的时间戳


def _ffmpeg_works(exe):
    """校验 ffmpeg 可执行且能跑起来。

    仅用 shutil.which 找到路径并不能说明它可用（可能是残缺文件或缺 DLL），
    这里实跑一次 -version 确认。

    Args:
        exe (str): 候选可执行文件路径。

    Returns:
        bool: 可用返回 True。
    """
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and b"ffmpeg" in proc.stdout.lower()


def _ffmpeg_path():
    """按 环境变量 → imageio-ffmpeg 自带 → 系统 PATH 的顺序找可用的 ffmpeg。

    结果会缓存，避免每段录像都跑一次探测子进程。

    Returns:
        str: ffmpeg 可执行文件路径；都不可用时返回 None。
    """
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE is not None:
        return _FFMPEG_CACHE or None

    candidates = []
    env_exe = os.getenv("IMAGEIO_FFMPEG_EXE")
    if env_exe:
        candidates.append(env_exe)
    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        # 依赖缺失或未安装，继续尝试系统 ffmpeg
        pass
    candidates.append(shutil.which("ffmpeg"))

    for exe in candidates:
        if _ffmpeg_works(exe):
            _FFMPEG_CACHE = exe
            return exe

    _FFMPEG_CACHE = ""
    return None


def _even_size(width, height):
    """把分辨率向下取偶。

    H.264 的 yuv420p 要求宽高均为偶数，否则 libx264 直接报错、产出 0 字节文件。

    Args:
        width (int): 原始宽度。
        height (int): 原始高度。

    Returns:
        tuple: (偶数宽度, 偶数高度)。
    """
    return width - width % 2, height - height % 2


def cleanup_clips(retention_days, output_dir=DEFAULT_OUTPUT_DIR):
    """清理录像目录。

    规则：
    - `eh1_clip_*.mp4` / `meow_clip_*.mp4`：修改时间超过 retention_days 天的删除；
      retention_days <= 0 表示永久保留。
    - `_tmp_clip_*` / `_tmp_eh1_*`：录制中途被中断留下的临时文件/日志，
      超过 TMP_MAX_AGE 即删除。
    - 其它文件一律不动。

    Args:
        retention_days (int): 录像保留天数，小于等于 0 表示永久保留。
        output_dir (str): 录像目录。

    Returns:
        int: 实际删除的文件数。
    """
    try:
        names = os.listdir(output_dir)
    except OSError:
        return 0

    now = time.time()
    removed = 0
    for name in names:
        path = os.path.join(output_dir, name)
        try:
            if not os.path.isfile(path):
                continue
            mtime = os.path.getmtime(path)
        except OSError:
            continue

        if name.startswith(TMP_PREFIXES):
            deadline = TMP_MAX_AGE
        elif name.startswith(CLIP_PREFIXES) and name.endswith(".mp4"):
            if retention_days <= 0:
                continue
            deadline = retention_days * 86400
        else:
            continue

        if now - mtime < deadline:
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            # 文件被占用/权限不足时跳过，下次清理再试
            pass

    if removed:
        if retention_days <= 0:
            keep_desc = "录像永久保留"
        else:
            keep_desc = f"录像保留 {retention_days} 天"
        logger.info(f"[录屏] 已清理 {removed} 个过期录像/临时文件（{keep_desc}）")
    return removed


def cleanup_clips_if_due(config, output_dir=DEFAULT_OUTPUT_DIR):
    """按配置清理过期录像（带节流，不必每轮战斗都真的扫目录）。

    保留天数取自「大世界通用设置」的 DebugClipRetentionDays，侵蚀一与短猫相接共用。
    任何 Opsi 任务都会自动绑定 OpsiGeneral，所以这里可以直接读属性。

    Args:
        config: 当前运行实例的 AzurLaneConfig。
        output_dir (str): 录像目录。

    Returns:
        int: 本次实际删除的文件数；未到清理时间返回 0。
    """
    global _LAST_CLEANUP
    now = time.time()
    if now - _LAST_CLEANUP < CLEANUP_INTERVAL:
        return 0
    _LAST_CLEANUP = now

    # 配置缺失时按「永久保留」处理：删除是不可逆操作，默认不删任何东西
    days = getattr(config, "OpsiGeneral_DebugClipRetentionDays", 0)
    try:
        days = int(days)
    except (TypeError, ValueError):
        logger.warning(f"[录屏] 录像保留天数配置无效: {days!r}，本次跳过清理")
        return 0
    return cleanup_clips(days, output_dir)


class _ScrcpyClip:
    """一个基于 scrcpy 设备视频流的 debug 录屏段。"""

    def __init__(self, config, fps=RECORD_FPS, prefix=CLIP_PREFIX_EH1,
                 width=1280, bitrate_scale=1.0):
        self.config = config
        self.fps = fps
        self.prefix = prefix
        self.width = width
        self.bitrate_scale = bitrate_scale
        self.output_dir = DEFAULT_OUTPUT_DIR
        self.tmp_path = None
        self.dec_log_path = None
        self.enc_log_path = None
        self._core = None
        self.video_socket = None
        self.control_socket = None
        self.server_stream = None
        self.alive = False
        self.resolution = (1280, 720)
        self.frame_size = 1280 * 720 * 3  # 单帧 bgr24 字节数
        self._dec = None  # ffmpeg: h264 -> rawvideo
        self._enc = None  # ffmpeg: rawvideo -> mp4
        self._dec_log = None
        self._enc_log = None
        self._socket_thread = None
        self._decode_thread = None
        self._pace_thread = None
        self._frames = queue.Queue(maxsize=1)  # 解码线程 -> 节流线程，只留最新帧
        self._decoder_done = threading.Event()
        self._stop = threading.Event()
        self._started_at = None
        self._stopped_at = None
        self._drain_deadline = float('inf')  # 收尾排空的截止时刻，finalize 里设置
        self._error = None  # 首个致命错误，仅用于诊断
        self._frames_decoded = 0
        self._frames_written = 0
        self._lags = 0

    # ------------------------------------------------ scrcpy 视频流
    @property
    def _bitrate(self):
        # scrcpy 1.20 超过 20Mbps 会回落，保守限制在 20Mbps 内
        base = max(1, self.width * int(self.width * 9 / 16) * self.fps)
        bitrate = int(base * 0.20 * self.bitrate_scale)
        return max(300_000, min(bitrate, 20_000_000))

    def _open_scrcpy(self):
        """启动 scrcpy-server 并完成握手。

        Raises:
            Exception: 任意环节失败。失败时已建立的 socket / server 进程会被
                `_close_scrcpy` 回收（调用方负责），不会泄漏到设备上。
        """
        from module.device.method.scrcpy.core import ScrcpyCore
        from module.device.method.scrcpy.options import ScrcpyOptions

        core = ScrcpyCore(self.config)
        self._core = core
        core.adb_push(self.config.SCRCPY_FILEPATH_LOCAL, self.config.SCRCPY_FILEPATH_REMOTE)

        # 显式把帧率传进去，不再临时改写 ScrcpyOptions.frame_rate 这个全局类属性
        commands = ScrcpyOptions.command_v120(
            jar_path=self.config.SCRCPY_FILEPATH_REMOTE, frame_rate=self.fps
        )
        # scrcpy-server 1.20 参数位置：max_size、bitrate、max_fps
        commands[6] = str(self.width)
        commands[7] = str(self._bitrate)
        commands[8] = str(self.fps)

        server_stream = core.adb.shell(commands, stream=True)
        self.server_stream = server_stream
        server_stream.conn.settimeout(3)

        ret = server_stream.read(10)
        if b"Aborted" in ret:
            raise RuntimeError("scrcpy-server 启动失败：Aborted")
        if ret == b"[server] E":
            ret += self._receive_more(server_stream)
            raise RuntimeError(ret.decode("utf-8", errors="replace"))
        ret += self._receive_more(server_stream)
        if ret:
            logger.info(f"[录屏] scrcpy-server: {ret.decode('utf-8', errors='replace').strip()}")

        # 握手顺序：video socket -> control socket -> 1 字节占位 -> 64 字节设备名 -> 4 字节分辨率
        self.video_socket = self._connect_scrcpy_socket(core)
        if self._recv_exact(self.video_socket, 1) != b"\x00":
            raise RuntimeError("scrcpy 视频流握手失败")
        self.control_socket = self._connect_scrcpy_socket(core)
        device_name = self._recv_exact(self.video_socket, 64).decode(
            "utf-8", errors="replace"
        ).rstrip("\x00")
        if device_name:
            logger.attr("[录屏] 设备", device_name)
        resolution = self._recv_exact(self.video_socket, 4)
        self.resolution = struct.unpack(">HH", resolution)
        self.video_socket.settimeout(1)

        if self.resolution[0] <= 0 or self.resolution[1] <= 0:
            raise RuntimeError(f"scrcpy 返回了非法分辨率: {self.resolution}")

        self.alive = True
        logger.attr("[录屏] 分辨率", self.resolution)

    @staticmethod
    def _recv_exact(sock, size):
        """从 socket 上读满 size 字节。

        socket.recv(n) 只保证「最多 n 字节」，小端数据也可能被拆包，必须循环读满。

        Args:
            sock (socket.socket): 已连接的 socket。
            size (int): 需要读取的字节数。

        Returns:
            bytes: 长度恰好为 size 的数据。

        Raises:
            RuntimeError: 连接在读满之前关闭。
        """
        buf = bytearray()
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                raise RuntimeError(
                    f"scrcpy 握手期间连接中断（{len(buf)}/{size} 字节）"
                )
            buf += chunk
        return bytes(buf)

    @staticmethod
    def _receive_more(server_stream, timeout=0.5):
        """尽力读取 scrcpy-server 的启动日志（仅用于诊断，读不到不算失败）。

        Args:
            server_stream: adb shell 流。
            timeout (float): 单次读取的最长等待。旧实现硬编码 3 秒，服务器没有更多
                输出时会让每次开录白白多等 3 秒。

        Returns:
            bytes: 读到的内容，没有则返回 b""。
        """
        try:
            old_timeout = server_stream.conn.gettimeout()
            server_stream.conn.settimeout(timeout)
            try:
                return server_stream.conn.recv(4096)
            finally:
                server_stream.conn.settimeout(old_timeout)
        except Exception:
            return b""

    def _connect_scrcpy_socket(self, core):
        """连接 scrcpy 的 abstract socket（video / control 各一条）。

        Args:
            core (ScrcpyCore): scrcpy 核心对象。

        Returns:
            socket.socket: 已连接的 socket。

        Raises:
            RuntimeError: 3 秒内连不上。
        """
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
        """启动 scrcpy 流 + 解码/编码管线。

        Returns:
            bool: 成功返回 True；失败会记录具体原因并返回 False（不影响游戏逻辑）。
        """
        ffmpeg = _ffmpeg_path()
        if not ffmpeg:
            logger.error(
                "[录屏] 未找到可用的 ffmpeg，debug 录屏无法工作。"
                "请执行 `uv sync` 安装 imageio-ffmpeg，或自行安装 ffmpeg 并加入 PATH"
            )
            return False
        if str(self.config.Emulator_ScreenshotMethod).lower().startswith("scrcpy"):
            logger.warning("[录屏] 截图方式为 scrcpy，无法并存第二条视频流，本次跳过录制")
            return False
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"[录屏] 创建输出目录失败: {e}")
            return False

        try:
            self._open_scrcpy()
        except Exception as e:
            self._close_scrcpy()
            logger.error(f"[录屏] scrcpy 启动失败，本次不录制: {e}")
            return False

        raw_width, raw_height = self.resolution
        enc_width, enc_height = _even_size(raw_width, raw_height)
        if (enc_width, enc_height) != (raw_width, raw_height):
            logger.warning(
                f"[录屏] 设备分辨率 {raw_width}x{raw_height} 含奇数边，"
                f"H.264 要求宽高为偶数，编码时裁剪为 {enc_width}x{enc_height}"
            )
        self.frame_size = raw_width * raw_height * 3  # bgr24

        ts = time.strftime("%Y%m%d_%H%M%S")
        self.tmp_path = os.path.join(self.output_dir, f"{TMP_PREFIX}{ts}.mp4")
        self.dec_log_path = os.path.join(self.output_dir, f"{TMP_PREFIX}{ts}.dec.log")
        self.enc_log_path = os.path.join(self.output_dir, f"{TMP_PREFIX}{ts}.enc.log")

        # 解码：裸 h264 -> rawvideo bgr24（收到即解，不解封包问题）
        # probesize/analyzeduration 用最小值：默认的 5 秒分析缓冲会让解码器起播时
        # 压住十几帧不吐，导致每段录像的开头几秒丢失。
        dec_cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-f", "h264",
            "-framerate", str(self.fps),
            "-i", "pipe:0",
            "-an",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "pipe:1",
        ]
        # 编码：rawvideo -> libx264 mp4（帧由 python 按 1/fps 墙钟投喂）
        enc_cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{raw_width}x{raw_height}",
            "-pix_fmt", "bgr24",
            "-r", str(self.fps),
            "-i", "pipe:0",
            "-an",
        ]
        if (enc_width, enc_height) != (raw_width, raw_height):
            enc_cmd += ["-vf", f"crop={enc_width}:{enc_height}:0:0"]
        enc_cmd += [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            self.tmp_path,
        ]

        # ffmpeg 的 stderr 落盘而不是 DEVNULL：既不会像管道那样写满阻塞，
        # 又能在失败时把真实原因报给用户。
        try:
            self._dec_log = open(self.dec_log_path, "wb")
            self._enc_log = open(self.enc_log_path, "wb")
            self._dec = subprocess.Popen(
                dec_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._dec_log, bufsize=0,
            )
            self._enc = subprocess.Popen(
                enc_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self._enc_log, bufsize=0,
            )
        except OSError as e:
            logger.error(f"[录屏] 启动 ffmpeg 失败: {e}")
            self._close_pipe(self._dec, "stdin")
            self._wait_proc(self._dec, DECODER_EXIT_TIMEOUT)
            self._close_log_files()
            self._close_scrcpy()
            self._discard()
            return False

        self._started_at = time.perf_counter()
        self._socket_thread = threading.Thread(
            target=self._socket_to_decoder, daemon=True
        )
        self._decode_thread = threading.Thread(
            target=self._decode_loop, daemon=True
        )
        self._pace_thread = threading.Thread(
            target=self._pace_loop, daemon=True
        )
        for th in (self._socket_thread, self._decode_thread, self._pace_thread):
            th.start()
        logger.info(
            f"[录屏] 开始录制（真实画面 {self.fps}fps, {raw_width}x{raw_height}）: {self.tmp_path}"
        )
        return True

    # ------------------------------------------------ 工作线程
    def _socket_to_decoder(self):
        """把 scrcpy 裸 H.264 喂给解码器；EOF/停止/出错时关闭解码器输入。"""
        # 取局部引用：finalize 会把 self.video_socket 置 None，避免竞态
        sock = self.video_socket
        try:
            while not self._stop.is_set() and self.alive and sock is not None:
                try:
                    data = sock.recv(0x10000)
                except socket.timeout:
                    continue
                except (ConnectionError, OSError) as e:
                    if not self._stop.is_set():
                        self._set_error(f"scrcpy 视频流中断: {e}")
                    break
                if not data:
                    if not self._stop.is_set():
                        self._set_error("scrcpy 视频流提前结束")
                    break
                try:
                    self._dec.stdin.write(data)
                    self._dec.stdin.flush()
                except Exception as e:
                    if not self._stop.is_set():
                        self._set_error(f"写入解码器失败: {e}")
                    break
        finally:
            # 让解码器收到 EOF，把缓冲里的帧吐完再退出
            self._close_pipe(self._dec, "stdin")

    def _decode_loop(self):
        """把解码器的 rawvideo 逐帧塞进队列，只保留最新一帧。

        只留最新帧可避免积压：一旦编码跟不上，队列不会无限增长导致视频延迟越来越大。
        """
        try:
            while True:
                data = self._read_exact(self.frame_size)
                if data is None:
                    break
                self._frames_decoded += 1
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._frames.put_nowait(data)
                except queue.Full:
                    pass
        finally:
            self._decoder_done.set()

    def _pace_loop(self):
        """按 1/fps 的墙钟节奏把帧交给编码器（本模块的核心）。

        每个时间点取一次队列：有新帧用新帧，没有就复用上一帧。因此源帧率高于
        30fps 时自动丢帧、低于 30fps 时自动补帧，**播放速度**恒等于真实速度。
        （总时长还会受解码器起播预读影响，见模块 docstring。）
        """
        interval = 1.0 / self.fps
        last_frame = None
        next_t = time.perf_counter()
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                if now < next_t:
                    # 用 Event.wait 而不是 sleep：finalize 时能立刻醒来
                    self._stop.wait(max(0.001, min(next_t - now, interval)))
                    continue

                # 取走队列中的最新帧（旧帧直接丢弃）
                while True:
                    try:
                        last_frame = self._frames.get_nowait()
                    except queue.Empty:
                        break

                if last_frame is not None:
                    try:
                        self._enc.stdin.write(last_frame)
                        self._enc.stdin.flush()
                        self._frames_written += 1
                    except Exception as e:
                        if not self._stop.is_set():
                            self._set_error(f"写入编码器失败: {e}")
                        break

                next_t += interval
                now = time.perf_counter()
                if next_t < now and now - next_t > MAX_LAG:
                    # 落后不超过 MAX_LAG 时靠连续投喂追平（时间轴保持对齐）；
                    # 超过说明编码根本跟不上，重新对齐并计数，否则会无休止追赶。
                    self._lags += 1
                    next_t = now

            self._drain_decoder()
        finally:
            self._close_pipe(self._enc, "stdin")

    def _drain_decoder(self):
        """收尾：把解码器还压着的帧全部写进编码器。

        ffmpeg 解码器有固定的起播缓冲（实测 ~19 帧），这些帧只有在拿到后续帧或
        收到 EOF 之后才会吐出来。若不管它们，每段录像都会少掉结尾一截。
        这里只写真实新帧、不再补帧，写完后编码器的时间轴正好补齐。
        """
        while True:
            drained = False
            while True:
                try:
                    frame = self._frames.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._enc.stdin.write(frame)
                    self._enc.stdin.flush()
                    self._frames_written += 1
                    drained = True
                except Exception:
                    return

            if self._decoder_done.is_set() and self._frames.empty():
                return
            if self._decode_thread is None:
                # 没有解码线程在跑（例如只驱动节流线程的场景），不会再有新帧
                return
            if time.perf_counter() > self._drain_deadline:
                self._set_error("收尾时解码器仍未吐出全部帧，录像结尾可能缺失")
                return
            if not drained:
                time.sleep(0.005)

    def _read_exact(self, size):
        """从解码器 stdout 读满一帧 rawvideo。

        Args:
            size (int): 单帧字节数。

        Returns:
            bytes: 完整的一帧；EOF 返回 None；帧不完整（管线断裂）时记录原因并返回 None。
        """
        buf = bytearray(size)
        view = memoryview(buf)
        got = 0
        try:
            while got < size:
                n = self._dec.stdout.readinto(view[got:])
                if n is None or n <= 0:
                    break
                got += n
        except Exception as e:
            self._set_error(f"读取解码器输出失败: {e}")
            return None
        if got == 0:
            return None
        if got < size:
            self._set_error(
                f"解码器输出在帧中途结束（{got}/{size} 字节），本段录像提前终止"
            )
            return None
        return bytes(buf)

    def _close_scrcpy(self):
        """关闭 scrcpy 相关的 socket 与 server 流（可重复调用）。"""
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

    # ------------------------------------------------ 收尾
    @staticmethod
    def _close_pipe(proc, name):
        """关闭子进程的 stdin，相当于给 ffmpeg 发 EOF。可重复调用。"""
        if proc is None:
            return
        pipe = getattr(proc, name, None)
        if pipe is None:
            return
        try:
            pipe.close()
        except Exception:
            pass

    @staticmethod
    def _wait_proc(proc, timeout):
        """等待子进程退出，超时则强杀。

        Args:
            proc (subprocess.Popen): 子进程。
            timeout (float): 等待秒数。

        Returns:
            bool: 在超时前自行退出返回 True；被强杀返回 False（产物不可信）。
        """
        if proc is None:
            return True
        try:
            proc.wait(timeout=timeout)
            return True
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        return False

    def _close_log_files(self):
        """关闭 ffmpeg stderr 日志文件句柄。"""
        for log_file in (self._dec_log, self._enc_log):
            if log_file is None:
                continue
            try:
                log_file.close()
            except Exception:
                pass
        self._dec_log = None
        self._enc_log = None

    def _set_error(self, reason):
        """记录首个致命错误（多线程调用，只保留第一条）。"""
        if self._error is None:
            self._error = reason

    def _ffmpeg_stderr_tail(self, limit=600):
        """读取两个 ffmpeg 的错误输出尾部，用于把失败原因暴露给用户。

        Args:
            limit (int): 每个子进程最多取多少字符。

        Returns:
            str: 形如「｜编码器: xxx」的拼接文本；没有内容时返回空串。
        """
        parts = []
        for name, path in (("解码器", self.dec_log_path), ("编码器", self.enc_log_path)):
            if not path:
                continue
            try:
                with open(path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - limit * 4))
                    data = f.read(limit * 4)
            except OSError:
                continue
            text = data.decode("utf-8", errors="replace").strip()
            if text:
                # 取尾部：真正导致失败的那条错误通常在最后
                parts.append(f"｜{name}: {text[-limit:]}")
        return "".join(parts)

    def _remove_file(self, path):
        """尽力删除一个文件（Windows 上可能被占用，重试几次）。"""
        if not path:
            return
        for _ in range(3):
            try:
                os.remove(path)
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.2)

    def _discard(self):
        """删除本次录制的全部临时文件（不保留的片段，或判定为无效的片段）。"""
        for path in (self.tmp_path, self.dec_log_path, self.enc_log_path):
            self._remove_file(path)

    def _fail(self, reason):
        """产物无效时统一报错，绝不谎报「已保存」。"""
        logger.error(f"[录屏] 本段录像未保存: {reason}{self._ffmpeg_stderr_tail()}")

    def _keep_record(self, encoder_ok, elapsed):
        """校验并保存本段录像。

        Args:
            encoder_ok (bool): 编码器是否正常收尾。
            elapsed (float): 本段实际经过的秒数。

        Returns:
            str: 最终 mp4 路径；产物无效时返回 None 并记录具体原因。
        """
        if self._frames_written <= 0:
            self._fail(
                "本段没有捕获到任何画面帧"
                "（scrcpy 在画面完全静止时不产生帧）"
            )
            return None
        if not self.tmp_path or not os.path.exists(self.tmp_path):
            self._fail("ffmpeg 没有生成输出文件")
            return None

        size = os.path.getsize(self.tmp_path)
        if not encoder_ok:
            self._fail(f"编码器未能正常收尾，录像不完整（{size} 字节）")
            return None
        if size < MIN_VALID_BYTES:
            self._fail(f"录像文件只有 {size} 字节，判定为无效")
            return None

        final_path = os.path.join(
            self.output_dir, f"{self.prefix}{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        )
        try:
            os.replace(self.tmp_path, final_path)
        except OSError as e:
            self._fail(f"保存录像失败: {e}")
            return None

        video_seconds = self._frames_written / self.fps
        logger.info(
            f"[录屏] 已保存: {final_path} "
            f"({size / 1024 / 1024:.1f} MB, 时长 {video_seconds:.1f}s)"
        )
        # 旧版在这里是静默的：用户只会拿到一段被压缩时长、看起来「加速」的录像
        if elapsed > 5 and video_seconds < elapsed * 0.8:
            logger.warning(
                f"[录屏] 录像时长 {video_seconds:.1f}s 明显短于实际经过的 {elapsed:.1f}s，"
                f"画面帧率过低或编码跟不上，这段视频会比真实情况快"
            )
        if self._lags:
            logger.warning(
                f"[录屏] 录制期间有 {self._lags} 次编码跟不上，视频时间轴可能不连续"
            )
        if self._error:
            logger.warning(f"[录屏] 录制期间出现异常: {self._error}")
        return final_path

    # ------------------------------------------------ 对外入口
    def finalize(self, keep):
        """结束录制：停流、收尾 ffmpeg、校验产物，决定保留还是删除。

        本函数保证不抛异常（异常也只会退化成「没有产物」），避免调用方的
        finally 里再炸一次。

        Args:
            keep (bool): 是否保留本段录像。

        Returns:
            str: 保留且产物有效时返回最终 mp4 路径；丢弃或产物无效时返回 None。
        """
        try:
            return self._finalize(keep)
        except Exception as e:
            logger.error(f"[录屏] 结束录制时发生异常，本段录像丢弃: {e}")
            try:
                self._stop.set()
                self._close_scrcpy()
            except Exception:
                pass
            try:
                self._discard()
            except Exception:
                pass
            return None

    def _finalize(self, keep):
        """finalize 的实际实现。"""
        self._stop.set()
        self._stopped_at = time.perf_counter()
        # 给节流线程留出排空解码器缓冲的时间，超时就不再等
        self._drain_deadline = self._stopped_at + DRAIN_TIMEOUT
        self._close_scrcpy()
        # 主动关闭解码器输入：即使喂帧线程卡在 write 上，解码器也能收到 EOF 而退出
        self._close_pipe(self._dec, "stdin")

        for th in (self._socket_thread, self._decode_thread, self._pace_thread):
            if th is not None:
                th.join(timeout=JOIN_TIMEOUT)

        # 线程都停了再关编码器输入，触发它收尾（pace 线程可能已经关过）
        self._close_pipe(self._enc, "stdin")

        # 编码器必须自己写完 moov atom：硬杀只会得到不可播放的废文件
        encoder_ok = self._wait_proc(self._enc, ENCODER_EXIT_TIMEOUT)
        # 解码器已经收到 EOF，正常会立刻退出；被杀不影响已编码的产物
        self._wait_proc(self._dec, DECODER_EXIT_TIMEOUT)
        self._close_log_files()

        elapsed = 0.0
        if self._started_at is not None and self._stopped_at is not None:
            elapsed = max(0.0, self._stopped_at - self._started_at)

        result = None
        if keep:
            result = self._keep_record(encoder_ok, elapsed)
        if result is None:
            self._discard()
        else:
            # 保存成功：诊断日志已完成使命，录像目录里只应留下 mp4
            self._remove_file(self.dec_log_path)
            self._remove_file(self.enc_log_path)
        return result


def clip_start(config, fps=RECORD_FPS, prefix=CLIP_PREFIX_EH1):
    """打开录屏。

    Args:
        config: 当前运行实例的 AzurLaneConfig（含 serial / scrcpy 路径配置）。
        fps (int): 目标帧率。
        prefix (str): 输出文件名前缀，用于区分是哪个任务录的。

    Returns:
        _ScrcpyClip: 录制句柄；启动失败返回 None。
    """
    global _ACTIVE
    if _ACTIVE is not None:
        # 正常情况下走不到这里（调用方保证 start/end 成对）。真发生了说明上一段
        # 没有被正常结束，先把它收尾，避免会话永久泄漏、之后再也录不了。
        logger.warning("[录屏] 上一段录制未正常结束，先收尾再开始新的一段")
        _finalize_active(keep=True)

    rec = _ScrcpyClip(config, fps=fps, prefix=prefix)
    if not rec.start():
        return None
    _ACTIVE = rec
    return rec


def _finalize_active(keep):
    """收尾当前会话并清空 _ACTIVE（即使 finalize 抛错也不会泄漏会话）。

    Args:
        keep (bool): 是否保留该段录像。

    Returns:
        str: 保留时的视频路径；无产物返回 None。
    """
    global _ACTIVE
    rec, _ACTIVE = _ACTIVE, None
    if rec is None:
        return None
    try:
        return rec.finalize(keep=keep)
    except Exception as e:
        # finalize 自身已兜底，这里是最后一道保险
        logger.error(f"[录屏] 结束录制时发生异常: {e}")
        return None


def clip_end(keep=True):
    """结束当前录屏。

    Args:
        keep (bool): 是否把该段保存为 mp4。默认 True（每一轮都保留）；
            传 False 会直接丢弃该段，不留下任何文件。

    Returns:
        str: 保留时的视频路径；无录制或产物无效时返回 None。
    """
    return _finalize_active(keep=keep)


@contextlib.contextmanager
def clip_recording(config, enabled, prefix=CLIP_PREFIX_EH1):
    """在 with 块内录制一段 debug 录像（进入时开录，退出时保存）。

    异常路径也会正常收尾，不会把会话留在活动状态。同一个进程内不会同时存在
    两段录制，因此调用方应避免嵌套。

    Args:
        config: 当前运行实例的 AzurLaneConfig。
        enabled (bool): 是否开启录制；False 时整个块不产生任何录像。
        prefix (str): 输出文件名前缀，用于区分是哪个任务录的。

    Yields:
        _ScrcpyClip | None: 录制句柄；未开启或启动失败时为 None。
    """
    clip = clip_start(config, prefix=prefix) if enabled else None
    try:
        yield clip
    finally:
        if clip is not None:
            clip_end(keep=True)
