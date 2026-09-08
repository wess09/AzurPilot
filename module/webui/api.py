"""
Web界面 REST API 路由。

提供 Starlette 路由处理函数，包括大世界统计、AP 时间线、通知推送、
截图获取、配置导入、远程设备控制等 HTTP/WebSocket 接口。
"""

import asyncio
import json
import os
import queue
import shutil
import socket
import struct
import subprocess
import threading
import time
from time import sleep

import cv2
from module.device.pkg_resources import get_distribution

_ = get_distribution

from adbutils import AdbError, Network
from starlette.responses import JSONResponse, HTMLResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from module.device.method.scrcpy import const as scrcpy_const
from module.device.method.scrcpy.control import ControlSender
from module.device.method.scrcpy.options import ScrcpyOptions
from module.device.method.utils import recv_all
from module.logger import logger
from module.config.utils import DEFAULT_CONFIG_NAME
from module.webui.deploy_settings import (
    deploy_settings_schema,
    get_startup_run,
    save_deploy_settings,
    set_startup_run,
)
from module.webui.launcher import is_local_request, launcher_control
from module.webui.launcher_trust import (
    TOKEN_TTL_SECONDS,
    check_secret,
    enabled as launcher_trust_enabled,
    issue_token,
    validate_token,
    webui_key,
)
from module.webui.lang import t


def is_demo_mode():
    return os.environ.get("DEMO") == "1"


