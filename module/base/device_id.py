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


def _get_mac_address() -> str:
    try:
        import uuid
        mac = uuid.getnode()
        # uuid.getnode() 在无法获取时会返回随机值（第8位为1）
        if (mac >> 40) % 2:
            return ''
        return ':'.join(f'{(mac >> i) & 0xff:02x}' for i in range(40, -1, -8))
    except Exception:
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

    mac = _get_mac_address()
    if mac:
        parts.append(f'mac={mac}')
    
    parts.append(f'platform={platform.node()}-{platform.machine()}')
    
    return '|'.join(parts)


def generate_device_id() -> str:
    """
    基于硬件指纹生成唯一设备ID
    
    使用 SHA-256 对硬件指纹进行哈希，取前 32 位十六进制字符
    保证同一台物理机器始终生成相同的 ID
    
    Returns:
        str: 32位十六进制字符串作为设备唯一标识
    """
    fingerprint = _collect_hardware_fingerprint()
    device_id = hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:32]
    logger.info(f'Hardware fingerprint components: {len(fingerprint.split("|"))} items')
    return device_id



_device_id: Optional[str] = None
_refresh_timer: Optional[threading.Timer] = None
_REFRESH_INTERVAL = 300  # 5 分钟 = 300 秒


def get_device_id() -> str:
    global _device_id
    if _device_id is None:
        _device_id = _init_device_id()
    return _device_id


def _init_device_id() -> str:
    """
    初始化设备 ID：始终由硬件信息生成，并立即覆写文件
    同时启动后台定时刷新线程
    
    Returns:
        str: 设备ID
    """
    device_id = generate_device_id()
    
    project_root = Path(__file__).resolve().parents[2]
    device_id_file = project_root / 'log' / 'device_id.json'
    
    # 立即覆写一次
    _overwrite_device_id(device_id, device_id_file)
    logger.info(f'Device ID initialized from hardware: {device_id[:8]}...')
    
    # 启动后台定时覆写
    _start_refresh_timer(device_id, device_id_file)
    
    return device_id


def _overwrite_device_id(device_id: str, file_path: Path):
    """
    强制覆写 device_id.json（无论文件当前内容如何）
    
    这是防篡改的核心：即使文件被外部修改，每 5 分钟也会被
    硬件生成的正确 ID 覆盖回来
    
    Args:
        device_id: 正确的设备ID
        file_path: JSON 文件路径
    """
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'device_id': device_id,
            '_generated_by': 'hardware_fingerprint',
            '_last_refresh': time.strftime('%Y-%m-%d %H:%M:%S'),
            '_warning': 'This file is auto-generated and overwritten every 5 minutes. Manual edits will be lost.'
        }
        
        with file_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.debug(f'Device ID file overwritten: {file_path}')
    except Exception as e:
        logger.warning(f'Failed to overwrite device ID file {file_path}: {e}')


def _refresh_callback(device_id: str, file_path: Path):
    """
    定时器回调：覆写文件并重新调度下一次刷新
    """
    _overwrite_device_id(device_id, file_path)
    _start_refresh_timer(device_id, file_path)


def _start_refresh_timer(device_id: str, file_path: Path):
    """
    启动（或重启）后台定时器，每隔 _REFRESH_INTERVAL 秒覆写一次文件
    使用 daemon 线程，程序退出时自动停止
    """
    global _refresh_timer
    
    # 取消旧定时器（如果存在）
    if _refresh_timer is not None:
        _refresh_timer.cancel()
    
    _refresh_timer = threading.Timer(
        _REFRESH_INTERVAL,
        _refresh_callback,
        args=(device_id, file_path)
    )
    _refresh_timer.daemon = True
    _refresh_timer.start()
