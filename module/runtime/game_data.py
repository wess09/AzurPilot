"""交易游戏文件的持久化认证存储，密钥随部署数据迁移。"""
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import stat
import uuid
from contextlib import contextmanager, closing
from pathlib import Path

from Crypto.Cipher import AES

from deploy.atomic import atomic_write
from module.api.protocol import ApiError
from module.config.transaction import config_transaction
from module.runtime.account_local import LocalProtector, dpapi
from module.runtime.account_vault import SecretKey

INSTANCE_FIELD = '_stockInstance'


def damaged(message='交易游戏文件校验失败，请恢复完整备份；已停止使用原文件'):
    return ApiError('STOCK_STORAGE_DAMAGED', message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class GameDataProtector:
    """独立保存认证密钥、实例登记与检查点，不绑定主机、用户或项目路径。"""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / 'config' / 'stock-exchange'
        self.state_path = self.directory / 'registry.json'
        self.key_path = self.state_path.with_name('game.key')
        self.context = None
        self.marker = self.directory / 'protected-v2'
        self.legacy_marker = self.directory / 'protected-v1'

    def _safe(self, path):
        """校验游戏数据目录之内的每一级路径都不是链接；root 以上的系统目录不参与判定。"""
        for parent in (path, *path.parents):
            if parent.is_symlink() or parent.is_junction():
                raise damaged('交易游戏文件路径包含链接，已停止使用')
            if parent == self.root or parent.resolve() == self.root:
                break

    def initialized(self):
        self.migrate_cache()
        if any(path.exists() for path in (self.marker, self.legacy_marker, self.state_path, self.key_path)):
            return True
        legacy = self._legacy_location()
        return legacy is not None and legacy[1].exists()

    def migrate_cache(self):
        """旧 cache 只搬文件；格式升级和认证统一由目标目录的读取流程处理。"""
        source = self.root / 'cache' / 'stock-exchange'
        if not source.exists():
            return
        self._safe(source)
        self._safe(self.directory)
        with config_transaction(self.directory):
            if not source.exists():
                return
            def move(old, new):
                self._safe(old)
                self._safe(new)
                if not new.exists():
                    new.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    shutil.move(old, new)
                elif old.is_dir() and new.is_dir():
                    for child in old.iterdir():
                        move(child, new / child.name)
                    old.rmdir()
                else:
                    # 默认读取 config；冲突时静默丢弃旧 cache 副本。
                    if old.is_dir():
                        for child in old.rglob('*'):
                            self._safe(child)
                        shutil.rmtree(old)
                    else:
                        old.unlink()

            try:
                move(source, self.directory)
            except OSError:
                raise damaged('旧玩家数据无法移入 config/stock-exchange/，请检查目录读写权限') from None

    def _legacy_location(self):
        """只为升级查找旧登记；新部署不依赖本机保护能力。"""
        protector = LocalProtector(self.root, 'stock-exchange-files-v1')
        try:
            return protector, protector.key_directory() / (protector.context + '.game')
        except ApiError:
            return None

    def _load_key(self, path, local=False):
        self._safe(path)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags), 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise ValueError()
            raw = file.read(4097)
        # 旧版 Windows 密钥仍需由原用户的 DPAPI 解封；Linux 仅依赖文件访问权限。
        key = SecretKey(dpapi(raw, decrypt=True) if local and os.name == 'nt' else raw)
        if len(key.value) != 32:
            key.clear()
            raise ValueError()
        return key

    def _write_key(self, key):
        """临时文件创建时就限制权限，再原子替换，避免写入半个密钥。"""
        temporary = self.key_path.with_name('game.' + uuid.uuid4().hex + '.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                  | getattr(os, 'O_BINARY', 0), 0o600), 'wb') as file:
                file.write(key.value)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.key_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _legacy_state(self, protector, path):
        """认证旧封装后迁移原密钥；不以易变的容器身份拒绝可解密数据。"""
        self._safe(path)
        envelope = json.loads(path.read_bytes())
        binding = json.loads(base64.b64decode(envelope['wrapped'], validate=True))
        if binding['provider'] != 'local' or binding['version'] != 1 or not isinstance(binding['host'], str):
            raise ValueError()
        local = self._load_key(protector.path(binding['id']), local=True)
        try:
            cipher = AES.new(local.value, AES.MODE_GCM, nonce=base64.b64decode(binding['nonce'], validate=True))
            cipher.update(f"AzurPilot/local/v1/{binding['host']}/{protector.context}/{binding['id']}".encode())
            key = SecretKey(cipher.decrypt_and_verify(base64.b64decode(binding['payload'], validate=True),
                                                     base64.b64decode(binding['tag'], validate=True)))
        finally:
            local.clear()
        try:
            if len(key.value) != 32:
                raise ValueError()
            self.context = protector.context
            data = self._decrypt(key, envelope, 'registry')
            self._validate_state(data)
            return data, key
        except BaseException:
            key.clear()
            raise

    @staticmethod
    def _validate_state(data):
        if (not isinstance(data, dict) or data.get('version') != 1
                or any(not isinstance(data.get(name), dict) for name in ('instances', 'files', 'anchors'))):
            raise ValueError()

    def _save_state(self, data, key):
        envelope = self._encrypt(key, data, 'registry')
        # 保留旧认证上下文，使现有密文和历史无需重写；新位置从登记中恢复上下文。
        envelope['context'] = self.context
        atomic_write(str(self.state_path), canonical(envelope))
        self.state_path.chmod(0o600)

    def _initialize(self):
        if self.marker.exists():
            raise damaged('交易游戏保护登记丢失，请恢复 config/stock-exchange/ 完整备份，不能自动重建身份')
        legacy = self._legacy_location()
        if legacy is not None and legacy[1].exists():
            protector, path = legacy
            self._safe(path)
            with config_transaction(path):
                try:
                    data, key = self._legacy_state(protector, path)
                except (ApiError, OSError, ValueError, TypeError, KeyError):
                    raise damaged('旧版交易游戏密钥或登记不可用，请恢复原密钥与完整备份后升级，不能自动重建身份') from None
        else:
            if self.legacy_marker.exists():
                raise damaged('旧版交易游戏保护登记丢失，请恢复原密钥与完整备份后升级，不能自动重建身份')
            data = {'version': 1, 'instances': {}, 'files': {}, 'anchors': {}}
            self.context = os.urandom(32).hex()
            if self.key_path.exists():
                # 首次初始化先保存密钥再保存空登记；中断时尚未登记身份或游戏文件。
                if (any(identity is not None for identity in self._configs().values())
                        or any(path.is_symlink() or path.is_file() and path != self.key_path and not path.name.endswith('.lock')
                               for path in self.directory.rglob('*'))):
                    raise damaged('交易游戏保护登记丢失，请恢复 config/stock-exchange/ 完整备份')
                key = self._load_key(self.key_path)
            else:
                key = SecretKey(os.urandom(32))
        created = False
        try:
            if self.key_path.exists():
                # 初始化或迁移中断只复用已确认属于当前登记的密钥。
                existing = self._load_key(self.key_path)
                try:
                    if not hmac.compare_digest(existing.value, key.value):
                        raise damaged('交易游戏保护登记丢失，请恢复 config/stock-exchange/ 完整备份')
                finally:
                    existing.clear()
            else:
                self._write_key(key)
                created = True
            self._save_state(data, key)
            return data, key
        except BaseException:
            try:
                if created and not self.state_path.exists():
                    self.key_path.unlink(missing_ok=True)
            finally:
                key.clear()
            raise

    @contextmanager
    def transaction(self):
        """登记与检查点跨进程串行更新；每次重新解封，缓存不能绕过密钥丢失。"""
        self.migrate_cache()
        self._safe(self.state_path)
        self._safe(self.key_path)
        self._safe(self.marker)
        self._safe(self.legacy_marker)
        self.state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with config_transaction(self.state_path):
            key = None
            try:
                if self.state_path.exists():
                    envelope = json.loads(self.state_path.read_bytes())
                    self.context = envelope['context']
                    if not isinstance(self.context, str) or not re.fullmatch(r'[0-9a-f]{64}', self.context):
                        raise ValueError()
                    try:
                        key = self._load_key(self.key_path)
                    except (OSError, ValueError):
                        raise damaged('交易游戏密钥丢失、损坏或无法读取，请恢复 config/stock-exchange/ 完整备份') from None
                    data = self._decrypt(key, envelope, 'registry')
                else:
                    data, key = self._initialize()
                self._validate_state(data)
                self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
                if not self.marker.exists():
                    atomic_write(str(self.marker), 'AzurPilot game protection v2\n')
                    self.marker.chmod(0o600)
                before = canonical(data)
                yield data, key
                if canonical(data) != before:
                    self._save_state(data, key)
            except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
                raise damaged() from None
            finally:
                if key is not None:
                    key.clear()

    def _encrypt(self, key, data, purpose):
        cipher = AES.new(key.value, AES.MODE_GCM, nonce=os.urandom(12))
        cipher.update(f'AzurPilot/game/v1/{self.context}/{purpose}'.encode())
        payload, tag = cipher.encrypt_and_digest(canonical(data))
        return {'version': 1, 'nonce': base64.b64encode(cipher.nonce).decode(),
                'tag': base64.b64encode(tag).decode(), 'payload': base64.b64encode(payload).decode()}

    def _decrypt(self, key, envelope, purpose):
        if envelope['version'] != 1:
            raise ValueError()
        cipher = AES.new(key.value, AES.MODE_GCM, nonce=base64.b64decode(envelope['nonce'], validate=True))
        cipher.update(f'AzurPilot/game/v1/{self.context}/{purpose}'.encode())
        return json.loads(cipher.decrypt_and_verify(base64.b64decode(envelope['payload'], validate=True),
                                                   base64.b64decode(envelope['tag'], validate=True)))

    def _configs(self):
        from module.api.config_service import accepts_name
        result = {}
        for path in (self.root / 'config').glob('*.json'):
            if not accepts_name(path.stem) or path.is_symlink() or path.is_junction():
                continue
            try:
                content = json.loads(path.read_bytes())
                if isinstance(content, dict) and isinstance(content.get('Alas'), dict):
                    result[path.stem] = content.get(INSTANCE_FIELD)
            except (OSError, ValueError):
                # 损坏的原配置保留登记，不能被视为删除后复用。
                result[path.stem] = None
        return result

    @staticmethod
    def _reconcile(data, configs):
        for identity, record in data['instances'].items():
            if not record['active']:
                continue
            if record.get('baseline'):
                # 旧统计按实例名存储；永久保留迁移来源，之后的重命名不能丢失旧月记录。
                record.setdefault('legacyStatsName', record['name'])
            matches = [name for name, value in configs.items() if value == identity]
            if record['name'] in matches:
                continue
            if len(matches) == 1 and record['name'] not in configs:
                record['name'] = matches[0]
            elif record['name'] not in configs and not matches:
                record['active'] = False

    def reconcile(self):
        if not self.initialized():
            return {}
        with self.transaction() as (data, _):
            self._reconcile(data, self._configs())
            return {identity: record['name'] for identity, record in data['instances'].items() if record['active']}

    def resolve(self, instance, fresh=False):
        from module.api.config_service import validate_name
        instance = validate_name(instance)
        path = self.root / 'config' / (instance + '.json')
        self._safe(path)
        with config_transaction(path):
            if not path.is_file():
                self.reconcile()
                raise ApiError('NOT_FOUND', '实例不存在')
            try:
                content = json.loads(path.read_bytes())
                if not isinstance(content, dict) or not isinstance(content.get('Alas'), dict):
                    raise ValueError()
            except (OSError, ValueError):
                raise ApiError('CONFIG_INVALID', '实例配置损坏，已停止游戏数据同步') from None
            with self.transaction() as (data, _):
                configs = self._configs()
                self._reconcile(data, configs)
                identity = content.get(INSTANCE_FIELD)
                record = data['instances'].get(identity) if isinstance(identity, str) else None
                if identity and (not record or not record['active']):
                    raise damaged('实例身份未登记或已删除，不能使用复制或回滚的玩家数据')
                if record and record['name'] == instance:
                    return identity
                if record and record['name'] not in configs and sum(value == identity for value in configs.values()) > 1:
                    raise damaged('存在多份相同实例身份，无法确定重命名来源，请保留原件')
                # 复制仍存在的实例只能取得新身份；仅原文件消失时识别为重命名。
                for old in data['instances'].values():
                    if old['active'] and old['name'] == instance:
                        old['active'] = False
                legacy_path = self.directory / 'identities' / (hashlib.sha256(instance.encode()).hexdigest() + '.json')
                legacy = INSTANCE_FIELD not in content and not fresh and legacy_path.exists()
                if legacy:
                    self._safe(legacy_path)
                    try:
                        previous = json.loads(legacy_path.read_bytes())
                        identity = str(uuid.UUID(previous['instanceId']))
                    except (OSError, ValueError, TypeError, KeyError, AttributeError):
                        raise damaged('旧实例身份损坏，请恢复身份备份') from None
                    if identity in data['instances']:
                        raise damaged('旧实例身份已登记，不能再次迁移')
                else:
                    identity = str(uuid.uuid4())
                predecessors = [key for key, row in data['instances'].items() if row['name'] == instance]
                baseline = not fresh and INSTANCE_FIELD not in content and not predecessors
                data['instances'][identity] = {'name': instance, 'active': True, 'schedulerName': instance, 'legacy': legacy,
                                               'predecessor': predecessors[-1] if predecessors else None,
                                               'baseline': baseline, 'legacyStatsName': instance if baseline else None}
                content[INSTANCE_FIELD] = identity
                atomic_write(str(path), json.dumps(content, ensure_ascii=False, indent=2))
                return identity

    def retire(self, instance):
        if self.initialized():
            with self.transaction() as (data, _):
                for record in data['instances'].values():
                    if record['name'] == instance:
                        record['active'] = False

    def record(self, identity):
        with self.transaction() as (data, _):
            row = data['instances'].get(identity)
            if not row or not row['active']:
                raise damaged('实例已经删除，已停止使用其玩家数据')
            return dict(row)

    def key(self, identity, purpose):
        with self.transaction() as (data, key):
            if not data['instances'].get(identity, {}).get('active'):
                raise damaged('实例已经删除，已停止使用其玩家数据')
            return SecretKey(hmac.digest(key.value, f'{identity}/{purpose}'.encode(), 'sha256'))

    def file_path(self, name):
        path = self.directory / name
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise damaged()
        self._safe(path)
        return path

    def read_file(self, name):
        with config_transaction(self.file_path(name)):
            return self._read_file(name)

    def _read_file(self, name):
        path = self.file_path(name)
        with self.transaction() as (data, key):
            expected = data['files'].get(name)
            if not path.exists():
                if expected:
                    raise damaged('受保护的交易文件丢失，请恢复完整备份')
                return None
            if not expected:
                raise damaged('交易文件未登记，不能自动接受替换文件')
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest not in (expected.get('head'), expected.get('pending')):
                raise damaged()
            result = self._decrypt(key, json.loads(raw), name)
            data['files'][name] = {'head': digest}
            return result

    def has_file(self, name):
        with self.transaction() as (data, _):
            return name in data['files']

    def write_file(self, name, value, legacy=False):
        with config_transaction(self.file_path(name)):
            self._write_file(name, value, legacy)

    def _write_file(self, name, value, legacy=False):
        path = self.file_path(name)
        if not legacy:
            self.read_file(name)
        # 先持久化候选检查点，再替换文件；崩溃只允许完整的旧版或候选新版。
        with self.transaction() as (data, key):
            raw = canonical(self._encrypt(key, value, name))
            digest = hashlib.sha256(raw).hexdigest()
            expected = data['files'].setdefault(name, {})
            expected['pending'] = digest
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        atomic_write(str(path), raw)
        path.chmod(0o600)
        with self.transaction() as (data, _):
            data['files'][name] = {'head': digest}

    def anchor(self, name, actual, prepare=False):
        with self.transaction() as (data, _):
            expected = data['anchors'].get(name)
            if prepare:
                data['anchors'].setdefault(name, {})['pending'] = actual
            elif expected is None:
                return False
            elif actual not in (expected.get('head'), expected.get('pending')):
                raise damaged('行动力历史哈希链或持久检查点不匹配，已停止同步')
            else:
                data['anchors'][name] = {'head': actual}
            return True

    def has_anchor(self, name):
        with self.transaction() as (data, _):
            return name in data['anchors']

    def relocate_scheduler(self, instance, identity):
        """手动重命名配置后迁移已提交的资源记录，冲突时保留两边原件。"""
        record = self.record(identity)
        old = record['schedulerName']
        directory = self.root / 'config' / 'scheduler'
        source, target = directory / (old + '.sqlite3'), directory / (instance + '.sqlite3')
        if old == instance:
            predecessor = record.get('predecessor')
            if predecessor and target.exists():
                with config_transaction(target):
                    with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as db:
                        chained = db.execute("SELECT 1 FROM sqlite_master WHERE name='action_point_chain_owner'").fetchone()
                        owner = db.execute('SELECT instance_id FROM action_point_chain_owner WHERE id=1').fetchone() if chained else None
                        if owner and owner[0] == predecessor:
                            backup = self.root / 'config' / 'backup' / ('stock-' + predecessor) / 'scheduler' / target.name
                            backup.parent.mkdir(parents=True, exist_ok=True)
                            self._safe(backup)
                            with closing(sqlite3.connect(backup)) as outgoing:
                                db.backup(outgoing)
                    if owner and owner[0] == predecessor:
                        # 只撤销旧交易历史，不能因交易身份变化清空普通调度和资源数据。
                        with closing(sqlite3.connect(target)) as db, db:
                            for table in ('action_point_history', 'action_point_chain', 'action_point_chain_owner'):
                                db.execute(f'DROP TABLE IF EXISTS {table}')
                with self.transaction() as (data, _):
                    data['instances'][identity]['predecessor'] = None
            return
        # 普通总库和历史文件不共享提交域，由加密的阶段记录支持中断续跑。
        from module.runtime.profile_relocation import relocate_profile
        relocate_profile(self, identity, old, instance)