def api_cl1_stats(request):
    try:
        from module.statistics.opsi_month import get_opsi_stats
        instance_name = request.query_params.get("instance", DEFAULT_CONFIG_NAME)
        stats = get_opsi_stats(instance_name=instance_name).get_detailed_summary()
        return JSONResponse({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"api_cl1_stats错误: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

def api_ap_timeline(request):
    try:
        from module.statistics.opsi_month import get_ap_timeline
        instance_name = request.query_params.get("instance", DEFAULT_CONFIG_NAME)
        timeline = get_ap_timeline(instance_name=instance_name)
        return JSONResponse({"success": True, "data": timeline})
    except Exception as e:
        logger.error(f"api_ap_timeline错误: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

def serve_obs_overlay(request):
    """
    提供OBS专用覆盖层页面
    用户可以在浏览器中访问 http://IP:PORT/obs 或者在OBS中添加浏览器源
    """
    try:
        html_path = "module/webui/obs_overlay.html"
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content)
    except Exception as e:
        return HTMLResponse(f"Error loading obs overlay: {e}", status_code=500)


def _get_ffmpeg_path():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _parse_int(value, default, minimum, maximum):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _parse_float(value, default, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _put_queue(queue_obj, item):
    try:
        queue_obj.put(item)
    except Exception:
        pass


def _video_stream_params(codec, width, height, fps, bitrate_scale=1.0):
    pixels_per_second = max(1, width * height * fps)
    bits_per_pixel = 0.42
    crf = 28
    normal_minimum = 320
    absolute_minimum = 160
    maximum = 20000

    bitrate_scale = max(0.25, min(float(bitrate_scale), 1.5))
    base_kbps = int(pixels_per_second * bits_per_pixel / 1000)
    maxrate_kbps = int(max(normal_minimum, base_kbps) * bitrate_scale)
    maxrate_kbps = max(absolute_minimum, min(maxrate_kbps, maximum))
    return {
        "crf": str(crf),
        "maxrate": f"{maxrate_kbps}k",
        "bufsize": f"{maxrate_kbps * 2}k",
        "maxrate_kbps": maxrate_kbps,
        "bitrate_scale": bitrate_scale,
    }


def _video_stream_command(ffmpeg, codec, width, height, fps, stream_params=None):
    stream_params = stream_params or _video_stream_params(codec, width, height, fps)
    base = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
    ]
    return base + [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-crf",
        stream_params["crf"],
        "-maxrate",
        stream_params["maxrate"],
        "-bufsize",
        stream_params["bufsize"],
        "-profile:v",
        "baseline",
        "-level",
        "3.1",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-keyint_min",
        str(fps),
        "-sc_threshold",
        "0",
        "-f",
        "mp4",
        "-movflags",
        "empty_moov+default_base_moof+frag_keyframe",
        "pipe:1",
    ]


def _scrcpy_remux_command(ffmpeg, fps):
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+genpts+nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-f",
        "h264",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "copy",
        "-flush_packets",
        "1",
        "-f",
        "mp4",
        "-movflags",
        "empty_moov+default_base_moof+frag_keyframe+separate_moof+dash",
        "pipe:1",
    ]


def _h264_start_code_size(data, index):
    if data[index:index + 4] == b"\x00\x00\x00\x01":
        return 4
    if data[index:index + 3] == b"\x00\x00\x01":
        return 3
    return 0


def _iter_h264_nals(data):
    starts = []
    index = 0
    length = len(data)
    while index < length - 3:
        size = _h264_start_code_size(data, index)
        if size:
            starts.append((index, size))
            index += size
        else:
            index += 1
    for pos, (start, size) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else length
        nal = data[start + size:end]
        if nal:
            yield nal


def _h264_avc1_codec(data):
    for nal in _iter_h264_nals(data):
        if (nal[0] & 0x1F) == 7 and len(nal) >= 4:
            return f"avc1.{nal[1]:02X}{nal[2]:02X}{nal[3]:02X}"
    return "avc1.42E01E"


def _h264_avcc_description(data):
    sps = None
    pps = None
    for nal in _iter_h264_nals(data):
        nal_type = nal[0] & 0x1F
        if nal_type == 7 and sps is None:
            sps = nal
        elif nal_type == 8 and pps is None:
            pps = nal
        if sps is not None and pps is not None:
            break
    if sps is None:
        return None
    payload = bytearray()
    payload += b"\x01"
    payload += sps[1:4]
    payload += b"\xff"
    payload += b"\xe1"
    payload += len(sps).to_bytes(2, "big")
    payload += sps
    if pps is None:
        payload += b"\x00"
    else:
        payload += b"\x01"
        payload += len(pps).to_bytes(2, "big")
        payload += pps
    return list(payload)


def _iter_h264_nals_flexible(chunks):
    for data in chunks:
        if not data:
            continue
        found = False
        for nal in _iter_h264_nals(data):
            found = True
            yield nal
        if not found:
            yield data


def _h264_avc1_codec_from_chunks(chunks):
    for nal in _iter_h264_nals_flexible(chunks):
        if (nal[0] & 0x1F) == 7 and len(nal) >= 4:
            return f"avc1.{nal[1]:02X}{nal[2]:02X}{nal[3]:02X}"
    return "avc1.42E01E"


def _collect_h264_preroll(session, stop_event, max_wait=3.0):
    deadline = time.time() + max_wait
    chunks = []
    has_sps = False
    has_pps = False
    has_frame = False
    while time.time() < deadline and not stop_event.is_set() and session.alive:
        chunk = session.read_video()
        if chunk is None:
            continue
        if chunk == b"":
            break
        chunks.append(chunk)
        data = b"".join(chunks)
        for nal in _iter_h264_nals(data):
            nal_type = nal[0] & 0x1F
            if nal_type == 7:
                has_sps = True
            elif nal_type == 8:
                has_pps = True
            elif nal_type in (1, 5):
                has_frame = True
        if has_sps and has_pps and has_frame:
            break
    return b"".join(chunks)


async def _collect_ws_scrcpy_preroll(session, max_wait=3.0):
    deadline = time.time() + max_wait
    chunks = []
    has_sps = False
    has_pps = False
    has_frame = False
    while time.time() < deadline and session.alive:
        timeout = max(0.1, min(0.5, deadline - time.time()))
        try:
            data = await asyncio.wait_for(session.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            continue
        if data is None:
            break
        if data == b"":
            continue
        parsed = _ws_scrcpy_parse_initial(data)
        if parsed:
            display = (parsed.get("displays") or [{}])[0]
            width = int(display.get("screen_width") or display.get("width") or session.resolution[0])
            height = int(display.get("screen_height") or display.get("height") or session.resolution[1])
            session.resolution = (max(1, width), max(1, height))
            continue
        chunks.append(data)
        for nal in _iter_h264_nals_flexible([data]):
            nal_type = nal[0] & 0x1F
            if nal_type == 7:
                has_sps = True
            elif nal_type == 8:
                has_pps = True
            elif nal_type in (1, 5):
                has_frame = True
        if has_sps and has_pps and has_frame:
            break
    return chunks


def _live_preview_error_message(error):
    message = str(error).strip()
    if message:
        return message

    name = error.__class__.__name__
    return f"{name}: {error!r}"


WS_SCRCPY_VERSION = "1.19-ws7"
WS_SCRCPY_PORT = 8886
WS_SCRCPY_PACKAGE = "com.genymobile.scrcpy.Server"
WS_SCRCPY_FILEPATH_LOCAL = "./bin/scrcpy/ws-scrcpy-server-v1.19-ws7.jar"
WS_SCRCPY_FILEPATH_REMOTE = "/data/local/tmp/ws-scrcpy-server-v1.19-ws7.jar"
WS_SCRCPY_MAGIC_INITIAL = b"scrcpy_initial"
WS_SCRCPY_DEVICE_NAME_LENGTH = 64
WS_SCRCPY_PID_FILE_REMOTE = "/data/local/tmp/ws_scrcpy.pid"


def _ws_scrcpy_int(data, offset):
    return struct.unpack_from(">i", data, offset)[0], offset + 4


def _ws_scrcpy_parse_initial(data):
    if not isinstance(data, (bytes, bytearray)) or not data.startswith(WS_SCRCPY_MAGIC_INITIAL):
        return None

    try:
        offset = len(WS_SCRCPY_MAGIC_INITIAL)
        name_bytes = bytes(data[offset:offset + WS_SCRCPY_DEVICE_NAME_LENGTH]).rstrip(b"\x00")
        offset += WS_SCRCPY_DEVICE_NAME_LENGTH
        display_count, offset = _ws_scrcpy_int(data, offset)
        displays = []
        for _index in range(max(0, display_count)):
            display_id, offset = _ws_scrcpy_int(data, offset)
            width, offset = _ws_scrcpy_int(data, offset)
            height, offset = _ws_scrcpy_int(data, offset)
            rotation, offset = _ws_scrcpy_int(data, offset)
            layer_stack, offset = _ws_scrcpy_int(data, offset)
            flags, offset = _ws_scrcpy_int(data, offset)
            connection_count, offset = _ws_scrcpy_int(data, offset)
            screen_info_len, offset = _ws_scrcpy_int(data, offset)
            screen_width = width
            screen_height = height
            if screen_info_len >= 25 and offset + screen_info_len <= len(data):
                screen_width = struct.unpack_from(">i", data, offset + 16)[0]
                screen_height = struct.unpack_from(">i", data, offset + 20)[0]
                rotation = data[offset + 24]
            offset += max(0, screen_info_len)
            video_settings_len, offset = _ws_scrcpy_int(data, offset)
            offset += max(0, video_settings_len)
            displays.append({
                "display_id": display_id,
                "width": width,
                "height": height,
                "screen_width": screen_width,
                "screen_height": screen_height,
                "rotation": rotation,
                "layer_stack": layer_stack,
                "flags": flags,
                "connection_count": connection_count,
            })

        encoders = []
        if offset + 4 <= len(data):
            encoder_count, offset = _ws_scrcpy_int(data, offset)
            for _index in range(max(0, encoder_count)):
                name_len, offset = _ws_scrcpy_int(data, offset)
                name = bytes(data[offset:offset + name_len]).decode("utf-8", errors="replace")
                offset += max(0, name_len)
                if name:
                    encoders.append(name)
        client_id = -1
        if offset + 4 <= len(data):
            client_id, offset = _ws_scrcpy_int(data, offset)

        return {
            "device_name": name_bytes.decode("utf-8", errors="replace"),
            "displays": displays,
            "encoders": encoders,
            "client_id": client_id,
        }
    except Exception as e:
        logger.warning(f"[WebUI] 解析 ws-scrcpy 初始信息失败: {e}")
        return None


def _build_ws_scrcpy_video_settings(width, fps, bitrate):
    height = max(180, int(round(width * 9 / 16)))
    payload = bytearray()
    payload += struct.pack(">B", 101)  # TYPE_CHANGE_STREAM_PARAMETERS
    payload += struct.pack(">i", int(bitrate))
    payload += struct.pack(">i", int(fps))
    payload += struct.pack(">b", 1)  # iFrameInterval，低延迟下更快恢复
    payload += struct.pack(">h", int(width))
    payload += struct.pack(">h", int(height))
    payload += struct.pack(">hhhh", 0, 0, 0, 0)  # crop
    payload += struct.pack(">b", 0)  # sendFrameMeta=false，浏览器直接收 H264
    payload += struct.pack(">b", -1)  # unlocked orientation
    payload += struct.pack(">i", 0)  # displayId
    payload += struct.pack(">i", 0)  # codecOptions
    payload += struct.pack(">i", 0)  # encoderName
    return bytes(payload)


class LiveWsScrcpySession:
    """
    NetrisTV/ws-scrcpy 的设备端 WebSocket server 会话。

    浏览器仍只连接 WebUI；这里负责启动设备端 server、ADB forward，并把视频和控制消息代理过去。
    """
    _sessions = {}
    _sessions_lock = threading.Lock()

    def __init__(self, instance, fps=60, width=640, bitrate_scale=1.0):
        from module.config.config import AzurLaneConfig
        from module.device.connection import Connection

        self.instance = instance
        self.fps = _parse_int(fps, 60, 15, 240)
        self.width = _parse_int(width, 640, 320, 1280)
        self.bitrate_scale = _parse_float(bitrate_scale, 1.0, 0.25, 1.5)
        self.config = AzurLaneConfig(instance)
        self.connection = Connection(self.config)
        self.server_stream = None
        self.local_port = None
        self.remote_ws = None
        self.loop = None
        self.send_lock = None
        self.alive = False
        self.resolution = (1280, 720)
        self.device_name = ""

    @classmethod
    def register(cls, instance, session):
        key = instance or DEFAULT_CONFIG_NAME
        with cls._sessions_lock:
            old = cls._sessions.get(key)
            if old is not None and old is not session:
                old.stop()
            cls._sessions[key] = session

    @classmethod
    def get(cls, instance):
        key = instance or DEFAULT_CONFIG_NAME
        with cls._sessions_lock:
            session = cls._sessions.get(key)
            if session is not None and session.alive:
                return session
        return None

    @classmethod
    async def release(cls, instance, session=None):
        key = instance or DEFAULT_CONFIG_NAME
        with cls._sessions_lock:
            current = cls._sessions.get(key)
            if current is not None and (session is None or current is session):
                cls._sessions.pop(key, None)
            else:
                current = None
        if current is not None:
            await current.stop_async()

    @property
    def bitrate(self):
        base = max(1, self.width * int(self.width * 9 / 16) * self.fps)
        bitrate = int(base * 0.20 * self.bitrate_scale)
        return max(300_000, min(bitrate, 20_000_000))

    def _server_command(self):
        args = [
            "/",
            WS_SCRCPY_PACKAGE,
            WS_SCRCPY_VERSION,
            "web",
            "ERROR",
            str(WS_SCRCPY_PORT),
            "false",
        ]
        return f"CLASSPATH={WS_SCRCPY_FILEPATH_REMOTE} nohup app_process {' '.join(args)} >/dev/null 2>&1 &"

    def _server_running(self):
        try:
            pid = self.connection.adb_shell(f"test -f {WS_SCRCPY_PID_FILE_REMOTE} && cat {WS_SCRCPY_PID_FILE_REMOTE}", timeout=2)
            pid = str(pid or "").strip().split()[0]
        except Exception:
            pid = ""
        if not pid:
            return False
        try:
            cmdline = self.connection.adb_shell(f"cat /proc/{int(pid)}/cmdline", timeout=2, rstrip=False)
        except Exception:
            return False
        return WS_SCRCPY_PACKAGE in str(cmdline) and WS_SCRCPY_VERSION in str(cmdline)

    def start_server(self):
        if not os.path.exists(WS_SCRCPY_FILEPATH_LOCAL):
            raise RuntimeError(f"未找到 ws-scrcpy server: {WS_SCRCPY_FILEPATH_LOCAL}")

        logger.hr("[WebUI] 实时 ws-scrcpy 预览启动")
        self.connection.adb_push(WS_SCRCPY_FILEPATH_LOCAL, WS_SCRCPY_FILEPATH_REMOTE)
        self.local_port = self.connection.adb_forward(f"tcp:{WS_SCRCPY_PORT}")
        if self._server_running():
            logger.info("[WebUI] ws-scrcpy server 已在运行，复用设备端服务")
            return
        output = self.connection.adb_shell(self._server_command(), timeout=2)
        if output:
            logger.info(output)

    async def connect(self):
        from websockets.asyncio.client import connect

        if not self.local_port:
            raise RuntimeError("ws-scrcpy 未创建 ADB forward")

        self.loop = asyncio.get_running_loop()
        self.send_lock = asyncio.Lock()
        url = f"ws://127.0.0.1:{self.local_port}/"
        last_error = None
        for _index in range(20):
            try:
                self.remote_ws = await connect(url, max_size=None, ping_interval=None, close_timeout=1)
                self.alive = True
                return
            except Exception as e:
                last_error = e
                await asyncio.sleep(0.1)
        raise RuntimeError(f"连接 ws-scrcpy server 失败: {last_error}")

    async def recv(self):
        if self.remote_ws is None:
            return None
        try:
            data = await self.remote_ws.recv()
        except Exception as e:
            self.alive = False
            code = getattr(e, "code", None)
            reason = getattr(e, "reason", "")
            if code is not None:
                logger.warning(f"[WebUI] ws-scrcpy 设备端连接关闭: code={code}, reason={reason}")
            else:
                logger.warning(f"[WebUI] ws-scrcpy 设备端接收失败: {_live_preview_error_message(e)}")
            return None
        if isinstance(data, str):
            return data.encode("utf-8", errors="replace")
        return bytes(data)

    async def send_binary(self, data):
        if not self.alive or self.remote_ws is None:
            return
        async with self.send_lock:
            await self.remote_ws.send(data)

    def _send_control(self, data):
        if not self.loop or not self.alive:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self.send_binary(data), self.loop)
            future.result(timeout=2)
        except Exception as e:
            logger.warning(f"[WebUI] 发送 ws-scrcpy 控制消息失败: {e}")

    def _scale_point(self, x, y):
        width, height = self.resolution
        x = int(max(0, min(1280, x)) * width / 1280)
        y = int(max(0, min(720, y)) * height / 720)
        return x, y

    def _touch_message(self, x, y, action, touch_id=-1):
        x, y = self._scale_point(x, y)
        width, height = self.resolution
        return struct.pack(
            ">BBqiiHHHi",
            scrcpy_const.TYPE_INJECT_TOUCH_EVENT,
            action,
            touch_id,
            int(x),
            int(y),
            int(width),
            int(height),
            0xFFFF,
            1,
        )

    @staticmethod
    def _keycode_message(keycode, action):
        return struct.pack(">BBiii", scrcpy_const.TYPE_INJECT_KEYCODE, action, int(keycode), 0, 0)

    @staticmethod
    def _text_message(text):
        data = str(text or "").encode("utf-8")
        return struct.pack(">Bi", scrcpy_const.TYPE_INJECT_TEXT, len(data)) + data

    def tap(self, x, y):
        self._send_control(self._touch_message(x, y, scrcpy_const.ACTION_DOWN))
        self._send_control(self._touch_message(x, y, scrcpy_const.ACTION_UP))

    def drag(self, start, end, duration_ms=220):
        sx, sy = start.get("x", 0), start.get("y", 0)
        ex, ey = end.get("x", 0), end.get("y", 0)
        duration = max(40, min(int(duration_ms or 220), 1500)) / 1000
        steps = max(3, min(int(duration / 0.012), 80))
        self._send_control(self._touch_message(sx, sy, scrcpy_const.ACTION_DOWN))
        for index in range(1, steps):
            ratio = index / steps
            x = int(sx + (ex - sx) * ratio)
            y = int(sy + (ey - sy) * ratio)
            self._send_control(self._touch_message(x, y, scrcpy_const.ACTION_MOVE))
            sleep(duration / steps)
        self._send_control(self._touch_message(ex, ey, scrcpy_const.ACTION_MOVE))
        self._send_control(self._touch_message(ex, ey, scrcpy_const.ACTION_UP))

    def keycode(self, keycode):
        self._send_control(self._keycode_message(keycode, scrcpy_const.ACTION_DOWN))
        self._send_control(self._keycode_message(keycode, scrcpy_const.ACTION_UP))

    def text(self, text):
        if text:
            self._send_control(self._text_message(text))

    async def stop_async(self):
        logger.hr("[WebUI] 实时 ws-scrcpy 预览停止")
        self.alive = False
        if self.remote_ws is not None:
            try:
                await self.remote_ws.close()
            except Exception:
                pass
            self.remote_ws = None

    def stop(self):
        self.alive = False
        if self.remote_ws is not None:
            try:
                if self.loop is not None and self.loop.is_running():
                    try:
                        current_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        current_loop = None
                    if current_loop is self.loop:
                        self.loop.create_task(self.remote_ws.close())
                    else:
                        future = asyncio.run_coroutine_threadsafe(self.remote_ws.close(), self.loop)
                        future.result(timeout=1)
            except Exception:
                pass
            self.remote_ws = None
        if self.server_stream is not None:
            try:
                self.server_stream.close()
            except Exception as e:
                logger.warning(f"[WebUI] 关闭 ws-scrcpy server stream 失败: {e}")
        self.server_stream = None


class LiveScrcpySession:
    """
    预览专用 scrcpy 会话。

    这里只桥接 H264 原始流和控制 socket，不启动 PyAV 解码线程。
    """
    _sessions = {}
    _sessions_lock = threading.Lock()

    def __init__(self, instance, fps=60, width=640, bitrate_scale=1.0):
        from module.config.config import AzurLaneConfig
        from module.device.method.scrcpy.core import ScrcpyCore

        self.instance = instance
        self.fps = _parse_int(fps, 60, 15, 240)
        self.width = _parse_int(width, 640, 320, 1280)
        self.bitrate_scale = _parse_float(bitrate_scale, 1.0, 0.25, 1.5)
        self.config = AzurLaneConfig(instance)
        self.connection = ScrcpyCore(self.config)
        self.video_socket = None
        self.control_socket = None
        self.server_stream = None
        self.alive = False
        self.resolution = (1280, 720)
        self.control_lock = threading.RLock()
        self.control_sender = ControlSender(self)

    @property
    def _scrcpy_control_socket(self):
        return self.control_socket

    @property
    def _scrcpy_control_socket_lock(self):
        return self.control_lock

    @property
    def _scrcpy_resolution(self):
        return self.resolution

    @classmethod
    def acquire(cls, instance, fps=60, width=640, bitrate_scale=1.0):
        key = instance or DEFAULT_CONFIG_NAME
        with cls._sessions_lock:
            session = cls._sessions.get(key)
            if session is not None:
                session.stop()
                cls._sessions.pop(key, None)
            session = cls(key, fps=fps, width=width, bitrate_scale=bitrate_scale)
            session.start()
            cls._sessions[key] = session
            return session

    @classmethod
    def get(cls, instance):
        key = instance or DEFAULT_CONFIG_NAME
        with cls._sessions_lock:
            session = cls._sessions.get(key)
            if session is not None and session.alive:
                return session
        return None

    @classmethod
    def release(cls, instance, session=None):
        key = instance or DEFAULT_CONFIG_NAME
        with cls._sessions_lock:
            current = cls._sessions.get(key)
            if current is not None and (session is None or current is session):
                cls._sessions.pop(key, None)
                current.stop()

    @property
    def bitrate(self):
        # scrcpy 1.20 超过 20Mbps 会回落默认值，保守限制在 20Mbps 内。
        base = max(1, self.width * int(self.width * 9 / 16) * self.fps)
        bitrate = int(base * 0.20 * self.bitrate_scale)
        return max(300_000, min(bitrate, 20_000_000))

    def _scrcpy_command(self):
        original_frame_rate = ScrcpyOptions.frame_rate
        try:
            ScrcpyOptions.frame_rate = self.fps
            commands = ScrcpyOptions.command_v120(jar_path=self.config.SCRCPY_FILEPATH_REMOTE)
        finally:
            ScrcpyOptions.frame_rate = original_frame_rate

        # scrcpy-server 1.20 参数位置：max_size、bitrate、max_fps。
        commands[6] = str(self.width)
        commands[7] = str(self.bitrate)
        commands[8] = str(self.fps)
        return commands

    def start(self):
        try:
            logger.hr("[WebUI] 实时 scrcpy 预览启动")
            self.connection.adb_push(self.config.SCRCPY_FILEPATH_LOCAL, self.config.SCRCPY_FILEPATH_REMOTE)
            self.server_stream = self.connection.adb.shell(self._scrcpy_command(), stream=True)
            self.server_stream.conn.settimeout(3)

            ret = self.server_stream.read(10)
            if b"Aborted" in ret:
                raise RuntimeError("scrcpy-server 启动失败：Aborted")
            if ret == b"[server] E":
                ret += recv_all(self.server_stream)
                raise RuntimeError(ret.decode("utf-8", errors="replace"))
            ret += self._receive_server_stream()
            logger.info(ret)

            self.video_socket = self._connect_scrcpy_socket()
            dummy_byte = self.video_socket.recv(1)
            if dummy_byte != b"\x00":
                raise RuntimeError("scrcpy 视频流握手失败")

            self.control_socket = self._connect_scrcpy_socket()
            device_name = self.video_socket.recv(64).decode("utf-8", errors="replace").rstrip("\x00")
            if device_name:
                logger.attr("Scrcpy直播设备", device_name)
            resolution = self.video_socket.recv(4)
            if len(resolution) != 4:
                raise RuntimeError("scrcpy 未返回视频分辨率")
            self.resolution = struct.unpack(">HH", resolution)
            logger.attr("Scrcpy直播分辨率", self.resolution)
            self.video_socket.settimeout(1)
            self.alive = True
        except Exception:
            self.stop()
            raise

    def _receive_server_stream(self):
        if self.server_stream is not None:
            try:
                return self.server_stream.conn.recv(4096)
            except Exception:
                pass
        return b""

    def _connect_scrcpy_socket(self):
        timeout_at = time.time() + 3
        while time.time() < timeout_at:
            try:
                sock = self.connection.adb.create_connection(Network.LOCAL_ABSTRACT, "scrcpy")
                sock.settimeout(3)
                return sock
            except AdbError:
                sleep(0.1)
        raise RuntimeError("连接 scrcpy socket 超时")

    def read_video(self, size=0x10000):
        if not self.video_socket:
            return b""
        try:
            return self.video_socket.recv(size)
        except socket.timeout:
            return None
        except (ConnectionError, OSError):
            return b""

    def scale_point(self, x, y):
        width, height = self.resolution
        x = int(max(0, min(1280, x)) * width / 1280)
        y = int(max(0, min(720, y)) * height / 720)
        return x, y

    def tap(self, x, y):
        x, y = self.scale_point(x, y)
        with self.control_lock:
            self.control_sender.touch(x, y, scrcpy_const.ACTION_DOWN)
            self.control_sender.touch(x, y, scrcpy_const.ACTION_UP)

    def drag(self, start, end, duration_ms=220):
        sx, sy = self.scale_point(start.get("x", 0), start.get("y", 0))
        ex, ey = self.scale_point(end.get("x", 0), end.get("y", 0))
        duration = max(40, min(int(duration_ms or 220), 1500)) / 1000
        steps = max(3, min(int(duration / 0.012), 80))
        with self.control_lock:
            self.control_sender.touch(sx, sy, scrcpy_const.ACTION_DOWN)
            for index in range(1, steps):
                ratio = index / steps
                x = int(sx + (ex - sx) * ratio)
                y = int(sy + (ey - sy) * ratio)
                self.control_sender.touch(x, y, scrcpy_const.ACTION_MOVE)
                sleep(duration / steps)
            self.control_sender.touch(ex, ey, scrcpy_const.ACTION_MOVE)
            self.control_sender.touch(ex, ey, scrcpy_const.ACTION_UP)

    def keycode(self, keycode):
        keycode = int(keycode)
        with self.control_lock:
            self.control_sender.keycode(keycode, scrcpy_const.ACTION_DOWN)
            self.control_sender.keycode(keycode, scrcpy_const.ACTION_UP)

    def text(self, text):
        text = str(text or "")
        if not text:
            return
        with self.control_lock:
            self.control_sender.text(text)

    def stop(self):
        logger.hr("[WebUI] 实时 scrcpy 预览停止")
        self.alive = False
        for obj in (self.control_socket, self.video_socket, self.server_stream):
            if obj is None:
                continue
            try:
                obj.close()
            except Exception as e:
                logger.warning(f"[WebUI] 关闭 scrcpy 资源失败: {e}")
        self.control_socket = None
        self.video_socket = None
        self.server_stream = None


class LiveControlDevice:
    def __init__(self, instance):
        from module.config.config import AzurLaneConfig
        from module.device.connection import Connection

        self.config = AzurLaneConfig(instance)
        self.connection = Connection(self.config)

    def tap(self, x, y):
        self.connection.adb_shell(["input", "tap", int(x), int(y)])

    def drag(self, start, end, duration_ms=220):
        p1 = (int(start.get("x", 0)), int(start.get("y", 0)))
        p2 = (int(end.get("x", 0)), int(end.get("y", 0)))
        duration_ms = max(40, min(int(duration_ms or 220), 1500))
        self.connection.adb_shell(["input", "swipe", p1[0], p1[1], p2[0], p2[1], duration_ms])

    def keycode(self, keycode):
        self.connection.adb_shell(["input", "keyevent", int(keycode)])

    def text(self, text):
        text = str(text or "").replace(" ", "%s")
        if text:
            self.connection.adb_shell(["input", "text", text])


def _key_to_android_keycode(key):
    mapping = {
        "Backspace": scrcpy_const.KEYCODE_DEL,
        "Delete": scrcpy_const.KEYCODE_FORWARD_DEL,
        "Enter": scrcpy_const.KEYCODE_ENTER,
        "Escape": scrcpy_const.KEYCODE_BACK,
        "Tab": scrcpy_const.KEYCODE_TAB,
        " ": scrcpy_const.KEYCODE_SPACE,
        "ArrowUp": scrcpy_const.KEYCODE_DPAD_UP,
        "ArrowDown": scrcpy_const.KEYCODE_DPAD_DOWN,
        "ArrowLeft": scrcpy_const.KEYCODE_DPAD_LEFT,
        "ArrowRight": scrcpy_const.KEYCODE_DPAD_RIGHT,
        "Home": scrcpy_const.KEYCODE_HOME,
        "End": scrcpy_const.KEYCODE_MOVE_END,
        "PageUp": scrcpy_const.KEYCODE_PAGE_UP,
        "PageDown": scrcpy_const.KEYCODE_PAGE_DOWN,
        "AppSwitch": scrcpy_const.KEYCODE_APP_SWITCH,
    }
    return mapping.get(key)


CONTROL_ACTION_KEYCODES = {
    "back": scrcpy_const.KEYCODE_BACK,
    "home": scrcpy_const.KEYCODE_HOME,
    "app_switch": scrcpy_const.KEYCODE_APP_SWITCH,
}


def _create_live_ws_scrcpy_session(instance, fps, target_width, bitrate_scale):
    return LiveWsScrcpySession(
        instance,
        fps=fps,
        width=target_width,
        bitrate_scale=bitrate_scale,
    )


def _acquire_live_scrcpy_session(instance, fps, target_width, bitrate_scale):
    return LiveScrcpySession.acquire(
        instance,
        fps=fps,
        width=target_width,
        bitrate_scale=bitrate_scale,
    )


def _init_live_screenshot_fallback(instance):
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

    if "ALAS_CONFIG_NAME" not in os.environ:
        os.environ["ALAS_CONFIG_NAME"] = instance

    config = AzurLaneConfig(instance)
    device = Device(config)
    return device, device.screenshot()


async def ws_live_screenshot(websocket):
    await websocket.accept()
    if is_demo_mode():
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "DEMO=1，实时预览已禁用，避免初始化设备资源。",
        }))
        await websocket.close()
        return

    instance = websocket.query_params.get("instance", DEFAULT_CONFIG_NAME)
    mode = websocket.query_params.get("mode", "auto").lower()
    if mode not in ("auto", "scrcpy", "screenshot"):
        mode = "auto"
    codec = "h264"
    fps = _parse_int(websocket.query_params.get("fps", "60"), 60, 15, 240)
    target_width = _parse_int(websocket.query_params.get("width", "640"), 640, 320, 1280)
    bitrate_scale = _parse_float(websocket.query_params.get("bitrate_scale", "1"), 1.0, 0.25, 1.5)

    try:
        from module.webui.fake_pil_module import remove_fake_pil_module
        remove_fake_pil_module()
    except Exception:
        pass

    if mode in ("auto", "scrcpy"):
        try:
            await _ws_live_scrcpy(websocket, instance, fps, target_width, bitrate_scale)
            return
        except WebSocketDisconnect:
            return
        except Exception as e:
            if mode == "scrcpy":
                message = _live_preview_error_message(e)
                logger.error(f"ws_live_scrcpy error: {message}")
                try:
                    await websocket.send_text(json.dumps({"type": "error", "message": message}))
                except Exception:
                    pass
                return
            logger.warning(f"[WebUI] scrcpy 预览不可用，回退截图模式: {_live_preview_error_message(e)}")

    ffmpeg = _get_ffmpeg_path()
    if not ffmpeg:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "未找到 ffmpeg，截图兜底模式无法启动。",
        }))
        await websocket.close()
        return

    await _ws_live_screenshot_fallback(websocket, instance, codec, ffmpeg, fps, target_width, bitrate_scale)


