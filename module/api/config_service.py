"""参数定义驱动的配置服务，在跨进程事务内校验并合并字段修改。"""
import copy
import hashlib
import json
import math
import re
import threading
from datetime import datetime
from pathlib import Path

import yaml

from deploy.atomic import atomic_write
from module.api.protocol import ApiError
from module.config.transaction import config_transaction

ROOT = Path(__file__).resolve().parents[2]
# 实例名会成为配置文件名，字符集必须避开路径分隔符与系统保留字符。
# 汉字（扩展 A、基本区、兼容区）允许出现在名称任意位置，其余字符仍限定为字母、数字、
# 短横线和下划线，保证名称既能在文件系统中安全落地，也能原样放进前端路由。
HAN = r'\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff'
NAME = re.compile(r'[A-Za-z' + HAN + r'][A-Za-z0-9_' + HAN + r'\-]{0,63}\Z')
RESERVED = {'template', 'deploy', 'backup', 'con', 'prn', 'aux', 'nul',
            *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}


class ConfigService:
    """只访问白名单配置，读操作不会触发运行器的配置写回。"""

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.directory = root / 'config'
        self.lock = threading.RLock()
        argument = root / 'module/config/argument'
        self.args = self.read_json(argument / 'args.json')
        self.menu = self.read_json(argument / 'menu.json')
        self.translations = self.read_json(root / 'module/config/i18n/zh-CN.json')
        self.template = self.read_json(self.directory / 'template.json')

    @staticmethod
    def read_json(path):
        return json.loads(path.read_text(encoding='utf-8'))

    def translate(self, key):
        value = self.translations
        for part in key.split('.'):
            value = value.get(part, {}) if isinstance(value, dict) else {}
        return value if isinstance(value, str) and value != key else key.split('.')[-1]

    def path(self, name, exists=True):
        if not isinstance(name, str) or not NAME.fullmatch(name) or name.lower() in RESERVED:
            raise ApiError('INVALID_PARAMS', '实例名须以字母或汉字开头，仅包含字母、数字、汉字、短横线或下划线')
        path = self.directory / f'{name}.json'
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise ApiError('INVALID_PARAMS', '配置路径无效')
        if exists and not path.is_file():
            raise ApiError('NOT_FOUND', '实例不存在')
        return path

    def names(self):
        return sorted(p.stem for p in self.directory.glob('*.json')
                      if NAME.fullmatch(p.stem) and p.stem.lower() not in RESERVED
                      and not p.is_symlink() and self.is_instance(p))

    def is_instance(self, path):
        try:
            return isinstance(self.read_json(path).get('Alas'), dict)
        except (OSError, ValueError, AttributeError):
            return False

    def read(self, name):
        path = self.path(name)
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get('Alas'), dict):
                raise ValueError()
        except (OSError, ValueError) as exc:
            raise ApiError('CONFIG_INVALID', '配置文件损坏，请从备份恢复') from exc
        # 旧配置缺失的参数在读时补齐，完整迁移仍由核心运行器负责。
        merged = copy.deepcopy(self.template)
        for task, groups in data.items():
            if isinstance(groups, dict):
                for group, fields in groups.items():
                    if isinstance(fields, dict):
                        merged.setdefault(task, {}).setdefault(group, {}).update(fields)
        return merged, hashlib.sha256(raw).hexdigest()

    def schema(self, language='zh-CN'):
        """按会话读取翻译，不修改运行器或其他浏览器的全局语言。"""
        if language not in {'zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW'}:
            raise ApiError('INVALID_PARAMS', '不支持的界面语言')
        translations = self.translations if language == 'zh-CN' else self.read_json(
            self.root / 'module/config/i18n' / f'{language}.json')
        return {'menu': self.menu, 'args': self.args, 'translations': translations}

    def get(self, name):
        data, revision = self.read(name)
        return {'instance': name, 'revision': revision, 'values': data}

    def create(self, name, source=None):
        with self.lock:
            path = self.path(name, exists=False)
            data = self.read(source)[0] if source else copy.deepcopy(self.template)
            # 排他创建避免不同会话覆盖已有配置。
            try:
                with path.open('x', encoding='utf-8') as file:
                    json.dump(data, file, ensure_ascii=False, indent=2)
            except FileExistsError as exc:
                raise ApiError('ALREADY_EXISTS', '同名实例已存在') from exc
            return self.get(name)

    @staticmethod
    def validate_shop_strategy(script):
        """校验受限 Lua 风格商店策略，不执行脚本。"""
        from module.shop_strategy import validate_strategy

        result = validate_strategy(script)
        if not result['valid']:
            diagnostics = result.get('diagnostics', [])
            first = diagnostics[0]['message'] if diagnostics else '脚本不符合受限策略语法'
            raise ApiError('INVALID_PARAMS', f'高级商店策略脚本无效：{first}', diagnostics)
        return result

    def validate_shop_advanced_groups(self, data, tasks):
        """校验最终配置快照中的高级模式与脚本组合。

        ``Mode`` 与 ``Script`` 能在同一事务中一并修改，因此不能在逐字段
        校验阶段提前判定。高级模式必须保存可执行的非空脚本；简单模式允许
        清空脚本以恢复默认配置。
        """
        for task in tasks:
            group = data.get(task, {}).get('ShopAdvanced')
            if not isinstance(group, dict) or group.get('Mode') != 'advanced':
                continue
            script = group.get('Script')
            if not isinstance(script, str) or not script.strip():
                raise ApiError(
                    'INVALID_PARAMS',
                    f'{task} 的高级模式需要先保存非空且有效的策略脚本',
                )
            self.validate_shop_strategy(script)

    def validate(self, path, value):
        parts = path.split('.')
        if len(parts) != 3:
            raise ApiError('INVALID_PARAMS', '配置路径必须为 Task.Group.Argument')
        field = self.args
        for part in parts:
            field = field.get(part, {})
        # 存储区禁止编辑内容，但允许通过同一配置事务显式清空。
        if field.get('type') == 'storage' and field.get('display') != 'hide' and type(value) is dict and not value:
            return parts
        if not field or field.get('display') in ('hide', 'disabled', 'readonly') or field.get('type') in ('storage', 'stored', 'state', 'lock'):
            raise ApiError('READ_ONLY', f'参数不存在或不允许修改：{path}')
        default, kind = field.get('value'), field.get('type')
        options = field.get('option')
        if kind == 'multiselect':
            if not isinstance(value, list) or len(value) > len(options or []) or any(
                not any(type(selected) is type(item) and selected == item for item in options or [])
                for selected in value
            ) or len(set(map(str, value))) != len(value):
                raise ApiError('INVALID_PARAMS', f'多选参数包含无效或重复选项：{path}')
            return parts
        if options and not any(type(value) is type(item) and value == item for item in options):
            raise ApiError('INVALID_PARAMS', f'请选择有效选项：{path}')
        if kind == 'checkbox' or isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, int):
            valid = type(value) is int
        elif isinstance(default, float):
            valid = type(value) in (float, int)
        else:
            valid = isinstance(value, str) or (default is None and value is None)
        if not valid or (isinstance(value, str) and len(value) > 20000) or (type(value) is float and not math.isfinite(value)):
            raise ApiError('INVALID_PARAMS', f'参数类型或长度不正确：{path}')
        rule = field.get('validate')
        if rule == 'datetime' or kind == 'datetime':
            try:
                if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
                    raise ValueError()
                datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError) as exc:
                raise ApiError('INVALID_PARAMS', f'日期格式应为 YYYY-MM-DD HH:mm:ss：{path}') from exc
        elif isinstance(rule, list) and len(rule) == 2:
            if type(value) not in (int, float) or not rule[0] <= value <= rule[1]:
                raise ApiError('INVALID_PARAMS', f'参数必须在 {rule[0]} 到 {rule[1]} 之间：{path}')
        elif isinstance(rule, str) and isinstance(value, (str, int, float)):
            if not re.fullmatch(rule, str(value)):
                raise ApiError('INVALID_PARAMS', f'参数格式不正确：{path}')
        if field.get('mode') == 'restricted_lua':
            self.validate_shop_strategy(value)
        if field.get('mode') == 'yaml' or kind == 'yaml':
            try:
                parsed = yaml.safe_load(value)
            except (yaml.YAMLError, ValueError, RecursionError) as exc:
                mark = getattr(exc, 'problem_mark', None)
                location = f'（第 {mark.line + 1} 行，第 {mark.column + 1} 列）' if mark else ''
                raise ApiError('INVALID_PARAMS', f'YAML 格式不正确{location}：{path}') from exc
            if parsed is not None and not isinstance(parsed, dict):
                raise ApiError('INVALID_PARAMS', f'YAML 顶层必须是键值映射：{path}')
        return parts

    def patch(self, name, revision, changes):
        with self.lock, config_transaction(self.path(name)):
            # revision 仅为旧客户端兼容参数。字段赋值合并到锁内最新快照，
            # 无关字段的运行状态更新不应拒绝用户输入；同字段按事务顺序生效。
            data, _ = self.read(name)
            seen = set()
            affected_shop_tasks = set()
            for change in changes:
                task, group, arg = self.validate(change.path, change.value)
                if change.path in seen:
                    raise ApiError('INVALID_PARAMS', '同一次保存不能重复修改同一个参数')
                seen.add(change.path)
                data.setdefault(task, {}).setdefault(group, {})[arg] = change.value
                self._sync_record_time(data[task][group], arg)
                if group == 'ShopAdvanced':
                    affected_shop_tasks.add(task)
            self.validate_shop_advanced_groups(data, affected_shop_tasks)
            atomic_write(str(self.path(name)), json.dumps(data, ensure_ascii=False, indent=2))
            return self.get(name)

    @staticmethod
    def _sync_record_time(fields, arg):
        """把 Value 参数对应的时间戳重置为当前时间。

        情绪等参数由“值 + 记录时间”两个字段推算实时状态，改值不刷新时间戳时，
        下次计算会把旧时间戳之后的恢复量重复计入。
        """
        if not arg.endswith('Value'):
            return
        record = arg[:-len('Value')] + 'Record'
        if record in fields:
            fields[record] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def delete(self, name, revision):
        with self.lock, config_transaction(self.path(name)):
            if self.read(name)[1] != revision:
                raise ApiError('CONFLICT', '配置已变化，请重新加载后删除')
            # 删除操作保留备份，用户可从 config/backup 手动恢复。
            backup = self.directory / 'backup'
            backup.mkdir(exist_ok=True)
            target = backup / f'{name}-{datetime.now():%Y%m%d-%H%M%S-%f}.json'
            self.path(name).replace(target)
            return {'deleted': name}
