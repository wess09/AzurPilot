import copy
import os
import subprocess
import sys
from typing import Optional, Union

from deploy.Windows.logger import logger
from deploy.Windows.utils import DEPLOY_CONFIG, DEPLOY_TEMPLATE, cached_property, poor_yaml_read, poor_yaml_write


GIT_OVER_CDN_REPOSITORY = 'git://git.pull/AzurPilot'
GIT_OVER_CDN_FALLBACK_REPOSITORY = 'https://gitcode.com/ddl2/AzurLaneAutoScript'


class ExecutionError(Exception):
    pass


class ConfigModel:
    # Git 配置
    Repository: str = "https://github.com/wess09/AzurPilot"
    Branch: str = "master"
    GitExecutable: str = "./.venv/Scripts/git/cmd/git.exe"
    GitProxy: Optional[str] = None
    SSLVerify: bool = False
    AutoUpdate: bool = True

    # Python 配置
    PythonExecutable: str = "./.venv/Scripts/python.exe"
    PypiMirror: Optional[str] = None
    InstallDependencies: bool = True

    # ADB 配置
    AdbExecutable: str = "./.venv/Scripts/adb.exe"
    ReplaceAdb: bool = True
    AutoConnect: bool = True
    InstallUiautomator2: bool = True

    # OCR 配置
    UseOcrServer: bool = False
    StartOcrServer: bool = False
    OcrServerPort: int = 22268
    OcrClientAddress: str = "127.0.0.1:22268"

    # 更新配置
    EnableReload: bool = True
    CheckUpdateInterval: int = 5
    AutoRestartTime: str = "03:50"

    # 杂项
    DiscordRichPresence: bool = False

    # 远程访问
    EnableRemoteAccess: bool = False
    SSHUser: Optional[str] = None
    SSHServer: Optional[str] = None
    SSHExecutable: Optional[str] = None

    # WebUI 配置
    WebuiHost: str = "0.0.0.0"
    WebuiPort: int = 22367
    Language: str = "en-US"
    Theme: str = "default"
    DpiScaling: bool = True
    Password: Optional[str] = None
    CDN: Union[str, bool] = False
    Run: Optional[str] = None
    AppAsarUpdate: bool = True
    NoSandbox: bool = True

    # 动态配置
    GitOverCdn: bool = False


class DeployConfig(ConfigModel):
    def __init__(self, file=DEPLOY_CONFIG):
        """初始化部署配置。

        Args:
            file (str): 用户部署配置文件路径。
        """
        self.file = file
        self.config = {}
        self.config_template = {}
        self.read()

        self.show_config()

    def show_config(self):
        logger.hr("Show deploy config", 1)
        for k, v in self.config.items():
            if k in ("Password", "SSHUser"):
                continue
            if self.config_template.get(k) == v:
                continue
            logger.info(f"{k}: {v}")

        logger.info(f"Rest of the configs are the same as default")

    def read(self):
        self.config = poor_yaml_read(DEPLOY_TEMPLATE)
        self.config_template = copy.deepcopy(self.config)
        origin = poor_yaml_read(self.file)
        self.config.update(origin)

        for key, value in self.config.items():
            if hasattr(self, key):
                super().__setattr__(key, value)

        self.config_redirect()

        if self.config != origin:
            self.write()

    def write(self):
        poor_yaml_write(self.config, self.file)

    def config_redirect(self):
        """部署配置重定向，处理旧配置到新配置的迁移。

        每次 `read()` 之后必须调用。
        """
        # 绕过 webui.config.DeployConfig.__setattr__()，不写入 deploy.yaml
        super().__setattr__('GitOverCdn', self.Repository in ['cn', GIT_OVER_CDN_REPOSITORY])
        if self.Repository in ['global']:
            super().__setattr__('Repository', 'https://github.com/wess09/AzurPilot')
        if self.Repository in ['cn', GIT_OVER_CDN_REPOSITORY]:
            super().__setattr__('Repository', GIT_OVER_CDN_FALLBACK_REPOSITORY)

    def filepath(self, path):
        """获取绝对文件路径。

        Args:
            path (str): 相对或绝对路径。

        Returns:
            str: 绝对文件路径。
        """
        if os.path.isabs(path):
            return path

        return (
            os.path.abspath(os.path.join(self.root_filepath, path))
            .replace(r"\\", "/")
            .replace("\\", "/")
        )

    @cached_property
    def root_filepath(self):
        return (
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
            .replace(r"\\", "/")
            .replace("\\", "/")
        )

    @cached_property
    def adb(self) -> str:
        exe = self.filepath(self.AdbExecutable)
        if os.path.exists(exe):
            return exe

        logger.warning(f'AdbExecutable: {exe} does not exist, use `adb` instead')
        return 'adb'

    @cached_property
    def git(self) -> str:
        exe = self.filepath(self.GitExecutable)
        if os.path.exists(exe):
            return exe

        logger.warning(f'GitExecutable: {exe} does not exist, use `git` instead')
        return 'git'

    @cached_property
    def python(self) -> str:
        exe = self.filepath(self.PythonExecutable)
        if os.path.exists(exe):
            return exe

        current = sys.executable.replace("\\", "/")
        logger.warning(f'PythonExecutable: {exe} does not exist, use current python instead: {current}')
        return current

    def execute(self, command, allow_failure=False, output=True):
        """执行系统命令。

        Args:
            command (str): 要执行的命令。
            allow_failure (bool): 是否允许失败。
            output (bool): 是否显示输出。

        Returns:
            bool: 是否成功。失败且不允许失败时终止安装流程。
        """
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        if not output:
            command = command + ' >nul 2>nul'
        logger.info(command)
        error_code = os.system(command)
        if error_code:
            if allow_failure:
                logger.info(f"[ allowed failure ], error_code: {error_code}")
                return False
            else:
                logger.info(f"[ failure ], error_code: {error_code}")
                self.show_error(command)
                raise ExecutionError
        else:
            logger.info(f"[ success ]")
            return True

    def subprocess_execute(self, cmd, timeout=10):
        """在子进程中执行命令。

        Args:
            cmd (list[str]): 命令列表。
            timeout: 超时秒数，默认 10。

        Returns:
            str: 命令的标准输出。
        """
        logger.info(' '.join(cmd))
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            process.kill()
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.info(f'TimeoutExpired, stdout={stdout}, stderr={stderr}')
        return stdout.decode()

    def show_error(self, command=None):
        logger.hr("Update failed", 0)
        self.show_config()
        logger.info("")
        logger.info(f"Last command: {command}")
        logger.info(
            "Please check your deploy settings in config/deploy.yaml "
            "and re-open AzurPilot.exe"
        )
        logger.info("Take the screenshot of entire window if you need help")