async def _ws_live_scrcpy(websocket, instance, fps, target_width, bitrate_scale):
    try:
        await _ws_live_ws_scrcpy(websocket, instance, fps, target_width, bitrate_scale)
        return
    except WebSocketDisconnect:
        raise
    except Exception as e:
        logger.warning(f"[WebUI] ws-scrcpy 预览不可用，回退原版 scrcpy: {_live_preview_error_message(e)}")

    await _ws_live_raw_scrcpy(websocket, instance, fps, target_width, bitrate_scale)


async def _ws_live_ws_scrcpy(websocket, instance, fps, target_width, bitrate_scale):
    session = await asyncio.to_thread(
        _create_live_ws_scrcpy_session,
        instance,
        fps,
        target_width,
        bitrate_scale,
    )
    LiveWsScrcpySession.register(instance, session)

    try:
        await asyncio.to_thread(session.start_server)
        await session.connect()

        initial = await asyncio.wait_for(session.recv(), timeout=3)
        info = _ws_scrcpy_parse_initial(initial)
        if not info:
            raise RuntimeError("ws-scrcpy 未返回初始设备信息")

        display = (info.get("displays") or [{}])[0]
        width = int(display.get("screen_width") or display.get("width") or target_width)
        height = int(display.get("screen_height") or display.get("height") or int(target_width * 9 / 16))
        session.resolution = (max(1, width), max(1, height))
        session.device_name = info.get("device_name") or ""
        if session.device_name:
            logger.attr("WsScrcpy直播设备", session.device_name)
        logger.attr("WsScrcpy直播分辨率", session.resolution)

        await session.send_binary(_build_ws_scrcpy_video_settings(target_width, fps, session.bitrate))
        preroll = await _collect_ws_scrcpy_preroll(session)
        codec_string = _h264_avc1_codec_from_chunks(preroll)
        logger.attr("WsScrcpy预缓冲", f"{sum(len(item) for item in preroll)} bytes, {codec_string}")
        await websocket.send_text(json.dumps({
            "type": "ready",
            "mode": "ws-scrcpy",
            "codec": "h264",
            "format": "raw_h264",
            "codec_string": codec_string,
            "description": None,
            "width": session.resolution[0],
            "height": session.resolution[1],
            "fps": fps,
            "bitrate_mode": "scrcpy",
            "maxrate": f"{int(session.bitrate / 1000)}k",
            "bitrate_scale": bitrate_scale,
        }))
        for data in preroll:
            await websocket.send_bytes(data)

        while session.alive:
            data = await session.recv()
            if data is None:
                break
            if data == b"":
                continue
            parsed = _ws_scrcpy_parse_initial(data)
            if parsed:
                display = (parsed.get("displays") or [{}])[0]
                width = int(display.get("screen_width") or display.get("width") or session.resolution[0])
                height = int(display.get("screen_height") or display.get("height") or session.resolution[1])
                session.resolution = (max(1, width), max(1, height))
                await websocket.send_text(json.dumps({
                    "type": "resize",
                    "width": session.resolution[0],
                    "height": session.resolution[1],
                }))
                continue
            await websocket.send_bytes(data)
    finally:
        await LiveWsScrcpySession.release(instance, session=session)


