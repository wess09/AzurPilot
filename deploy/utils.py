import os
import re
import sys
from typing import Callable, Generic, TypeVar

from deploy.atomic import atomic_read_text, atomic_write

T = TypeVar("T")

DEPLOY_CONFIG = './config/deploy.yaml'
DEPLOY_TEMPLATE = './deploy/template'


def get_deploy_template():
    if sys.platform == 'win32':
        return './config/deploy.template.yaml'
    if sys.platform == 'darwin':
        return './config/deploy.template-linux.yaml'
    if sys.platform.startswith('linux'):
        return './config/deploy.template-linux.yaml'
    return DEPLOY_TEMPLATE


class cached_property(Generic[T]):
    """带类型支持的缓存属性描述符。

    属性只在首次访问时计算一次，之后替换为普通属性。
    删除属性后会重新计算。来源：bottlepy/bottle。
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

    仅支持简单的 key: value 格式，不支持嵌套结构。

    Args:
        file (str): YAML 文件路径。

    Returns:
        dict: 解析后的键值对。
    """
    content = atomic_read_text(file)
    data = {}
    regex = re.compile(r'^(.*?):(.*?)$')
    for line in content.splitlines():
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
    text = atomic_read_text(template_file)
    text = text.replace('\\', '/')

    for key, value in data.items():
        if value is None:
            value = 'null'
        elif value is True:
            value = "true"
        elif value is False:
            value = "false"
        text = re.sub(f'{key}:.*?\n', f'{key}: {value}\n', text)

    atomic_write(file, text)
