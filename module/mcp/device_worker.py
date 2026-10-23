"""设备工具的独立工作进程，避免设备库阻塞 ASGI 或污染实例环境变量。"""
import base64
import json
import os
import subprocess
import time
from io import BytesIO
from pathlib import Path


def restart_adb():
    """
    重启 ADB 服务进程。

    优先寻找部署配置或虚拟环境中的 ADB 二进制，依次执行 kill-server 和 start-server。

    Returns:
        dict: 包含执行结果描述的字典。
    """
    from module.runtime.setting import State

    adb_path = State.deploy_config.AdbExecutable
    adb_path = adb_path.replace('\\', '/') if adb_path else ''
    if not adb_path or not os.path.exists(adb_path):
        adb_path = next((os.path.abspath(path) for path in (
            './.venv/Scripts/adb.exe', './.venv/bin/adb', './bin/adb/adb.exe'
        ) if os.path.exists(path)), 'adb')
    for command in ('kill-server', 'start-server'):
        subprocess.run([adb_path, command], check=True, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {'text': f'Success: Restarted ADB service using {adb_path}.'}


def perform(operation, instance):
    """
    在工作进程中执行具体的设备或模拟器操作。

    Args:
        operation: 操作指令类型，如 'restart_adb'、'restart_emulator'、'get_screenshot'。
        instance: Alas 实例配置名称。

    Returns:
        dict: 包含文本或 base64 图像数据的执行结果字典。

    Raises:
        ValueError: 当操作指令不受支持时抛出。
    """
    if operation == 'restart_adb':
        return restart_adb()
    os.environ['ALAS_CONFIG_NAME'] = instance
    from module.config.config import AzurLaneConfig
    config = AzurLaneConfig(instance)
    if operation == 'restart_emulator':
        # 显式手动管理不依赖 ADB 在线，也不受异常自动重启开关限制。
        from module.device.platform import Platform
        platform = Platform(config, connect=False)
        stopped = platform.emulator_stop()
        if stopped is False:
            raise RuntimeError('手动停止模拟器失败')
        # 保留原有平台退出缓冲；整个步骤受父进程硬超时约束。
        time.sleep(60)
        started = platform.emulator_start()
        if started is False:
            raise RuntimeError('手动启动模拟器失败')
        if stopped is None or started is None:
            return {'text': f'已执行 {instance} 的重启调用；平台未返回完成确认，请检查设备连接'}
        return {'text': f'Success: Restarted emulator for {instance}'}
    from module.device.device import Device
    device = Device(config)
    if operation == 'get_screenshot':
        from PIL import Image
        import PIL.JpegImagePlugin  # noqa: F401

        buffered = BytesIO()
        Image.fromarray(device.screenshot()).save(buffered, format='JPEG')
        return {'image': base64.b64encode(buffered.getvalue()).decode('ascii')}
    raise ValueError('未知设备操作')


def execute(operation, instance, result_path):
    """
    执行设备操作并将结果序列化写入临时文件供父进程读取。

    Args:
        operation: 操作类型名称。
        instance: 实例名称。
        result_path: 结果保存的绝对路径。
    """
    try:
        result = perform(operation, instance)
    except Exception as exc:
        result = {'error': str(exc)}
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