async def _ws_live_raw_scrcpy(websocket, instance, fps, target_width, bitrate_scale):
    stop_event = threading.Event()
    session = None

    try:
        session = await asyncio.to_thread(
            _acquire_live_scrcpy_session,
            instance,
            fps,
            target_width,
            bitrate_scale,
        )
        width, height = session.resolution
        preroll = await asyncio.to_thread(_collect_h264_preroll, session, stop_event)
        if not preroll:
            raise RuntimeError("scrcpy 未输出 H264 视频数据")
        codec_string = _h264_avc1_codec(preroll)
        description = _h264_avcc_description(preroll)
        logger.attr("Scrcpy预缓冲", f"{len(preroll)} bytes, {codec_string}")
        await websocket.send_text(json.dumps({
            "type": "ready",
            "mode": "scrcpy",
            "codec": "h264",
            "format": "raw_h264",
            "codec_string": codec_string,
            "description": description,
            "width": width,
            "height": height,
            "fps": fps,
            "bitrate_mode": "scrcpy",
            "maxrate": f"{int(session.bitrate / 1000)}k",
            "bitrate_scale": bitrate_scale,
        }))
        await websocket.send_bytes(preroll)

        while not stop_event.is_set() and session.alive:
            raw_h264 = await asyncio.to_thread(session.read_video)
            if raw_h264 is None:
                continue
            if raw_h264 == b"":
                if not stop_event.is_set() and session.alive:
                    await websocket.send_text(json.dumps({"type": "error", "message": "scrcpy 视频流已断开"}))
                break
            await websocket.send_bytes(raw_h264)
    finally:
        stop_event.set()
        # 预览关闭即停止 scrcpy，避免后台持续占用编码器。
        if session is not None:
            await asyncio.to_thread(LiveScrcpySession.release, instance, session=session)


