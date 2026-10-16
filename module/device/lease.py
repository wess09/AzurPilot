"""按物理设备互斥；锁跨配置、工作区和进程，进程退出由操作系统释放。"""
import hashlib
import os
import tempfile
import threading
from pathlib import Path

from module.device.method.utils import get_serial_pair
from module.exception import RequestHumanTakeover

_guard = threading.RLock()
_held = {}


def device_key(serial):
    """只统一有协议依据的同设备别名，不把邻近 MuMu 端口当成同一台。"""
    serial = str(serial).strip().replace('localhost:', '127.0.0.1:')
    return get_serial_pair(serial)[0] or serial


class DeviceLease:
    def __init__(self, serial, owner, directory=None):
        self.key, self.owner, self.released = device_key(serial), str(owner), True
        root = Path(directory or tempfile.gettempdir()) / 'azurpilot-device-locks'
        with _guard:
            previous = _held.get(self.key)
            if previous:
                if previous['owner'] != self.owner:
                    raise RequestHumanTakeover('该物理设备已有其他实例控制，请先停止占用实例')
                previous['count'] += 1
            else:
                root.mkdir(parents=True, exist_ok=True)
                file = (root / (hashlib.sha256(self.key.encode()).hexdigest() + '.lock')).open('a+b')
                try:
                    if file.tell() == 0:
                        file.write(b'0')
                        file.flush()
                    file.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    file.close()
                    raise RequestHumanTakeover('该物理设备已有其他进程控制，请先停止占用实例') from exc
                _held[self.key] = dict(file=file, owner=self.owner, count=1)
            self.released = False

    def release(self):
        """重复释放无副作用；同实例多个 Device 引用共用一份操作系统锁。"""
        with _guard:
            if self.released:
                return
            self.released = True
            entry = _held[self.key]
            entry['count'] -= 1
            if entry['count'] == 0:
                entry['file'].close()
                del _held[self.key]
