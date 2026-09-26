"""项目外的本机自动解锁密钥；软件绑定不具有 TPM 的硬件防复制能力。"""
import base64
import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path

from Crypto.Cipher import AES

from module.api.protocol import ApiError


def is_local(blob):
    try:
        return isinstance(blob, bytes) and json.loads(blob).get('provider') == 'local'
    except (ValueError, AttributeError, UnicodeError):
        return False


def dpapi(data, decrypt=False):
    """DPAPI 仅绑定当前 Windows 用户；输入和输出不进入命令行或日志。"""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    incoming, outgoing = Blob(len(data), source), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
            raise ValueError()
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(source, 0, len(data))
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(outgoing.data)


class LocalProtector:
    def __init__(self, root, instance):
        self.root, self.instance = Path(root).resolve(), instance
        self.context = hashlib.sha256((str(self.root) + '\0' + instance).encode()).hexdigest()

    @staticmethod
    def key_directory():
        if os.name == 'nt':
            return Path.home() / 'AppData' / 'Local' / 'AzurPilot' / 'account-keys'
        if sys.platform == 'linux':
            return Path.home() / '.local' / 'share' / 'azurpilot' / 'account-keys'
        raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机自动解锁目前支持 Windows 和 Linux')

    @staticmethod
    def host_identity():
        if os.name == 'nt':
            from module.runtime.account_tpm import TpmProtector
            # MachineGuid 检测迁移；实际用户保护由 DPAPI 完成。
            identity = TpmProtector.host_identity()
            result = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'], capture_output=True,
                                    timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            sid = re.search(rb'S-1-[0-9-]+', result.stdout)
            if result.returncode or sid is None:
                raise ApiError('LOCAL_KEY_UNAVAILABLE', '无法确认当前 Windows 用户身份')
            identity += '\0' + sid.group().decode('ascii')
        elif sys.platform == 'linux':
            identity = ''
            for name in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
                try:
                    candidate = Path(name).read_text().strip()
                except OSError:
                    continue
                if re.fullmatch(r'[0-9a-fA-F]{32}', candidate):
                    identity = candidate + '\0' + str(os.geteuid())
                    break
            if not identity:
                raise ApiError('LOCAL_KEY_UNAVAILABLE', '无法读取有效 Linux machine-id，已拒绝本机自动解锁')
        else:
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机自动解锁目前支持 Windows 和 Linux')
        return hashlib.sha256(identity.encode()).hexdigest()

    def path(self, key_id):
        if not re.fullmatch(r'[0-9a-f]{32}', key_id):
            raise ValueError()
        directory = self.key_directory()
        if directory.resolve().is_relative_to(self.root):
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机密钥目录不能位于项目内')
        # 拒绝链接与 Windows junction，防止写入路径被引导到项目或共享目录。
        for parent in (directory, *directory.parents):
            if parent.is_symlink() or parent.is_junction():
                raise ValueError()
        path = directory / (self.context + '-' + key_id + '.key')
        if path.is_symlink() or path.is_junction():
            raise ValueError()
        return path

    def prepare_directory(self, directory):
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if os.name == 'nt':
            script = r'''
$ErrorActionPreference = 'Stop'
try {
    $path = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    [System.IO.DirectoryInfo]::new($path).SetAccessControl($acl)
} catch { exit 1 }
'''
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    input=json.dumps(str(directory)).encode(), capture_output=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError()
        else:
            if directory.stat().st_uid != os.geteuid():
                raise ValueError()
            directory.chmod(0o700)

    def load(self, key_id):
        path = self.path(key_id)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags), 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise ValueError()
            if os.name != 'nt':
                directory = path.parent.stat()
                if (info.st_uid != os.geteuid() or info.st_mode & 0o077
                        or directory.st_uid != os.geteuid() or directory.st_mode & 0o077):
                    raise ValueError()
            data = file.read(4097)
        key = dpapi(data, decrypt=True) if os.name == 'nt' else data
        if len(key) != 32:
            raise ValueError()
        return key

    def binding(self, blob):
        binding = json.loads(blob)
        if binding['provider'] != 'local' or binding['version'] != 1:
            raise ValueError()
        if binding['host'] != self.host_identity():
            raise ApiError('LOCAL_DEVICE_CHANGED', '本机自动解锁的主机或用户身份已改变')
        return binding

    def wrap(self, key, previous=None):
        from module.runtime.account_vault import SecretKey
        secret = None
        path = None
        created = False
        try:
            host = self.host_identity()
            key_id = self.binding(previous)['id'] if previous else uuid.uuid4().hex
            path = self.path(key_id)
            if previous:
                secret = SecretKey(self.load(key_id))
            else:
                self.prepare_directory(path.parent)
                secret = SecretKey(os.urandom(32))
                data = dpapi(secret.value) if os.name == 'nt' else secret.value
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600), 'wb') as file:
                    created = True
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
            cipher = AES.new(secret.value, AES.MODE_GCM, nonce=os.urandom(12))
            cipher.update(f'AzurPilot/local/v1/{host}/{self.context}/{key_id}'.encode())
            ciphertext, tag = cipher.encrypt_and_digest(key)
            return json.dumps({'provider': 'local', 'version': 1, 'host': host, 'id': key_id,
                               'nonce': base64.b64encode(cipher.nonce).decode(), 'tag': base64.b64encode(tag).decode(),
                               'payload': base64.b64encode(ciphertext).decode()}).encode()
        except Exception:
            if created and path is not None:
                from module.runtime.account_vault import AccountVault
                AccountVault.wipe_file(path)
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '无法建立本机自动解锁，请检查用户密钥目录、权限及系统加密服务') from None
        finally:
            if secret is not None:
                secret.clear()

    def unwrap(self, blob):
        from module.runtime.account_vault import SecretKey
        secret = None
        try:
            binding = self.binding(blob)
            secret = SecretKey(self.load(binding['id']))
            cipher = AES.new(secret.value, AES.MODE_GCM, nonce=base64.b64decode(binding['nonce'], validate=True))
            cipher.update(f"AzurPilot/local/v1/{binding['host']}/{self.context}/{binding['id']}".encode())
            key = cipher.decrypt_and_verify(base64.b64decode(binding['payload'], validate=True),
                                            base64.b64decode(binding['tag'], validate=True))
            if len(key) != 32:
                raise ValueError()
            return key
        except ApiError:
            raise
        except Exception:
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机密钥丢失、权限不安全或封装失效；启动已阻止，可用实例密码解除绑定后重建') from None
        finally:
            if secret is not None:
                secret.clear()

    def remove(self, blob):
        from module.runtime.account_vault import AccountVault
        binding = json.loads(blob)
        AccountVault.wipe_file(self.path(binding['id']))
