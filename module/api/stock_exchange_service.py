"""AzurPilot 独立股票实例接入；交易与用户会话均留在交易所。"""
import json
import os
import sqlite3
import threading
import time
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from module.base import http
from module.api.protocol import ApiError
from module.api.stock_exchange_identity import load_identity, binding_key, make_instance_request
from module.api.stock_exchange_history import ActionHistory
from module.runtime.game_data import GameDataProtector, damaged


def exchange_url():
    value = os.environ.get('STOCK_EXCHANGE_URL', 'https://stock.azurpilot.com').rstrip('/')
    try:
        parsed = urlparse(value)
        parsed.port
    except ValueError:
        raise ApiError('INVALID_PARAMS', 'STOCK_EXCHANGE_URL 地址格式无效') from None
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path
            or not parsed.hostname or parsed.scheme not in ('https', 'http')
            or parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1')):
        raise ApiError('INVALID_PARAMS', 'STOCK_EXCHANGE_URL 须为 HTTPS origin，本机开发可使用回环 HTTP')
    return value


def account_operation(method):
    """重建与后台同步互斥，避免旧身份在重建后继续上传。"""
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.operation_lock:
            return method(self, *args, **kwargs)
    return run


class StockExchangeService:
    """每实例注册一只独立股票；私钥仅用于接入，交易账户与实例解耦。"""
    def __init__(self, configs):
        self.configs = configs
        self.protection = GameDataProtector(configs.root)
        self.path = self.protection.directory / 'stocks-v2.json'
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.listeners = set()
        self.bindings, self.identities, self.instance_locks = {}, {}, {}
        self.stamps, self.records, self.statuses = {}, {}, {}
        self.remote_status, self.last_status = {}, {}
        self.retired = set()
        self.history = ActionHistory(configs.root)
        self.names = {}
        self.storage_error = None
        self.refresh_stamp = None
        self.refresh_check = 0
        self.monitors = set()
        try:
            self._refresh()
        except ApiError as error:
            self.storage_error = error

    @staticmethod
    def _valid_binding(value):
        return (isinstance(value, dict) and type(value.get('stockId')) is int and value['stockId'] > 0
                and all(isinstance(value.get(field), str) and value[field] for field in ('bindingKey', 'username', 'url')))

    def _storage_stamp(self):
        paths = [self.path, self.protection.marker, self.protection.legacy_marker,
                 self.protection.state_path, self.protection.key_path]
        paths.extend(sorted((Path(self.configs.root) / 'config').glob('*.json')))
        result = []
        for path in paths:
            try:
                stat = path.stat()
                result.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
            except FileNotFoundError:
                result.append((str(path), None))
            except OSError:
                raise damaged('无法检查游戏文件状态，已停止同步') from None
        return tuple(result)

    @account_operation
    def _refresh(self):
        """文件系统重命名沿用 UUID；删除和同名重建撤销旧身份及监视。"""
        with self.lock:
            self.protection.migrate_cache()
            stamp = self._storage_stamp()
            if stamp == self.refresh_stamp and self.storage_error is None and time.monotonic() < self.refresh_check:
                return
            if not self.path.exists() and not self.protection.initialized():
                return
            active = self.protection.reconcile()
            configs = self.protection._configs()
            for identity, name in active.items():
                if name in configs and configs[name] != identity:
                    self.protection.resolve(name)
            active = self.protection.reconcile()
            retired = self.protection.read_file('stocks-retired-v2.json') or {}
            if not isinstance(retired, dict) or any(not isinstance(key, str) or value is not True for key, value in retired.items()):
                raise damaged('股票删除登记格式无效')
            self.retired = set(retired)
            stored = self.protection.read_file('stocks-v2.json') or {}
            if not isinstance(stored, dict) or any(not self._valid_binding(value) for value in stored.values()):
                raise damaged('股票绑定文件格式无效')
            current = {name: identity for identity, name in active.items()}
            for old, identity in self.names.items():
                new = active.get(identity)
                if new == old:
                    continue
                for state in (self.identities, self.stamps, self.records, self.statuses, self.remote_status, self.last_status,
                              self.history.scanned, self.history.next_send, self.history.next_check, self.history.failures, self.history.pending,
                              self.history.legacy_warnings):
                    value = state.pop(old, None)
                    if new and value is not None:
                        state[new] = value
            self.names = current
            self.bindings = {active[identity]: value for identity, value in stored.items() if identity in active}
            self.monitors = {name for name, value in self.bindings.items() if not value.get('deleted') and self.names.get(name) not in self.retired}
            self.storage_error = None
            self.history.discard_retired(active)
            retired = set(stored) - set(active)
            if retired:
                self.protection.write_file('stocks-v2.json', {key: value for key, value in stored.items() if key in active})
            with self.protection.transaction() as (state, _):
                retired = [identity for identity, record in state['instances'].items() if not record['active']]
            for identity in retired:
                for name in ('identities/' + identity + '.json', 'history/' + identity + '.sqlite3'):
                    path = self.protection.file_path(name)
                    for suffix in ('', '-wal', '-shm'):
                        try:
                            path.with_name(path.name + suffix).unlink(missing_ok=True)
                        except PermissionError:
                            # 另一进程的 SQLite 连接可能尚未退出；登记已撤销，后续继续清理密文。
                            pass
            self.refresh_stamp = self._storage_stamp()
            self.refresh_check = time.monotonic() + 300

    def _identity(self, instance):
        with self.lock:
            identity, key = load_identity(self.configs.root, instance)
            binding = self.bindings.get(instance)
            if binding and binding['bindingKey'] != binding_key(identity, key):
                raise damaged('股票绑定与当前实例身份不匹配')
            self.identities[instance] = identity, key
            return identity, key

    def _instance_lock(self, instance):
        identity = self.protection.resolve(instance)
        with self.lock:
            return self.instance_locks.setdefault(identity, threading.RLock())

    def start(self):
        with self.lock:
            if (self.monitors or self.storage_error) and self.thread is None:
                self.thread = threading.Thread(target=self._run, name='stock-instance-relay', daemon=True)
                self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)
        # 正在网络超时中的守护线程退出后再关闭日志，避免竞态。
        if not self.thread or not self.thread.is_alive():
            self.history.close()

    def subscribe(self, listener):
        """仅推送本地实例状态，不再为交易页面保持远端行情连接。"""
        with self.lock:
            self.listeners.add(listener)
        def unsubscribe():
            with self.lock:
                self.listeners.discard(listener)
        return unsubscribe

    def _notify(self, data):
        with self.lock:
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(data)

    def _save(self):
        from module.config.transaction import config_transaction
        with config_transaction(self.path):
            stored = self.protection.read_file('stocks-v2.json') or {}
            active = self.protection.reconcile()
            stored = {identity: value for identity, value in stored.items() if identity in active}
            for name, value in self.bindings.items():
                identity, key = self._identity(name)
                if binding_key(identity, key) != value['bindingKey']:
                    raise damaged('不能保存不属于当前实例的股票数据')
                stored[identity] = value
            self.protection.write_file('stocks-v2.json', stored)
        self.names = {name: self.protection.resolve(name) for name in self.bindings}

    def _read_snapshot(self, instance):
        database = Path(self.configs.root) / 'config' / 'scheduler' / (instance + '.sqlite3')
        paths = [self.configs.path(instance), database, Path(str(database) + '-wal')]
        stamp = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths)
        with self.lock:
            if self.stamps.get(instance) == stamp and time.monotonic() < self.history.scanned.get(instance, 0):
                return self.records.get(instance)
        data, _ = self.configs.read(instance)
        record = None
        try:
            point = self.history.capture(instance, data, database)
            if point:
                record = {'instance': instance, 'actionPoints': point[1], 'observedAt': point[0] // 1000}
        except sqlite3.Error:
            raise ApiError('STOCK_HISTORY_UNAVAILABLE', '行动力历史暂不可读取，已停止同步，稍后重试') from None
        with self.lock:
            self.records[instance] = record
            self.stamps[instance] = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths)
        return record

    def _signed(self, instance, action, username='', points=None):
        identity, key = self._identity(instance)
        return make_instance_request(identity, key, action, username, points)

    def _remote(self, path, method='POST', body=None):
        headers = {'Content-Type': 'application/json'}
        payload = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        try:
            response = http.request(method, exchange_url() + '/api' + path, data=payload,
                                    headers=headers, timeout=12)
        except (http.RequestException, TimeoutError, OSError):
            raise ApiError('STOCK_UNAVAILABLE', '交易所暂不可连接，稍后自动重试') from None
        with response:
            raw = response.content
            try:
                data = json.loads(raw) if raw else None
            except (ValueError, TypeError):
                raise ApiError('STOCK_INVALID_RESPONSE', '交易所响应格式无效') from None
            return {'status': response.status_code, 'data': data}

    @staticmethod
    def _accepted(reply):
        if reply['status'] >= 400:
            error = (reply['data'] or {}).get('error', {})
            raise ApiError(error.get('code', 'STOCK_ERROR'), error.get('message', '交易所拒绝请求'))
        return reply['data']

    @account_operation
    def status(self, instance, refresh=False):
        self._refresh()
        self.configs.path(instance)
        identity, _ = self._identity(instance)
        binding = self.bindings.get(instance)
        now = time.monotonic()
        is_deleted = identity in self.retired or bool((binding or {}).get('deleted'))
        record = self.records.get(instance) if is_deleted else self._read_snapshot(instance)
        if not is_deleted and (refresh or now >= self.last_status.get(instance, 0)):
            try:
                reply = self._remote('/v2/instance/status', 'POST', self._signed(instance, 'status'))
                if reply['status'] == 404 and (reply.get('data') or {}).get('error', {}).get('code') == 'STOCK_NOT_REGISTERED':
                    self.remote_status[instance] = None
                else:
                    result = self._accepted(reply)
                    self._remember_stock(instance, result)
                self.last_status[instance] = now + 15
            except ApiError as error:
                if error.code == 'STOCK_DELETED':
                    self._mark_deleted(instance)
                self.statuses[instance] = str(error)
                if not binding and identity not in self.retired:
                    raise
        self.start()
        remote = self.remote_status.get(instance) or {}
        stock = remote.get('stock')
        binding = self.bindings.get(instance)
        is_deleted = identity in self.retired or bool((binding or {}).get('deleted'))
        return {'url': exchange_url(), 'instance': instance, 'instanceId': identity,
                'registered': not is_deleted and (bool(stock or binding) if instance not in self.remote_status else bool(stock)),
                'deleted': is_deleted, 'bound': not is_deleted and bool(stock and stock.get('bound')),
                'stock': stock, 'bindingCode': '' if is_deleted else remote.get('bindingCode', ''),
                'message': self.statuses.get(instance, '行动力增量同步已启用' if binding else '输入股票名称即可注册当前实例'),
                'lastObservedAt': record['observedAt'] if record else 0}

    def _mark_deleted(self, instance):
        """持久保存远端删除状态，退出监视；重启后不再重试原身份。"""
        identity, _ = self._identity(instance)
        retired = self.protection.read_file('stocks-retired-v2.json') or {}
        retired[identity] = True
        self.protection.write_file('stocks-retired-v2.json', retired)
        self.retired.add(identity)
        binding = self.bindings.get(instance)
        if binding:
            self.bindings[instance] = {**binding, 'deleted': True}
            self._save()
        self.remote_status[instance] = None
        self.monitors.discard(instance)
        self.history.pending.pop(instance, None)
        self.statuses[instance] = '股票已被管理员删除，已停止行动力上报；交易账户需重新绑定其他股票'
        self._notify({'instance': instance})

    def _remember_stock(self, instance, result):
        stock = result.get('stock') or {}
        if type(stock.get('id')) is not int or stock['id'] <= 0 or not isinstance(stock.get('name'), str):
            raise ApiError('STOCK_INVALID_RESPONSE', '交易所股票响应无效')
        identity, key = self._identity(instance)
        previous = self.bindings.get(instance)
        if previous and previous['url'] != exchange_url():
            raise ApiError('STOCK_ORIGIN_CHANGED', '实例股票接入地址已改变，请核实原登记')
        if previous and previous['stockId'] != stock['id']:
            raise ApiError('INSTANCE_MISMATCH', '远端股票与当前实例登记不一致')
        self.bindings[instance] = {'stockId': stock['id'], 'username': stock['name'],
                                   'bindingKey': binding_key(identity, key), 'url': exchange_url(),
                                   'capabilities': result.get('capabilities', [])}
        changed = previous != self.bindings[instance]
        self.remote_status[instance] = result
        self.monitors.add(instance)
        if changed:
            self._save()

    @account_operation
    def register(self, instance, username, notice_version=''):
        self._refresh()
        self.configs.path(instance)
        username = username.strip()
        if not 2 <= len(username) <= 32 or any(char in username for char in '\r\n\x00'):
            raise ApiError('INVALID_PARAMS', '股票名称须为 2 至 32 个字符')
        if (self.bindings.get(instance) or {}).get('deleted') or self.protection.resolve(instance) in self.retired:
            raise ApiError('STOCK_DELETED', '股票已被管理员删除，当前实例身份不可重新注册；请使用其他实例股票绑定交易账户')
        if not self.bindings.get(instance) and notice_version != 'stock-public-v2-20261101':
            raise ApiError('STOCK_NOTICE_REQUIRED', '注册前需确认行动力报价与交易数据公开及持续自动同步的告知')
        with self._instance_lock(instance):
            result = self._accepted(self._remote('/v2/instance/register', 'POST', self._signed(instance, 'register', username)))
            self._remember_stock(instance, result)
            self.last_status[instance] = time.monotonic() + 15
        self.start()
        self._notify({'instance': instance})
        return self.status(instance)

    @account_operation
    def rebuild(self, instance, confirm=False, scope='instance'):
        from module.api.stock_exchange_recovery import StockExchangeRecovery
        recovery = StockExchangeRecovery(self.configs, self._valid_binding, registry='stocks-v2.json')
        if confirm:
            self.history.close()
        result = recovery.rebuild(instance, confirm, scope)
        if result['rebuilt']:
            with self.lock:
                for name in result['affectedInstances']:
                    for state in (self.bindings, self.identities, self.names, self.stamps, self.records,
                                  self.statuses, self.remote_status, self.last_status, self.history.scanned,
                                  self.history.next_send, self.history.next_check, self.history.failures,
                                  self.history.pending, self.history.legacy_warnings):
                        state.pop(name, None)
                    self.monitors.discard(name)
                self.storage_error = None
                self.refresh_stamp = None
            self._refresh()
            self._notify({'instance': instance})
        return result

    @account_operation
    def sync_once(self, only=None, force=False):
        try:
            self._refresh()
        except ApiError as error:
            with self.lock:
                self.storage_error = error
                for name in self.monitors:
                    self.statuses[name] = str(error)
            if force:
                raise
            return
        with self.lock:
            instances = [only] if only else tuple(self.monitors)
        for instance in instances:
            if self.stop.is_set():
                return
            with self._instance_lock(instance):
                self._sync_history(instance, force)

    def _sync_history(self, instance, force):
        try:
            with self.lock:
                binding = self.bindings.get(instance)
            if not binding or binding.get('deleted') or self.protection.resolve(instance) in self.retired:
                return
            if binding['url'] != exchange_url():
                raise ApiError('STOCK_ORIGIN_CHANGED', '交易所地址与绑定地址不一致，已停止转发')
            if force or time.monotonic() >= self.last_status.get(instance, 0):
                status = self._accepted(self._remote('/v2/instance/status', 'POST', self._signed(instance, 'status')))
                self._remember_stock(instance, status)
                self.last_status[instance] = time.monotonic() + 15
            self._read_snapshot(instance)
            if force or time.monotonic() >= self.history.scanned.get(instance, 0):
                data, _ = self.configs.read(instance)
                database = Path(self.configs.root) / 'config' / 'scheduler' / (instance + '.sqlite3')
                self.history.capture(instance, data, database, force=True)
            if not force and not self.history.ready(instance):
                return
            identity, key = self._identity(instance)
            self.history.synchronize(instance, identity, key, binding, self._remote, self._accepted, force)
            while self.history.pending.get(instance) and not self.stop.is_set():
                self.history.synchronize(instance, identity, key, binding, self._remote, self._accepted, force)
            self.statuses[instance] = '行动力已同步；等待新记录'
            if self.history.legacy_warnings.get(instance):
                self.statuses[instance] += '；' + self.history.legacy_warnings[instance]
        except (ApiError, OSError, sqlite3.Error, ValueError, TypeError) as error:
            if isinstance(error, ApiError) and error.code == 'STOCK_DELETED':
                with self.lock:
                    self._mark_deleted(instance)
                return
            with self.lock:
                self.statuses[instance] = '行动力历史等待补传：' + str(error)
            if force:
                raise

    def _run(self):
        try:
            while not self.stop.wait(2):
                self.sync_once()
        finally:
            self.history.close()