async def _ws_live_screenshot_fallback(websocket, instance, codec, ffmpeg, fps, target_width, bitrate_scale):
    stop_event = threading.Event()
    out_queue = queue.Queue(maxsize=16)
    proc = None

    try:
        device, first = await asyncio.to_thread(_init_live_screenshot_fallback, instance)
        src_height, src_width = first.shape[:2]
        target_height = int(round(target_width * src_height / src_width))
        if target_height % 2:
            target_height += 1
        size = (target_width, target_height)
        stream_params = _video_stream_params(codec, target_width, target_height, fps, bitrate_scale)

        mime = 'video/mp4; codecs="avc1.42E01E"'
        await websocket.send_text(json.dumps({
            "type": "ready",
            "mode": "screenshot",
            "codec": codec,
            "mime": mime,
            "width": target_width,
            "height": target_height,
            "fps": fps,
            "bitrate_mode": "dynamic",
            "maxrate": stream_params["maxrate"],
            "bitrate_scale": stream_params["bitrate_scale"],
        }))

        proc = subprocess.Popen(
            _video_stream_command(ffmpeg, codec, target_width, target_height, fps, stream_params),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        def normalize_frame(image):
            if image.shape[1] != target_width or image.shape[0] != target_height:
                image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
            if not image.flags["C_CONTIGUOUS"]:
                image = image.copy()
            return image

        def writer():
            frame_interval = 1 / fps
            next_frame = time.perf_counter()
            image = first
            while not stop_event.is_set():
                try:
                    proc.stdin.write(normalize_frame(image).tobytes())
                    proc.stdin.flush()
                except Exception:
                    break
                next_frame += frame_interval
                sleep_for = next_frame - time.perf_counter()
                if sleep_for > 0:
                    stop_event.wait(sleep_for)
                if stop_event.is_set():
                    break
                try:
                    image = device.screenshot()
                except Exception as e:
                    _put_queue(out_queue, ("error", str(e)))
                    break
            try:
                proc.stdin.close()
            except Exception:
                pass

        def reader():
            while not stop_event.is_set():
                try:
                    chunk = proc.stdout.read(32768)
                except Exception:
                    break
                if not chunk:
                    break
                _put_queue(out_queue, ("data", chunk))
            _put_queue(out_queue, ("eof", None))

        def stderr_reader():
            try:
                err = proc.stderr.read().decode("utf-8", errors="replace").strip()
            except Exception:
                err = ""
            if err and not stop_event.is_set():
                _put_queue(out_queue, ("error", err[-1000:]))

        threading.Thread(target=writer, daemon=True).start()
        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=stderr_reader, daemon=True).start()

        while not stop_event.is_set():
            kind, payload = await asyncio.to_thread(out_queue.get)
            if kind == "data":
                await websocket.send_bytes(payload)
            elif kind == "error":
                await websocket.send_text(json.dumps({"type": "error", "message": payload}))
                break
            else:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        message = _live_preview_error_message(e)
        logger.error(f"ws_live_screenshot error: {message}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": message}))
        except Exception:
            pass
    finally:
        stop_event.set()
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass


