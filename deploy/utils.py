import os
import re
from typing import Callable, Generic, TypeVar

from deploy.atomic import atomic_read_text, atomic_write

T = TypeVar("T")

DEPLOY_CONFIG = './config/deploy.yaml'
DEPLOY_TEMPLATE = './deploy/template'


class cached_property(Generic[T]):
    """
    cached-property from https://github.com/pydanny/cached-property
    Add typing support

    A property that is only computed once per instance and then replaces itself
    with an ordinary attribute. Deleting the attribute resets the property.
    Source: https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
    """

    def __init__(self, func: Callable[..., T]):
        self.func = func

    def __get__(self, obj, cls) -> T:
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


def iter_folder(folder, is_dir=False, ext=None):
    """
    Args:
        folder (str):
        is_dir (bool): True to iter directories only
        ext (str): File extension, such as `.yaml`

    Yields:
        str: Absolute path of files
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
    """
    Poor implementation to load yaml without pyyaml dependency, but with re

    Args:
        file (str):

    Returns:
        dict:
    """
    content = atomic_read_text(file)
    data = {}
    indent_stack = []
    current_dict = data
    
    for line in content.splitlines():
        # 去除行尾的换行符、制表符和空格，保留缩进空格
        line = line.rstrip('\n\r\t ')
        if line.startswith('#'):
            continue
        
        # 计算缩进级别（使用所有空白字符）
        indent = len(line) - len(line.lstrip())
        line = line.lstrip()
        
        if not line:
            continue
        
        result = re.match(r'^(.*?):(.*?)$', line)
        if result:
            k, v = result.group(1), result.group(2).strip()
            
            # 管理缩进栈
            while indent_stack:
                if indent_stack[-1][0] < indent:
                    # 栈顶缩进小于当前行，说明当前是子节点，保持当前字典
                    break
                else:
                    # 栈顶缩进大于等于当前行，弹出栈顶
                    # 如果是大于，说明是返回父节点；如果是等于，说明是同级节点
                    indent_stack.pop()
            
            # 如果缩进栈不为空，使用栈顶的字典作为当前字典
            if indent_stack:
                current_dict = indent_stack[-1][1]
            else:
                current_dict = data
            
            if v:
                if v.lower() == 'null':
                    v = None
                elif v.lower() == 'false':
                    v = False
                elif v.lower() == 'true':
                    v = True
                elif v.isdigit():
                    v = int(v)
                current_dict[k] = v
            else:
                # 嵌套字典
                new_dict = {}
                current_dict[k] = new_dict
                # 将新字典添加到缩进栈
                indent_stack.append((indent, new_dict))
                current_dict = new_dict

    return data


def poor_yaml_write(data, file, template_file=DEPLOY_TEMPLATE):
    """
    Args:
        data (dict):
        file (str):
        template_file (str):
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
