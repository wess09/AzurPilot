"""设备控制契约的纯函数部分：坐标、文本、按键、诊断命令与观测帧缓存。

这里只依赖标准库，供父进程校验和子进程执行共用。图像签名由调用方传入
PIL/numpy 计算，本模块只负责比较，避免把设备库拖进 ASGI 进程。
"""
import json
import re
import shutil
import time
from pathlib import Path


# 设备控制类工具：必须持有租约才能执行。
CONTROL_OPERATIONS = ('click', 'swipe', 'long_press', 'input_text', 'press_key', 'adb_shell')

# 坐标系固定为观测帧的像素坐标（左上角原点），与截图尺寸一致。
MAX_COORDINATE = 10000
MIN_SWIPE_DISTANCE = 10        # 与 Control.swipe 的距离检查保持一致
FRAME_CHANGED_THRESHOLD = 1.0  # 32×32 灰度平均差，0-255 量纲；静止帧实测噪声 ≤0.1
STATUS_BAR_RATIO = 0.06        # 比对前裁掉状态栏，避免时钟跳变被判成画面变化
SIGNATURE_SIZE = 32
MAX_FRAMES_PER_INSTANCE = 20
MAX_SHELL_OUTPUT = 4000

# input text 由设备端 sh 执行，只放行不会触发 shell 解析的字符。
TEXT_PATTERN = re.compile(r'^[A-Za-z0-9 .,_:/@+\-=]*$')
SHELL_ARGUMENT_PATTERN = re.compile(r'^[A-Za-z0-9_.:/-]+$')

KEYCODES = {
    'HOME': 3, 'BACK': 4, 'CALL': 5, 'ENDCALL': 6, 'VOLUME_UP': 24,
    'VOLUME_DOWN': 25, 'POWER': 26, 'CAMERA': 27, 'TAB': 61, 'SPACE': 62,
    'ENTER': 66, 'DEL': 67, 'MENU': 82, 'NOTIFICATION': 83, 'SEARCH': 84,
    'PLAY_PAUSE': 85, 'STOP': 86, 'NEXT': 87, 'PREVIOUS': 88, 'MUTE': 91,
    'PAGE_UP': 92, 'PAGE_DOWN': 93, 'ESCAPE': 111, 'FORWARD_DEL': 112,
    'MOVE_HOME': 122, 'MOVE_END': 123, 'SLEEP': 223, 'WAKEUP': 224,
    'APP_SWITCH': 187,
}

# 只放行只读诊断命令；控制类命令必须走专用工具，避免对状态产生隐式修改。
ADB_SHELL_ALLOWED = {
    'dumpsys': {'window', 'activity', 'display', 'battery', 'package', 'input'},
    'getprop': None,
    'wm': {'size', 'density'},
    'pm': {'list', 'path'},
}
MAX_SHELL_ARGUMENTS = 6


class DeviceOperationError(Exception):
    """设备子进程内可携带稳定错误码的失败。"""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def frame_root():
    """观测帧记录目录；指向项目 cache 下的专用子目录。"""
    return Path('cache') / 'mcp_frames'


def frame_path(instance, frame_id):
    return frame_root() / instance / f'{frame_id}.json'


def save_frame(instance, record):
    """落盘一帧的元数据与灰度签名，并淘汰该实例的旧记录。"""
    directory = frame_root() / instance
    directory.mkdir(parents=True, exist_ok=True)
    frame_path(instance, record['frame_id']).write_text(
        json.dumps(record, ensure_ascii=False), encoding='utf-8')
    records = sorted(directory.glob('*.json'), key=lambda item: item.stat().st_mtime,
                     reverse=True)
    for stale in records[MAX_FRAMES_PER_INSTANCE:]:
        try:
            stale.unlink()
        except OSError:
            pass


def load_frame(instance, frame_id):
    """读取观测帧记录；不存在或已淘汰时返回 None。"""
    if not re.fullmatch(r'[0-9a-f]{32}', frame_id or ''):
        return None
    path = frame_path(instance, frame_id)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def clear_frames(instance=None):
    """清理观测帧缓存；仅供测试与实例删除时回收。"""
    targets = [frame_root() / instance] if instance else [frame_root()]
    for target in targets:
        shutil.rmtree(target, ignore_errors=True)