async def ws_live_control(websocket):
    await websocket.accept()
    if is_demo_mode():
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "DEMO=1，实时控制已禁用，避免初始化设备资源。",
        }))
        await websocket.close()
        return
    instance = websocket.query_params.get("instance", DEFAULT_CONFIG_NAME)
    fallback = None

    def get_target():
        nonlocal fallback
        ws_session = LiveWsScrcpySession.get(instance)
        if ws_session is not None:
            return ws_session
        session = LiveScrcpySession.get(instance)
        if session is not None:
            return session
        if fallback is None:
            fallback = LiveControlDevice(instance)
        return fallback

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "控制消息不是有效 JSON"}))
                continue

            action = data.get("type")
            target = get_target()
            if action == "tap":
                x = int(data.get("x", 0))
                y = int(data.get("y", 0))
                logger.info(f"[WebUI] 实时预览控制：点击 ({x}, {y})")
                await asyncio.to_thread(target.tap, x, y)
            elif action == "drag":
                start = data.get("start") or {}
                end = data.get("end") or {}
                duration_ms = data.get("duration_ms", 220)
                logger.info(f"[WebUI] 实时预览控制：拖拽 {start} -> {end}")
                await asyncio.to_thread(target.drag, start, end, duration_ms)
            elif action == "key":
                keycode = data.get("keycode")
                if keycode is None:
                    keycode = _key_to_android_keycode(data.get("key"))
                if keycode is not None:
                    logger.info(f"[WebUI] 实时预览控制：按键 {keycode}")
                    await asyncio.to_thread(target.keycode, keycode)
            elif action == "text":
                text = data.get("text", "")
                logger.info("[WebUI] 实时预览控制：文本输入")
                await asyncio.to_thread(target.text, text)
            elif action == "back":
                logger.info("[WebUI] 实时预览控制：返回")
                await asyncio.to_thread(target.keycode, scrcpy_const.KEYCODE_BACK)
            elif action in CONTROL_ACTION_KEYCODES:
                keycode = CONTROL_ACTION_KEYCODES[action]
                logger.info(f"[WebUI] 实时预览控制：系统按键 {action} ({keycode})")
                await asyncio.to_thread(target.keycode, keycode)
            else:
                await websocket.send_text(json.dumps({"type": "error", "message": f"未知控制动作: {action}"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        message = _live_preview_error_message(e)
        logger.error(f"ws_live_control error: {message}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": message}))
        except Exception:
            pass

_notification_queue = asyncio.Queue()


async def api_notify(request):
    """POST /api/notify — 接收通知推送到 SSE"""
    data = await request.json()
    await _notification_queue.put(data)
    return JSONResponse({'success': True})


async def api_notify_stream(request):
    """GET /api/notify_stream — SSE 端点，启动器订阅接收通知"""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                n = await asyncio.wait_for(_notification_queue.get(), timeout=30)
                yield f"data: {json.dumps(n, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def api_launcher_status(request):
    """GET /api/launcher/status — 查询启动器连接和开机自启动状态"""
    request_local = is_local_request(request)
    return JSONResponse(launcher_control.status(request_local=request_local))


async def api_launcher_startup(request):
    """POST /api/launcher/startup — 请求启动器设置 Windows 开机自启动"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "开机自启动只能从本机 WebUI 设置"},
            status_code=403,
        )

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "请求体不是有效 JSON"}, status_code=400)

    if "enabled" not in data:
        return JSONResponse({"success": False, "error": "缺少 enabled 字段"}, status_code=400)
    if not isinstance(data.get("enabled"), bool):
        return JSONResponse({"success": False, "error": "enabled 必须是布尔值"}, status_code=400)

    result = await launcher_control.set_autostart(data["enabled"])
    status = 200 if result.get("success") else 500
    return JSONResponse(result, status_code=status)


async def api_launcher_stream(request):
    """GET /api/launcher/stream — 启动器订阅的本地命令流"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "启动器命令流只允许本机连接"},
            status_code=403,
        )

    async def event_generator():
        await launcher_control.mark_connected()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    command = await asyncio.wait_for(launcher_control.next_command(), timeout=30)
                    launcher_control.keep_alive()
                    yield launcher_control.event(command)
                except asyncio.TimeoutError:
                    launcher_control.keep_alive()
                    yield launcher_control.keepalive_event()
        finally:
            launcher_control.mark_disconnected()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def api_launcher_report(request):
    """POST /api/launcher/report — 启动器回报命令执行结果"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "启动器回报只允许本机连接"},
            status_code=403,
        )

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "请求体不是有效 JSON"}, status_code=400)

    result = await launcher_control.report(data)
    return JSONResponse(result)


# 免密令牌只对回环开放，但仍对"试密钥"做简单限频，避免本机其它进程暴力探测。
_LAUNCHER_SECRET_FAILURES: list[float] = []
_LAUNCHER_SECRET_WINDOW = 300  # 秒
_LAUNCHER_SECRET_MAX_FAILURES = 15


def _launcher_secret_try_allowed() -> bool:
    """最近窗口内错误尝试是否超过阈值。"""
    now = time.time()
    while _LAUNCHER_SECRET_FAILURES and now - _LAUNCHER_SECRET_FAILURES[0] > _LAUNCHER_SECRET_WINDOW:
        _LAUNCHER_SECRET_FAILURES.pop(0)
    return len(_LAUNCHER_SECRET_FAILURES) < _LAUNCHER_SECRET_MAX_FAILURES


def _launcher_secret_failure() -> None:
    _LAUNCHER_SECRET_FAILURES.append(time.time())


async def api_launcher_trusted_login(request):
    """POST /api/launcher/trusted-login — 启动器以信任密钥换取一次性免密令牌"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "免密通道只允许本机连接"},
            status_code=403,
        )
    if not launcher_trust_enabled():
        # 未由启动器（带信任密钥）拉起，或未配置 WebUI 密码，免密通道整体关闭。
        return JSONResponse(
            {"success": False, "error": "启动器免密通道未启用"},
            status_code=403,
        )
    if not _launcher_secret_try_allowed():
        return JSONResponse(
            {"success": False, "error": "尝试次数过多，请稍后再试"},
            status_code=429,
        )

    secret = request.headers.get("x-webui-launcher-secret")
    if not check_secret(secret):
        _launcher_secret_failure()
        return JSONResponse(
            {"success": False, "error": "信任密钥无效"},
            status_code=403,
        )

    token = issue_token()
    if token is None:
        return JSONResponse(
            {"success": False, "error": "免密令牌签发失败"},
            status_code=403,
        )
    return JSONResponse(
        {"success": True, "token": token, "ttl": TOKEN_TTL_SECONDS}
    )


