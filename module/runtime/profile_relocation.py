"""可恢复的实例重命名：协调普通调度总库、受保护历史文件与身份登记。

迁移阶段保存在已加密且经过认证的 registry 中。遇到不匹配的目标文件时
一律停止，不用路径存在性推测身份，也不覆盖来源以外的数据。
"""
import hashlib
import os
import sqlite3
import uuid
from contextlib import closing

from module.config.transaction import config_transaction
from module.runtime.game_data import damaged
from module.scheduler.store import ConflictError, ProgramStore


def _digest(path):
    """流式计算历史数据库的 SHA-256，避免一次性加载大型文件。"""
    result = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _snapshot(source, temporary):
    """用 SQLite 备份 API 取得含已提交 WAL 的一致历史副本。"""
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as incoming, \
            closing(sqlite3.connect(temporary)) as outgoing:
        incoming.backup(outgoing)
    return _digest(temporary)


def _discard_source(source):
    """只有目标已通过指纹验证后才清除旧历史及其旁路文件。"""
    for suffix in ('', '-wal', '-shm'):
        source.with_name(source.name + suffix).unlink(missing_ok=True)


def _history_copy(protector, identity, source, target, journal):
    """按已登记的摘要续跑文件迁移，检测双文件与被更换的目标。"""
    expected = journal.get('digest')
    if target.exists():
        if not expected or _digest(target) != expected:
            raise damaged('实例重命名目标历史与迁移登记不符，已保留两边原件')
        if source.exists():
            temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.verify')
            protector._safe(temporary)
            try:
                if _snapshot(source, temporary) != expected:
                    raise damaged('重命名期间旧历史已发生变化，不能自动删除，请恢复备份后处理')
            finally:
                temporary.unlink(missing_ok=True)
            _discard_source(source)
        return

    if not source.exists():
        if journal['history']:
            raise damaged('实例重命名历史源与目标均丢失，请从完整备份恢复')
        return
    if not journal['history']:
        raise damaged('迁移过程中出现未登记的旧历史文件，已停止并保留原件')

    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.relocating')
    protector._safe(temporary)
    verifier = target.with_name(target.name + '.' + uuid.uuid4().hex + '.verify')
    protector._safe(verifier)
    try:
        checksum = _snapshot(source, temporary)
        # SQLite 的正常只读连接可能触发 WAL 检查点或清理旁路文件；
        # 主文件/WAL 的原始字节因此不稳定。比较两份逻辑一致的 SQLite 快照。
        if _snapshot(source, verifier) != checksum:
            raise damaged('旧历史在快照期间发生变化，请停止旧写入进程后重试')
        # 再次验证必须使用全新目标库；复用 SQLite 连接目标会改变文件头计数器。
        verifier.unlink(missing_ok=True)
        # 将复制文件的摘要先持久化，再发布目标文件；重启后可识别重复副本。
        with protector.transaction() as (data, _):
            active = data['instances'][identity]['relocation']
            if active['source'] != journal['source'] or active['target'] != journal['target']:
                raise damaged('实例迁移登记在执行过程中发生改变')
            active['digest'] = checksum
        os.replace(temporary, target)
        if _snapshot(source, verifier) != checksum:
            raise damaged('旧历史在发布后发生变化，已保留原件，请人工核对')
        _discard_source(source)
    finally:
        temporary.unlink(missing_ok=True)
        verifier.unlink(missing_ok=True)


def relocate_profile(protector, identity, source_name, target_name):
    """逐阶段迁移实例；成功后才原子更新加密的身份登记。"""
    directory = protector.root / 'config' / 'scheduler'
    source = directory / (source_name + '.sqlite3')
    target = directory / (target_name + '.sqlite3')
    guard = protector.directory / ('relocation-' + identity + '.json')
    for path in (source, target, guard):
        protector._safe(path)

    store = ProgramStore(protector.root / 'config')
    store.database.ensure_ready()
    # 每个身份只有一个可进行中的迁移；加密登记不是可被任意覆盖的本地标记。
    with config_transaction(guard):
        with protector.transaction() as (data, _):
            record = data['instances'].get(identity)
            if not record or not record['active'] or record['name'] != target_name:
                raise damaged('实例身份或重命名目标已改变，拒绝迁移')
            if record['schedulerName'] != source_name:
                raise damaged('实例调度来源已改变，拒绝迁移')
            journal = record.get('relocation')
            if journal is None:
                with store.database.transaction(write=False) as db:
                    if store._has_state(db, target_name):
                        raise damaged('实例重命名目标已有调度数据，已保留原件')
                    ordinary = store._has_state(db, source_name)
                if target.exists():
                    raise damaged('实例重命名目标已有历史文件，已保留两边原件')
                journal = {'source': source_name, 'target': target_name,
                           'ordinary': ordinary, 'history': source.exists(), 'digest': None}
                record['relocation'] = journal
            elif (not isinstance(journal, dict)
                  or journal.get('source') != source_name or journal.get('target') != target_name
                  or type(journal.get('ordinary')) is not bool
                  or type(journal.get('history')) is not bool
                  or (journal.get('digest') is not None
                      and (not isinstance(journal['digest'], str) or len(journal['digest']) != 64))):
                raise damaged('实例重命名阶段记录无效，请保留原件')

        with config_transaction(source), config_transaction(target):
            with store.database.transaction(write=False) as db:
                old_state = store._has_state(db, source_name)
                new_state = store._has_state(db, target_name)
            if journal['ordinary']:
                if old_state and new_state or not old_state and not new_state:
                    raise damaged('实例重命名调度数据状态不一致，已停止迁移')
                if old_state:
                    try:
                        store.relocate(source_name, target_name)
                    except ConflictError:
                        raise damaged('实例重命名后调度数据冲突，已保留原件') from None
            elif old_state or new_state:
                raise damaged('检测到未登记的调度数据，不能自动接管目标实例')
            _history_copy(protector, identity, source, target, journal)

        with protector.transaction() as (data, _):
            record = data['instances'][identity]
            active = record.get('relocation')
            if (record['schedulerName'] != source_name or not isinstance(active, dict)
                    or active.get('source') != source_name or active.get('target') != target_name):
                raise damaged('实例迁移完成前身份登记已发生变化')
            record['schedulerName'] = target_name
            record.pop('relocation', None)
