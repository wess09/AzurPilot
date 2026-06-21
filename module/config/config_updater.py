import re
import typing as t
from copy import deepcopy

from cached_property import cached_property

from deploy.utils import DEPLOY_TEMPLATE, poor_yaml_read, poor_yaml_write
from module.base.timer import timer
from module.config.deep import deep_default, deep_get, deep_iter, deep_set
from module.config.env import IS_ON_PHONE_CLOUD
from module.config.server import VALID_CHANNEL_PACKAGE, VALID_PACKAGE, VALID_SERVER_LIST, to_package, to_server
from module.config.utils import *
from module.config.redirect_utils.utils import *

CONFIG_IMPORT = '''
# 此文件是配置系统的更新器。
# 负责读取配置定义、生成 config_generated.py 以及处理配置的版本迁移、i18n 生成等核心管理任务。
import datetime

# 此文件由 module/config/config_updater.py 自动生成。
# 请勿手动修改。


class GeneratedConfig:
    """
    自动生成的配置类
    """
'''.strip().split('\n')
ARCHIVES_PREFIX = {
    'cn': '档案 ',
    'en': 'archives ',
    'jp': '檔案 ',
    'tw': '檔案 '
}
MAINS = ['Main', 'Main2', 'Main3']
EVENTS = ['Event', 'Event2', 'Event3', 'EventA', 'EventB', 'EventC', 'EventD', 'EventSp']
GEMS_FARMINGS = ['GemsFarming', 'ThreeOilLowCost']
RAIDS = ['Raid', 'RaidDaily', 'RaidScuttle']
WAR_ARCHIVES = ['WarArchives']
COALITIONS = ['Coalition', 'CoalitionSp']
MARITIME_ESCORTS = ['MaritimeEscort']
HOSPITAL = ['Hospital', 'HospitalEvent']


class Event:
    def __init__(self, text):
        self.date, self.directory, self.name, self.cn, self.en, self.jp, self.tw \
            = [x.strip() for x in text.strip('| \n').split('|')]

        self.directory = self.directory.replace(' ', '_')
        self.cn = self.cn.replace('、', '')
        self.en = self.en.replace(',', '').replace('\'', '').replace('\\', '')
        self.jp = self.jp.replace('、', '')
        self.tw = self.tw.replace('、', '')
        self.is_war_archives = self.directory.startswith('war_archives')
        self.is_raid = self.directory.startswith('raid_')
        self.is_coalition = self.directory.startswith('coalition_')
        for server in ARCHIVES_PREFIX.keys():
            if self.__getattribute__(server) == '-':
                self.__setattr__(server, None)
            else:
                if self.is_war_archives:
                    self.__setattr__(server, ARCHIVES_PREFIX[server] + self.__getattribute__(server))

    def __str__(self):
        return self.directory

    def __eq__(self, other):
        return str(self) == str(other)

    def __lt__(self, other):
        return str(self) < str(other)

    def __hash__(self):
        return hash(str(self))


