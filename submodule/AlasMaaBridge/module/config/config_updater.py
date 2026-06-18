from cached_property import cached_property

from module.base.timer import timer
from module.config import config_updater
from module.config.deep import deep_get, deep_iter, deep_set
from module.config.utils import *


class ConfigGenerator(config_updater.ConfigGenerator):
    """MAA 配置生成器，负责生成 args.json、menu.json 和 i18n 翻译文件。"""

    @timer
    def generate(self):
        """执行完整的配置生成流程。

        生成 args.json、menu.json、config_generated.py 以及各语言的 i18n 文件。
        """
        write_file(filepath_args(), self.args)
        write_file(filepath_args('menu'), self.menu)
        self.generate_code()
        for lang in LANGUAGES:
            self.generate_i18n(lang)

    @timer
    def generate_i18n(self, lang):
        """加载旧翻译并生成新的翻译文件。

        合并 args.json 中的定义与旧翻译文件中已有的翻译，
        保留已有翻译，为新增条目使用默认的 key 路径作为占位符。

        Args:
            lang: 目标语言代码，如 'zh-CN'、'en-US' 等。
        """
        new = {}
        old = read_file(filepath_i18n(lang))

        def deep_load(keys, default=True, words=('name', 'help')):
            for word in words:
                k = keys + [str(word)]
                d = ".".join(k) if default else str(word)
                v = deep_get(old, keys=k, default=d)
                deep_set(new, keys=k, value=v)

        # Menu
        for path, data in deep_iter(self.task, depth=3):
            if 'tasks' not in path:
                continue
            task_group, _, task = path
            deep_load(['Menu', task_group])
            deep_load(['Task', task])
        # Arguments
        visited_group = set()
        for path, data in deep_iter(self.argument, depth=2):
            if path[0] not in visited_group:
                deep_load([path[0], '_info'])
                visited_group.add(path[0])
            deep_load(path)
            if 'option' in data:
                deep_load(path, words=data['option'], default=False)

        # GUI i18n
        for path, _ in deep_iter(self.gui, depth=2):
            group, key = path
            deep_load(keys=['Gui', group], words=(key,))

        # Copy stage names from MaaFight to MaaFightWeekly
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        for stage, trans in deep_get(new, keys='MaaFight.Stage', default={}).items():
            if '-' not in stage:
                continue
            for day in day_names:
                if deep_get(new, keys=['MaaFightWeekly', day, stage]):
                    deep_set(new, keys=['MaaFightWeekly', day, stage], value=trans)

        write_file(filepath_i18n(lang), new)


class ConfigUpdater(config_updater.ConfigUpdater):
    """MAA 配置更新器，负责配置文件的读取、更新和迁移。"""

    redirection = []

    @cached_property
    def args(self):
        return read_file(filepath_args(mod_name='maa'))

    def read_file(self, config_name, is_template=False):
        """读取配置文件并与默认值合并。

        Args:
            config_name: 配置文件名称。
            is_template: 是否为模板模式，模板模式下所有值使用默认值。

        Returns:
            dict: 合并后的配置字典。
        """
        old = read_file(filepath_config(config_name, 'maa'))
        return self.config_update(old, is_template=is_template)

    @staticmethod
    def write_file(config_name, data, mod_name='maa'):
        """写入配置文件。

        Args:
            config_name: 配置文件名称。
            data: 要写入的配置数据。
            mod_name: 模块名称，默认为 'maa'。
        """
        write_file(filepath_config(config_name, mod_name), data)

    def config_update(self, old, is_template=False):
        """将旧配置与新的参数定义合并。

        遍历 args.json 中的参数定义，从旧配置中读取值，
        对缺失或无效的值使用默认值填充。

        Args:
            old: 旧配置字典。
            is_template: 是否为模板模式，模板模式下强制使用默认值。

        Returns:
            dict: 更新后的配置字典。
        """
        new = {}

        for keys, data in deep_iter(self.args, depth=3):
            value = deep_get(old, keys=keys, default=data['value'])
            if is_template or value is None or value == '' or data['type'] == 'lock' or data.get('display') == 'hide':
                value = data['value']
            value = parse_value(value, data=data)
            deep_set(new, keys=keys, value=value)

        if not is_template:
            new = self.config_redirect(old, new)

        return new


if __name__ == '__main__':
    # 确保在模块根目录下运行
    import os

    os.chdir(os.path.join(os.path.dirname(__file__), "../../"))
    ConfigGenerator().generate()
    os.chdir('../../')
    ConfigUpdater().update_file('template', is_template=True)
