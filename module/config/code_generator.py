import typing as t


class TabWrapper:
    """缩进管理上下文管理器。

    在进入时增加缩进层级，退出时减少缩进层级，
    同时负责添加前缀和后缀代码。
    """

    def __init__(self, generator, prefix='', suffix='', newline=True):
        """
        Args:
            generator: 所属的代码生成器实例。
            prefix: 进入上下文时输出的前缀代码。
            suffix: 退出上下文时输出的后缀代码。
            newline: 前缀后是否换行。
        """
        self.generator = generator
        self.prefix = prefix
        self.suffix = suffix
        self.newline = newline

        self.nested = False

    def __enter__(self):
        if not self.nested and self.prefix:
            self.generator.add(self.prefix, newline=self.newline)
        self.generator.tab_count += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.generator.tab_count -= 1
        if self.suffix:
            self.generator.add(self.suffix)

    def __repr__(self):
        return self.prefix

    def set_nested(self, suffix=''):
        self.nested = True
        self.suffix += suffix


class CodeGenerator:
    """Python 源代码生成器。

    提供一系列方法用于构建带正确缩进的 Python 代码，
    支持生成 import、变量、类、函数、列表、字典等结构。
    """

    def __init__(self):
        self.tab_count = 0
        self.lines = []

    def generate(self) -> t.Iterable[str]:
        """生成代码行，子类应重写此方法。"""
        yield ''

    def add(self, line, comment=False, newline=True):
        """添加一行代码到输出缓冲区。

        Args:
            line: 要添加的代码文本。
            comment: 是否作为注释输出（自动添加 # 前缀）。
            newline: 是否在行尾添加换行符。
        """
        self.lines.append(self._line_with_tabs(line, comment=comment, newline=newline))

    def print(self):
        """将生成的代码输出到控制台。"""
        lines = ''.join(self.lines)
        print(lines)

    def write(self, file: str = None):
        """将生成的代码写入文件。

        Args:
            file: 输出文件路径。
        """
        lines = ''.join(self.lines)
        with open(file, 'w', encoding='utf-8', newline='') as f:
            f.write(lines)

    def _line_with_tabs(self, line, comment=False, newline=True):
        """根据当前缩进层级格式化一行代码。

        Args:
            line: 原始代码文本。
            comment: 是否添加注释前缀。
            newline: 是否追加换行符。

        Returns:
            带缩进的代码行字符串。
        """
        if comment:
            line = '# ' + line
        out = '    ' * self.tab_count + line
        if newline:
            out += '\n'
        return out

    def _repr(self, obj):
        """将对象转换为代码表示形式。

        字符串中的多行文本会被格式化为 docstring。
        其他对象使用 repr() 输出。

        Args:
            obj: 需要转换的对象。

        Returns:
            对象的代码表示字符串。
        """
        if isinstance(obj, str):
            if '\n' in obj:
                out = '"""\n'
                with self.tab():
                    for line in obj.strip().split('\n'):
                        line = line.strip()
                        out += self._line_with_tabs(line)
                out += self._line_with_tabs('"""', newline=False)
                return out
        return repr(obj)

    def tab(self):
        """创建一个缩进上下文管理器。

        Returns:
            TabWrapper 实例，可用作 `with` 语句的上下文管理器。
        """
        return TabWrapper(self)

    def Empty(self):
        """添加一个空行。"""
        self.add('')

    def Import(self, text, empty=2):
        """添加 import 语句块。

        Args:
            text: import 语句文本，多行用换行分隔。
            empty: import 块后的空行数量，默认为 2。
        """
        for line in text.strip().split('\n'):
            line = line.strip()
            self.add(line)
        for _ in range(empty):
            self.Empty()

    def Value(self, key=None, value=None, type_=None, **kwargs):
        """添加变量赋值语句。

        Args:
            key: 变量名。
            value: 变量值。
            type_: 类型注解（可选）。
            **kwargs: 额外的键值对，每个都会生成一行赋值。
        """
        if key is not None:
            if type_ is not None:
                self.add(f'{key}: {type_} = {self._repr(value)}')
            else:
                self.add(f'{key} = {self._repr(value)}')
        for key, value in kwargs.items():
            self.Value(key, value)

    def Comment(self, text):
        """添加注释块。

        Args:
            text: 注释文本，多行用换行分隔，每行自动添加 # 前缀。
        """
        for line in text.strip().split('\n'):
            line = line.strip()
            self.add(line, comment=True)

    def List(self, key=None):
        """创建列表上下文。

        Args:
            key: 列表变量名。若为 None 则生成匿名列表。

        Returns:
            TabWrapper 实例，配合 `with` 语句生成列表代码。
        """
        if key is not None:
            return TabWrapper(self, prefix=str(key) + ' = [', suffix=']')
        else:
            return TabWrapper(self, prefix='[', suffix=']', newline=False)

    def ListItem(self, value):
        """向列表中添加一个元素。

        Args:
            value: 列表元素值，可以是普通值或 TabWrapper 嵌套结构。
        """
        if isinstance(value, TabWrapper):
            value.set_nested(suffix=',')
            self.add(f'{self._repr(value)}')
            return value
        else:
            self.add(f'{self._repr(value)},')

    def Dict(self, key=None):
        """创建字典上下文。

        Args:
            key: 字典变量名。若为 None 则生成匿名字典。

        Returns:
            TabWrapper 实例，配合 `with` 语句生成字典代码。
        """
        if key is not None:
            return TabWrapper(self, prefix=str(key) + ' = {', suffix='}')
        else:
            return TabWrapper(self, prefix='{', suffix='}', newline=False)

    def DictItem(self, key=None, value=None):
        """向字典中添加一个键值对。

        Args:
            key: 字典键。
            value: 字典值，可以是普通值或 TabWrapper 嵌套结构。
        """
        if isinstance(value, TabWrapper):
            value.set_nested(suffix=',')
            if key is not None:
                self.add(f'{self._repr(key)}: {self._repr(value)}')
            return value
        else:
            if key is not None:
                self.add(f'{self._repr(key)}: {self._repr(value)},')

    def Object(self, object_class, key=None):
        """创建对象实例化上下文。

        Args:
            object_class: 类名字符串。
            key: 赋值变量名。若为 None 则生成匿名构造。

        Returns:
            TabWrapper 实例，配合 `with` 语句生成构造代码。
        """
        if key is not None:
            return TabWrapper(self, prefix=f'{key} = {object_class}(', suffix=')')
        else:
            return TabWrapper(self, prefix=f'{object_class}(', suffix=')', newline=False)

    def ObjectAttr(self, key=None, value=None):
        """为对象添加一个属性参数。

        Args:
            key: 属性名。若为 None 则为位置参数。
            value: 属性值，可以是普通值或 TabWrapper 嵌套结构。
        """
        if isinstance(value, TabWrapper):
            value.set_nested(suffix=',')
            if key is None:
                self.add(f'{self._repr(value)}')
            else:
                self.add(f'{key}={self._repr(value)}')
            return value
        else:
            if key is None:
                self.add(f'{self._repr(value)},')
            else:
                self.add(f'{key}={self._repr(value)},')

    def Class(self, name, inherit=None):
        """创建类定义上下文。

        Args:
            name: 类名。
            inherit: 父类名（可选）。

        Returns:
            TabWrapper 实例，配合 `with` 语句生成类定义代码。
        """
        if inherit is not None:
            return TabWrapper(self, prefix=f'class {name}({inherit}):')
        else:
            return TabWrapper(self, prefix=f'class {name}:')

    def Def(self, name, args=''):
        """创建函数定义上下文。

        Args:
            name: 函数名。
            args: 参数列表字符串（可选）。

        Returns:
            TabWrapper 实例，配合 `with` 语句生成函数定义代码。
        """
        return TabWrapper(self, prefix=f'def {name}({args}):')


generator = CodeGenerator()
Import = generator.Import
Value = generator.Value
Comment = generator.Comment
Dict = generator.Dict
DictItem = generator.DictItem