class ConfigGenerator:
    @cached_property
    def argument(self):
        """加载 argument.yaml 并标准化其结构。

        数据格式::

            <group>:
                <argument>:
                    type: checkbox|select|textarea|input
                    value:
                    option (Optional): 选项列表，如果参数有可选项。
                    validate (Optional): datetime
        """
        data = {}
        raw = read_file(filepath_argument('argument'))
        filtered_raw = {k: v for k, v in raw.items() if not k.startswith('_')}
        for path, value in deep_iter(filtered_raw, depth=2):
            arg = {
                'type': 'input',
                'value': '',
                # option
            }
            if not isinstance(value, dict):
                value = {'value': value}
            arg['type'] = data_to_type(value, arg=path[1])
            if isinstance(value['value'], datetime):
                arg['type'] = 'datetime'
                arg['validate'] = 'datetime'
            # 手动定义的优先级最高
            arg.update(value)
            deep_set(data, keys=path, value=arg)

        # 定义 Storage 组
        arg = {
            'type': 'storage',
            'value': {},
            'valuetype': 'ignore',
            'display': 'disabled',
        }
        deep_set(data, keys=['Storage', 'Storage'], value=arg)
        return data

    @cached_property
    def task(self):
        """加载任务定义文件 task.yaml。

        数据格式::

            <task_group>:
                <task>:
                    <group>:
        """
        return read_file(filepath_argument('task'))

    @cached_property
    def default(self):
        """加载任务默认值定义文件 default.yaml。

        数据格式::

            <task>:
                <group>:
                    <argument>: value
        """
        return read_file(filepath_argument('default'))

    @cached_property
    def override(self):
        """加载不可修改的覆盖值定义文件 override.yaml。

        数据格式::

            <task>:
                <group>:
                    <argument>: value
        """
        return read_file(filepath_argument('override'))

    @cached_property
    def gui(self):
        """加载 GUI 界面翻译键定义文件 gui.yaml。

        数据格式::

            <i18n_group>:
                <i18n_key>: value, value is None
        """
        return read_file(filepath_argument('gui'))

    @cached_property
    def dashboard(self):
        """加载仪表盘资源定义文件 dashboard.yaml。

        数据格式::

            <dashboard>
              - <group>
        """
        return read_file(filepath_argument('dashboard'))


    @cached_property
    @timer
    def args(self):
        """
        将多个定义文件合并为标准化的 JSON。

            task.yaml ---+
        argument.yaml ---+-----> args.json
        override.yaml ---+
         default.yaml ---+

        """
        # 构建 args
        data = {}
        # 将仪表盘添加到 args
        dashboard_and_task = {**self.task, **self.dashboard}
        for path, groups in deep_iter(dashboard_and_task, min_depth=1, depth=3):
            if 'tasks' not in path and 'Dashboard' not in path:
                continue
            task = path[2] if 'tasks' in path else path[0]
            # 为所有任务添加 Storage 组
            groups.append('Storage')
            for group in groups:
                if group not in self.argument:
                    print(f'`{task}.{group}` is not related to any argument group')
                    continue
                deep_set(data, keys=[task, group], value=deepcopy(self.argument[group]))

        def check_override(path, value):
            # 检查参数是否存在（若不存在则跳过）
            old = deep_get(data, keys=path, default=None)
            if old is None:
                print(f'`{".".join(path)}` is not a existing argument')
                return False
            # 检查类型是否匹配（但允许 `Interval` 类型不同）
            old_value = old.get('value', None) if isinstance(old, dict) else old
            value = old.get('value', None) if isinstance(value, dict) else value
            if type(value) != type(old_value) \
                    and old_value is not None \
                    and path[2] not in ['SuccessInterval', 'FailureInterval']:
                print(
                    f'`{value}` ({type(value)}) and `{".".join(path)}` ({type(old_value)}) are in different types')
                return False
            # 检查选项值是否在允许列表中
            if isinstance(old, dict) and 'option' in old:
                if value not in old['option']:
                    print(f'`{value}` is not an option of argument `{".".join(path)}`')
                    return False
            return True

        # 设置默认值
        for p, v in deep_iter(self.default, depth=3):
            if not check_override(p, v):
                continue
            deep_set(data, keys=p + ['value'], value=v)
        # 覆盖不可修改的参数
        for p, v in deep_iter(self.override, depth=3):
            if not check_override(p, v):
                continue
            if isinstance(v, dict):
                typ = v.get('type')
                if typ == 'state':
                    pass
                elif typ == 'lock':
                    pass
                elif deep_get(v, keys='value') is not None:
                    deep_default(v, keys='display', value='hide')
                for arg_k, arg_v in v.items():
                    deep_set(data, keys=p + [arg_k], value=arg_v)
            else:
                deep_set(data, keys=p + ['value'], value=v)
                deep_set(data, keys=p + ['display'], value='hide')
        # 设置任务命令
        for path, groups in deep_iter(self.task, depth=3):
            if 'tasks' not in path:
                continue
            task = path[2]
            if deep_get(data, keys=f'{task}.Scheduler.Command'):
                deep_set(data, keys=f'{task}.Scheduler.Command.value', value=task)
                deep_set(data, keys=f'{task}.Scheduler.Command.display', value='hide')

        # 非主线任务隐藏 Campaign.Mode（Mode 仅适用于主线地图）
        for task in list(data.keys()):
            if task not in MAINS:
                if deep_get(data, keys=f'{task}.Campaign.Mode') is not None:
                    deep_set(data, keys=f'{task}.Campaign.Mode.display', value='hide')

        return data

    @timer
    def generate_code(self):
        """
        根据 args.json 生成 config_generated.py。

        args.json ---> config_generated.py

        """
        visited_group = set()
        visited_path = set()
        lines = CONFIG_IMPORT
        for path, data in deep_iter(self.argument, depth=2):
            group, arg = path
            if group not in visited_group:
                lines.append('')
                lines.append(f'    # 配置组 `{group}`')
                visited_group.add(group)

            option = ''
            if 'option' in data and data['option']:
                option = '  # ' + ', '.join([str(opt) for opt in data['option']])
            path = '.'.join(path)
            lines.append(f'    {path_to_arg(path)} = {repr(parse_value(data["value"], data=data))}{option}')
            visited_path.add(path)

        with open(filepath_code(), 'w', encoding='utf-8', newline='') as f:
            for text in lines:
                f.write(text + '\n')

    @timer
    def generate_i18n(self, lang):
        """
        加载旧翻译文件并生成新的翻译文件。

                     args.json ---+-----> i18n/<lang>.json
        (old) i18n/<lang>.json ---+

        """
        new = {}
        old = read_file(filepath_i18n(lang))

        def deep_load(keys, default=True, words=('name', 'help')):
            for word in words:
                k = keys + [str(word)]
                d = ".".join(k) if default else str(word)
                v = deep_get(old, keys=k, default=d)
                deep_set(new, keys=k, value=v)

        # 菜单翻译
        for path, data in deep_iter(self.task, depth=3):
            if 'tasks' not in path:
                continue
            task_group, _, task = path
            if task_group != 'Dashboard':
                deep_load(['Menu', task_group])
                deep_load(['Task', task])
        # 参数翻译
        visited_group = set()
        dashboard_args = deep_get(read_file(filepath_argument("task")), 'Dashboard.tasks.Dashboard', default=[])
        for path, data in deep_iter(self.argument, depth=2):
            if path[0] not in dashboard_args:
                if path[0] not in visited_group:
                    deep_load([path[0], '_info'])
                    visited_group.add(path[0])
                deep_load(path)
            if 'option' in data:
                deep_load(path, words=data['option'], default=False)
        # 活动名称翻译
        # 名称来源优先级：同语言服务器 > en > cn > jp > tw
        events = {}
        for event in self.event:
            if lang in LANG_TO_SERVER:
                name = event.__getattribute__(LANG_TO_SERVER[lang])
                if name:
                    deep_default(events, keys=event.directory, value=name)
        for server in ['en', 'cn', 'jp', 'tw']:
            for event in self.event:
                name = event.__getattribute__(server)
                if name:
                    deep_default(events, keys=event.directory, value=name)
        for event in sorted(self.event):
            name = events.get(event.directory, event.directory)
            deep_set(new, keys=f'Campaign.Event.{event.directory}', value=name)
        # 包名翻译
        for package, server in VALID_PACKAGE.items():
            path = ['Emulator', 'PackageName', package]
            if deep_get(new, keys=path) == package:
                deep_set(new, keys=path, value=server.upper())

        for package, server_and_channel in VALID_CHANNEL_PACKAGE.items():
            server, channel = server_and_channel
            name = deep_get(new, keys=['Emulator', 'PackageName', to_package(server)])
            if lang == SERVER_TO_LANG[server]:
                value = f'{name} {channel}渠道服 {package}'
            else:
                value = f'{name} {package}'
            deep_set(new, keys=['Emulator', 'PackageName', package], value=value)
        # 游戏服务器名称
        for server, _list in VALID_SERVER_LIST.items():
            for index in range(len(_list)):
                path = ['Emulator', 'ServerName', f'{server}-{index}']
                prefix = server.split('_')[0].upper()
                prefix = '国服' if prefix == 'CN' else prefix
                deep_set(new, keys=path, value=f'[{prefix}] {_list[index]}')
        # GUI 界面翻译
        for path, _ in deep_iter(self.gui, depth=2):
            group, key = path
            deep_load(keys=['Gui', group], words=(key,))
        # zh-TW
        dic_repl = {
            '設置': '設定',
            '支持': '支援',
            '啓': '啟',
            '异': '異',
            '服務器': '伺服器',
            '文件': '檔案',
        }
        if lang == 'zh-TW':
            for path, value in deep_iter(new, depth=3):
                for before, after in dic_repl.items():
                    value = value.replace(before, after)
                deep_set(new, keys=path, value=value)

        write_file(filepath_i18n(lang), new)

    @cached_property
    def menu(self):
        """
        根据 task.yaml 生成 menu.json。

        task.yaml --> menu.json

        """
        data = {}
        for task_group in self.task.keys():
            if task_group != 'Dashboard':
                value = deep_get(self.task, keys=[task_group, 'menu'])
                if value not in ['collapse', 'list']:
                    value = 'collapse'
                deep_set(data, keys=[task_group, 'menu'], value=value)
                value = deep_get(self.task, keys=[task_group, 'page'])
                if value not in ['setting', 'tool']:
                    value = 'setting'
                deep_set(data, keys=[task_group, 'page'], value=value)
                tasks = deep_get(self.task, keys=[task_group, 'tasks'], default={})
                tasks = list(tasks.keys())
                deep_set(data, keys=[task_group, 'tasks'], value=tasks)

        return data

    @cached_property
    @timer
    def event(self):
        """
        Returns:
            list[Event]: 活动列表，按时间从新到旧排列
        """

        def calc_width(text):
            return len(text) + len(re.findall(
                r'[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff、！（）]', text))

        lines = []
        data_lines = []
        data_widths = []
        column_width = [4] * 7  # `:---`
        events = []
        with open('./campaign/Readme.md', encoding='utf-8') as f:
            for text in f.readlines():
                if not re.search(r'^\|.+\|$', text):
                    # not a table line
                    lines.append(text)
                elif re.search(r'^.*\-{3,}.*$', text):
                    # is a delimiter line
                    continue
                else:
                    line_entries = [x.strip() for x in text.strip('| \n').split('|')]
                    data_lines.append(line_entries)
                    data_width = [calc_width(string) for string in line_entries]
                    data_widths.append(data_width)
                    column_width = [max(l1, l2) for l1, l2 in zip(column_width, data_width)]
                    if re.search(r'\d{8}', text):
                        event = Event(text)
                        events.append(event)
        for i, (line, old_width) in enumerate(zip(data_lines, data_widths)):
            lines.append('| ' + ' | '.join([cell + ' ' * (width - length) for cell, width, length in zip(line, column_width, old_width)]) + ' |\n')
            if i == 0:
                lines.append('| ' + ' | '.join([':' + '-' * (width - 1) for width in column_width]) + ' |\n')
        with open('./campaign/Readme.md', 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return events[::-1]

    def insert_event(self):
        """
        将活动信息插入到 `self.args` 中。

        ./campaign/Readme.md -----+
                                  v
                   args.json -----+-----> args.json
        """
        for server in ARCHIVES_PREFIX.keys():
            for event in self.event:
                name = event.__getattribute__(server)

                def insert(key):
                    opts = deep_get(self.args, keys=f'{key}.Campaign.Event.option_{server}', default=[])
                    if event not in opts:
                        opts.append(event)
                    deep_set(self.args, keys=f'{key}.Campaign.Event.option_{server}', value=opts)

                if name:
                    if event.is_raid:
                        if not hasattr(self, f'_{server}_latest_raid_date'):
                            setattr(self, f'_{server}_latest_raid_date', int(event.date))
                        if int(event.date) == getattr(self, f'_{server}_latest_raid_date'):
                            for task in RAIDS:
                                insert(task)
                    elif event.is_war_archives:
                        for task in WAR_ARCHIVES:
                            insert(task)
                    elif event.is_coalition:
                        if not hasattr(self, f'_{server}_latest_coalition_date'):
                            setattr(self, f'_{server}_latest_coalition_date', int(event.date))
                        if int(event.date) == getattr(self, f'_{server}_latest_coalition_date'):
                            for task in COALITIONS:
                                insert(task)
                    else:
                        if not hasattr(self, f'_{server}_latest_event_date'):
                            setattr(self, f'_{server}_latest_event_date', int(event.date))
                        if int(event.date) == getattr(self, f'_{server}_latest_event_date'):
                            for task in EVENTS + GEMS_FARMINGS:
                                insert(task)

        for task in EVENTS + GEMS_FARMINGS + WAR_ARCHIVES + RAIDS + COALITIONS:
            latest = {}
            for server in ARCHIVES_PREFIX.keys():
                latest[server] = deep_get(self.args, keys=f'{task}.Campaign.Event.option_{server}', default=[])
            options = set().union(*latest.values())
            options = sorted([option for option in options if option != 'campaign_main'])
            if task not in WAR_ARCHIVES:
                deep_set(self.args, keys=f'{task}.Campaign.Event.option_bold', value=options)
            deep_set(self.args, keys=f'{task}.Campaign.Event.option', value=options)
            deep_set(self.args, keys=f'{task}.Campaign.Event.option_bold', value=options)

    @staticmethod
    def generate_deploy_template():
        template = poor_yaml_read(DEPLOY_TEMPLATE)
        cn = {
            'Repository': 'git://git.pull/AzurPilot',
            'PypiMirror': 'https://mirrors.aliyun.com/pypi/simple',
            'Language': 'zh-CN',
        }
        aidlux = {
            'GitExecutable': './.venv/bin/git',
            'PythonExecutable': './.venv/bin/python',
            'AdbExecutable': './.venv/bin/adb',
        }

        docker = {
            'GitExecutable': './.venv/bin/git',
            'PythonExecutable': './.venv/bin/python',
            'AdbExecutable': './.venv/bin/adb',
        }

        linux = {
            'GitExecutable': './.venv/bin/git',
            'PythonExecutable': './.venv/bin/python',
            'AdbExecutable': './.venv/bin/adb',
            'SSHExecutable': '/usr/bin/ssh',
            'ReplaceAdb': 'false'
        }

        def update(suffix, *args):
            file = f'./config/deploy.{suffix}.yaml'
            new = deepcopy(template)
            for dic in args:
                new.update(dic)
            poor_yaml_write(data=new, file=file)

        update('template')
        update('template-cn', cn)
        update('template-AidLux', aidlux)
        update('template-AidLux-cn', aidlux, cn)
        update('template-docker', docker)
        update('template-docker-cn', docker, cn)
        update('template-linux', linux)
        update('template-linux-cn', linux, cn)

    def insert_package(self):
        option = deep_get(self.argument, keys='Emulator.PackageName.option')
        option += list(VALID_PACKAGE.keys())
        option += list(VALID_CHANNEL_PACKAGE.keys())
        deep_set(self.argument, keys='Emulator.PackageName.option', value=option)
        deep_set(self.args, keys='Alas.Emulator.PackageName.option', value=option)

    def insert_server(self):
        option = deep_get(self.argument, keys='Emulator.ServerName.option')
        server_list = []
        for server, _list in VALID_SERVER_LIST.items():
            for index in range(len(_list)):
                server_list.append(f'{server}-{index}')
        option += server_list
        deep_set(self.argument, keys='Emulator.ServerName.option', value=option)
        deep_set(self.args, keys='Alas.Emulator.ServerName.option', value=option)

    @timer
    def generate(self):
        _ = self.args
        _ = self.menu
        _ = self.event
        self.insert_event()
        self.insert_package()
        self.insert_server()
        write_file(filepath_args(), self.args)
        write_file(filepath_args('menu'), self.menu)
        self.generate_code()
        for lang in LANGUAGES:
            self.generate_i18n(lang)
        self.generate_deploy_template()


class ConfigUpdater:
    # 格式：source, target, (可选) convert_func
    redirection = [
        # ('OpsiDaily.OpsiDaily.BuySupply', 'OpsiShop.Scheduler.Enable'),
        # ('OpsiDaily.Scheduler.Enable', 'OpsiDaily.OpsiDaily.DoMission'),
        # ('OpsiShop.Scheduler.Enable', 'OpsiShop.OpsiShop.BuySupply'),
        # ('ShopOnce.GuildShop.Filter', 'ShopOnce.GuildShop.Filter', bp_redirect),
        # ('ShopOnce.MedalShop2.Filter', 'ShopOnce.MedalShop2.Filter', bp_redirect),
        # (('Alas.DropRecord.SaveResearch', 'Alas.DropRecord.UploadResearch'),
        #  'Alas.DropRecord.ResearchRecord', upload_redirect),
        # (('Alas.DropRecord.SaveCommission', 'Alas.DropRecord.UploadCommission'),
        #  'Alas.DropRecord.CommissionRecord', upload_redirect),
        # (('Alas.DropRecord.SaveOpsi', 'Alas.DropRecord.UploadOpsi'),
        #  'Alas.DropRecord.OpsiRecord', upload_redirect),
        # (('Alas.DropRecord.SaveMeowfficerTalent', 'Alas.DropRecord.UploadMeowfficerTalent'),
        #  'Alas.DropRecord.MeowfficerTalent', upload_redirect),
        # ('Alas.DropRecord.SaveCombat', 'Alas.DropRecord.CombatRecord', upload_redirect),
        # ('Alas.DropRecord.SaveMeowfficer', 'Alas.DropRecord.MeowfficerBuy', upload_redirect),
        # ('Alas.Emulator.PackageName', 'Alas.DropRecord.API', api_redirect),
        # ('Alas.RestartEmulator.Enable', 'Alas.RestartEmulator.ErrorRestart'),
        # ('OpsiGeneral.OpsiGeneral.BuyActionPoint', 'OpsiGeneral.OpsiGeneral.BuyActionPointLimit', action_point_redirect),
        # ('BattlePass.BattlePass.BattlePassReward', 'Freebies.BattlePass.Collect'),
        # ('DataKey.Scheduler.Enable', 'Freebies.DataKey.Collect'),
        # ('DataKey.DataKey.ForceGet', 'Freebies.DataKey.ForceCollect'),
        # ('SupplyPack.SupplyPack.WeeklyFreeSupplyPack', 'Freebies.SupplyPack.Collect'),
        # ('Commission.Commission.CommissionFilter', 'Commission.Commission.CustomFilter'),
        # 2023.02.17
        # ('OpsiAshBeacon.OpsiDossierBeacon.Enable', 'OpsiAshBeacon.OpsiAshBeacon.AttackMode', dossier_redirect),
        # ('General.Retirement.EnhanceFavourite', 'General.Enhance.ShipToEnhance', enhance_favourite_redirect),
        # ('General.Retirement.EnhanceFilter', 'General.Enhance.Filter'),
        # ('General.Retirement.EnhanceCheckPerCategory', 'General.Enhance.CheckPerCategory', enhance_check_redirect),
        # ('General.Retirement.OldRetireN', 'General.OldRetire.N'),
        # ('General.Retirement.OldRetireR', 'General.OldRetire.R'),
        # ('General.Retirement.OldRetireSR', 'General.OldRetire.SR'),
        # ('General.Retirement.OldRetireSSR', 'General.OldRetire.SSR'),
        # (('GemsFarming.GemsFarming.FlagshipChange', 'GemsFarming.GemsFarming.FlagshipEquipChange'),
        #  'GemsFarming.GemsFarming.ChangeFlagship',
        #  change_ship_redirect),
        # (('GemsFarming.GemsFarming.VanguardChange', 'GemsFarming.GemsFarming.VanguardEquipChange'),
        #  'GemsFarming.GemsFarming.ChangeVanguard',
        #  change_ship_redirect),
        # ('Alas.DropRecord.API', 'Alas.DropRecord.API', api_redirect2)
        # 2025.04.17
        # ('Coalition.Coalition.Mode', 'Coalition.Coalition.Mode', coalition_to_frostfall),
        # 2025.06.26
        # ('Coalition.Coalition.Mode', 'Coalition.Coalition.Mode', coalition_to_little_academy),
    ]

    # redirection += [
    #     (
    #         (f'{task}.Emotion.CalculateEmotion', f'{task}.Emotion.IgnoreLowEmotionWarn'),
    #         f'{task}.Emotion.Mode',
    #         emotion_mode_redirect
    #     ) for task in [
    #         'Main', 'Main2', 'Main3', 'GemsFarming',
    #         'Event', 'Event2', 'EventA', 'EventB', 'EventC', 'EventD', 'EventSp', 'Raid', 'RaidDaily',
    #         'Sos', 'WarArchives',
    #     ]
    # ]

    @cached_property
    def args(self):
        return read_file(filepath_args())

    def config_update(self, old, is_template=False):
        """
        Args:
            old: 旧配置字典。
            is_template: 是否为模板配置。

        Returns:
            更新后的配置字典。
        """
        new = {}

        for keys, data in deep_iter(self.args, depth=3):
            # 跳过非字典项（叶子值，如字符串、数字等）
            if not isinstance(data, dict):
                continue
            value = deep_get(old, keys=keys, default=data['value'])
            typ = data['type']
            display = data.get('display')
            value_empty = value == '' and not data.get('preserve_empty')
            if is_template or value is None or value_empty \
                    or typ in ['lock', 'state'] or (display == 'hide' and typ != 'stored'):
                value = data['value']
            value = parse_value(value, data=data)
            deep_set(new, keys=keys, value=value)

        # 处理 AzurStatsID
        if is_template:
            deep_set(new, 'Alas.DropRecord.AzurStatsID', None)
        else:
            deep_default(new, 'Alas.DropRecord.AzurStatsID', random_id())
        # 更新到最新活动
        server = to_server(deep_get(new, 'Alas.Emulator.PackageName', 'cn'))
        if not is_template:
            for task in EVENTS + RAIDS + COALITIONS:
                opts = deep_get(self.args, keys=f'{task}.Campaign.Event.option_{server}', default=[])
                if opts and not deep_get(new, keys=f'{task}.Campaign.Event', default='campaign_main') in opts:
                    deep_set(new,
                             keys=f'{task}.Campaign.Event',
                             value=opts[0])

            for task in ['GemsFarming']:
                opts = deep_get(self.args, keys=f'{task}.Campaign.Event.option_{server}', default=[])
                if opts and deep_get(new, keys=f'{task}.Campaign.Event', default='campaign_main') not in opts:
                    deep_set(new,
                             keys=f'{task}.Campaign.Event',
                             value=opts[0])
        # 作战档案不允许选择 campaign_main
        for task in WAR_ARCHIVES:
            opts = deep_get(self.args, keys=f'{task}.Campaign.Event.option_{server}', default=[])
            if opts and deep_get(new, keys=f'{task}.Campaign.Event', default='campaign_main') == 'campaign_main':
                deep_set(new,
                         keys=f'{task}.Campaign.Event',
                         value=opts[0])

        # 活动不允许默认关卡 12-4
        def default_stage(t, stage):
            if deep_get(new, keys=f'{t}.Campaign.Name', default='12-4') in ['7-2', '12-4']:
                deep_set(new, keys=f'{t}.Campaign.Name', value=stage)

        for task in EVENTS + WAR_ARCHIVES:
            default_stage(task, 'D3')
        for task in COALITIONS:
            default_stage(task, 'TC-3')

        if not is_template:
            new = self.config_redirect(old, new)
            old_priority = deep_get(old, 'General.YukikazeTaskManager.TaskPriorityAdjustment')
            new_priority = deep_get(new, 'General.YukikazeTaskManager.TaskPriorityAdjustment')
            template_priority = deep_get(
                self.args, 'General.YukikazeTaskManager.TaskPriorityAdjustment.value'
            )
            if (
                    isinstance(old_priority, str)
                    and 'OpsiScheduling' not in old_priority
                    and isinstance(new_priority, str)
                    and new_priority == old_priority
                    and old_priority.replace(
                        '> OpsiCrossMonth\n> Commission > Tactical > Research',
                        '> OpsiCrossMonth\n> OpsiScheduling\n> Commission > Tactical > Research',
                    ) == template_priority
            ):
                deep_set(new, 'General.YukikazeTaskManager.TaskPriorityAdjustment', template_priority)
        new = self._override(new)

        return new

    def config_redirect(self, old, new):
        """
        将旧配置转换为新格式。

        Args:
            old: 旧配置字典。
            new: 新配置字典。

        Returns:
            转换后的配置字典。
        """
        for row in self.redirection:
            if len(row) == 2:
                source, target = row
                update_func = None
            elif len(row) == 3:
                source, target, update_func = row
            else:
                continue

            if isinstance(source, tuple):
                value = []
                error = False
                for attribute in source:
                    tmp = deep_get(old, keys=attribute)
                    if tmp is None:
                        error = True
                        continue
                    value.append(tmp)
                if error:
                    continue
            else:
                value = deep_get(old, keys=source)
                if value is None:
                    continue

            if update_func is not None:
                value = update_func(value)

            if isinstance(target, tuple):
                for k, v in zip(target, value):
                    # 允许更新相同的键
                    if (deep_get(old, keys=k) is None) or (source == target):
                        deep_set(new, keys=k, value=v)
            elif (deep_get(old, keys=target) is None) or (source == target):
                deep_set(new, keys=target, value=value)

        return new

    def _override(self, data):
        def remove_drop_save(key):
            value = deep_get(data, keys=key, default='do_not')
            if value == 'save_and_upload':
                value = 'upload'
                deep_set(data, keys=key, value=value)
            elif value == 'save':
                value = 'do_not'
                deep_set(data, keys=key, value=value)

        if IS_ON_PHONE_CLOUD:
            deep_set(data, 'Alas.Emulator.Serial', '127.0.0.1:5555')
            deep_set(data, 'Alas.Emulator.ScreenshotMethod', 'DroidCast_raw')
            deep_set(data, 'Alas.Emulator.ControlMethod', 'MaaTouch')
            for arg in deep_get(self.args, keys='Alas.DropRecord', default={}).keys():
                remove_drop_save(arg)

        return data

    def save_callback(self, key: str, value: t.Any) -> t.Iterable[t.Tuple[str, t.Any]]:
        """
        配置保存时的回调函数，用于联动更新相关配置项。

        Args:
            key: 配置 JSON 中的键路径，例如 "Main.Emotion.Fleet1Value"。
            value: 用户设置的值，例如 "98"。

        Yields:
            str: 需要设置的配置 JSON 键路径，例如 "Main.Emotion.Fleet1Record"。
            any: 需要设置的值，例如 "2020-01-01 00:00:00"。
        """
        if "Emotion" in key and "Value" in key:
            key = key.split(".")
            key[-1] = key[-1].replace("Value", "Record")
            yield ".".join(key), datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 智能调度与侵蚀1配置双向同步
        # 当修改智能调度的黄币保留时，同步到侵蚀1
        if key == 'OpsiScheduling.OpsiScheduling.OperationCoinsPreserve':
            yield 'OpsiHazard1Leveling.OpsiHazard1Leveling.OperationCoinsPreserve', value
        # 当修改侵蚀1的黄币保留时，同步到智能调度
        elif key == 'OpsiHazard1Leveling.OpsiHazard1Leveling.OperationCoinsPreserve':
            yield 'OpsiScheduling.OpsiScheduling.OperationCoinsPreserve', value
        
        # 智能调度与侵蚀1虚拟资产保留双向同步
        if key == 'OpsiScheduling.OpsiScheduling.VirtualAssetPreserve':
            yield 'OpsiHazard1Leveling.OpsiHazard1Leveling.PreserveVirtualAsset', value
        elif key == 'OpsiHazard1Leveling.OpsiHazard1Leveling.PreserveVirtualAsset':
            yield 'OpsiScheduling.OpsiScheduling.VirtualAssetPreserve', value
        
        # 智能调度与短猫行动力保留双向同步
        # 只有当值 > 0 时才同步（值为0表示不覆盖，使用各任务自己的配置）
        if key == 'OpsiScheduling.OpsiScheduling.ActionPointPreserve':
            if value and int(value) > 0:
                yield 'OpsiMeowfficerFarming.OpsiMeowfficerFarming.ActionPointPreserve', value
        elif key == 'OpsiMeowfficerFarming.OpsiMeowfficerFarming.ActionPointPreserve':
            if value and int(value) > 0:
                yield 'OpsiScheduling.OpsiScheduling.ActionPointPreserve', value

        # 注意：动态下拉菜单更新仅在 pywebio > 1.8.0 时可用
        # elif key == 'Alas.Emulator.ScreenshotMethod' and value == 'nemu_ipc':
        #     yield 'Alas.Emulator.ControlMethod', 'nemu_ipc'
        # elif key == 'Alas.Emulator.ControlMethod' and value == 'nemu_ipc':
        #     yield 'Alas.Emulator.ScreenshotMethod', 'nemu_ipc'

    def read_file(self, config_name, is_template=False):
        """
        读取并更新配置文件。

        Args:
            config_name: 配置文件名，对应 ./config/{file}.json。
            is_template: 是否为模板配置。

        Returns:
            更新后的配置字典。
        """
        old = read_file(filepath_config(config_name))
        new = self.config_update(old, is_template=is_template)
        # 更新后的配置未写回文件，出于性能考虑已注释掉写入操作
        # self.write_file(config_name, new)
        return new

    @staticmethod
    def write_file(config_name, data, mod_name='alas'):
        """
        写入配置文件。

        Args:
            config_name: 配置文件名，对应 ./config/{file}.json。
            data: 要写入的配置数据。
            mod_name: 模块名称，默认为 'alas'。
        """
        write_file(filepath_config(config_name, mod_name), data)

    @timer
    def update_file(self, config_name, is_template=False):
        """
        读取、更新并写入配置文件。

        Args:
            config_name: 配置文件名，对应 ./config/{file}.json。
            is_template: 是否为模板配置。

        Returns:
            更新后的配置字典。
        """
        data = self.read_file(config_name, is_template=is_template)
        self.write_file(config_name, data)
        return data


if __name__ == '__main__':
    """
    执行完整的配置生成流程。

                 task.yaml -+----------------> menu.json
             argument.yaml -+-> args.json ---> config_generated.py
             override.yaml -+       |
                  gui.yaml --------\\|
                                   ||
    (old) i18n/<lang>.json --------\\========> i18n/<lang>.json
    (old)    template.json ---------\\========> template.json
    """
    # 确保在 Alas 根目录下运行
    import os

    os.chdir(os.path.join(os.path.dirname(__file__), '../../'))

    ConfigGenerator().generate()
    ConfigUpdater().update_file('template', is_template=True)
