"""参数定义驱动的配置服务模块。

在跨进程事务内校验并合并字段修改，提供配置读取、更新、导入、删除与元数据获取能力。
"""

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
from module.combat.emotion_state import EmotionRecoveryState
from module.config.time_source import now as current_time
from module.config.transaction import config_transaction

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = 'template'
# 实例名会成为配置文件名。允许中日文、字母、数字、下划线、点号、空格与短横线，
# 也与上游一致：config/ 下除 template 外任何 *.json 都算实例。
HIRAGANA = r'\u3041-\u3096'
KATAKANA = r'\u30a1-\u30fa\u30fc\u31f0-\u31ff\uff66-\uff9f'
HAN = r'\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff'
CJK = HIRAGANA + KATAKANA + HAN
# 首字符不能是下划线、点号或空格，它们只出现在名称中段与末尾。
NAME = re.compile(r'[A-Za-z0-9' + CJK + r'][A-Za-z0-9_. ' + CJK + r'\-]{0,63}\Z')
# 名字里以点分段的基名与这些词相同时继续拦下：template 是模板，其余是 Windows 设备名。
RESERVED = {TEMPLATE, 'deploy', 'backup', 'con', 'prn', 'aux', 'nul',
            *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
OPSI_EXPLORE_PROGRESS = {
    'OpsiExplore.OpsiExplore.ExploreProgress',
    'OpsiScheduling.OpsiSmartExplore.Progress',
}


def validate_name(value):
    """校验实例名并返回它的规范形式。

    末尾的空白与点归一化掉：Windows 上 `ap .json` 落盘就是 `ap.json`，
    两者本就是同一个文件。前导点不削，`.` 与 `..` 是路径成分，`.隐藏` 这类名字一概拒。
    以点分段的基名命中 RESERVED 即拒：`template` 与 `template.fpy` 都是模板。

    Args:
        value (str): 待校验的实例名称。

    Returns:
        str: 规整化后的安全实例名称。

    Raises:
        ApiError: 实例名类型错误或包含非法字符、保留名时抛出。
    """
    if not isinstance(value, str):
        raise ApiError('INVALID_PARAMS', '实例名无效')
    name = re.sub(r'[\s.]+\Z', '', value.strip())
    if not NAME.fullmatch(name) or name.split('.')[0].lower() in RESERVED:
        raise ApiError('INVALID_PARAMS', '实例名无效：不能含路径分隔符或 Windows 保留字符，不能以点开头，不能是保留名')
    return name


def accepts_name(value):
    """列举时用的宽松版检验函数。

    不合规的文件名当作不存在，不让一个坏文件名打断整份列表。

    Args:
        value: 待检查的文件名或实例名。

    Returns:
        bool: 符合命名规范返回 True，否则返回 False。
    """
    try:
        return validate_name(value) == value
    except ApiError:
        return False


class ConfigService:
    """参数驱动的配置服务。

    只访问白名单配置，读操作不会触发运行器的配置写回。

    Attributes:
        root (Path): 仓库根目录。
        directory (Path): 配置文件夹路径 (config/)。
        import_directory (Path): 导入源配置文件夹路径 (config/import/)。
        lock (threading.RLock): 配置操作重入锁。
        args (dict): 参数元数据定义。
        menu (dict): 菜单结构元数据。
        translations (dict): 简体中文翻译字典。
        template (dict): 模板配置快照。
    """

    def __init__(self, root: Path = ROOT):
        """初始化配置服务。

        Args:
            root (Path, optional): 根目录。默认为 ROOT。
        """
        self.root = root
        self.directory = root / 'config'
        from module.persistence.database import get_database
        self.database = get_database(self.directory)
        # 导入源单独一个目录：config/ 下的 *.json 都算实例，导入源不能与实例列表混在一起。
        self.import_directory = self.directory / 'import'
        self.lock = threading.RLock()
        argument = root / 'module/config/argument'
        self.args = self.read_json(argument / 'args.json')
        self.menu = self.read_json(argument / 'menu.json')
        self.translations = self.read_json(root / 'module/config/i18n/zh-CN.json')
        self.template = self.read_json(self.directory / 'template.json')

    @staticmethod
    def read_json(path):
        """读取并反序列化 JSON 文件。

        Args:
            path (Path): JSON 文件路径。

        Returns:
            Any: 解析后的 JSON 对象。
        """
        return json.loads(path.read_text(encoding='utf-8'))

    def translate(self, key):
        """根据路径键翻译文本。

        Args:
            key (str): 点号分隔的国际化路径键。

        Returns:
            str: 翻译后的显示文本或键的最后一段。
        """
        value = self.translations
        for part in key.split('.'):
            value = value.get(part, {}) if isinstance(value, dict) else {}
        return value if isinstance(value, str) and value != key else key.split('.')[-1]

    def path(self, name, exists=True):
        """解析并校验实例配置文件路径。

        Args:
            name (str): 实例名称。
            exists (bool, optional): 是否要求文件必须已存在。默认为 True。

        Returns:
            Path: 安全校验通过的配置文件路径。

        Raises:
            ApiError: 路径非法或不存在时抛出。
        """
        name = validate_name(name)
        path = self.directory / f'{name}.json'
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise ApiError('INVALID_PARAMS', '配置路径无效')
        if exists and not path.is_file():
            raise ApiError('NOT_FOUND', '实例不存在')
        return path

    def names(self):
        """列出当前存在的所有合法实例名称。

        Returns:
            list[str]: 排序后的实例名列表。
        """
        return sorted(p.stem for p in self.directory.glob('*.json')
                      if accepts_name(p.stem) and not p.is_symlink() and self.is_instance(p))

    def save_import(self, name, content):
        """把上传的配置写进导入目录；先解成 JSON 并确认有 Alas 段，坏文件不入库。

        Args:
            name (str): 导入目标名称。
            content (str): JSON 配置字符串。

        Returns:
            dict: 包含导入文件名称的字典。

        Raises:
            ApiError: JSON 损坏、格式不符或路径非法时抛出。
        """
        name = validate_name(name)
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise ApiError('INVALID_PARAMS', '不是合法的 JSON 配置文件') from exc
        if not isinstance(data, dict) or not isinstance(data.get('Alas'), dict):
            raise ApiError('INVALID_PARAMS', '配置文件缺少 Alas 段')
        if '_schedulerProgram' in data:
            from module.scheduler.store import ProgramStore
            try:
                ProgramStore.import_bundle(data['_schedulerProgram'])
            except (ValueError, KeyError, TypeError) as exc:
                raise ApiError('INVALID_PARAMS', f'调度方案导入失败：{exc}') from exc
        self.import_directory.mkdir(parents=True, exist_ok=True)
        path = self.import_directory / f'{name}.json'
        if path.is_symlink() or path.resolve().parent != self.import_directory.resolve():
            raise ApiError('INVALID_PARAMS', '导入路径无效')
        with path.open('w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        return {'name': name}

    def is_instance(self, path):
        """判断指定 JSON 文件是否包含合法的 Alas 实例配置。

        Args:
            path (Path): 文件路径。

        Returns:
            bool: 属于合法配置实例返回 True，否则返回 False。
        """
        try:
            return isinstance(self.read_json(path).get('Alas'), dict)
        except (OSError, ValueError, AttributeError):
            return False

    def importable(self):
        """获取导入目录里可供挑选的配置文件列表。

        Returns:
            list[dict]: 包含 name 和 modified 信息的字典列表。
        """
        if not self.import_directory.is_dir():
            return []
        return [{'name': path.stem, 'modified': path.stat().st_mtime}
                for path in sorted(self.import_directory.glob('*.json'))
                if accepts_name(path.stem) and not path.is_symlink() and self.is_instance(path)]

    def read_import(self, name):
        """读导入目录里的一份配置；与实例名同样用白名单校验，不做任意路径读取。

        Args:
            name (str): 导入配置文件名。

        Returns:
            dict: 配置数据字典。

        Raises:
            ApiError: 导入路径非法或文件不存在时抛出。
        """
        name = validate_name(name)
        path = self.import_directory / f'{name}.json'
        if path.is_symlink() or path.resolve().parent != self.import_directory.resolve():
            raise ApiError('INVALID_PARAMS', '导入路径无效')
        if not path.is_file() or not self.is_instance(path):
            raise ApiError('NOT_FOUND', '导入文件不存在')
        return self.read_json(path)

    def read(self, name):
        """读取指定实例的配置内容与文件版本校验值。

        Args:
            name (str): 实例名称。

        Returns:
            tuple[dict, str]: 补全模板后的完整配置字典与 sha256 校验哈希。

        Raises:
            ApiError: 文件损坏或无 Alas 根节点时抛出 CONFIG_INVALID。
        """
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
        if '_stockInstance' in data:
            merged['_stockInstance'] = data['_stockInstance']
        for task, groups in data.items():
            if isinstance(groups, dict):
                for group, fields in groups.items():
                    if isinstance(fields, dict):
                        merged.setdefault(task, {}).setdefault(group, {}).update(fields)
                        # 新名称出现前，WebUI 也要显示旧航母开关的实际值。
                        if task == 'General' and group == 'Enhance':
                            legacy = fields.get('SkipSingleCommonCV')
                            if 'KeepCommonCV' not in fields and isinstance(legacy, bool):
                                merged[task][group]['KeepCommonCV'] = legacy
                            merged[task][group].pop('SkipSingleCommonCV', None)
        from module.config.redirect_utils.shop import migrate_shop_options

        merged, shop_warnings = migrate_shop_options(data, merged)
        if shop_warnings:
            from module.logger import logger

            for task, reason in shop_warnings:
                logger.warning(f'{task}：{reason}，已暂停任务，请检查购买配置后重新启用')
        return merged, hashlib.sha256(raw).hexdigest()

    def schema(self, language='zh-CN'):
        """按会话读取前端菜单与参数元数据，不修改全局语言设置。

        Args:
            language (str, optional): 语言代码。默认为 'zh-CN'。

        Returns:
            dict: 包含 menu, args, translations 的架构字典。

        Raises:
            ApiError: 不支持的语言代码时抛出 INVALID_PARAMS。
        """
        if language not in {'zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW'}:
            raise ApiError('INVALID_PARAMS', '不支持的界面语言')
        translations = self.translations if language == 'zh-CN' else self.read_json(
            self.root / 'module/config/i18n' / f'{language}.json')
        return {'menu': self.menu, 'args': self.args, 'translations': translations}

    def get(self, name):
        """获取指定实例当前的配置数据与版本号。

        Args:
            name (str): 实例名称。

        Returns:
            dict: 包含 instance, revision, values 的字典。
        """
        data, revision = self.read(name)
        # 内部身份不属于参数契约，编辑界面只接收参数组。
        data.pop('_stockInstance', None)
        return {'instance': name, 'revision': revision, 'values': data}

    def export(self, name):
        """配置导出携带方案，排除调度运行变量和资源历史。"""
        from module.scheduler.store import ProgramStore
        data, _ = self.read(name)
        from module.runtime.game_data import INSTANCE_FIELD
        data.pop(INSTANCE_FIELD, None)
        store = ProgramStore(self.directory, store=self.database)
        if store.exists(name):
            data['_schedulerProgram'] = store.export(name)
        return data

    def create(self, name, source=None, import_file=None):
        """创建新的实例配置文件。

        Args:
            name (str): 新建实例名称。
            source (str, optional): 复制源实例名称。默认为 None。
            import_file (str, optional): 导入目录中的源文件名。默认为 None。

        Returns:
            dict: 新建实例的配置数据及版本。

        Raises:
            ApiError: 实例名冲突或已存在时抛出 ALREADY_EXISTS。
        """
        # 先归一化，落盘名与返回给客户端的实例名才是同一个。
        name = validate_name(name)
        with self.lock:
            if import_file:
                data = self.read_import(import_file)
            elif source:
                data = self.read(source)[0]
            else:
                data = copy.deepcopy(self.template)
            bundle = data.pop('_schedulerProgram', None)
            from module.runtime.game_data import INSTANCE_FIELD
            # 空占位表示新实例，首次使用时登记 UUID，禁止把复制的仪表盘当迁移来源。
            data[INSTANCE_FIELD] = None
            from module.scheduler.store import ProgramStore
            store = ProgramStore(self.directory, store=self.database)
            if bundle is not None:
                try:
                    bundle = store.import_bundle(bundle)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ApiError('INVALID_PARAMS', f'调度方案导入失败：{exc}') from exc
            path = self.path(name, exists=False)
            # 排他创建避免不同会话覆盖已有配置。
            try:
                with path.open('x', encoding='utf-8') as file:
                    json.dump(data, file, ensure_ascii=False, indent=2)
            except FileExistsError as exc:
                raise ApiError('ALREADY_EXISTS', '同名实例已存在') from exc
            try:
                if source:
                    store.copy(source, name)
                elif bundle is not None:
                    store.import_program(name, {key: bundle[key] for key in ('mode', 'draft', 'active')})
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return self.get(name)


    def validate(self, path, value):
        """严格校验单项参数的修改路径与取值范围。

        Args:
            path (str): 参数路径（格式为 Task.Group.Argument）。
            value (Any): 修改后的新值。

        Returns:
            list[str]: 解析后的 [Task, Group, Argument] 列表。

        Raises:
            ApiError: 路径格式错误、只读参数、类型不匹配或超出校验规则时抛出。
        """
        parts = path.split('.')
        if len(parts) != 3:
            raise ApiError('INVALID_PARAMS', '配置路径必须为 Task.Group.Argument')
        field = self.args
        for part in parts:
            field = field.get(part, {})
        # 开荒进度仍只读，只允许按钮清空；断点由下方事务同步重置。
        if path in OPSI_EXPLORE_PROGRESS and field and type(value) is str and value == '':
            return parts
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
        """批量修改实例配置项，并在文件事务中原子写回。

        Args:
            name (str): 实例名称。
            revision (str): 客户端已知的版本哈希。
            changes (list): 包含 path 和 value 的修改条目列表。

        Returns:
            dict: 修改后的最新实例配置。

        Raises:
            ApiError: 重复修改同一参数或校验失败时抛出。
        """
        with self.lock, config_transaction(self.path(name)):
            # revision 仅为旧客户端兼容参数。字段赋值合并到锁内最新快照，
            # 无关字段的运行状态更新不应拒绝用户输入；同字段按事务顺序生效。
            data, _ = self.read(name)
            seen = set()
            edited_groups = {}
            for change in changes:
                task, group, arg = self.validate(change.path, change.value)
                if change.path in seen:
                    raise ApiError('INVALID_PARAMS', '同一次保存不能重复修改同一个参数')
                seen.add(change.path)
                data.setdefault(task, {}).setdefault(group, {})[arg] = change.value
                if change.path in OPSI_EXPLORE_PROGRESS:
                    self._reset_opsi_explore_progress(data, change.path)
                edited_groups.setdefault((task, group), set()).add(arg)
            # 按最终配置校准；同一批先改心情再改恢复条件，也使用最终条件。
            now = current_time() if any(group in ('Emotion', 'PublicEmotion') and
                                        any(arg.endswith('Value') for arg in args)
                                        for (_, group), args in edited_groups.items()) else None
            for (task, group), args in edited_groups.items():
                fields = data[task][group]
                for arg in args:
                    self._sync_record_time(fields, arg, now if group in ('Emotion', 'PublicEmotion') else None)
                if group in ('Emotion', 'PublicEmotion'):
                    prefixes = ('Fleet1', 'Fleet2') if group == 'Emotion' else ('Fleet',)
                    for prefix in prefixes:
                        if prefix + 'Value' in args:
                            try:
                                fields[prefix + 'RecoveryState'] = EmotionRecoveryState.calibrate(
                                    fields[prefix + 'Value'], now, fields[prefix + 'Recover'],
                                    fields[prefix + 'Oath'], fields[prefix + 'Onsen']).export()
                            except KeyError as exc:
                                raise ApiError(
                                    'INVALID_PARAMS', f'{task}.{group}.{exc.args[0]}: 缺少心情恢复配置'
                                ) from None
                            except ValueError as exc:
                                raise ApiError(
                                    'INVALID_PARAMS', f'{task}.{group}.{prefix}Value: {exc}'
                                ) from None
                        elif any(prefix + suffix in args for suffix in ('Recover', 'Oath', 'Onsen')):
                            fields[prefix + 'RecoveryState'] = None
            atomic_write(str(self.path(name)), json.dumps(data, ensure_ascii=False, indent=2))
            return self.get(name)

    @staticmethod
    def _reset_opsi_explore_progress(data, path):
        """清空对应开荒断点，保留本月行动力购买记录及其他任务状态。"""
        if path == 'OpsiExplore.OpsiExplore.ExploreProgress':
            fields = data.setdefault('OpsiExplore', {}).setdefault('OpsiExplore', {})
            fields['LastZone'] = 0
            fields['MeowfficerCleanupState'] = None
        else:
            storage = data.setdefault('OpsiScheduling', {}).setdefault('Storage', {}).get('Storage')
            if isinstance(storage, dict):
                storage.pop('SmartExplore', None)

    @staticmethod
    def _sync_record_time(fields, arg, now=None):
        """把 Value 参数对应的时间戳重置为当前时间。

        情绪等参数由“值 + 记录时间”两个字段推算实时状态，改值不刷新时间戳时，
        下次计算会把旧时间戳之后的恢复量重复计入。

        Args:
            fields (dict): 当前分组配置字典。
            arg (str): 当前修改的参数名。
            now (datetime, optional): 心情校准使用的统一精确时间，其他成对字段沿用原格式。
        """
        if not arg.endswith('Value'):
            return
        record = arg[:-len('Value')] + 'Record'
        if record in fields:
            fields[record] = (datetime.now().strftime('%Y-%m-%d %H:%M:%S') if now is None
                              else now.isoformat(sep=' ', timespec='microseconds'))

    def delete(self, name, revision):
        """删除指定实例并自动创建备份。

        Args:
            name (str): 待删除的实例名称。
            revision (str): 校验版本哈希。

        Returns:
            dict: 包含 deleted 实例名的响应字典。

        Raises:
            ApiError: 版本冲突时抛出 CONFLICT。
        """
        with self.lock, config_transaction(self.path(name)):
            if self.read(name)[1] != revision:
                raise ApiError('CONFLICT', '配置已变化，请重新加载后删除')
            # 删除操作保留备份，用户可从 config/backup 手动恢复。
            backup = self.directory / 'backup'
            backup.mkdir(exist_ok=True)
            target = backup / f'{name}-{datetime.now():%Y%m%d-%H%M%S-%f}.json'
            import shutil
            shutil.copy2(self.path(name), target)
            from module.scheduler.store import ProgramStore
            ProgramStore(self.directory, store=self.database).archive(name, backup / target.stem)
            self.path(name).unlink()
            return {'deleted': name}
