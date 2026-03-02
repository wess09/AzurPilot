import os
import re
import subprocess
import time

import psutil

from module.base.decorator import run_once
from module.base.timer import Timer
from module.device.connection import AdbDeviceWithStatus
from module.device.platform.platform_base import PlatformBase
from module.device.platform.emulator_mac import EmulatorMac, EmulatorInstanceMac, EmulatorManagerMac
from module.logger import logger


class PlatformMac(PlatformBase, EmulatorManagerMac):
    """
    Mac platform emulator control.
    Supports BlueStacks Air and MuMu Pro on macOS.
    """

    def __init__(self, config):
        """
        Initialize PlatformMac with config.
        
        Args:
            config: Configuration object with Emulator_Serial
        """
        self.config = config
        self.serial = str(config.Emulator_Serial) if config else ''

    @classmethod
    def execute(cls, command, wait=True):
        """
        Args:
            command (str): Command to execute
            wait (bool): Whether to wait for completion
            
        Returns:
            subprocess.Popen or subprocess.CompletedProcess:
        """
        # On Mac, use shell=True for complex commands
        logger.info(f'Execute: {command}')
        if wait:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True
            )
            return result
        else:
            return subprocess.Popen(command, shell=True)

    @classmethod
    def kill_process_by_regex(cls, regex: str) -> int:
        """
        Kill processes with name matching the given regex.
        
        Args:
            regex: Regex pattern to match process names
            
        Returns:
            int: Number of processes killed
        """
        count = 0
        for proc in psutil.process_iter():
            try:
                name = proc.name()
                if re.search(regex, name, re.IGNORECASE):
                    logger.info(f'Kill emulator process: {name}')
                    proc.kill()
                    count += 1
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return count

    def _emulator_start(self, instance: EmulatorInstanceMac):
        """
        Start a emulator without error handling
        """
        exe: str = instance.emulator.path

        if instance == EmulatorMac.BlueStacksAir:
            # Use open command to launch BlueStacks Air app
            # First find the app bundle
            app_path = EmulatorMac.find_app_bundle('BlueStacks')
            if app_path:
                self.execute(f'open -a "{app_path}"', wait=False)
            else:
                raise Exception('BlueStacks Air app not found')

        elif instance == EmulatorMac.MuMuPro:
            # MuMu on macOS requires two steps:
            # 1. Start MuMuPlayer.app (required for mumutool to work)
            # 2. Use mumutool to open the emulator instance
            app_path = EmulatorMac.find_app_bundle('MuMu')
            if app_path:
                # Step 1: Start MuMuPlayer in background
                self.execute(f'open -a "{app_path}"', wait=False)
                # Give MuMuPlayer a moment to initialize
                import time
                time.sleep(2)
                # Step 2: Use mumutool to open emulator instance 0
                mumutool = os.path.join(app_path, 'Contents/MacOS/mumutool')
                self.execute(f'"{mumutool}" open 0', wait=True)
            else:
                raise Exception('MuMu Pro app not found')

        else:
            # Generic fallback: try to open by path
            if os.path.exists(exe):
                self.execute(f'open "{exe}"', wait=False)
            else:
                raise Exception(f'Cannot start unknown emulator: {instance}')

    def _emulator_stop(self, instance: EmulatorInstanceMac):
        """
        Stop a emulator without error handling
        """
        if instance == EmulatorMac.BlueStacksAir:
            # Try to find and kill BlueStacks processes
            killed = self.kill_process_by_regex(r'BlueStacks')
            if killed == 0:
                # Fallback: use osascript to quit
                self.execute('osascript -e \'tell application "BlueStacks" to quit\'', wait=True)
        
        elif instance == EmulatorMac.MuMuPro:
            # Use mumutool to gracefully close the emulator
            app_path = EmulatorMac.find_app_bundle('MuMu')
            if app_path:
                mumutool = os.path.join(app_path, 'Contents/MacOS/mumutool')
                self.execute(f'"{mumutool}" close 0', wait=True)
            else:
                # Fallback: kill processes
                self.kill_process_by_regex(r'MuMu')
        
        else:
            # Generic fallback: kill by process name from instance
            if instance.name:
                self.kill_process_by_regex(instance.name)

    def _emulator_function_wrapper(self, func):
        """
        Args:
            func (callable): _emulator_start or _emulator_stop

        Returns:
            bool: If success
        """
        try:
            func(self.emulator_instance)
            return True
        except Exception as e:
            logger.exception(e)

        logger.error(f'Emulator function {func.__name__}() failed')
        return False

    def emulator_start_watch(self):
        """
        Returns:
            bool: True if startup completed
                False if timeout
        """
        logger.hr('Emulator start', level=2)
        serial = self.emulator_instance.serial

        @run_once
        def show_online(m):
            logger.info(f'Emulator online: {m}')

        @run_once
        def show_ping(m):
            logger.info(f'Command ping: {m}')

        @run_once
        def show_package(m):
            logger.info(f'Found azurlane packages: {m}')

        interval = Timer(0.5).start()
        timeout = Timer(180).start()
        
        while 1:
            interval.wait()
            interval.reset()
            if timeout.reached():
                logger.warning(f'Emulator start timeout')
                return False

            try:
                # Check device connection
                devices = self.list_device().select(serial=serial)
                if devices:
                    device: AdbDeviceWithStatus = devices.first_or_none()
                    if device.status == 'device':
                        pass
                    if device.status == 'offline':
                        self.adb_client.disconnect(serial)
                        self.adb_client.connect(serial)
                        continue
                else:
                    # Try to connect
                    self.adb_client.connect(serial)
                    continue
                show_online(devices.first_or_none())

                # Check command availability
                try:
                    pong = self.adb_shell(['echo', 'pong'])
                except Exception as e:
                    logger.info(e)
                    continue
                show_ping(pong)

                # Check azurlane package
                packages = self.list_known_packages(show_log=False)
                if len(packages):
                    pass
                else:
                    continue
                show_package(packages)

                # All check passed
                break
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                logger.info(e)
                continue
            except Exception as e:
                logger.exception(e)
                continue

        logger.info('Emulator start completed')
        return True

    def emulator_start(self):
        logger.hr('Emulator start', level=1)
        for _ in range(3):
            # Stop
            if not self._emulator_function_wrapper(self._emulator_stop):
                return False
            # Start
            if self._emulator_function_wrapper(self._emulator_start):
                # Success
                self.emulator_start_watch()
                return True
            else:
                # Failed to start, stop and start again
                if self._emulator_function_wrapper(self._emulator_stop):
                    continue
                else:
                    return False

        logger.error('Failed to start emulator 3 times, stopped')
        return False

    def emulator_stop(self):
        logger.hr('Emulator stop', level=1)
        for _ in range(3):
            # Stop
            if self._emulator_function_wrapper(self._emulator_stop):
                # Success
                return True
            else:
                # Failed to stop, start and stop again
                if self._emulator_function_wrapper(self._emulator_start):
                    continue
                else:
                    return False

        logger.error('Failed to stop emulator 3 times, stopped')
        return False


if __name__ == '__main__':
    from module.config import AzurLaneConfig
    config = AzurLaneConfig(config_name='alas')
    self = PlatformMac(config)
    d = self.emulator_instance
    print(d)
