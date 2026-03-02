import os
import re
import subprocess
from dataclasses import dataclass

import psutil

from module.device.platform.emulator_base import EmulatorBase, EmulatorInstanceBase, EmulatorManagerBase
from module.device.platform.utils import cached_property


def abspath(path):
    return os.path.abspath(path).replace('\\', '/')


class EmulatorInstanceMac(EmulatorInstanceBase):
    @cached_property
    def emulator(self):
        """
        Returns:
            Emulator:
        """
        return EmulatorMac(self.path)


class EmulatorMac(EmulatorBase):
    """
    Mac emulator types.
    Values here must match those in argument.yaml EmulatorInfo.Emulator.option
    """
    BlueStacksAir = 'BlueStacksAir'
    BlueStacksMIM = 'BlueStacksMIM'
    MuMuPro = 'MuMuPro'

    @classmethod
    def path_to_type(cls, path: str) -> str:
        """
        Args:
            path: Path to .app bundle or .exe file (case insensitive)

        Returns:
            str: Emulator type, such as EmulatorMac.BlueStacksAir
        """
        path = path.lower()
        
        # BlueStacks MIM (Hyper-V based)
        if 'bluestacksmim' in path or 'bluestacks_mim' in path:
            return cls.BlueStacksMIM
        
        # BlueStacks Air
        if 'bluestacks' in path:
            if '/bluestacks.app/' in path or path.endswith('/bluestacks.app'):
                return cls.BlueStacksAir
            # Also check for the executable
            if 'bluestacks' in path and ('hd-player' in path or path.endswith('bluestacks')):
                return cls.BlueStacksAir
        
        # MuMu Pro (Mac)
        if 'mumu' in path:
            # Check for MuMuEmulator (the actual emulator process)
            if 'mumuemulator' in path or 'mumu' in path and 'emulator' in path:
                return cls.MuMuPro
            # Also check for MuMuPlayer (older versions)
            if '/mumu' in path and 'player' in path:
                return cls.MuMuPro
        
        return ''

    @staticmethod
    def find_app_bundle(search_name: str, exclude_names: list = None) -> str:
        """
        Find an application bundle in /Applications.
        
        Args:
            search_name: Name to search for (e.g., "BlueStacks", "MuMu")
            exclude_names: List of names to exclude from matches
            
        Returns:
            str: Full path to .app bundle, or empty string if not found
        """
        apps_dir = '/Applications'
        if not os.path.exists(apps_dir):
            return ''
        
        if exclude_names is None:
            exclude_names = []
        
        # First, try to find exact match
        for item in os.listdir(apps_dir):
            if item.lower() == search_name.lower():
                # Check exclusions
                excluded = False
                for ex in exclude_names:
                    if item.lower() == ex.lower():
                        excluded = True
                        break
                if not excluded:
                    return os.path.join(apps_dir, item)
        
        # Then try startswith (but prefer shorter/cleaner names)
        matches = []
        for item in os.listdir(apps_dir):
            if item.lower().startswith(search_name.lower()):
                # Check exclusions
                excluded = False
                for ex in exclude_names:
                    if item.lower().startswith(ex.lower()):
                        excluded = True
                        break
                if not excluded:
                    matches.append(item)
        
        if matches:
            # Return the shortest match (most likely the base name)
            return os.path.join(apps_dir, min(matches, key=len))
        
        return ''

    def iter_instances(self):
        """
        Yields:
            EmulatorInstance: Emulator instances found on Mac
        """
        if self == EmulatorMac.BlueStacksMIM:
            # BlueStacks MIM (Hyper-V) uses port 5555 + 10*n
            app_path = self.find_app_bundle('BlueStacksMIM')
            if app_path:
                yield EmulatorInstanceMac(
                    serial='127.0.0.1:5555',
                    name='BlueStacksMIM',
                    path=app_path + '/Contents/MacOS/BlueStacks'
                )
        
        elif self == EmulatorMac.BlueStacksAir:
            # BlueStacks Air typically uses port 5555 + 10*n
            # Default instance: 127.0.0.1:5555
            # Multi-instance: 127.0.0.1:5555, 5565, 5575, etc.
            app_path = self.find_app_bundle('BlueStacks')
            if app_path:
                # Try to find instances from config
                config_path = os.path.expanduser('~/Library/Preferences/com.bluestacks.blueStacks.plist')
                if os.path.exists(config_path):
                    try:
                        result = subprocess.run(
                            ['defaults', 'read', config_path, 'bst.instance'],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            # Parse instance info
                            yield EmulatorInstanceMac(
                                serial='127.0.0.1:5555',
                                name='BlueStacksAir',
                                path=app_path + '/Contents/MacOS/BlueStacks'
                            )
                            return
                    except Exception:
                        pass
                
                # Default instance
                yield EmulatorInstanceMac(
                    serial='127.0.0.1:5555',
                    name='BlueStacksAir',
                    path=app_path + '/Contents/MacOS/BlueStacks'
                )
        
        elif self == EmulatorMac.MuMuPro:
            # MuMu Pro typically uses port 16384 + 32*n
            app_path = self.find_app_bundle('MuMu')
            if app_path:
                # Find vms directory
                vms_base = os.path.join(os.path.dirname(os.path.dirname(app_path)), 'vms')
                if os.path.exists(vms_base):
                    for folder in os.listdir(vms_base):
                        folder_path = os.path.join(vms_base, folder)
                        if os.path.isdir(folder_path):
                            # Try to find port from config
                            config_file = os.path.join(folder_path, 'config.ini')
                            if os.path.exists(config_file):
                                try:
                                    with open(config_file, 'r', encoding='utf-8', errors='ignore') as f:
                                        content = f.read()
                                        port_match = re.search(r'port=(\d+)', content)
                                        if port_match:
                                            port = port_match.group(1)
                                        else:
                                            port = '16384'
                                except Exception:
                                    port = '16384'
                            else:
                                port = '16384'
                            
                            yield EmulatorInstanceMac(
                                serial=f'127.0.0.1:{port}',
                                name=folder,
                                path=app_path + '/Contents/MacOS/MuMuEmulator.app/Contents/MacOS/MuMuEmulator'
                            )
                else:
                    # Default instance
                    yield EmulatorInstanceMac(
                        serial='127.0.0.1:16384',
                        name='MuMuPro',
                        path=app_path + '/Contents/MacOS/MuMuEmulator.app/Contents/MacOS/MuMuEmulator'
                    )

    def iter_adb_binaries(self) -> list:
        """
        Yields:
            str: Filepath to adb binaries found in this emulator
        """
        # Look for adb in common locations
        adb_locations = [
            self.abspath('../ADB/adb'),
            self.abspath('../../Android/SDK/platform-tools/adb'),
            '/usr/local/bin/adb',
            '/opt/homebrew/bin/adb',
        ]
        
        for adb_path in adb_locations:
            if os.path.exists(adb_path):
                yield adb_path
        
        # Also try to find BlueStacks/MuMu bundled adb
        if self == EmulatorMac.BlueStacksAir:
            app_path = self.find_app_bundle('BlueStacks')
            if app_path:
                adb_path = os.path.join(app_path, 'Contents/Resources/ADB/adb')
                if os.path.exists(adb_path):
                    yield adb_path
        
        elif self == EmulatorMac.MuMuPro:
            app_path = self.find_app_bundle('MuMu')
            if app_path:
                adb_path = os.path.join(app_path, 'Contents/MacOS/ADB/adb')
                if os.path.exists(adb_path):
                    yield adb_path


class EmulatorManagerMac(EmulatorManagerBase):
    @staticmethod
    def iter_running_emulator():
        """
        Yields:
            str: Path to emulator executables, may contain duplicate values
        """
        try:
            for proc in psutil.process_iter():
                try:
                    name = proc.info.get('name', '')
                    if not name:
                        continue
                    
                    # Check for Mac emulator processes
                    name_lower = name.lower()
                    if 'bluestacks' in name_lower or 'mumu' in name_lower:
                        # Try to get the actual path
                        try:
                            cmdline = proc.cmdline()
                            if cmdline:
                                yield cmdline[0]
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            pass
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
        except Exception:
            pass

    @cached_property
    def all_emulators(self) -> list:
        """
        Get all emulators installed on current Mac.
        """
        emulators = []
        
        # Check for BlueStacks MIM (Hyper-V)
        app_path = EmulatorMac.find_app_bundle('BlueStacksMIM')
        if app_path:
            exe_path = app_path + '/Contents/MacOS/BlueStacks'
            if os.path.exists(exe_path):
                emulators.append(EmulatorMac(exe_path))
        
        # Check for BlueStacks Air (not MIM)
        app_path = EmulatorMac.find_app_bundle('BlueStacks', exclude_names=['BlueStacksMIM'])
        if app_path:
            exe_path = app_path + '/Contents/MacOS/BlueStacks'
            if os.path.exists(exe_path):
                emulators.append(EmulatorMac(exe_path))
        
        # Check for MuMu Pro
        app_path = EmulatorMac.find_app_bundle('MuMu')
        if app_path:
            # Check for MuMuEmulator (the actual emulator process)
            exe_path = app_path + '/Contents/MacOS/MuMuEmulator.app/Contents/MacOS/MuMuEmulator'
            if os.path.exists(exe_path):
                emulators.append(EmulatorMac(exe_path))
            else:
                # Fallback to MuMuPlayer (older versions)
                exe_path = app_path + '/Contents/MacOS/MuMuPlayer'
                if os.path.exists(exe_path):
                    emulators.append(EmulatorMac(exe_path))
        
        return emulators

    @cached_property
    def all_emulator_instances(self) -> list:
        """
        Get all emulator instances installed on current Mac.
        """
        instances = []
        for emulator in self.all_emulators:
            instances += list(emulator.iter_instances())
        return sorted(instances, key=lambda x: str(x))


if __name__ == '__main__':
    self = EmulatorManagerMac()
    for emu in self.all_emulator_instances:
        print(emu)
