import random
import sys
from typing import Optional, Union

from deploy.geo import get_country_code
from deploy.config_transaction import DeployConfigTransaction
from deploy.logger import logger
from deploy.utils import *


GIT_OVER_CDN_REPOSITORY = 'git://git.pull/AzurPilot'
GIT_OVER_CDN_FALLBACK_REPOSITORIES = [
    'https://cnb.cool/AzurPilot/AzurPilot',
    'https://gitcode.com/ddl2/AzurPilot',
]
GIT_OVER_CDN_FALLBACK_REPOSITORY = GIT_OVER_CDN_FALLBACK_REPOSITORIES[1]


def choose_fallback_repository() -> str:
    """在可用的国内镜像源（CNB 与 GitCode）之间分流，避免单一镜像源流量过大引发风控。"""
    return random.choice(GIT_OVER_CDN_FALLBACK_REPOSITORIES)
GITHUB_REPOSITORY = 'https://github.com/wess09/AzurPilot'


class ErrorCodes:
    """部署错误码：同时作为进程退出码返回，启动器按码分类展示。

    码段与 gui.py 的 EXIT_*（70-76）互不重叠；新增码值必须同步
    启动器（alas-launcher）的错误码映射表。
    """

    EXEC_UNKNOWN = 1
    COMMAND_FAILED = 10      # execute() 通用命令执行失败
    GIT_FETCH_FAILED = 11    # git fetch 主源与全部镜像重试穷尽
    GIT_MERGE_FAILED = 12    # git pull/merge 合并失败
    DEPS_SYNC_FAILED = 13    # 依赖同步（uv sync / pip）失败


class ExecutionError(Exception):
    """部署流程执行失败；code 取 ErrorCodes，供上游结构化识别。"""

    def __init__(self, code: int = ErrorCodes.EXEC_UNKNOWN, message: str = ''):
        super().__init__(message or f'deploy failed with error code {code}')
        self.code = code


class ConfigModel:
    """部署配置模型，定义所有配置项及其默认值。"""
    # Git 配置
    Repository: str = GITHUB_REPOSITORY
    Branch: str = "master"
    GitExecutable: str = "./.venv/Scripts/git/cmd/git.exe" if sys.platform == "win32" else "./.venv/bin/git"
    GitProxy: Optional[str] = None
    SSLVerify: bool = False
    UseMirrorChyan: bool = False
    MirrorChyanCdk: Optional[str] = None

    # Python 配置
    PythonExecutable: str = "./.venv/Scripts/python.exe" if sys.platform == "win32" else "./.venv/bin/python"
    PypiMirror: Optional[str] = None
    InstallDependencies: bool = True

    # ADB 配置
    AdbExecutable: str = "./.venv/Scripts/adb.exe" if sys.platform == "win32" else "./.venv/bin/adb"
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
    RemoteAccessMode: str = "auto"
    CloudflareRegistry: str = "https://remote.azurpilot.com"
    CloudflareDeviceId: str = ""
    RemoteAccessPort: int = 0
    RemoteAccessPublicPort: int = 0
    SSHUser: Optional[str] = None
    SSHServer: Optional[str] = None
    SSHExecutable: Optional[str] = None
    AllowedRedirectHosts: Optional[str] = None
    MaxRedirects: int = 2
    SignalingServer: Optional[str] = None
    StunServers: Optional[str] = '["stun:stun.l.google.com:19302"]'
    TurnServers: Optional[str] = None
    TurnCredentialMode: str = "static"

    # WebUI 配置
    WebuiHost: str = "0.0.0.0"
    WebuiPort: int = 25548
    WebuiSSLKey: Optional[str] = None
    WebuiSSLCert: Optional[str] = None
    Language: str = "en-US"
    Theme: str = "default"
    DpiScaling: bool = True
    Password: Optional[str] = None
    CDN: Union[str, bool] = False
    # --watermark. 关闭未经验证版本的水印。默认 False，即默认显示水印，
    # 用于提醒当前运行的是未经验证的构建（见 module/webui/app_shell.py）。
    DisableBranchWatermark: bool = False
    Run: Optional[str] = None

    # 动态配置
    GitOverCdn: bool = False
    MirrorChyan: bool = False


