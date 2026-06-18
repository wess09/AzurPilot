import os
import re
from dataclasses import dataclass

from tqdm import tqdm

from module.base.decorator import cached_property
from module.device.method.utils import removeprefix

# PlayerPrefs 调用模式匹配正则
REGEX_SETTING = re.compile(r'PlayerPrefs.Get(\w{1,10})\((.*)\)')
# 设置键名提取正则
REGEX_SETTING_KEY = re.compile(r'"(.*?)"')


def _strip_code(string):
    """提取字符串中最外层括号匹配的代码片段。

    Args:
        string: 包含括号的代码字符串。

    Yields:
        括号内的字符，遇到最外层右括号时停止。
    """
    nested = 0
    for word in string:
        if word == '(':
            nested += 1
        if word == ')':
            # 遇到最外层右括号时结束
            if nested == 1:
                yield word
                return
            nested -= 1
        yield word


def strip_code(string):
    """拼接 _strip_code 生成器的输出为完整字符串。"""
    return ''.join(list(_strip_code(string)))


@dataclass
class Field:
    """游戏设置字段定义，用于存储 PlayerPrefs 读取的配置项。

    Attributes:
        formatter: 值类型转换函数（int/str/float）。
        default: 默认值。
        regex: 用于匹配设置键名的正则表达式。
    """
    formatter: callable
    default: ''
    regex: str


@dataclass
class LuaSetting:
    """从 Lua 脚本中提取的 PlayerPrefs 设置项。

    Attributes:
        raw: 原始代码行。
        typ: 值类型，可选 "Int"、"String"、"Float"。
        code: 设置键名和默认值的代码片段。
        duplicate: 是否为重复项。
    """
    raw: str
    typ: str  # "Int", "String", "Float"
    code: str  # 如 "AUTOFIGHT_BATTERY_SAVEMODE, 0" 或 "world_help_progress"

    duplicate = False

    @cached_property
    def default(self):
        """解析设置项的默认值。

        Returns:
            根据类型返回 int/str/float 默认值，无法解析时返回 None。
        """
        if ',' in self.code:
            name, default = self.code.split(',', 1)
            default = default.strip(' ",')
            if self.typ == 'Int':
                try:
                    return int(default)
                except ValueError:
                    return 0
            if self.typ == 'String':
                return repr(default)
            if self.typ == 'Float':
                try:
                    return float(default)
                except ValueError:
                    return 0.
        else:
            if self.typ == 'Int':
                return 0
            if self.typ == 'String':
                return repr('')
            if self.typ == 'Float':
                return 0.
        return None

    @cached_property
    def key(self):
        """提取设置项的键名，将特殊字符替换为下划线。

        Returns:
            清理后的键名字符串，无法提取时返回空字符串。
        """
        if ',' in self.code:
            code = self.code.rsplit(',', 1)[0].strip(' ')
        else:
            code = self.code.strip(' ')

        res = REGEX_SETTING_KEY.search(code)
        if res:
            return res.group(1).replace('.', '_').replace('%', '_').replace('-', '_').replace(':', '_').strip('_')
        else:
            return ''

    @cached_property
    def formatter(self):
        """获取值类型对应的格式化函数名。

        Returns:
            'int'、'str' 或 'float'。
        """
        if self.typ == 'Int':
            return 'int'
        if self.typ == 'String':
            return 'str'
        if self.typ == 'Float':
            return 'float'
        return 'str'

    @cached_property
    def regex(self):
        """生成匹配设置键名的正则表达式。

        Returns:
            正则表达式字符串的 repr 形式。
        """
        if ',' in self.code:
            code = self.code.rsplit(',', 1)[0].strip(' ')
        else:
            code = self.code.strip(' ')

        pieces = code.split('..')

        def iter_piece():
            for piece in pieces:
                res = REGEX_SETTING_KEY.search(piece)
                if res:
                    yield res.group(1)
                else:
                    yield '(.*)'

        return repr(''.join(list(iter_piece())))

    @cached_property
    def generated(self):
        """生成该设置项的 Python 代码行。

        Returns:
            包含注释和赋值语句的代码行列表。
        """
        if self.key == '':
            return [
                f'# {self.raw}',
                'pass  # 未知'
            ]
        if self.duplicate:
            return [
                f'# {self.raw}',
                'pass  # 重复'
            ]

        return [
            f'# {self.raw}',
            f'{self.key} = Field(formatter={self.formatter}, default={self.default}, regex={self.regex})'
        ]


class SettingExtractor:
    """从 Lua 脚本中提取 PlayerPrefs 设置并生成 Python 定义文件。"""

    @staticmethod
    def iter_setting_from_file(file):
        """从单个 Lua 文件中提取所有 PlayerPrefs 设置。

        Args:
            file: Lua 文件路径。

        Yields:
            LuaSetting 对象，每个对应一个 PlayerPrefs 调用。
        """
        with open(file, mode='r', encoding='utf8') as f:
            data = list(f.readlines())

        for row in data:
            row = row.strip()
            res = REGEX_SETTING.search(row)
            if res:
                row = strip_code(res.group(0))
                res = REGEX_SETTING.search(row)
                if res:
                    yield LuaSetting(raw=row, typ=res.group(1), code=res.group(2))

    @staticmethod
    def iter_file_from_folder(folder):
        """遍历文件夹中的所有文件。

        Args:
            folder: 目标文件夹路径。

        Yields:
            文件的完整路径。
        """
        for path, folders, files in os.walk(folder):
            for file in files:
                file = f'{path}/{file}'
                yield file

    def iter_generated_lines(self, folder):
        """生成设置文件的所有代码行。

        Args:
            folder: Lua 脚本所在文件夹路径。

        Yields:
            Python 代码行字符串，包括导入语句、类定义和字段赋值。
        """
        dic_settings = set()
        yield 'from module.game_setting.setting_extractor import Field'
        yield ''
        yield '# 由 module/game_setting/setting_extractor.py 自动生成'
        yield '# 请勿手动修改。'
        yield ''
        yield ''
        yield 'class GameSettingsGenerated:'
        files = list(self.iter_file_from_folder(folder))
        for file in tqdm(files):
            settings = list(self.iter_setting_from_file(file))
            if not settings:
                continue
            yield ''
            f = removeprefix(file, folder).replace("\\", "/")
            yield f'    # {f}'
            for setting in settings:
                if setting.key in dic_settings:
                    setting.duplicate = True
                dic_settings.add(setting.key)
                for line in setting.generated:
                    yield f'    {line}'

    def generate(self, folder, output='./module/game_setting/setting_generated.py'):
        """生成 Python 设置定义文件。

        Args:
            folder: Lua 脚本所在文件夹路径。
            output: 输出文件路径，默认为 setting_generated.py。
        """
        lines = [l + '\n' for l in self.iter_generated_lines(folder)]
        with open(output, mode='w', encoding='utf8') as f:
            f.writelines(lines)


if __name__ == '__main__':
    # AzurLaneLuaScripts\CN 的路径
    FOLDER = r''
    ex = SettingExtractor()
    ex.generate(FOLDER)