def compare_signature(before, after):
    """返回两帧灰度签名的平均绝对差（0-255），用于判断画面是否变化。"""
    if not before or not after or len(before) != len(after):
        return None
    total = sum(abs(int(a) - int(b)) for a, b in zip(before, after))
    return round(total / len(before), 3)


def frame_changed(difference):
    return None if difference is None else difference >= FRAME_CHANGED_THRESHOLD


def ensure_point(x, y, width, height):
    """校验坐标落在当前观测帧内。"""
    if not (0 <= x < width and 0 <= y < height):
        raise DeviceOperationError(
            'OUT_OF_RANGE', f'坐标 ({x}, {y}) 超出当前画面 {width}×{height}',
            {'x': x, 'y': y, 'width': width, 'height': height,
             'hint': '坐标须使用 azurpilot_observe_device 返回帧的像素坐标'})


def ensure_swipe(x1, y1, x2, y2, width, height):
    ensure_point(x1, y1, width, height)
    ensure_point(x2, y2, width, height)
    if abs(x1 - x2) + abs(y1 - y2) < MIN_SWIPE_DISTANCE:
        raise DeviceOperationError(
            'INVALID_PARAMS', f'滑动距离小于 {MIN_SWIPE_DISTANCE}px，设备会按点击处理',
            {'from': [x1, y1], 'to': [x2, y2], 'minimum': MIN_SWIPE_DISTANCE})


def escape_text(text):
    """把文本转成 `input text` 可安全接收的形式；空格使用 %s 占位。"""
    if not text:
        raise DeviceOperationError('INVALID_PARAMS', 'text 不能为空')
    if not TEXT_PATTERN.fullmatch(text):
        rejected = sorted({char for char in text if not TEXT_PATTERN.fullmatch(char)})
        raise DeviceOperationError(
            'UNSUPPORTED_TEXT', '文本包含设备端 sh 无法安全传入的字符，请改用 ASCII 字母数字与常用标点',
            {'rejected': rejected[:10],
             'allowed': '字母、数字、空格与 ., _ : / @ + - ='})
    return text.replace(' ', '%s')


def keycode(key):
    if key not in KEYCODES:
        raise DeviceOperationError('INVALID_PARAMS', f'不支持的按键：{key}',
                                   {'allowed': sorted(KEYCODES)})
    return KEYCODES[key]


def validate_shell(argv):
    """校验受限诊断命令，返回可直接交给 adb shell 的参数列表。"""
    if not 1 <= len(argv) <= MAX_SHELL_ARGUMENTS:
        raise DeviceOperationError('INVALID_PARAMS', f'命令参数数量须在 1-{MAX_SHELL_ARGUMENTS} 之间')
    for argument in argv:
        if not SHELL_ARGUMENT_PATTERN.fullmatch(argument or ''):
            raise DeviceOperationError(
                'ADB_SHELL_DENIED', f'命令参数包含不允许的字符：{argument!r}',
                {'argument': argument})
    command, allowed = argv[0], ADB_SHELL_ALLOWED.get(argv[0])
    if command not in ADB_SHELL_ALLOWED:
        raise DeviceOperationError(
            'ADB_SHELL_DENIED', f'命令 {command} 不在诊断白名单内',
            {'command': command, 'allowed': sorted(ADB_SHELL_ALLOWED)})
    if allowed is not None and len(argv) > 1 and argv[1] not in allowed:
        raise DeviceOperationError(
            'ADB_SHELL_DENIED', f'{command} 不支持子命令 {argv[1]}',
            {'command': command, 'subcommand': argv[1], 'allowed': sorted(allowed)})
    return list(argv)


def truncate(text, limit=MAX_SHELL_OUTPUT):
    text = text or ''
    return text[:limit], len(text) > limit


def isoformat(timestamp=None):
    from datetime import datetime, timezone
    moment = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp else \
        datetime.now(timezone.utc)
    return moment.isoformat()


def now():
    return time.time()
