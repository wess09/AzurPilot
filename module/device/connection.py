import ipaddress
import json
import logging
import re
import socket
import subprocess
import time
from functools import wraps

import uiautomator2 as u2
from adbutils import AdbClient, AdbDevice, AdbTimeout, ForwardItem, ReverseItem
from adbutils.errors import AdbError

from module.base.decorator import Config, cached_property, del_cached_property, run_once
from module.base.timer import Timer
from module.base.utils import ensure_time
from module.config.deep import deep_get
from module.config.server import VALID_CHANNEL_PACKAGE, VALID_PACKAGE, set_server
from module.device.connection_attr import ConnectionAttr
from module.device.env import IS_LINUX, IS_MACINTOSH, IS_WINDOWS
from module.device.method.pool import WORKER_POOL
from module.device.method.remove_warning import remove_shell_warning
from module.device.method.utils import (PackageNotInstalled, RETRY_TRIES, get_serial_pair, handle_adb_error,
                                        handle_unknown_host_service, possible_reasons, random_port, recv_all,
                                        retry_sleep)
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.logger import logger
from module.map.map_grids import SelectedGrids


def retry(func):
    """带自动重试的装饰器，处理 ADB 连接和设备相关异常。

    对指定函数进行最多 RETRY_TRIES 次重试，根据不同的异常类型
    采取不同的恢复策略（重连 ADB、重启服务、检测包等）。
    """
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Adb): ADB 设备实例。
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 无法处理的异常，直接中断重试
            except RequestHumanTakeover:
                break
            # 无法处理，必须向上传播以触发模拟器重启
            except EmulatorNotRunningError:
                raise
            # ADB 服务被杀死时触发
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
            # ADB 错误
            except AdbError as e:
                if handle_adb_error(e):
                    def init():
                        self.adb_reconnect()
                elif handle_unknown_host_service(e):
                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                else:
                    break
            # 包未安装
            except PackageNotInstalled as e:
                logger.error(e)

                def init():
                    self.detect_package()
            # 未知异常，可能是损坏的图像数据
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        if func.__name__ in [
            'adb_connect', 'adb_reconnect', 'adb_start_server',
            'screenshot', 'screenshot_adb', 'screenshot_uiautomator2', 'screenshot_ascreencap',
            'screenshot_droidcast', 'screenshot_droidcast_raw', 'screenshot_scrcpy',
            'screenshot_nemu_ipc', 'screenshot_ldopengl',
        ]:
            logger.critical(f'重试 {func.__name__}() 失败')
            raise EmulatorNotRunningError
        logger.critical(f'重试 {func.__name__}() 失败')
        raise RequestHumanTakeover

    return retry_wrapper


class AdbDeviceWithStatus(AdbDevice):
    def __init__(self, client: AdbClient, serial: str, status: str):
        self.status = status
        super().__init__(client, serial)

    def __str__(self):
        return f'AdbDevice({self.serial}, {self.status})'

    __repr__ = __str__

    def __bool__(self):
        return True

    @cached_property
    def port(self) -> int:
        try:
            return int(self.serial.split(':')[1])
        except (IndexError, ValueError):
            return 0

    @cached_property
    def may_mumu12_family(self):
        # 127.0.0.1:16XXX
        return 16384 <= self.port <= 17408


