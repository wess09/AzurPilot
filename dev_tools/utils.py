"""游戏数据辅助工具模块，包含解密 Lua 脚本的高级加载器。"""
import os
import re

from tqdm import tqdm

from dev_tools.slpp import slpp


class LuaLoader:
    """解密游戏 Lua 脚本加载器。

    支持自动解析多服目录别名及多种 Lua 模块与表格组织格式。

    Attributes:
        folder (str): Lua 数据存储根目录路径。
        server (str): 当前选定的服务器代号。
    """

    server_alias = [
        ['zh-CN', 'zh-cn', 'cn', 'CN'],
        ['en-US', 'en-us', 'en', 'EN'],
        ['ja-JP', 'ja-jp', 'jp', 'JP'],
        ['zh-TW', 'zh-tw', 'tw', 'TW'],
        ['ko-KR', 'ko-kr', 'kr', 'KR'],
    ]

    def __init__(self, folder, server='zh-CN'):
        """初始化 Lua 加载器。

        Args:
            folder (str): Lua 脚本仓库根目录。
            server (str): 目标服务器代号，默认为 'zh-CN'。
        """
        self.folder = folder
        self._server = ''
        self.server = server

    @property
    def server(self):
        return self._server

    @server.setter
    def server(self, value):
        self._server = self.get_alias(value)

    def get_alias(self, server):
        """解析并返回本地存在的对应服务器别名目录名称。

        Args:
            server (str): 输入的服务器代号。

        Returns:
            str: 匹配到的目录名称。
        """
        try:
            with os.scandir(self.folder) as entries:
                directories = {
                    entry.name.lower(): entry.name
                    for entry in entries if entry.is_dir()
                }
        except OSError:
            return server

        for alias_list in self.server_alias:
            if server in alias_list:
                for alias in alias_list:
                    name = directories.get(alias.lower())
                    if name is not None:
                        return name

        return server

    def filepath(self, path):
        """获取目标相对路径在当前服务器目录下的完整文件路径。

        Args:
            path (str): 目标相对路径。

        Returns:
            str: 拼接后的完整文件路径。
        """
        return os.path.join(self.folder, self.server, path)

    def _find_matching_brace(self, text, start_index):
        """查找指定位置左花括号对应的闭合右花括号下标。

        Args:
            text (str): 包含 Lua 代码的文本。
            start_index (int): 起始左花括号所在的位置下标。

        Returns:
            int: 匹配的闭合右花括号下标，未找到返回 -1。
        """
        depth = 0
        in_string = None
        escape = False
        for i in range(start_index, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == in_string:
                    in_string = None
            else:
                if ch in ('"', "'"):
                    in_string = ch
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return i
        return -1

    def _infer_base_name(self, file, keyword):
        """推断 pg.base 命名空间下的子表名称。

        Args:
            file (str): 文件路径。
            keyword (str | None): 显式指定的关键字。

        Returns:
            str: 推断得到的表基名。
        """
        if keyword:
            keyword = keyword.strip()
            if keyword.startswith('pg.base.'):
                return keyword[len('pg.base.'):]
            if keyword.startswith('pg.'):
                return keyword[len('pg.'):]
            return keyword
        return os.path.splitext(os.path.basename(file))[0]

    def _load_pg_base_entries(self, text, base_name):
        """提取并解析 pg.base 形式定义的各下标记录项。

        Args:
            text (str): 文件全文文本。
            base_name (str): pg.base 下的表名。

        Returns:
            dict[int, Any]: 索引映射到对应解析内容的字典。
        """
        pattern = rf"pg\.base\.{re.escape(base_name)}\[(\d+)\]\s*=\s*\{{"
        result = {}
        for m in re.finditer(pattern, text):
            start = m.end() - 1
            end = self._find_matching_brace(text, start)
            if end == -1:
                continue
            table_text = text[start:end + 1]
            result[int(m.group(1))] = slpp.decode(table_text)
        return result

    def _load_file(self, file, keyword=None):
        """读取并解析单个 Lua 文件的内容为字典。

        Args:
            file (str): 相对文件路径。
            keyword (str | None): 可选的关键字，用于指定特定表名。

        Returns:
            dict: 解析得到的键值数据字典。
        """
        with open(self.filepath(file), 'r', encoding='utf-8') as f:
            text = f.read()

        if 'pg.base.' in text:
            base_name = self._infer_base_name(file, keyword)
            if not base_name:
                m = re.search(r"pg\.base\.([A-Za-z0-9_]+)\[", text)
                base_name = m.group(1) if m else None
            if base_name:
                result = self._load_pg_base_entries(text, base_name)
                if result:
                    return result

        result = {}
        matched = re.findall(r'function \(\)(.*?)end[()]', text, re.S)
        if matched:
            # 大多数文件采用闭包函数格式
            """
            pg = pg or {}
            slot0 = pg
            slot0.chapter_template = {}

            (function ()
                ...
            end)()
            """
            for func in matched:
                add = slpp.decode('{' + func + '}')
                result.update(add)
        elif text.startswith('pg'):
            # 旧格式
            """
            pg = pg or {}
            pg.item_data_statistics = {
                ...
            }
            """
            # 或
            """
            pg = pg or {}

            rawset(pg, "item_data_statistics", rawget(pg, "item_data_statistics") or {
                ...
            }
            """
            text = '{' + text.split('{', 2)[2]
            result = slpp.decode(text)
        else:
            # 裸数据格式
            """
            _G.pg.expedition_data_template[...] = {
                ...
            }
            _G.pg.expedition_data_template[...] = {
                ...
            }
            ...
            """
            text = '{' + text + '}'
            result = slpp.decode(text)

        return result

    def load(self, path, keyword=None):
        """加载指定路径的 Lua 文件或目录并转换为 Python 字典。

        Args:
            path (str): 相对于 {folder}/{server} 的路径，可为文件或目录。
            keyword (str | None): 可选关键字参数。

        Returns:
            dict: 合并解析后的字典数据。
        """
        print(f'Loading {path}')
        if os.path.isdir(self.filepath(path)):
            result = {}
            for file in tqdm(os.listdir(self.filepath(path))):
                result.update(self._load_file(f'./{path}/{file}', keyword=keyword))
        else:
            result = self._load_file(path, keyword=keyword)

        print(f'{len(result.keys())} items loaded')
        return result


if __name__ == '__main__':
    # 使用示例
    lua = LuaLoader(r'xxx/AzurLaneData', server='en-US')
    res = lua.load('./sharecfg/item_data_statistics.lua')
