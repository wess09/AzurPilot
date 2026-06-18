import os
import sys
import typing as t
import subprocess

from pydantic import BaseModel

from module.base.decorator import cached_property, del_cached_property
from module.device.connection import Connection
from module.device.method.utils import get_serial_pair
from module.device.platform.emulator_base import EmulatorInstanceBase, EmulatorManagerBase, remove_duplicated_path
from module.logger import logger
from module.map.map_grids import SelectedGrids


class EmulatorInfo(BaseModel):
    """模拟器信息配置模型。"""
    emulator: str = ''
    name: str = ''
    path: str = ''

    # 用于 chinac.com 云手机平台的 API
    # access_key: SecretStr = ''
    # secret: SecretStr = ''


def serial_to_id(serial: str):
    """
    根据 serial 推算实例 ID。
    例如:
        "127.0.0.1:16384" -> 0
        "127.0.0.1:16416" -> 1
        端口 16414 到 16418 -> 1

    Returns:
        int: 实例 ID，推算失败则返回 None
    """
    try:
        port = int(serial.split(':')[1])
    except (IndexError, ValueError):
        return None
    index, offset = divmod(port - 16384 + 16, 32)
    offset -= 16
    if 0 <= index < 32 and offset in [-2, -1, 0, 1, 2]:
        return index
    else:
        return None


