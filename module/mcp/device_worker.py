"""设备工具的独立工作进程，避免设备库阻塞 ASGI 或污染实例环境变量。"""
import base64
import json
import os
import subprocess
import time
from io import BytesIO
from pathlib import Path


def restart_adb():
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
        from PIL import Image
        import PIL.JpegImagePlugin  # noqa: F401

        buffered = BytesIO()
        Image.fromarray(device.screenshot()).save(buffered, format='JPEG')
        return {'image': base64.b64encode(buffered.getvalue()).decode('ascii')}
    raise ValueError('未知设备操作')


def execute(operation, instance, result_path):
    try:
        result = perform(operation, instance)
    except Exception as exc:
        result = {'error': str(exc)}
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
