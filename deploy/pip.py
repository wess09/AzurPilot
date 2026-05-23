import subprocess
import shutil
import shlex
import sys
import typing as t
from dataclasses import dataclass
from urllib.parse import urlparse

from deploy.config import DeployConfig, ExecutionError
from deploy.logger import logger
from deploy.utils import *


@dataclass
class DataDependency:
    name: str
    version: str

    def __post_init__(self):
        # uvicorn[standard] -> uvicorn
        self.name = re.sub(r'\[.*\]', '', self.name)
        # opencv_python -> opencv-python
        self.name = self.name.replace('_', '-').strip()
        # PyYaml -> pyyaml
        self.name = self.name.lower()
        self.version = self.version.strip()
        self.version = re.sub(r'\.0$', '', self.version)

    @cached_property
    def pretty_name(self):
        return f'{self.name}=={self.version}'

    def __str__(self):
        return self.pretty_name

    __repr__ = __str__

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))


class PipManager(DeployConfig):
    @cached_property
    def python(self) -> str:
        # No need to read PythonExecutable
        # since you run this code with python, current python is the python

        # exe = self.filepath(self.PythonExecutable)
        # if os.path.exists(exe):
        #     return exe

        current = sys.executable.replace("\\", "/")
        # logger.warning(f'PythonExecutable: {exe} does not exist, use current python instead: {current}')
        return current

    @cached_property
    def requirements_file(self):
        if self.RequirementsFile == 'requirements.txt':
            return 'requirements.txt'
        else:
            return self.filepath("RequirementsFile")

    @cached_property
    def pip(self):
        return f'"{self.python}" -m pip'

    @cached_property
    def uv(self):
        exe = shutil.which('uv')
        if exe:
            return exe.replace("\\", "/")
        return None

    def execute_pip(self, args):
        cmd = [self.python, '-m', 'pip'] + list(map(str, args))
        command = shlex.join(cmd)
        logger.info(command)
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        process = subprocess.Popen(cmd, shell=False)
        process.communicate()
        if process.returncode:
            logger.info(f"[ failure ], error_code: {process.returncode}")
            self.show_error(command)
            raise ExecutionError
        logger.info(f"[ success ]")
        return True

    def execute_uv_pip(self, args):
        if not self.uv:
            logger.critical('uv is required to install dependencies without modifying system Python')
            raise ExecutionError

        cmd = [self.uv, 'pip'] + list(map(str, args))
        command = shlex.join(cmd)
        logger.info(command)
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        process = subprocess.Popen(cmd, shell=False)
        process.communicate()
        if process.returncode:
            logger.info(f"[ failure ], error_code: {process.returncode}")
            self.show_error(command)
            raise ExecutionError
        logger.info(f"[ success ]")
        return True

    @cached_property
    def python_site_packages(self) -> str:
        import site
        paths = site.getsitepackages()
        # site-packages should be site-packages folder
        for path in paths:
            if path.endswith('site-packages'):
                return path
        # Otherwise pick first
        return paths[0]

    @cached_property
    def set_installed_dependency(self) -> t.Set[DataDependency]:
        data = []
        regex = re.compile(r'(.*)-(.*).dist-info')
        try:
            for name in os.listdir(self.python_site_packages):
                res = regex.search(name)
                if res:
                    dep = DataDependency(name=res.group(1), version=res.group(2))
                    data.append(dep)
        except FileNotFoundError:
            logger.info(f'Directory not found: {self.python_site_packages}')
        return set(data)

    @cached_property
    def set_required_dependency(self) -> t.Set[DataDependency]:
        data = []
        regex = re.compile('(.*)==(.*)[ ]*#')
        file = self.requirements_file
        try:
            with open(file, 'r', encoding='utf-8') as f:
                for line in f.readlines():
                    res = regex.search(line)
                    if res:
                        dep = DataDependency(name=res.group(1), version=res.group(2))
                        data.append(dep)
        except FileNotFoundError:
            logger.info(f'File not found: {file}')
        return set(data)

    @cached_property
    def set_dependency_to_install(self) -> t.Set[DataDependency]:
        """
        A poor dependency comparison, but much much faster than `pip install` and `pip list`
        """
        data = []
        for dep in self.set_required_dependency:
            if dep not in self.set_installed_dependency:
                data.append(dep)
        return set(data)

    def pip_install(self):
        logger.hr('Update Dependencies', 0)

        if not self.InstallDependencies:
            logger.info('InstallDependencies is disabled, skip')
            return

        if not len(self.set_dependency_to_install):
            logger.info('All dependencies installed')
            return
        else:
            logger.info(f'Dependencies to install: {self.set_dependency_to_install}')

        logger.hr('Check Python', 1)
        self.execute(f'"{self.python}" --version')

        uv_arg = []
        pip_arg = []
        if self.PypiMirror:
            mirror = self.PypiMirror
            uv_arg += ['--default-index', mirror]
            pip_arg += ['-i', mirror]
            # Trust http mirror or skip ssl verify
            if 'http:' in mirror or not self.SSLVerify:
                hostname = urlparse(mirror).hostname
                if hostname:
                    uv_arg += ['--allow-insecure-host', hostname]
                    pip_arg += ['--trusted-host', hostname]
        elif not self.SSLVerify:
            uv_arg += ['--allow-insecure-host', 'pypi.org']
            uv_arg += ['--allow-insecure-host', 'files.pythonhosted.org']
            pip_arg += ['--trusted-host', 'pypi.org']
            pip_arg += ['--trusted-host', 'files.pythonhosted.org']

        # Don't update pip, just leave it.
        # logger.hr('Update pip', 1)
        # self.execute(f'"{self.pip}" install --upgrade pip{arg}')
        pip_arg += ['--disable-pip-version-check']

        logger.hr('Update Dependencies', 1)
        if self.uv:
            self.execute_uv_pip(
                ['install', '--python', self.python, '-r', self.requirements_file] + uv_arg
            )
        elif sys.platform == 'win32':
            logger.warning('uv is not available, fallback to python -m pip on Windows')
            self.execute_pip(['install', '-r', self.requirements_file] + pip_arg)
        else:
            logger.critical('uv is required to install dependencies without modifying system Python')
            raise ExecutionError