async def launcher_login(request):
    """GET /launcher-login?token= — 校验令牌后预置本机窗口的登录状态。

    返回与 WebUI 同源的种子页，把当前有效密码写入 localStorage["password"] 并跳回
    首页；下次会话 login() 命中，无需再输密码。非回环/令牌无效一律拒绝。
    """
    if not is_local_request(request):
        return _launcher_login_denied()
    token = request.query_params.get("token")
    if not validate_token(token):
        return _launcher_login_denied()

    key = webui_key()
    if not key:
        # 未配置密码时本就不需要登录，直接回首页。
        return HTMLResponse(
            '<!doctype html><script>location.replace("/");</script>',
            status_code=200,
        )

    # json.dumps 生成合法 JS 字符串字面量，安全内嵌任意密码。
    password_literal = json.dumps(str(key))
    html = (
        "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
        "<title>AzurPilot 免密登录</title>"
        "<script>"
        "localStorage.setItem('password', " + password_literal + ");"
        "location.replace('/');"
        "</script>"
        "<body>正在免密登录，请稍候…</body></html>"
    )
    return HTMLResponse(html, status_code=200)


def _launcher_login_denied():
    return HTMLResponse(
        "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
        "<title>拒绝访问</title><body>该链接无效或已过期，请从启动器重新打开。</body></html>",
        status_code=403,
    )


