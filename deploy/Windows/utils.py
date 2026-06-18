import os
import re
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

T = TypeVar("T")

DEPLOY_CONFIG = './config/deploy.yaml'
DEPLOY_TEMPLATE = './deploy/Windows/template.yaml'


class cached_property(Generic[T]):
    """带类型支持的缓存属性描述符。

    属性只在首次访问时计算一次，之后替换为普通属性。
    删除属性后会重新计算。
    """

    def __init__(self, func: Callable[..., T]):
        self.func = func

    def __get__(self, obj, cls) -> T:
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


def iter_folder(folder, is_dir=False, ext=None):
    """遍历目录下的文件或子目录。

    Args:
        folder (str): 目录路径。
        is_dir (bool): True 时只遍历子目录。
        ext (str): 文件扩展名过滤，如 '.yaml'。

    Yields:
        str: 文件或目录的绝对路径。
    """
    for file in os.listdir(folder):
        sub = os.path.join(folder, file)
        if is_dir:
            if os.path.isdir(sub):
                yield sub.replace('\\\\', '/').replace('\\', '/')
        elif ext is not None:
            if not os.path.isdir(sub):
                _, extension = os.path.splitext(file)
                if extension == ext:
                    yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')
        else:
            yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')


def poor_yaml_read(file):
    """简易 YAML 读取，不依赖 pyyaml，使用正则解析。

    Args:
        file (str): YAML 文件路径。

    Returns:
        dict: 解析后的键值对。
    """
    if not os.path.exists(file):
        return {}

    data = {}
    regex = re.compile(r'^(.*?):(.*?)$')
    with open(file, 'r', encoding='utf-8') as f:
        for line in f.readlines():
            line = line.strip('\n\r\t ').replace('\\', '/')
            if line.startswith('#'):
                continue
            result = re.match(regex, line)
            if result:
                k, v = result.group(1), result.group(2).strip('\n\r\t\' ')
                if v:
                    if v.lower() == 'null':
                        v = None
                    elif v.lower() == 'false':
                        v = False
                    elif v.lower() == 'true':
                        v = True
                    elif v.isdigit():
                        v = int(v)
                    data[k] = v

    return data


def poor_yaml_write(data, file, template_file=DEPLOY_TEMPLATE):
    """简易 YAML 写入，基于模板文件替换键值。

    Args:
        data (dict): 要写入的键值对。
        file (str): 输出文件路径。
        template_file (str): 模板文件路径。
    """
    with open(template_file, 'r', encoding='utf-8') as f:
        text = f.read().replace('\\', '/')

    for key, value in data.items():
        if value is None:
            value = 'null'
        elif value is True:
            value = "true"
        elif value is False:
            value = "false"
        text = re.sub(f'{key}:.*?\n', f'{key}: {value}\n', text)

    with open(file, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


@dataclass
class DataProcessInfo:
    proc: object  # psutil.Process or psutil._pswindows.Process
    pid: int

    @cached_property
    def name(self):
        try:
            name = self.proc.name()
        except:
            name = ''
        return name

    @cached_property
    def cmdline(self):
        try:
            cmdline = self.proc.cmdline()
        except:
            # 可能抛出 psutil.AccessDenied 或 NoSuchProcess
            cmdline = []
        cmdline = ' '.join(cmdline).replace(r'\\', '/').replace('\\', '/')
        return cmdline

    def __str__(self):
        # 不打印 proc 属性，获取进程属性会消耗时间
        return f'DataProcessInfo(name="{self.name}", pid={self.pid}, cmdline="{self.cmdline}")'

    __repr__ = __str__


def iter_process() -> Iterable[DataProcessInfo]:
    """遍历系统中所有进程。

    Yields:
        DataProcessInfo: 进程信息。
    """
    try:
        import psutil
    except ModuleNotFoundError:
        return

    if psutil.WINDOWS:
        # 直接访问 psutil._psplatform.Process 以跳过 is_running() 调用，耗时约 0.017s
        for pid in psutil.pids():
            proc = psutil._psplatform.Process(pid)
            yield DataProcessInfo(
                proc=proc,
                pid=proc.pid,
            )
    else:
        # 非 Windows 平台使用 process_iter()，耗时约 0.45s
        for proc in psutil.process_iter():
            yield DataProcessInfo(
                proc=proc,
                pid=proc.pid,
            )
