"""茗交所本地账户重建；保留原件，并仅清理交易身份与认证历史。"""
import json
import hashlib
import os
import shutil
import sqlite3
import uuid
from contextlib import ExitStack, closing

from deploy.atomic import atomic_write
from module.api.protocol import ApiError
from module.config.transaction import config_transaction
from module.runtime.account_vault import SecretKey
from module.runtime.game_data import INSTANCE_FIELD, GameDataProtector
from module.scheduler.history_store import AuthenticatedHistoryStore


class StockExchangeRecovery:
    def __init__(self, configs, valid_binding):
        self.configs = configs
        self.protection = GameDataProtector(configs.root)
        self.valid_binding = valid_binding

    def plan(self, instance):
        self.configs.path(instance)
        try:
            with self.protection.transaction():
                pass
            bindings = self.protection.read_file('bindings.json') or {}
            if not isinstance(bindings, dict) or any(not self.valid_binding(row) for row in bindings.values()):
                raise ValueError()
            scope, names = 'instance', [instance]
        except (ApiError, OSError, ValueError, TypeError, KeyError):
            # 共享密钥、登记或绑定不可读时，无法可靠地区分各账户。
            scope, names = 'all', sorted(self.protection._configs())
        return {'instance': instance, 'scope': scope, 'affectedInstances': names, 'rebuilt': False}

    def rebuild(self, instance, confirm=False, scope='instance'):
        plan = self.plan(instance)
        if not confirm:
            return plan
        if scope != plan['scope']:
            raise ApiError('STOCK_REBUILD_SCOPE_CHANGED', '重建范围已变化，请重新确认', plan)
        store = AuthenticatedHistoryStore(self.protection.root / 'config')
        with ExitStack() as locks:
            # 与资源写入保持相同锁顺序；重建不改变调度程序、变量和最新资源记录。
            for name in plan['affectedInstances']:
                locks.enter_context(config_transaction(store.path(name)))
            for name in plan['affectedInstances']:
                locks.enter_context(config_transaction(self.configs.path(name)))
            locks.enter_context(config_transaction(self.protection.directory))
            locks.enter_context(config_transaction(self.protection.state_path))
            latest = self.plan(instance)
            if latest != plan:
                raise ApiError('STOCK_REBUILD_SCOPE_CHANGED', '重建范围已变化，请重新确认', latest)
            backup = self.protection.root / 'config' / 'backup' / ('stock-rebuild-' + uuid.uuid4().hex)
            self.protection._safe(backup)
            backup.mkdir(parents=True, mode=0o700)
            # 先完成可恢复快照，再改动任何原数据。
            if self.protection.directory.exists():
                for path in self.protection.directory.rglob('*'):
                    self.protection._safe(path)
                shutil.copytree(self.protection.directory, backup / 'stock-exchange', ignore=shutil.ignore_patterns('*.lock'))
            configs = {}
            for name in plan['affectedInstances']:
                path = self.configs.path(name)
                content = json.loads(path.read_bytes())
                if not isinstance(content, dict) or not isinstance(content.get('Alas'), dict):
                    raise ApiError('CONFIG_INVALID', '实例配置损坏，请先修复配置')
                configs[name] = content
                shutil.copyfile(path, backup / path.name)
                if store.path(name).exists():
                    store.backup(name, backup / 'scheduler' / store.path(name).name)
            if scope == 'all':
                # 显式重建不退回旧本机登记，也不复用损坏密钥。
                self.protection.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
                for path in self.protection.directory.iterdir():
                    if path.name.endswith('.lock'):
                        continue
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                self.protection.context = os.urandom(32).hex()
                key = SecretKey(os.urandom(32))
                try:
                    self.protection._write_key(key)
                    self.protection._save_state({'version': 1, 'instances': {}, 'files': {}, 'anchors': {}}, key)
                    atomic_write(str(self.protection.marker), 'AzurPilot game protection v2\n')
                finally:
                    key.clear()
            else:
                with self.protection.transaction() as (data, _):
                    retired = {identity for identity, row in data['instances'].items() if row['name'] == instance}
                bindings = self.protection.read_file('bindings.json') or {}
                if self.protection.has_file('bindings.json'):
                    self.protection.write_file('bindings.json', {key: row for key, row in bindings.items() if key not in retired})
                with self.protection.transaction() as (data, _):
                    for identity in retired:
                        data['instances'][identity]['active'] = False
                # 未完成格式升级的旧身份也必须退出，否则重新开户会复用旧私钥。
                legacy = hashlib.sha256(instance.encode()).hexdigest()
                for name in ('identities/' + legacy + '.json', 'history/' + legacy + '.sqlite3'):
                    path = self.protection.file_path(name)
                    for suffix in ('', '-wal', '-shm'):
                        path.with_name(path.name + suffix).unlink(missing_ok=True)
            for name, content in configs.items():
                content[INSTANCE_FIELD] = None
                atomic_write(str(self.configs.path(name)), json.dumps(content, ensure_ascii=False, indent=2))
                if store.path(name).exists():
                    with closing(sqlite3.connect(store.path(name))) as db, db:
                        for table in ('action_point_history', 'action_point_chain', 'action_point_chain_owner'):
                            db.execute(f'DROP TABLE IF EXISTS {table}')
            return {**plan, 'rebuilt': True}
