"""设备工具的独立工作进程，避免设备库阻塞 ASGI 或污染实例环境变量。"""
import base64
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from module.mcp.device_contract import (
    CONTROL_OPERATIONS,
    SIGNATURE_SIZE,
    STATUS_BAR_RATIO,
    DeviceOperationError,
    compare_signature,
    ensure_point,
    ensure_swipe,
    escape_text,
    frame_changed,
    keycode,
    save_frame,
    truncate,
    validate_shell,
)

# 动作结束后等待界面稳定再取第二帧；只是采样时机，不代替业务确认。
SETTLE_SECONDS = 0.5


def adb_executable():
    """
    解析 ADB 可执行文件路径，优先级与设备连接模块保持一致。

    Returns:
        str: 可用的 ADB 路径；都已缺失时回退到 PATH 中的 adb。
    """
    import shutil
    import sys

    from module.runtime.setting import State

    candidates = []
    try:
        deploy = State.deploy_config
        configured = deploy.AdbExecutable
        if configured:
            candidates.append(os.path.abspath(os.path.join(deploy.root_filepath, configured)))
    except Exception:
        pass
    candidates.extend(os.path.abspath(path) for path in (
        './.venv/Scripts/adb.exe', './.venv/bin/adb', './bin/adb/adb.exe'))
    candidates.append(os.path.abspath(os.path.join(
        sys.executable, '../adb.exe' if os.name == 'nt' else '../adb')))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate.replace('\\', '/')
    return shutil.which('adb') or 'adb'


def adb_environment():
    """
    为 ADB 子进程准备独立的临时目录。

    Windows 上多个 ADB 版本共用 ``%TEMP%\\adb.log``，后者会被先启动的守护进程
    独占，导致 ``start-server`` 直接以权限错误退出。把 TMP 指向项目内目录可以
    避免与系统里的其他 ADB 抢同一个日志文件。

    Returns:
        dict: 注入 TMP/TEMP 的环境变量副本。
    """
    directory = Path('cache') / 'adb-tmp'
    directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment['TMP'] = environment['TEMP'] = str(directory.resolve())
    return environment


def prepare_environment():
    """把本进程的临时目录固定到项目内，让设备库内部的 adb 调用也不再抢日志文件。"""
    directory = Path('cache') / 'adb-tmp'
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('TMP', 'TEMP'):
        os.environ[name] = str(directory.resolve())


def adb_serials():
    """读取各实例配置里的串口，供重启后恢复 TCP 设备连接。"""
    serials = []
    for path in sorted(Path('config').glob('*.json')):
        if path.name in ('template.json', 'deploy.json'):
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        emulator = data.get('Alas', {}).get('Emulator', {}) if isinstance(data, dict) else {}
        serial = emulator.get('Serial') if isinstance(emulator, dict) else None
        if isinstance(serial, str) and ':' in serial and serial not in serials:
            serials.append(serial)
    return serials