async def api_deploy_settings(request):
    """GET /api/deploy/settings — 查询 deploy.yaml 可视化配置。"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "部署设置只允许从本机 WebUI 读取"},
            status_code=403,
        )

    try:
        return JSONResponse({"success": True, "data": deploy_settings_schema(t)})
    except Exception as e:
        logger.error(f"[WebUI] 读取部署设置失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


async def api_deploy_settings_save(request):
    """POST /api/deploy/settings — 保存 deploy.yaml 可视化配置。"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "部署设置只允许从本机 WebUI 保存"},
            status_code=403,
        )

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "请求体不是有效 JSON"}, status_code=400)

    try:
        result = save_deploy_settings(data)
    except PermissionError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=403)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"[WebUI] 保存部署设置失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    return JSONResponse({"success": True, "data": result})


async def api_deploy_startup_run(request):
    """GET /api/deploy/startup-run — 查询实例是否随 WebUI 启动自动运行。"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "启动时自动运行只允许从本机 WebUI 读取"},
            status_code=403,
        )

    try:
        result = get_startup_run(request.query_params.get("instance", ""))
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"[WebUI] 读取启动时自动运行失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    return JSONResponse({"success": True, "data": result})


async def api_deploy_startup_run_save(request):
    """POST /api/deploy/startup-run — 保存实例启动时自动运行设置。"""
    if not is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "启动时自动运行只允许从本机 WebUI 保存"},
            status_code=403,
        )

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "请求体不是有效 JSON"}, status_code=400)

    try:
        result = set_startup_run(data.get("instance", ""), data.get("enabled"))
    except PermissionError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=403)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"[WebUI] 保存启动时自动运行失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    return JSONResponse({"success": True, "data": result})


async def api_import_legacy_upload(request):
    """
    接收浏览器上传的旧 AzurPilot 文件夹内容，写入本项目对应位置。
    前端使用 webkitdirectory 选择文件夹后上传。
    """
    from pathlib import Path

    try:
        form = await request.form()
        current_root = Path(os.getcwd()).resolve()

        result = {
            "config": 0,
            "db": 0,
            "cl1": 0,
            "azurstat": 0,
            "skipped": 0,
            "errors": 0,
        }

        for file in form.getlist('file'):
            if not hasattr(file, 'filename') or not file.filename:
                continue

            relative_path = file.filename.replace("\\", "/")
            filename = Path(relative_path).name

            # 提取根级相对路径：跳过前导 / 和可能的文件夹名前缀
            parts = relative_path.split("/")
            # parts[0]='' (前导 /), parts[1]可能是文件夹名或 config/log
            start_idx = 1
            if len(parts) >= 3 and parts[1] not in ("config", "log"):
                start_idx = 2  # parts[1] 是文件夹名，跳过
            sub_path = "/".join(parts[start_idx:])

            # 判断是否需要处理该文件
            rel_target = None

            # 只匹配 根目录/config/ 下的 .json/.db（排除 template*）
            if sub_path.startswith("config/"):
                ext = Path(filename).suffix.lower()
                if ext in (".json", ".db") and not filename.lower().startswith("template"):
                    rel_target = sub_path

            # 只匹配 根目录/log/cl1/ 下的所有文件
            if sub_path.startswith("log/cl1/"):
                rel_target = sub_path

            # 只匹配 根目录/log/azurstat_meowofficer_farming.csv
            if sub_path == "log/azurstat_meowofficer_farming.csv":
                rel_target = sub_path

            if rel_target is None:
                result["skipped"] += 1
                continue

            target = current_root / rel_target

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                content = await file.read()
                target.write_bytes(content)

                if rel_target.startswith("config/"):
                    ext = Path(filename).suffix.lower()
                    if ext == ".json":
                        result["config"] += 1
                    else:
                        result["db"] += 1
                elif rel_target.startswith("log/cl1/"):
                    result["cl1"] += 1
                elif "azurstat" in rel_target:
                    result["azurstat"] += 1
            except Exception as e:
                logger.error(f"[WebUI] 写入失败 {target}: {e}")
                result["errors"] += 1

        logger.info(f"[WebUI] 导入完成: {result}")
        return JSONResponse({"success": True, "data": result})
    except Exception as e:
        logger.error(f"[WebUI] 导入API错误: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


api_routes = [
    Route("/api/cl1_stats", api_cl1_stats),
    Route("/api/ap_timeline", api_ap_timeline),
    Route("/api/notify", api_notify, methods=["POST"]),
    Route("/api/notify_stream", api_notify_stream),
    Route("/api/launcher/status", api_launcher_status),
    Route("/api/launcher/startup", api_launcher_startup, methods=["POST"]),
    Route("/api/launcher/stream", api_launcher_stream),
    Route("/api/launcher/report", api_launcher_report, methods=["POST"]),
    Route("/api/launcher/trusted-login", api_launcher_trusted_login, methods=["POST"]),
    Route("/launcher-login", launcher_login, methods=["GET"]),
    Route("/api/deploy/settings", api_deploy_settings),
    Route("/api/deploy/settings", api_deploy_settings_save, methods=["POST"]),
    Route("/api/deploy/startup-run", api_deploy_startup_run),
    Route("/api/deploy/startup-run", api_deploy_startup_run_save, methods=["POST"]),
    Route("/api/import_legacy_upload", api_import_legacy_upload, methods=["POST"]),
    Route("/obs", serve_obs_overlay),
    WebSocketRoute("/ws/live_screenshot", ws_live_screenshot),
    WebSocketRoute("/ws/live_control", ws_live_control),
]