class DeployConfig(DeployConfigTransaction, ConfigModel):
    """部署配置管理器，负责配置的读取、保存、重定向与执行环境管理。"""

    def __init__(self, file=DEPLOY_CONFIG):
        """初始化部署配置。

        Args:
            file (str): 用户部署配置文件路径。
        """
        self.file = file
        self.template_file = get_deploy_template()
        self.config = {}
        self.config_template = {}
        self._github_location_checked = False
        # 地区查询可能等待网络；预读仅用于查询，事务内仍重新读取最新配置。
        values = {**poor_yaml_read(self.template_file), **poor_yaml_read(self.file)}
        self._github_country_code = (get_country_code()
                                     if values.get('Repository') == GITHUB_REPOSITORY else None)
        self.read()

        self.show_config()

    def show_config(self):
        """打印与默认模板不同的配置项。"""
        logger.hr("Show deploy config", 1)
        for k, v in self.config.items():
            if k in ("Password", "SSHUser", "MirrorChyanCdk"):
                continue
            if self.config_template.get(k) == v:
                continue
            logger.info(f"{k}: {v}")

        logger.info(f"Rest of the configs are the same as default")

    def config_redirect(self):
        """部署配置重定向，处理旧配置到新配置的迁移。

        每次 `read()` 之后必须调用。
        """
        self.config.pop('AutoUpdate', None)
        self._redirect_github_repository()
        if self.Repository in [
            'https://gitee.com/LmeSzinc/AzurLaneAutoScript',
            'https://gitee.com/lmeszinc/azur-lane-auto-script-mirror',
            'https://e.coding.net/llop18870/alas/AzurLaneAutoScript.git',
            'https://e.coding.net/saarcenter/alas/AzurLaneAutoScript.git',
            'https://git.saarcenter.com/LmeSzinc/AzurLaneAutoScript.git',
            'git://git.lyoko.io/AzurLaneAutoScript',
            'https://gitcode.com/ZhangMusan/AzurLaneAutoScript',
            'https://gitcode.com/nerom/AzurLaneAutoScript',
            'https://gitee.com/wqeaxc/AzurLaneAutoScript1',
            'https://git.nanoda.work/git/AzurLaneAutoScript',
            'https://git.nanoda.work/git/AzurPilot',
            'https://git.nanoda.work',
        ]:
            object.__setattr__(self, 'Repository', GIT_OVER_CDN_REPOSITORY)
            self.config['Repository'] = GIT_OVER_CDN_REPOSITORY
        if self.PypiMirror in [
            'https://pypi.tuna.tsinghua.edu.cn/simple'
        ]:
            object.__setattr__(self, 'PypiMirror', 'https://mirrors.aliyun.com/pypi/simple')
            self.config['PypiMirror'] = 'https://mirrors.aliyun.com/pypi/simple'

        # 绕过 webui.config.DeployConfig.__setattr__()，不写入 deploy.yaml
        super().__setattr__(
            'GitOverCdn',
            self.Repository in ['cn', GIT_OVER_CDN_REPOSITORY] and self.Branch == 'master'
        )
        super().__setattr__(
            'MirrorChyan',
            (bool(getattr(self, 'UseMirrorChyan', False)) or self.Repository == 'mirrorchyan')
            and self.Branch == 'master'
        )
        if self.Repository in ['global']:
            super().__setattr__('Repository', 'https://github.com/wess09/AzurPilot')
        if self.Repository in ['cn', GIT_OVER_CDN_REPOSITORY, 'mirrorchyan']:
            super().__setattr__('Repository', choose_fallback_repository())
        if self.Repository in ['cnb']:
            super().__setattr__('Repository', GIT_OVER_CDN_FALLBACK_REPOSITORIES[0])
        if self.Repository in ['gitcode']:
            super().__setattr__('Repository', GIT_OVER_CDN_FALLBACK_REPOSITORIES[1])

    def _redirect_github_repository(self):
        """为官方 GitHub 源一次性选择适合当前网络的更新镜像。"""
        if self._github_location_checked or self.Repository != GITHUB_REPOSITORY:
            return

        self._github_location_checked = True
        country_code = self._github_country_code
        if country_code == 'cn':
            logger.info('检测到中国大陆网络，切换至国内 Git 更新源')
            object.__setattr__(self, 'Repository', GIT_OVER_CDN_REPOSITORY)
            self.config['Repository'] = GIT_OVER_CDN_REPOSITORY
        elif country_code is None:
            logger.warning('无法检测网络所在国家，保留 GitHub 更新源')
        else:
            logger.info('当前网络不在中国大陆，保留 GitHub 更新源')

    def filepath(self, key):
        """根据配置键获取绝对文件路径。

        Args:
            key (str): 配置键名。

        Returns:
            str: 绝对文件路径。
        """
        path = self.config[key]
        # 启动器可写入带双引号的 YAML 路径，引号不是文件名的一部分。
        if len(path) >= 2 and path[0] == path[-1] == '"':
            path = path[1:-1]
        return (
            os.path.abspath(os.path.join(self.root_filepath, path))
            .replace(r"\\", "/")
            .replace("\\", "/")
            .replace('"', '"')
        )

    @cached_property
    def root_filepath(self):
        """获取项目根目录绝对路径。

        Returns:
            str: 格式化为斜杠分隔的根目录绝对路径。
        """
        return (
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
            .replace(r"\\", "/")
            .replace("\\", "/")
            .replace('"', '"')
        )

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
        # Windows cmd /c 会剥掉首尾引号；额外包一层，保留程序路径和参数的引号。
        shell_command = f'"{command}"' if os.name == 'nt' and command.startswith('"') else command
        error_code = os.system(shell_command)
        if error_code:
            if allow_failure:
                logger.info(f"[ allowed failure ], error_code: {error_code}")
                return False
            else:
                logger.info(f"[ failure ], error_code: {error_code}")
                self.show_error(command)
                raise ExecutionError(
                    ErrorCodes.COMMAND_FAILED,
                    f'Command failed (exit {error_code}): {command}',
                )
        else:
            logger.info(f"[ success ]")
            return True

    def show_error(self, command=None):
        """展示更新失败信息及排查指引。

        Args:
            command (str, optional): 导致失败的命令。
        """
        logger.hr("Update failed", 0)
        self.show_config()
        logger.info("")
        logger.info(f"Last command: {command}")
        logger.info(
            "Please check your deploy settings in config/deploy.yaml "
            "and re-open AzurPilot.exe"
        )
        logger.info("Take the screenshot of entire window if you need help")