def restart_adb():
    """
    重启 ADB 服务进程，并恢复此前连接过的 TCP 设备。

    kill-server 会让 ``127.0.0.1:<port>`` 这类网络设备一起掉线，必须重新 connect，
    否则重启 ADB 反而会让实例失去设备。

    Returns:
        dict: 包含 ADB 路径、重连结果与当前在线设备列表的字典。
    """
    adb = adb_executable()
    environment = adb_environment()
    for command in ('kill-server', 'start-server'):
        subprocess.run([adb, command], check=True, timeout=20, env=environment,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    reconnected = []
    for serial in adb_serials():
        result = subprocess.run([adb, 'connect', serial], capture_output=True, text=True,
                                timeout=20, env=environment)
        if result.returncode == 0 and 'connected' in result.stdout:
            reconnected.append(serial)
    listing = subprocess.run([adb, 'devices'], capture_output=True, text=True,
                             timeout=20, env=environment)
    devices = [line.split()[0] for line in listing.stdout.splitlines()[1:]
               if line.strip() and line.split()[-1] == 'device']
    return {'scope': 'global', 'adb_restarted': True, 'adb_path': adb,
            'reconnected': reconnected, 'devices': devices,
            'text': f'Restarted ADB service using {adb}; online: {devices}'}


def capture(device, instance):
    """
    采集一帧画面并登记观测帧记录。

    Args:
        device: 已初始化的 Device 实例。
        instance (str): 实例名称，用于隔离帧缓存。

    Returns:
        dict: 含 JPEG base64、帧标识、尺寸、方向、采集时间、后端与灰度签名。
    """
    from PIL import Image

    buffered = BytesIO()
    image = Image.fromarray(device.screenshot())
    width, height = image.size
    # 状态栏的时钟与电量会自然跳动，不裁掉会让「画面未变化」误判为已变化。
    body = image.convert('L').crop((0, int(height * STATUS_BAR_RATIO), width, height))
    signature = list(body.resize((SIGNATURE_SIZE, SIGNATURE_SIZE), Image.BILINEAR).tobytes())
    frame_id = uuid.uuid4().hex
    record = {
        'frame_id': frame_id,
        'instance': instance,
        'width': width,
        'height': height,
        'orientation': 'landscape' if width >= height else 'portrait',
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'cached': False,
        'backend': str(device.config.Emulator_ScreenshotMethod),
        'signature': signature,
    }
    save_frame(instance, record)
    image.save(buffered, format='JPEG')
    return {
        'image': base64.b64encode(buffered.getvalue()).decode('ascii'),
        'frame_id': frame_id,
        'width': width,
        'height': height,
        'orientation': record['orientation'],
        'captured_at': record['captured_at'],
        'cached': False,
        'backend': record['backend'],
        'signature': signature,
    }


def verify_observation(record, current):
    """
    比对观测帧与当前画面尺寸；方向或尺寸变化即视为观测失效。

    Args:
        record (dict): 之前的观测帧记录。
        current (dict): 本次采集的当前帧。

    Raises:
        DeviceOperationError: 画面尺寸或方向已变化时抛出。
    """
    if (record['width'], record['height']) != (current['width'], current['height']):
        raise DeviceOperationError(
            'STALE_OBSERVATION',
            '设备画面尺寸已变化，原观测帧的坐标不再可靠；请重新观测后再操作',
            {'observed': [record['width'], record['height']],
             'current': [current['width'], current['height']]})
    if record['orientation'] != current['orientation']:
        raise DeviceOperationError(
            'STALE_OBSERVATION', '设备方向已变化，原观测帧的坐标不再可靠；请重新观测后再操作',
            {'observed': record['orientation'], 'current': current['orientation']})


def dispatch_control(device, operation, params, width, height):
    """
    在真实设备上执行输入动作。

    Args:
        device: 已初始化的 Device 实例。
        operation (str): click / swipe / long_press / input_text / press_key / adb_shell。
        params (dict): 工具参数。
        width (int): 当前画面宽度。
        height (int): 当前画面高度。

    Returns:
        dict: 附加到结果中的动作明细。

    Raises:
        DeviceOperationError: 参数越界或不支持的按键/命令时抛出。
    """
    if operation == 'click':
        x, y = int(params['x']), int(params['y'])
        ensure_point(x, y, width, height)
        method = device.config.Emulator_ControlMethod
        device.click_methods.get(method, device.click_adb)(x, y)
        return {'target': [x, y], 'control_method': method}

    if operation == 'swipe':
        x1, y1, x2, y2 = (int(params[key]) for key in ('x1', 'y1', 'x2', 'y2'))
        ensure_swipe(x1, y1, x2, y2, width, height)
        duration = params.get('duration_ms', 300) / 1000
        device.swipe((x1, y1), (x2, y2), duration=duration, name='MCP_SWIPE')
        return {'from': [x1, y1], 'to': [x2, y2],
                'duration_ms': params.get('duration_ms', 300),
                'control_method': device.config.Emulator_ControlMethod}

    if operation == 'long_press':
        x, y = int(params['x']), int(params['y'])
        ensure_point(x, y, width, height)
        duration = params.get('duration_ms', 1000) / 1000
        from module.base.button import Button

        button = Button(area=(x, y, x + 1, y + 1), color=(0, 0, 0),
                        button=(x, y, x + 1, y + 1), name=f'MCP_LONG_PRESS_{x}_{y}')
        device.long_click(button, duration=duration)
        return {'target': [x, y], 'duration_ms': params.get('duration_ms', 1000),
                'control_method': device.config.Emulator_ControlMethod}

    if operation == 'input_text':
        # 默认不追加确认键：是否需要回车由调用方用 azurpilot_press_key 明确表达。
        device.adb_shell(['input', 'text', escape_text(params['text'])], timeout=15)
        return {'text_length': len(params['text']), 'confirm_key_sent': False}

    if operation == 'press_key':
        code = keycode(params['key'])
        device.adb_shell(['input', 'keyevent', str(code)], timeout=15)
        return {'key': params['key'], 'keycode': code}

    raise DeviceOperationError('INVALID_PARAMS', f'未知控制动作：{operation}')


def diagnose(device, params):
    """
    执行受限只读诊断命令；不采集画面，也不改变设备状态。

    Args:
        device: 已初始化的 Device 实例。
        params (dict): 含 argv 与 timeout_ms 的参数。

    Returns:
        dict: 命令输出与执行明细。
    """
    argv = validate_shell(params['argv'])
    timeout = min(params.get('timeout_ms', 10000) / 1000, 20)
    output, clipped = truncate(device.adb_shell(argv, timeout=timeout))
    return {'frame_id': None, 'width': None, 'height': None, 'frame_changed': None,
            'frame_difference': None, 'observation_verified': False,
            'detail': {'argv': argv}, 'output': output, 'truncated': clipped}


def perform(operation, instance, params=None):
    """
    在工作进程中执行具体的设备或模拟器操作。

    Args:
        operation: 操作指令类型，如 'restart_adb'、'restart_emulator'、'get_screenshot'。
        instance: Alas 实例配置名称。
        params: 与控制类操作相关的参数字典。

    Returns:
        dict: 包含文本或 base64 图像数据的执行结果字典。

    Raises:
        ValueError: 当操作指令不受支持时抛出。
        DeviceOperationError: 参数越界、观测失效或命令被拒绝时抛出。
    """
    params = params or {}
    prepare_environment()
    if operation == 'restart_adb':
        return restart_adb()
    os.environ['ALAS_CONFIG_NAME'] = instance
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

    device = Device(AzurLaneConfig(instance))
    if operation == 'restart_emulator':
        device.emulator_stop()
        # 保留上游平台退出缓冲；整个步骤受父进程硬超时约束。
        time.sleep(60)
        device.emulator_start()
        return {'text': f'Success: Restarted emulator for {instance}'}
    if operation == 'get_screenshot':
        return capture(device, instance)
    if operation not in CONTROL_OPERATIONS:
        raise ValueError('未知设备操作')
    if operation == 'adb_shell':
        return diagnose(device, params)

    current = capture(device, instance)
    observed = params.get('frame_id')
    if observed:
        from module.mcp.device_contract import load_frame

        record = load_frame(instance, observed)
        if record is None:
            raise DeviceOperationError(
                'STALE_OBSERVATION', '观测帧不存在或已淘汰，请重新观测后再操作',
                {'frame_id': observed})
        verify_observation(record, current)

    try:
        detail = dispatch_control(device, operation, params,
                                  current['width'], current['height'])
    except Exception as exc:
        # 动作是否已下发不确定：把当前帧带回，供调用方先观测再决定。
        if isinstance(exc, DeviceOperationError):
            exc.details = {**(exc.details or {}), 'frame_id': current['frame_id']}
        raise

    if not params.get('verify', True):
        return {'frame_id': current['frame_id'], 'width': current['width'],
                'height': current['height'], 'frame_changed': None,
                'frame_difference': None, 'observation_verified': bool(observed),
                'detail': detail}

    time.sleep(SETTLE_SECONDS)
    after = capture(device, instance)
    difference = compare_signature(current['signature'], after['signature'])
    return {'frame_id': after['frame_id'], 'width': after['width'],
            'height': after['height'],
            'frame_changed': frame_changed(difference),
            'frame_difference': difference,
            'observation_verified': bool(observed),
            'detail': detail}


def execute(operation, instance, params, result_path):
    """
    执行设备操作并将结果序列化写入临时文件供父进程读取。

    Args:
        operation: 操作类型名称。
        instance: 实例名称。
        params: 操作参数。
        result_path: 结果保存的绝对路径。
    """
    try:
        result = perform(operation, instance, params)
    except DeviceOperationError as exc:
        result = {'error': exc.message, 'code': exc.code, 'details': exc.details}
    except Exception as exc:
        result = {'error': str(exc)}
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
