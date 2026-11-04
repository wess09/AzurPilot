"""实例持久身份与签名；只确认身份和请求完整性，不验证游戏数据真实性。"""
import base64
import hashlib
import json
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from module.api.protocol import ApiError
from module.runtime.game_data import GameDataProtector
from module.config.transaction import config_transaction


def load_identity(root, instance):
    protection = GameDataProtector(root)
    identity = protection.resolve(instance)
    with config_transaction(protection.file_path('identities/' + identity + '.json')):
        key = _load_key(protection, instance, identity)
    protection.relocate_scheduler(instance, identity)
    return identity, key


def _load_key(protection, instance, identity):
    """首次生成签名私钥也纳入文件事务，多个进程必须得到同一把私钥。"""
    name = 'identities/' + identity + '.json'
    data = protection.read_file(name)
    legacy = protection.record(identity)['legacy']
    path = protection.directory / 'identities' / (hashlib.sha256(instance.encode()).hexdigest() + '.json')
    if data is None and legacy:
        try:
            data = json.loads(path.read_bytes())
        except (OSError, ValueError):
            raise ApiError('STOCK_IDENTITY_DAMAGED', '旧实例交易身份损坏，请恢复完整备份') from None
    if data is None:
        key = Ed25519PrivateKey.generate()
        data = {'instanceId': identity, 'privateKey': base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()}
        protection.write_file(name, data)
    try:
        if str(uuid.UUID(data['instanceId'])) != identity:
            raise ValueError()
        key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(data['privateKey'], validate=True))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ApiError('STOCK_IDENTITY_DAMAGED', '实例交易身份损坏，请恢复身份备份，不能自动创建新身份') from None
    if legacy:
        if not protection.file_path(name).exists():
            protection.write_file(name, data)
        from module.runtime.account_vault import AccountVault
        AccountVault.wipe_file(path)
        with protection.transaction() as (state, _):
            state['instances'][identity]['legacy'] = False
    return key


def binding_key(instance_id, key):
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    return hashlib.sha256((public + '\n' + instance_id).encode()).hexdigest()


def make_instance_request(instance_id, key, action, username='', points=None, months=None):
    """v2 请求只验证实例持有私钥；行情点统一使用毫秒与整数行动力。"""
    import time
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    values = [{'t': int(t), 'p': int(total)} for t, total in (points or [])]
    result = {'instanceId': instance_id, 'publicKey': public, 'issuedAt': int(time.time())}
    if action == 'register':
        result['username'] = username
    if action == 'report':
        result['points'] = values
    packed = json.dumps(values, ensure_ascii=False, separators=(',', ':'))
    canonical = f"mmex-v2\n{action}\n{instance_id}\n{public}\n{result['issuedAt']}\n{username}\n{packed}\n"
    if action == 'reconcile':
        result['months'] = [{'month': row['month'], 'count': row['count'], 'digest': row['digest']} for row in (months or [])]
        canonical += json.dumps(result['months'], ensure_ascii=False, separators=(',', ':')) + '\n'
    result['signature'] = base64.b64encode(key.sign(canonical.encode())).decode()
    return result