class Connection(ConnectionAttr):
    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig, str): ./config 目录下的用户配置名称。
        """
        super().__init__(config)
        if not self.is_over_http:
            self.detect_device()

        # 连接设备
        self.adb_connect(wait_device=False)
        logger.attr('AdbDevice', self.adb)

        # 检测包名
        self.package = self.config.Emulator_PackageName
        if self.package == 'auto':
            self.detect_package()
        else:
            set_server(self.package)
        logger.attr('PackageName', self.package)
        logger.attr('Server', self.config.SERVER)

        self.check_mumu_app_keep_alive()

    @Config.when(DEVICE_OVER_HTTP=False)
    def adb_command(self, cmd, timeout=10):
        """在子进程中执行 ADB 命令，通常用于拉取或推送大文件。

        Args:
            cmd (list): ADB 命令参数列表。
            timeout (int): 超时时间（秒）。

        Returns:
            str: 命令的标准输出。
        """
        cmd = list(map(str, cmd))
        cmd = [self.adb_binary, '-s', self.serial] + cmd
        return self.subprocess_run(cmd, timeout=timeout)

    def subprocess_run(self, cmd, timeout=10):
        """运行子进程命令并返回标准输出。

        Args:
            cmd (list): 命令参数列表。
            timeout (int): 超时时间（秒）。

        Returns:
            str: 命令的标准输出。
        """
        logger.info(f'Execute: {cmd}')
        # 不再使用 gooey，直接 shell=False
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.warning(f'TimeoutExpired when calling {cmd}, stdout={stdout}, stderr={stderr}')
        return stdout

    @Config.when(DEVICE_OVER_HTTP=True)
    def adb_command(self, cmd, timeout=10):
        logger.critical(
            f'尝试执行 {cmd}, '
            f'但 adb_command() 在通过 http 连接时不可用: {self.serial}, '
        )
        raise RequestHumanTakeover

    def adb_start_server(self):
        """启动 ADB 服务。

        使用 `adb devices` 代替 `adb start-server`，通过子进程方式启动 ADB
        以杀死其他已存在的 ADB 进程，返回值实际上无用。
        """
        stdout = self.subprocess_run([self.adb_binary, 'devices'])
        logger.info(stdout)
        return stdout

    @Config.when(DEVICE_OVER_HTTP=False)
    def adb_shell(self, cmd, stream=False, recvall=True, timeout=10, rstrip=True):
        """执行 ADB shell 命令，等价于 `adb -s <serial> shell <*cmd>`。

        Args:
            cmd (list, str): shell 命令或命令参数列表。
            stream (bool): 为 True 时返回流对象而非字符串。默认 False。
            recvall (bool): stream=True 时是否接收全部数据。默认 True。
            timeout (int): 超时时间（秒）。默认 10。
            rstrip (bool): 是否去除末尾空行。默认 True。

        Returns:
            stream=False 时返回 str。
            stream=True 且 recvall=True 时返回 bytes。
            stream=True 且 recvall=False 时返回 socket。
        """
        if not isinstance(cmd, str):
            cmd = list(map(str, cmd))

        if stream:
            result = self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip)
            if recvall:
                try:
                    # 返回 bytes
                    return recv_all(result)
                finally:
                    try:
                        if hasattr(result, 'close'):
                            result.close()
                        elif hasattr(result, 'conn') and hasattr(result.conn, 'close'):
                            result.conn.close()
                    except Exception:
                        pass
            else:
                # 返回 socket
                return result
        else:
            result = self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip)
            result = remove_shell_warning(result)
            # 返回 str
            return result

    @Config.when(DEVICE_OVER_HTTP=True)
    def adb_shell(self, cmd, stream=False, recvall=True, timeout=10, rstrip=True):
        """通过 HTTP 执行 shell 命令，等价于 http://127.0.0.1:7912/shell?command={command}。

        Args:
            cmd (list, str): shell 命令或命令参数列表。
            stream (bool): 为 True 时返回流数据而非字符串。默认 False。
            recvall (bool): stream=True 时是否接收全部数据。默认 True。
            timeout (int): 超时时间（秒）。默认 10。
            rstrip (bool): 是否去除末尾空行。默认 True。

        Returns:
            stream=False 时返回 str。
            stream=True 时返回 bytes。
        """
        if not isinstance(cmd, str):
            cmd = list(map(str, cmd))

        if stream:
            result = self.u2.shell(cmd, stream=stream, timeout=timeout)
            # 已接收全部数据，忽略 `recvall` 参数
            result = remove_shell_warning(result.content)
            # 返回 bytes
            return result
        else:
            result = self.u2.shell(cmd, stream=stream, timeout=timeout).output
            if rstrip:
                result = result.rstrip()
            result = remove_shell_warning(result)
            # 返回 str
            return result

    def adb_getprop(self, name):
        """获取 Android 系统属性，等价于 `getprop <name>`。

        Args:
            name (str): 属性名称。

        Returns:
            str: 属性值。
        """
        return self.adb_shell(['getprop', name]).strip()

    @cached_property
    @retry
    def cpu_abi(self) -> str:
        """获取设备的 CPU ABI 类型。

        Returns:
            str: CPU ABI，如 arm64-v8a、armeabi-v7a、x86、x86_64。
        """
        abi = self.adb_getprop('ro.product.cpu.abi')
        if not len(abi):
            logger.error(f'CPU ABI invalid: "{abi}"')
        return abi

    @cached_property
    @retry
    def sdk_ver(self) -> int:
        """获取 Android SDK/API 版本号，详见 https://apilevels.com/。"""
        sdk = self.adb_getprop('ro.build.version.sdk')
        try:
            return int(sdk)
        except ValueError:
            logger.error(f'SDK version invalid: {sdk}')

        return 0

    @cached_property
    @retry
    def is_avd(self):
        if get_serial_pair(self.serial)[0] is None:
            return False
        if 'ranchu' in self.adb_getprop('ro.hardware'):
            return True
        if 'goldfish' in self.adb_getprop('ro.hardware.audio.primary'):
            return True
        return False

    @cached_property
    @retry
    def is_waydroid(self):
        res = self.adb_getprop('ro.product.brand')
        logger.attr('ro.product.brand', res)
        return 'waydroid' in res.lower()

    @cached_property
    @retry
    def is_bluestacks_air(self):
        # BlueStacks Air 是 BlueStacks 的 Mac 版本
        if not IS_MACINTOSH:
            return False
        # 127.0.0.1:5555 + 10*n，最多假设 32 个实例
        if not (5555 <= self.port <= 5875):
            return False
        # [bst.installed_images]: [Tiramisu64]
        # [bst.instance]: [Tiramisu64]
        # Tiramisu64 是 Android 13，BlueStacks Air 是唯一使用 Android 13 的 BlueStacks 版本
        res = self.adb_getprop('bst.installed_images')
        logger.attr('bst.installed_images', res)
        if 'Tiramisu64' in res:
            return True
        return False

    @cached_property
    @retry
    def is_mumu_pro(self):
        # MuMu Pro 是 MuMu 的 Mac 版本
        if not IS_MACINTOSH:
            return False
        if not self.is_mumu_family:
            return False
        logger.attr('is_mumu_pro', True)
        return True

    @cached_property
    @retry
    def nemud_app_keep_alive(self) -> str:
        res = self.adb_getprop('nemud.app_keep_alive')
        logger.attr('nemud.app_keep_alive', res)
        return res

    @cached_property
    @retry
    def nemud_player_version(self) -> str:
        # [nemud.player_product_version]: [3.8.27.2950]，MuMu 模拟器版本号
        res = self.adb_getprop('nemud.player_version')
        logger.attr('nemud.player_version', res)
        return res

    @cached_property
    @retry
    def nemud_player_engine(self) -> str:
        # MuMu 模拟器引擎类型：NEMUX 或 MACPRO
        res = self.adb_getprop('nemud.player_engine')
        logger.attr('nemud.player_engine', res)
        return res

    def check_mumu_app_keep_alive(self):
        if not self.is_mumu_family:
            return False

        res = self.nemud_app_keep_alive
        if res == '':
            # 属性为空，可能是 MuMu6 或 MuMu12 版本 < 3.5.6
            return True
        elif res == 'false':
            # 已禁用
            return True
        elif res == 'true':
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover
        else:
            logger.warning(f'Invalid nemud.app_keep_alive value: {res}')
            return False

    @cached_property
    def is_mumu_over_version_400(self) -> bool:
        if not self.is_mumu_family:
            return False
        # >= 4.0 版本在 getprop 中没有版本信息
        if self.nemud_player_version == '':
            return True
        return False

    @cached_property
    def is_mumu_over_version_356(self) -> bool:
        """判断 MuMu12 版本是否 >= 3.5.6。

        该版本具有 nemud.app_keep_alive 属性且始终为竖屏设备。
        Mac 上的 MuMu PRO 也具有相同特性。

        Returns:
            bool: 是否为 MuMu12 >= 3.5.6 版本。
        """
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return True
        if self.nemud_app_keep_alive != '':
            return True
        if IS_MACINTOSH:
            if 'MACPRO' in self.nemud_player_engine:
                return True
        return False

    @cached_property
    def _nc_server_host_port(self):
        """获取 netcat 服务器的监听和连接地址信息。

        Returns:
            tuple: (server_listen_host, server_listen_port, client_connect_host, client_connect_port)
        """
        # BlueStacks Hyper-V 使用 ADB reverse
        if self.is_bluestacks_hyperv:
            host = '127.0.0.1'
            logger.info(f'Connecting to BlueStacks hyper-v, using host {host}')
            port = self.adb_reverse(f'tcp:{self.config.REVERSE_SERVER_PORT}')
            return host, port, host, self.config.REVERSE_SERVER_PORT
        # 模拟器监听本机
        if self.is_emulator or self.is_over_http:
            # Mac 模拟器
            if self.is_bluestacks_air or self.is_mumu_pro:
                logger.info(f'Connecting to local emulator, using host 127.0.0.1')
                port = random_port(self.config.FORWARD_PORT_RANGE)
                return '127.0.0.1', port, "10.0.2.2", port
            # 获取主机 IP
            try:
                host = socket.gethostbyname(socket.gethostname())
            except socket.gaierror as e:
                logger.error(e)
                logger.error(f'Unknown host name: {socket.gethostname()}')
                host = '127.0.0.1'
            # 修复 Linux AVD 主机地址
            if IS_LINUX and host == '127.0.1.1':
                host = '127.0.0.1'
            logger.info(f'Connecting to local emulator, using host {host}')
            port = random_port(self.config.FORWARD_PORT_RANGE)
            # AVD 实例使用 10.0.2.2 作为客户端地址
            if self.is_avd:
                return host, port, "10.0.2.2", port
            return host, port, host, port
        # 局域网设备，监听与目标设备同一网段的主机
        if self.is_network_device:
            hosts = socket.gethostbyname_ex(socket.gethostname())[2]
            logger.info(f'Current hosts: {hosts}')
            ip = ipaddress.ip_address(self.serial.split(':')[0])
            for host in hosts:
                if ip in ipaddress.ip_interface(f'{host}/24').network:
                    logger.info(f'Connecting to local network device, using host {host}')
                    port = random_port(self.config.FORWARD_PORT_RANGE)
                    return host, port, host, port
        # 其他设备，创建 ADB reverse 并监听 127.0.0.1
        host = '127.0.0.1'
        logger.info(f'Connecting to unknown device, using host {host}')
        port = self.adb_reverse(f'tcp:{self.config.REVERSE_SERVER_PORT}')
        return host, port, host, self.config.REVERSE_SERVER_PORT

    @cached_property
    def reverse_server(self):
        """在 Alas 端建立服务器，供模拟器端访问。

        绕过 adb shell 直接传输数据，速度更快。
        """
        del_cached_property(self, '_nc_server_host_port')
        host_port = self._nc_server_host_port
        logger.info(f'Reverse server listening on {host_port[0]}:{host_port[1]}, '
                    f'client can send data to {host_port[2]}:{host_port[3]}')
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(host_port[:2])
        server.settimeout(5)
        server.listen(5)
        return server

    @cached_property
    def nc_command(self):
        """获取设备上可用的 netcat 命令。

        Returns:
            list[str]: 可用的 nc 命令，如 ['nc'] 或 ['busybox', 'nc']。
        """
        if self.is_emulator:
            sdk = self.sdk_ver
            logger.info(f'sdk_ver: {sdk}')
            if sdk >= 28:
                # LD Player 9 没有 `nc`，尝试 `busybox nc`
                # BlueStacks Pie (Android 9) 有 `nc` 但无法发送数据，优先尝试 `busybox nc`
                trial = [
                    ['busybox', 'nc'],
                    ['nc'],
                ]
            else:
                trial = [
                    ['nc'],
                    ['busybox', 'nc'],
                ]
        else:
            trial = [
                ['nc'],
                ['busybox', 'nc'],
            ]
        for command in trial:
            # 大约 3ms
            # 成功时结果应为命令帮助信息
            # nc: bad argument count (see "nc --help")
            result = self.adb_shell(command)
            # `/system/bin/sh: nc: not found`
            if 'not found' in result:
                continue
            # `/system/bin/sh: busybox: inaccessible or not found\n`
            if 'inaccessible' in result:
                continue
            logger.attr('nc command', command)
            return command

        logger.error('没有可用的 `netcat` 命令，请使用不带 `_nc` 后缀的截图方法')
        raise RequestHumanTakeover

    def adb_shell_nc(self, cmd, timeout=5, chunk_size=262144):
        """通过 netcat 传输数据，绕过 adb shell 直接传输，速度更快。

        Args:
            cmd (list): shell 命令参数列表。
            timeout (int): 超时时间（秒）。默认 5。
            chunk_size (int): 接收数据的块大小。默认 262144。

        Returns:
            bytes: 接收到的原始数据。
        """
        # 服务端开始监听
        server = self.reverse_server
        server.settimeout(timeout)
        # 客户端发送数据，等待服务端接受连接
        # <command> | nc 127.0.0.1 {port}
        cmd += ["|", *self.nc_command, *self._nc_server_host_port[2:]]
        stream = self.adb_shell(cmd, stream=True, recvall=False)

        def _safe_close(s):
            try:
                # AdbConnection 可能暴露 close 方法或持有 `conn` 属性
                if hasattr(s, 'close'):
                    s.close()
                    return
                if hasattr(s, 'conn') and hasattr(s.conn, 'close'):
                    s.conn.close()
                    return
                if isinstance(s, socket.socket):
                    s.close()
            except Exception:
                pass

        try:
            # 服务端接受连接
            conn, conn_port = server.accept()
        except socket.timeout:
            try:
                output = recv_all(stream, chunk_size=chunk_size)
                logger.warning(str(output))
            finally:
                _safe_close(stream)
            raise AdbTimeout('reverse server accept timeout')

        try:
            # 服务端接收数据
            data = recv_all(conn, chunk_size=chunk_size, recv_interval=0.001)
        finally:
            # 服务端关闭连接，同时关闭 adb 流资源
            try:
                conn.close()
            except Exception:
                pass
            _safe_close(stream)

        return data

    def adb_exec_out(self, cmd, serial=None):
        cmd.insert(0, 'exec-out')
        return self.adb_command(cmd, serial)

    def adb_forward(self, remote):
        """执行 `adb forward <local> <remote>`。

        在 FORWARD_PORT_RANGE 中选择一个随机端口，或复用已有的端口转发，
        同时移除多余的转发记录。

        Args:
            remote (str): 远程地址，如：
                tcp:<port>
                localabstract:<unix domain socket name>
                localreserved:<unix domain socket name>
                localfilesystem:<unix domain socket name>
                dev:<character device name>
                jdwp:<process pid> (remote only)

        Returns:
            int: 本地端口号。
        """
        port = 0
        for forward in self.adb.forward_list():
            if forward.serial == self.serial and forward.remote == remote and forward.local.startswith('tcp:'):
                if not port:
                    logger.info(f'Reuse forward: {forward}')
                    port = int(forward.local[4:])
                else:
                    logger.info(f'Remove redundant forward: {forward}')
                    self.adb_forward_remove(forward.local)

        if port:
            return port
        else:
            # 创建新的端口转发
            port = random_port(self.config.FORWARD_PORT_RANGE)
            forward = ForwardItem(self.serial, f'tcp:{port}', remote)
            logger.info(f'Create forward: {forward}')
            self.adb.forward(forward.local, forward.remote)
            return port

    def _adb_reverse_transport(self, remote: str, local: str, norebind: bool = False):
        """执行 ADB reverse 转发（移植自 https://github.com/openatx/adbutils/pull/116 的修复）。

        不要使用 self.adb.reverse()，请使用此方法。
        """
        args = ["reverse:forward"]
        if norebind:
            args.append("norebind")
        args.append(remote + ";" + local)
        cmd = ":".join(args)
        with self.adb_client._connect() as c:
            c.send_command(f'host:transport:{self.serial}')
            c.check_okay()
            c.send_command(cmd)
            c.check_okay()

    def adb_reverse(self, remote):
        port = 0
        for reverse in self.adb.reverse_list():
            if reverse.remote == remote and reverse.local.startswith('tcp:'):
                if not port:
                    logger.info(f'Reuse reverse: {reverse}')
                    port = int(reverse.local[4:])
                else:
                    logger.info(f'Remove redundant reverse: {reverse}')
                    self.adb_reverse_remove(reverse.remote)

        if port:
            return port
        else:
            # 创建新的 reverse 转发
            port = random_port(self.config.FORWARD_PORT_RANGE)
            reverse = ReverseItem(remote, f'tcp:{port}')
            logger.info(f'Create reverse: {reverse}')
            self._adb_reverse_transport(reverse.remote, reverse.local)
            return port

    def adb_forward_remove(self, local):
        """移除 ADB 端口转发，等价于 `adb -s <serial> forward --remove <local>`。

        移除不存在的转发时不会抛出异常。

        关于发送到 ADB 服务器的命令详情，参见：
        https://cs.android.com/android/platform/superproject/+/master:packages/modules/adb/SERVICES.TXT

        Args:
            local (str): 本地地址，如 'tcp:2437'。
        """
        try:
            with self.adb_client._connect() as c:
                list_cmd = f"host-serial:{self.serial}:killforward:{local}"
                c.send_command(list_cmd)
                c.check_okay()
        except AdbError as e:
            # 移除不存在的转发时不会抛出异常
            # adbutils.errors.AdbError: listener 'tcp:8888' not found
            msg = str(e)
            if re.search(r'listener .*? not found', msg):
                logger.warning(f'{type(e).__name__}: {msg}')
            else:
                raise

    def adb_reverse_remove(self, local):
        """移除 ADB reverse 转发，等价于 `adb -s <serial> reverse --remove <local>`。

        移除不存在的 reverse 时不会抛出异常。

        Args:
            local (str): 本地地址，如 'tcp:2437'。
        """
        try:
            with self.adb_client._connect() as c:
                c.send_command(f"host:transport:{self.serial}")
                c.check_okay()
                list_cmd = f"reverse:killforward:{local}"
                c.send_command(list_cmd)
                c.check_okay()
        except AdbError as e:
            # 移除不存在的转发时不会抛出异常
            # adbutils.errors.AdbError: listener 'tcp:8888' not found
            msg = str(e)
            if re.search(r'listener .*? not found', msg):
                logger.warning(f'{type(e).__name__}: {msg}')
            else:
                raise

    def adb_push(self, local, remote):
        """推送文件到设备，等价于 `adb push <local> <remote>`。

        Args:
            local (str): 本地文件路径。
            remote (str): 设备上的目标路径。

        Returns:
            str: 命令输出。
        """
        cmd = ['push', local, remote]
        return self.adb_command(cmd)

    def _wait_device_appear(self, serial, first_devices=None):
        """等待设备出现在 ADB 设备列表中。

        Args:
            serial (str): 设备序列号。
            first_devices (list[AdbDeviceWithStatus]): 首次设备列表，避免重复查询。

        Returns:
            bool: 设备是否出现。
        """
        # 等待略长于 5 秒
        timeout = Timer(5.2).start()
        first_log = True
        while 1:
            if first_devices is not None:
                devices = first_devices
                first_devices = None
            else:
                devices = self.list_device()
            # 检查设备是否出现
            for device in devices:
                if device.serial == serial and device.status == 'device':
                    return True
            # 延迟后再次检查
            if timeout.reached():
                break
            if first_log:
                logger.info(f'Waiting device appear: {serial}')
                first_log = False
            time.sleep(0.05)

        return False

    @Config.when(DEVICE_OVER_HTTP=False)
    def adb_connect(self, wait_device=True):
        """连接到指定序列号的设备，最多尝试 3 次。

        如果旧版 ADB 服务器正在运行而 Alas 使用的是较新版本（常见于国产模拟器），
        第一次连接用于杀死旧服务器，第二次才是真正的连接。

        Args:
            wait_device (bool): 是否等待 emulator-* 和 android 设备出现。默认 True。

        Returns:
            bool: 是否连接成功。
        """
        # 连接前先断开离线设备
        devices = self.list_device()
        for device in devices:
            if device.status == 'offline':
                logger.warning(f'Device {device.serial} is offline, disconnect it before connecting')
                msg = self.adb_client.disconnect(device.serial)
                if msg:
                    logger.info(msg)
            elif device.status == 'unauthorized':
                logger.error(f'Device {device.serial} is unauthorized, please accept ADB debugging on your device')
            elif device.status == 'device':
                pass
            else:
                logger.warning(f'Device {device.serial} is is having a unknown status: {device.status}')

        # 跳过 emulator-5554 和 Android 手机的连接，因为它们插入后应自动连接
        if 'emulator-' in self.serial:
            if wait_device:
                if self._wait_device_appear(self.serial, first_devices=devices):
                    logger.info(f'Serial {self.serial} connected')
                    return True
                else:
                    logger.info(f'Serial {self.serial} is not connected')
            logger.info(f'"{self.serial}" is a `emulator-*` serial, skip adb connect')
            return True
        if re.match(r'^[a-zA-Z0-9]+$', self.serial):
            if wait_device:
                if self._wait_device_appear(self.serial, first_devices=devices):
                    logger.info(f'Serial {self.serial} connected')
                    return True
                else:
                    logger.info(f'Serial {self.serial} is not connected')
            logger.info(f'"{self.serial}" seems to be a Android serial, skip adb connect')
            return True

        # 尝试连接
        for _ in range(3):
            msg = self.adb_client.connect(self.serial)
            logger.info(msg)
            # Connected to 127.0.0.1:59865
            # Already connected to 127.0.0.1:59865
            if 'connected' in msg:
                return True
            # bad port number '598265' in '127.0.0.1:598265'
            elif 'bad port' in msg:
                possible_reasons('Serial incorrect, might be a typo')
                raise RequestHumanTakeover
            # cannot connect to 127.0.0.1:55555:
            # No connection could be made because the target machine actively refused it. (10061)
            elif '(10061)' in msg:
                # MuMu12 端口被占用时可能会切换序列号
                # 暴力连接附近端口以处理序列号切换
                if self.is_mumu12_family:
                    before = self.serial
                    serial_list = [self.serial.replace(str(self.port), str(self.port + offset))
                                   for offset in [1, -1, 2, -2]]
                    self.adb_brute_force_connect(serial_list)
                    self.detect_device()
                    if self.serial != before:
                        return True
                run_once(self.check_mumu_bridge_network)()
                # 设备不存在
                logger.warning('No such device exists, please restart the emulator or set a correct serial')
                logger.warning('该模拟器 Serial 不存在，请重启模拟器或设置正确的 Serial。')
                logger.warning('ADB 无法连接至该模拟器，或是模拟器未启动。')
                raise EmulatorNotRunningError

        # 连接失败
        logger.warning(f'Failed to connect {self.serial} after 3 trial, assume connected')
        self.detect_device()
        return False

    def adb_brute_force_connect(self, serial_list):
        """暴力连接多个序列号，用于处理 MuMu12 端口切换。

        Args:
            serial_list (list[str]): 要尝试连接的序列号列表。
        """
        def connect(s):
            try:
                msg = self.adb_client.connect(s)
            except Exception:
                return ''
            logger.info(msg)
            return msg

        with WORKER_POOL.wait_jobs() as pool:
            for serial in serial_list:
                pool.start_thread_soon(connect, serial)

    def check_mumu_bridge_network(self):
        """检查 MuMu12 是否开启了网络桥接（需要关闭）。

        Returns:
            bool: 检查成功返回 True，跳过检查返回 False。
        """
        if not self.is_mumu12_family:
            return True
        if not hasattr(self, 'find_emulator_instance'):
            return False
        # 假设 PlatformBase 继承了此类
        instance = self.find_emulator_instance(
            serial=self.serial,
        )
        if instance is None:
            logger.warning(f'Failed to check check_mumu_bridge_network, emulator instance not found')
            return False
        file = instance.mumu_vms_config('customer_config.json')
        try:
            with open(file, mode='r', encoding='utf-8') as f:
                s = f.read()
                data = json.loads(s)
        except FileNotFoundError:
            logger.warning(f'Failed to check check_mumu_bridge_network, file {file} not exists')
            return False
        value = deep_get(data, keys='customer.network_bridge_opened', default=None)
        logger.attr('customer.network_bridge_opened', value)
        if str(value).lower() == 'true':
            logger.critical('Please turn off "Network Bridging" in the settings of MuMuPlayer')
            logger.critical('请在MuMU模拟器设置中关闭 网络桥接')
            raise RequestHumanTakeover
        return True

    @Config.when(DEVICE_OVER_HTTP=True)
    def adb_connect(self, wait_device=True):
        # 通过 HTTP 连接时不需要 adb connect
        return True

    def release_resource(self):
        del_cached_property(self, 'hermit_session')
        del_cached_property(self, 'droidcast_session')
        del_cached_property(self, '_minitouch_builder')
        del_cached_property(self, '_maatouch_builder')
        del_cached_property(self, 'reverse_server')

    def adb_disconnect(self):
        msg = self.adb_client.disconnect(self.serial)
        if msg:
            logger.info(msg)
        self.release_resource()

    def adb_restart(self):
        """重启 ADB 客户端。"""
        logger.info('Restart adb')
        # 终止当前客户端
        self.adb_client.server_kill()
        # 重新初始化 ADB 客户端
        del_cached_property(self, 'adb_client')
        self.release_resource()
        _ = self.adb_client

    @Config.when(DEVICE_OVER_HTTP=False)
    def adb_reconnect(self):
        """重新连接 ADB 设备。

        未找到设备时重启 ADB 客户端，否则尝试重新连接设备。
        """
        if self.config.Emulator_AdbRestart and len(self.list_device()) == 0:
            # 重启 ADB
            self.adb_restart()
            # 连接设备
            self.adb_connect()
            self.detect_device()
        else:
            self.adb_disconnect()
            self.adb_connect()
            self.detect_device()

    @Config.when(DEVICE_OVER_HTTP=True)
    def adb_reconnect(self):
        logger.warning(
            f'When connecting a device over http: {self.serial} '
            f'adb_reconnect() is skipped, you may need to restart ATX manually'
        )

    def install_uiautomator2(self):
        """初始化 uiautomator2 并移除 minicap。"""
        logger.info('Install uiautomator2')
        init = u2.init.Initer(self.adb, loglevel=logging.DEBUG)
        # MuMu X 没有 ro.product.cpu.abi，从 ro.product.cpu.abilist 中选取 abi
        if init.abi not in ['x86_64', 'x86', 'arm64-v8a', 'armeabi-v7a', 'armeabi']:
            init.abi = init.abis[0]
        init.set_atx_agent_addr('127.0.0.1:7912')
        try:
            init.install()
        except ConnectionError:
            u2.init.GITHUB_BASEURL = 'http://tool.appetizer.io/openatx'
            init.install()
        self.uninstall_minicap()

    def uninstall_minicap(self):
        """卸载 minicap。minicap 在部分模拟器上无法工作或会发送压缩图像。"""
        logger.info('Removing minicap')
        self.adb_shell(["rm", "/data/local/tmp/minicap"])
        self.adb_shell(["rm", "/data/local/tmp/minicap.so"])

    @Config.when(DEVICE_OVER_HTTP=False)
    def restart_atx(self):
        """重启 ATX 服务。

        Minitouch 同一时间只支持一个连接，重启 ATX 以踢掉现有连接。
        """
        logger.info('Restart ATX')
        atx_agent_path = '/data/local/tmp/atx-agent'
        self.adb_shell([atx_agent_path, 'server', '--stop'])
        self.adb_shell([atx_agent_path, 'server', '--nouia', '-d', '--addr', '127.0.0.1:7912'])

    @Config.when(DEVICE_OVER_HTTP=True)
    def restart_atx(self):
        logger.warning(
            f'When connecting a device over http: {self.serial} '
            f'restart_atx() is skipped, you may need to restart ATX manually'
        )

    @staticmethod
    def sleep(second):
        """休眠指定时间。

        Args:
            second (int, float, tuple): 休眠时间（秒），可以是固定值或范围元组。
        """
        time.sleep(ensure_time(second))

    _orientation_description = {
        0: '正常',
        1: 'HOME 键在右侧',
        2: 'HOME 键在顶部',
        3: 'HOME 键在左侧',
    }
    orientation = 0

    @retry
    def get_orientation(self):
        """获取设备屏幕方向。

        Returns:
            int: 屏幕方向值：
                0: 正常
                1: HOME 键在右侧
                2: HOME 键在顶部
                3: HOME 键在左侧
        """
        _DISPLAY_RE = re.compile(
            r'.*DisplayViewport{.*valid=true, .*orientation=(?P<orientation>\d+), .*deviceWidth=(?P<width>\d+), deviceHeight=(?P<height>\d+).*'
        )
        output = self.adb_shell(['dumpsys', 'display'])

        res = _DISPLAY_RE.search(output, 0)

        if res:
            o = int(res.group('orientation'))
            if o in Connection._orientation_description:
                pass
            else:
                o = 0
                logger.warning(f'Invalid device orientation: {o}, assume it is normal')
        else:
            o = 0
            logger.warning('Unable to get device orientation, assume it is normal')

        self.orientation = o
        logger.attr('Device Orientation', f'{o} ({Connection._orientation_description.get(o, "Unknown")})')
        return o

    @retry
    def list_device(self):
        """列出所有 ADB 设备。

        Returns:
            SelectedGrids[AdbDeviceWithStatus]: 设备列表。
        """
        devices = []
        try:
            with self.adb_client._connect() as c:
                c.send_command("host:devices")
                c.check_okay()
                output = c.read_string_block()
                for line in output.splitlines():
                    parts = line.strip().split("\t")
                    if len(parts) != 2:
                        continue
                    device = AdbDeviceWithStatus(self.adb_client, parts[0], parts[1])
                    devices.append(device)
        except ConnectionResetError as e:
            # 仅在国内用户中出现
            # ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接。
            logger.error(e)
            if '强迫关闭' in str(e):
                logger.critical('无法连接至ADB服务，请关闭UU加速器、原神私服、以及一些劣质代理软件。'
                                '它们会劫持电脑上所有的网络连接，包括Alas与模拟器之间的本地连接。')
        return SelectedGrids(devices)

    def detect_device(self):
        """检测可用设备。

        如果 serial=='auto' 且只检测到 1 个设备，则使用该设备。
        """
        logger.hr('Detect device')
        available = SelectedGrids([])
        devices = SelectedGrids([])

        @run_once
        def brute_force_connect():
            logger.info('Brute force connect')
            from deploy.Windows.emulator import EmulatorManager
            manager = EmulatorManager()
            manager.brute_force_connect()

        for _ in range(2):
            logger.info('Here are the available devices, '
                        'copy to Alas.Emulator.Serial to use it or set Alas.Emulator.Serial="auto"')
            devices = self.list_device()

            # 显示可用设备
            available = devices.select(status='device')
            for device in available:
                logger.info(device.serial)
            if not len(available):
                logger.info('No available devices')

            # 显示不可用设备
            unavailable = devices.delete(available)
            if len(unavailable):
                logger.info('Here are the devices detected but unavailable')
                for device in unavailable:
                    logger.info(f'{device.serial} ({device.status})')

            # 暴力连接
            if self.config.Emulator_Serial == 'auto' and available.count == 0:
                logger.warning(f'No available device found')
                if IS_WINDOWS:
                    brute_force_connect()
                    continue
                else:
                    break
            else:
                break

        # 自动设备检测
        if self.config.Emulator_Serial == 'auto':
            if available.count == 0:
                logger.critical('没有找到可用设备，自动设备检测无法工作，'
                                '请在 Alas.Emulator.Serial 中设置一个确切的序列号，而不是使用 "auto"')
                raise RequestHumanTakeover
            elif available.count == 1:
                logger.info(f'自动设备检测只找到一个设备，正在使用它')
                self.config.Emulator_Serial = self.serial = available[0].serial
                del_cached_property(self, 'adb')
            elif available.count == 2 \
                    and available.select(serial='127.0.0.1:7555') \
                    and available.select(may_mumu12_family=True):
                logger.info(f'自动设备检测到 MuMu12 设备，正在使用它')
                # 对于 MuMu12 序列号如 127.0.0.1:7555 和 127.0.0.1:16384
                # 忽略 7555，使用 16384
                remain = available.select(may_mumu12_family=True).first_or_none()
                self.config.Emulator_Serial = self.serial = remain.serial
                del_cached_property(self, 'adb')
            else:
                logger.critical('找到多个设备，自动设备检测无法决定选择哪个，'
                                '请将下面列出的可用设备之一复制到 Alas.Emulator.Serial 中')
                raise RequestHumanTakeover

        # 处理雷电模拟器
        # 雷电模拟器序列号在 `127.0.0.1:5555+{X}` 和 `emulator-5554+{X}` 之间跳转
        # 动态处理，不写入配置
        port_serial, emu_serial = get_serial_pair(self.serial)
        if port_serial and emu_serial:
            # 可能是雷电模拟器，检查已连接设备
            port_device = devices.select(serial=port_serial).first_or_none()
            emu_device = devices.select(serial=emu_serial).first_or_none()
            if port_device and emu_device:
                # 找到配对设备，检查状态以获取正确的序列号
                if port_device.status == 'device' and emu_device.status == 'offline':
                    self.serial = port_serial
                    logger.info(f'LDPlayer device pair found: {port_device}, {emu_device}. '
                                f'Using serial: {self.serial}')
                elif port_device.status == 'offline' and emu_device.status == 'device':
                    self.serial = emu_serial
                    logger.info(f'LDPlayer device pair found: {port_device}, {emu_device}. '
                                f'Using serial: {self.serial}')
            elif not devices.select(serial=self.serial):
                # 当前序列号未找到
                if port_device and not emu_device:
                    logger.info(f'Current serial {self.serial} not found but paired device {port_serial} found. '
                                f'Using serial: {port_serial}')
                    self.serial = port_serial
                if not port_device and emu_device:
                    logger.info(f'Current serial {self.serial} not found but paired device {emu_serial} found. '
                                f'Using serial: {emu_serial}')
                    self.serial = emu_serial

        # 将 MuMu12 从 127.0.0.1:7555 重定向到 127.0.0.1:16xxx
        if self.serial == '127.0.0.1:7555':
            for _ in range(2):
                mumu12 = available.select(may_mumu12_family=True)
                if mumu12.count == 1:
                    emu_serial = mumu12.first_or_none().serial
                    logger.warning(f'Redirect MuMu12 {self.serial} to {emu_serial}')
                    self.config.Emulator_Serial = self.serial = emu_serial
                    break
                elif mumu12.count >= 2:
                    logger.warning(f'发现多个 MuMu12 序列号，无法重定向')
                    break
                else:
                    # 仅有 127.0.0.1:7555
                    if self.is_mumu_over_version_356:
                        # is_mumu_over_version_356 和 nemud_app_keep_alive 已缓存
                        # 因为是同一设备，可以接受
                        logger.warning(f'Device {self.serial} is MuMu12 but corresponding port not found')
                        if IS_WINDOWS:
                            brute_force_connect()
                        devices = self.list_device()
                        # 显示可用设备
                        available = devices.select(status='device')
                        for device in available:
                            logger.info(device.serial)
                        if not len(available):
                            logger.info('No available devices')
                        continue
                    else:
                        # MuMu6
                        break

        # MuMu12 端口 16384 被占用时会使用 127.0.0.1:16385，自动重定向
        # 动态处理，不写入配置
        if self.is_mumu12_family:
            matched = False
            for device in available.select(may_mumu12_family=True):
                if device.port == self.port:
                    # 精确匹配
                    matched = True
                    break
            if not matched:
                for device in available.select(may_mumu12_family=True):
                    if -2 <= device.port - self.port <= 2:
                        # 端口已切换
                        logger.info(f'MuMu12 serial switched {self.serial} -> {device.serial}')
                        del_cached_property(self, 'port')
                        del_cached_property(self, 'is_mumu12_family')
                        del_cached_property(self, 'is_mumu_family')
                        self.serial = device.serial
                        break

    @retry
    def list_package(self, show_log=True):
        """列出设备上所有已安装的包。

        优先使用 dumpsys 以提高速度。
        """
        # 约 80ms
        if show_log:
            logger.info('Get package list')
        output = self.adb_shell(r'dumpsys package | grep "Package \["')
        packages = re.findall(r'Package \[([^\s]+)\]', output)
        if len(packages):
            return packages

        # 约 200ms
        if show_log:
            logger.info('Get package list')
        output = self.adb_shell(['pm', 'list', 'packages'])
        packages = re.findall(r'package:([^\s]+)', output)
        return packages

    def list_known_packages(self, show_log=True):
        """列出设备上已知的游戏包（碧蓝航线及其渠道包）。

        Args:
            show_log (bool): 是否输出日志。默认 True。

        Returns:
            list[str]: 包名列表。
        """
        packages = self.list_package(show_log=show_log)
        packages = [p for p in packages if p in VALID_PACKAGE or p in VALID_CHANNEL_PACKAGE]
        return packages

    def detect_package(self, set_config=True):
        """检测设备上的碧蓝航线客户端包。"""
        logger.hr('Detect package')
        packages = self.list_known_packages()

        # 显示可用包
        logger.info(f'Here are the available packages in device "{self.serial}", '
                    f'copy to Alas.Emulator.PackageName to use it')
        if len(packages):
            for package in packages:
                logger.info(package)
        else:
            logger.info(f'在设备 "{self.serial}" 上没有找到可用包')

        # 自动包检测
        if len(packages) == 0:
            logger.critical(f'没有找到碧蓝航线包，'
                            f'请确认碧蓝航线已安装在设备 "{self.serial}" 上')
            raise RequestHumanTakeover
        if len(packages) == 1:
            logger.info('自动包检测只找到一个包，正在使用它')
            self.package = packages[0]
            # 写入配置
            if set_config:
                self.config.Emulator_PackageName = self.package
            # 设置服务器
            logger.info('Server changed, release resources')
            set_server(self.package)
        else:
            logger.critical(
                f'找到多个碧蓝航线包，自动包检测无法决定选择哪个，'
                '请将上面列出的可用包之一复制到 Alas.Emulator.PackageName 中')
            raise RequestHumanTakeover
