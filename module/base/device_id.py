"""
Device ID 管理模块
"""
import hashlib
import json
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from module.logger import logger

def _wmic_query(wmic_class: str, field: str) -> str:
    """
    通过 WMIC 查询 Windows 硬件信息
    
    Args:
        wmic_class: WMI 类名 (例如 'baseboard', 'cpu')
        field: 要查询的字段名
        
    Returns:
        str: 查询结果字符串，失败返回空字符串
    """
    try:
        result = subprocess.run(
            ['wmic', wmic_class, 'get', field],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0
        )
        lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        if len(lines) >= 2:
            return lines[1]
    except Exception:
        pass
    return ''

def _collect_hardware_fingerprint() -> str:
    parts = []
    
    if platform.system() == 'Windows':
        hw_queries = [
            ('baseboard', 'serialnumber'),
            ('cpu', 'processorid'),
            ('bios', 'serialnumber'),
            ('diskdrive', 'serialnumber'),
        ]
        for cls, field in hw_queries:
            val = _wmic_query(cls, field)
            if val and val.lower() not in ('to be filled by o.e.m.', 'default string', 'none', ''):
                parts.append(f'{cls}.{field}={val}')
    else:
        for mid_path in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                mid = Path(mid_path).read_text().strip()
                if mid:
                    parts.append(f'machine-id={mid}')
                    break
            except Exception:
                pass

        if platform.system() == 'Darwin':
            try:
                result = subprocess.run(
                    ['system_profiler', 'SPHardwareDataType'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.splitlines():
                    if 'Hardware UUID' in line:
                        parts.append(f'hw-uuid={line.split(":")[-1].strip()}')
                        break
            except Exception:
                pass

    # 已完全舍弃 MAC 地址依赖
    parts.append(f'platform={platform.node()}-{platform.machine()}')
    
    return '|'.join(parts)


def generate_device_id() -> str:
    """
    基于硬件指纹生成唯一设备ID
    """
    fingerprint = _collect_hardware_fingerprint()
    device_id = hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:32]
    return device_id


_device_id: Optional[str] = None
_old_device_id: Optional[str] = None # 用于记录迁移前的旧 ID
_refresh_timer: Optional[threading.Timer] = None
_REFRESH_INTERVAL = 300


def get_device_id() -> str:
    global _device_id
    if _device_id is None:
        _device_id = _init_device_id()
    return _device_id


def get_old_device_id() -> Optional[str]:
    """
    获取迁移前的旧 ID
    """
    global _old_device_id
    return _old_device_id


def _init_device_id() -> str:
    global _old_device_id
    device_id = generate_device_id()
    
    project_root = Path(__file__).resolve().parents[2]
    device_id_file = project_root / 'log' / 'device_id.json'
    
    # 自动识别变更并暂存旧 ID 用于数据库热迁移
    if device_id_file.exists():
        try:
            with device_id_file.open('r', encoding='utf-8') as f:
                old_data = json.load(f)
                stored_id = old_data.get('device_id')
                if stored_id and stored_id != device_id:
                    _old_device_id = stored_id
                    logger.info(f'Device ID change detected for migration! Old: {stored_id[:8]}, New: {device_id[:8]}')
        except Exception:
            pass

    # 立即覆写新 ID
    _overwrite_device_id(device_id, device_id_file)
    logger.info(f'Device ID initialized: {device_id[:8]}...')
    
    _start_refresh_timer(device_id, device_id_file)
    
    return device_id


def _overwrite_device_id(device_id: str, file_path: Path):
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'device_id': device_id,
            '_generated_by': 'hardware_fingerprint_v2_no_mac',
            '_last_refresh': time.strftime('%Y-%m-%d %H:%M:%S'),
            '_warning': 'This file is auto-generated and overwritten every 5 minutes.'
        }
        with file_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f'Failed to overwrite device ID file: {e}')


def _refresh_callback(device_id: str, file_path: Path):
    _overwrite_device_id(device_id, file_path)
    _start_refresh_timer(device_id, file_path)


def _start_refresh_timer(device_id: str, file_path: Path):
    global _refresh_timer
    if _refresh_timer is not None:
        _refresh_timer.cancel()
    _refresh_timer = threading.Timer(_REFRESH_INTERVAL, _refresh_callback, args=(device_id, file_path))
    _refresh_timer.daemon = True
    _refresh_timer.start()