class PlatformBase(Connection, EmulatorManagerBase):
    """
    平台基类，平台可以是不同操作系统或云手机服务。
    每个 `Platform` 子类必须实现以下 API:
    - all_emulators()
    - all_emulator_instances()
    - emulator_start()
    - emulator_stop()
    """

    def __init__(self, config, *, connect: bool = True):
        """
        Args:
            config: AzurLaneConfig 实例或配置名称
            connect: 是否立即建立 ADB 连接
        """
        if connect:
            super().__init__(config)
        else:
            from module.device.connection_attr import ConnectionAttr
            ConnectionAttr.__init__(self, config)

    def emulator_start(self):
        """
        启动模拟器，直到启动完成。
        - 需要支持重试。
        - 禁止使用无聊的 sleep 来等待启动。
        """
        logger.info(f'Current platform {sys.platform} does not support emulator_start, skip')

    def emulator_stop(self):
        """
        停止模拟器。
        """
        logger.info(f'Current platform {sys.platform} does not support emulator_stop, skip')

    def run_remote_ssh_command(self, command=None):
        """
        通过远程 SSH 执行命令。

        Args:
            command: 要执行的远程命令
        """
        if not getattr(self.config, 'EmulatorInfo_EnableRemoteSSH', False):
            logger.info('Remote SSH is not enabled (EnableRemoteSSH=False), skip')
            return

        host = self.config.EmulatorInfo_RemoteSSHHost
        port = self.config.EmulatorInfo_RemoteSSHPort
        user = self.config.EmulatorInfo_RemoteSSHUser
        key = getattr(self.config, 'EmulatorInfo_RemoteSSHPublicKey', '')

        if not command:
            logger.warning('No SSH command provided, skip')
            return

        if not host:
            logger.warning(f'RemoteSSHHost is empty, skip remote SSH command: {command}')
            return

        logger.hr('Remote SSH Command', level=1)
        target = f'{user}@{host}' if user else host
        # -n: 将 stdin 重定向到 /dev/null
        # -T: 禁用伪终端分配
        # BatchMode: 避免在密码提示时挂起
        cmd = ['ssh', '-n', '-T', '-p', str(port), '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']

        key_file = None
        if key and len(key) > 50:
            import tempfile
            try:
                fd, key_file = tempfile.mkstemp()
                with os.fdopen(fd, 'w') as f:
                    f.write(key.strip() + '\n')

                if os.name == 'nt':
                    user_env = os.environ.get('USERNAME')
                    subprocess.run(['icacls', key_file, '/reset'], capture_output=True)
                    subprocess.run(['icacls', key_file, '/inheritance:r'], capture_output=True)
                    subprocess.run(['icacls', key_file, '/grant:r', f'{user_env}:F'], capture_output=True)
                else:
                    os.chmod(key_file, 0o600)

                cmd += ['-i', key_file]
                logger.info(f'Using provided private key for authentication')
            except Exception as e:
                logger.error(f'Failed to create or secure temporary key file: {e}')

        cmd += [target, command]
        logger.info(f'Executing remote command: {" ".join(cmd)}')

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # 缓存 stderr 输出，仅在失败时显示
            stderr_content = []

            import threading

            def collect_stderr():
                for line in process.stderr:
                    stderr_content.append(line.strip())

            def collect_stdout():
                for line in process.stdout:
                    logger.info(f'Remote: {line.strip()}')

            stderr_thread = threading.Thread(target=collect_stderr)
            stdout_thread = threading.Thread(target=collect_stdout)
            stderr_thread.start()
            stdout_thread.start()

            try:
                # 主线程等待进程退出
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                logger.error('Remote SSH command timed out after 30 seconds')
            finally:
                stderr_thread.join(timeout=5)
                stdout_thread.join(timeout=5)

            if process.returncode == 0:
                logger.info('Remote command executed successfully')
            else:
                logger.error(f'Remote command failed with return code {process.returncode}')
                for line in stderr_content:
                    logger.error(f'Remote Error: {line}')
        except Exception as e:
            logger.error(f'Failed to execute remote SSH command: {e}')
        finally:
            if key_file and os.path.exists(key_file):
                try:
                    os.remove(key_file)
                except Exception as e:
                    logger.error(f'Failed to remove temporary key file: {e}')

    @cached_property
    def emulator_info(self) -> EmulatorInfo:
        """
        从配置中解析模拟器信息。

        Returns:
            EmulatorInfo: 模拟器信息
        """
        emulator = self.config.EmulatorInfo_Emulator
        if emulator == 'auto':
            emulator = ''

        def parse_info(value):
            if isinstance(value, str):
                value = value.strip().replace('\n', '')
                if value in ['None', 'False', 'True']:
                    value = ''
                return value
            else:
                return ''

        name = parse_info(self.config.EmulatorInfo_name)
        path = parse_info(self.config.EmulatorInfo_path)

        return EmulatorInfo(
            emulator=emulator,
            name=name,
            path=path,
        )

    @cached_property
    def emulator_instance(self) -> t.Optional[EmulatorInstanceBase]:
        """
        查找并返回当前配置对应的模拟器实例。

        Returns:
            EmulatorInstanceBase: 模拟器实例，未找到则返回 None
        """
        data = self.emulator_info
        old_info = dict(
            emulator=data.emulator,
            path=data.path,
            name=data.name,
        )
        # 将 emulator-5554 重定向到 127.0.0.1:5555
        serial = self.serial
        port_serial, _ = get_serial_pair(self.serial)
        if port_serial is not None:
            serial = port_serial

        instance = self.find_emulator_instance(
            serial=serial,
            name=data.name,
            path=data.path,
            emulator=data.emulator,
        )

        # 写入完整的模拟器数据
        if instance is not None:
            new_info = dict(
                emulator=instance.type,
                path=instance.path,
                name=instance.name,
            )
            if new_info != old_info:
                with self.config.multi_set():
                    self.config.EmulatorInfo_Emulator = instance.type
                    self.config.EmulatorInfo_name = instance.name
                    self.config.EmulatorInfo_path = instance.path
                del_cached_property(self, 'emulator_info')

        return instance

    def find_emulator_instance(
            self,
            serial: str,
            name: str = None,
            path: str = None,
            emulator: str = None
    ) -> t.Optional[EmulatorInstanceBase]:
        """
        通过序列号、名称、路径和类型查找模拟器实例。

        Args:
            serial: 序列号，如 "127.0.0.1:5555"
            name: 实例名称，如 "Nougat64"
            path: 模拟器安装路径，如 "C:/Program Files/BlueStacks_nxt/HD-Player.exe"
            emulator: 模拟器类型，定义在 Emulator 类中，如 "BlueStacks5"

        Returns:
            EmulatorInstanceBase: 模拟器实例，未找到则返回 None
        """
        logger.hr('Find emulator instance', level=2)
        if emulator == 'SSH':
            instance = EmulatorInstanceBase(
                serial=serial,
                name=name or '',
                path=path or '',
            )
            # 为 SSH 实例临时修改 type 属性
            instance.__dict__['type'] = 'SSH'
            logger.hr('Emulator instance', level=2)
            logger.info(f'Found emulator instance (SSH): {instance}')
            return instance

        instances = SelectedGrids(self.all_emulator_instances)
        for instance in instances:
            logger.info(instance)
        search_args = dict(serial=serial)

        # 按序列号搜索
        select = instances.select(**search_args)
        if select.count == 0:
            logger.warning(f'No emulator instance with {search_args}, serial invalid')
            return None
        if select.count == 1:
            instance = select[0]
            logger.hr('Emulator instance', level=2)
            logger.info(f'Found emulator instance: {instance}')
            return instance

        # MuMu12 的额外修复
        # MuMu12 的 vbox 配置中可能是 127.0.0.1:7555，但用户设置的 serial 是 127.0.0.1:16xxx
        # 此时检查 serial 是否与 instance_id 匹配
        instance_id = serial_to_id(self.serial)
        if instance_id is not None:
            select = instances.select(MuMuPlayer12_id=instance_id)
            # 当 select.count == 1 时不输出日志，因为这只是一次试探性匹配
            if select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # 在多个同序列号实例中，优先按模拟器类型搜索（用户最容易配置的选项，更可靠）
        if emulator:
            search_args['type'] = emulator
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, type invalid')
                search_args.pop('type')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # 多个同序列号实例，按名称搜索
        if name:
            search_args['name'] = name
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, name invalid')
                search_args.pop('name')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # 多个同序列号和名称的实例，按路径搜索
        if path:
            search_args['path'] = path
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, path invalid')
                search_args.pop('path')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # 仍然有多个实例，从正在运行的模拟器中查找
        running = remove_duplicated_path(list(self.iter_running_emulator()))
        logger.info('Running emulators')
        for exe in running:
            logger.info(exe)
        if len(running) == 1:
            logger.info('Only one running emulator')
            # 等同于按路径搜索
            search_args['path'] = running[0]
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, path invalid')
                search_args.pop('path')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # 仍然有多个实例
        logger.warning(f'Found multiple emulator instances with {search_args}')
        return None
