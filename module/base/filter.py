"""正则过滤系统模块。

提供基于正则表达式的 Filter 类，用于解析和匹配游戏物品（舰船、装备等）的过滤规则。
支持预设字符串和 ">" 分隔的优先级排序语法。
"""

from functools import reduce
import re

from module.base.runtime_context import runtime_state
from module.logger import logger


class _FilterRuntimeState:
    """模块级 Filter 在单个 worker 中的已解析规则。"""

    __slots__ = ('filter_raw', 'filter')

    def __init__(self, filter_raw, parsed_filter):
        self.filter_raw = filter_raw
        self.filter = parsed_filter


class Filter:
    def __init__(self, regex, attr, preset=()):
        """
        Args:
            regex: 正则表达式，用于解析过滤字符串。
            attr: 对象属性名列表，与正则捕获组一一对应。
            preset: 内置的预设字符串列表，匹配时直接输出而不需要正则解析。
        """
        if isinstance(regex, str):
            regex = re.compile(regex)
        self.regex = regex
        self.attr = attr
        self.preset = tuple(list(p.lower() for p in preset))
        self.__dict__['_runtime_filter_raw'] = []
        self.__dict__['_runtime_filter'] = []

    def _state(self):
        return runtime_state(
            self,
            'filter',
            lambda: _FilterRuntimeState(
                list(self.__dict__['_runtime_filter_raw']),
                list(self.__dict__['_runtime_filter']),
            ),
        )

    @property
    def filter_raw(self):
        state = self._state()
        return state.filter_raw if state is not None else self.__dict__['_runtime_filter_raw']

    @filter_raw.setter
    def filter_raw(self, value):
        state = self._state()
        if state is None:
            self.__dict__['_runtime_filter_raw'] = value
        else:
            state.filter_raw = value

    @property
    def filter(self):
        state = self._state()
        return state.filter if state is not None else self.__dict__['_runtime_filter']

    @filter.setter
    def filter(self, value):
        state = self._state()
        if state is None:
            self.__dict__['_runtime_filter'] = value
        else:
            state.filter = value

    def load(self, string):
        """
        加载过滤字符串，多个过滤条件之间用 ">" 连接。

        同时会将各种 Unicode 类 ">" 字符统一替换为标准 ">"。
        """
        string = str(string)
        string = re.sub(r'[ \t\r\n]', '', string)
        string = re.sub(r'[＞﹥›˃ᐳ❯]', '>', string)
        self.filter_raw = string.split('>')
        self.filter = [self.parse_filter(f) for f in self.filter_raw]

    def is_preset(self, filter):
        return len(filter) and filter.lower() in self.preset

    def apply(self, objs, func=None):
        """
        将过滤条件应用到对象列表上，返回匹配的结果。

        Args:
            objs: 对象和预设字符串的混合列表。
            func: 可选的额外过滤函数，接收一个对象，返回 True 表示保留。

        Returns:
            匹配的对象和预设字符串列表，如 [object, object, object, 'reset']。
        """
        out = []
        for raw, filter in zip(self.filter_raw, self.filter):
            if self.is_preset(raw):
                raw = raw.lower()
                if raw not in out:
                    out.append(raw)
            else:
                for index, obj in enumerate(objs):
                    if self.apply_filter_to_obj(obj=obj, filter=filter) and obj not in out:
                        out.append(obj)

        if func is not None:
            objs, out = out, []
            for obj in objs:
                if isinstance(obj, str):
                    out.append(obj)
                elif func(obj):
                    out.append(obj)
                else:
                    # 丢弃该对象
                    pass

        return out

    def applys(self, objs, funcs):
        """
        将多个过滤函数依次应用到对象列表上。

        Args:
            objs: 对象和预设字符串的混合列表。
            funcs: 过滤函数列表，每个函数接收一个对象并返回 True 表示保留。
                所有函数都返回 True 时对象才会被保留。

        Returns:
            匹配的对象和预设字符串列表，如 [object, object, object, 'reset']。
        """
        return self.apply(objs, func=lambda x: all(func(x)for func in funcs))

    def apply_filter_to_obj(self, obj, filter):
        """
        检查对象是否满足过滤条件。

        Args:
            obj: 待检查的对象。
            filter: 过滤条件列表，与 `self.attr` 一一对应。

        Returns:
            对象是否满足过滤条件。
        """

        for attr, value in zip(self.attr, filter):
            if not value:
                continue

            obj_val = obj.__getattribute__(attr)
            
            # 允许通用物品（如没有特定 sub_genre 的 PlateT3）
            # 匹配带有特定 sub_genre 的过滤规则
            if attr == 'sub_genre' and obj_val is None:
                continue

            if str(obj_val).lower() != str(value):
                return False

        return True

    def parse_filter(self, string):
        """
        解析单个过滤条件字符串。

        Args:
            string: 过滤条件字符串。

        Returns:
            解析后的属性值列表，无效过滤条件返回 ['1nVa1d', None, ...]。
        """
        string = string.replace(' ', '').lower()
        result = re.search(self.regex, string)

        if self.is_preset(string):
            return [string]

        if result and len(string) and result.span()[1]:
            return [result.group(index + 1) for index, attr in enumerate(self.attr)]
        else:
            logger.warning(f'[过滤器] 无效的过滤器: "{string}"。此选择器不匹配正则表达式，也不是预设。')
            # 无效的过滤条件将被忽略
            # 返回不可能匹配的值以确保被跳过
            return ['1nVa1d'] + [None] * (len(self.attr) - 1)
