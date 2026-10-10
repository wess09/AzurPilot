"""仓库统计快照：整次扫描原子提交，页面查询只读取已提交的数据。"""

from datetime import datetime
from pathlib import Path
from module.persistence.database import BusinessDatabase, for_legacy_path, get_database, register_instance

DATABASE = Path('./config/storage_statistics.db')


def _database(database):
    if isinstance(database, BusinessDatabase):
        return database
    return for_legacy_path(database, 'storage') if database is not None else get_database()


def _available(store):
    return store.path.exists() or store.marker.exists() or any(path.exists() for paths in store.legacy_sources.values() for path in paths) or (store.directory / 'storage_statistics.db').exists()


def save_snapshot(instance, server, items, *, started_at, pages, catalog_version, database=None):
    """原子保存完整清单；未知数量用 None，校验失败不写入新数据。"""
    if not instance or not server or not items or type(pages) is not int or pages < 1:
        raise ValueError('仓库快照缺少完整扫描信息')
    identifiers = set()
    for item in items:
        identifier = item.get('id')
        amount = item.get('amount')
        if not identifier or identifier in identifiers or not item.get('name') or not item.get('group'):
            raise ValueError('仓库物品标识缺失或重复')
        identifiers.add(identifier)
        if amount is not None and (type(amount) is not int or not 0 < amount <= 2 ** 63 - 1):
            raise ValueError('仓库数量未通过校验')
    store = _database(database)
    finished_at = datetime.now().isoformat(sep=' ', timespec='seconds')
    with store.transaction() as connection:
        register_instance(connection, instance)
        cursor = connection.execute('''INSERT INTO storage_scans
            (instance, server, started_at, finished_at, pages, catalog_version)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (instance, server, started_at, finished_at, pages, catalog_version))
        scan_id = cursor.lastrowid
        connection.executemany('''INSERT INTO storage_items
            (scan_id, item_id, name, item_group, amount) VALUES (?, ?, ?, ?, ?)''',
            [(scan_id, item['id'], item['name'], item['group'], item['amount']) for item in items])
    return scan_id


def latest_snapshot(instance, *, database=None):
    """只读查询最近完整快照；从未运行时不创建数据库。"""
    store = _database(database)
    if not _available(store):
        return None
    with store.transaction(write=False) as connection:
        scan = connection.execute('SELECT * FROM storage_scans WHERE instance=? ORDER BY id DESC LIMIT 1',
                                  (instance,)).fetchone()
        if scan is None:
            return None
        result = dict(scan)
        result['items'] = [dict(row) for row in connection.execute('''SELECT item_id AS id,
            name, item_group AS "group", amount FROM storage_items WHERE scan_id=? ORDER BY rowid''',
            (scan['id'],))]
        return result


def get_storage_timeline(instance, *, since=None, until=None, through_id=None, limit=50001, database=None):
    """只读成功扫描的历史，按完成时间排序；未发现的数量继续保留 None。"""
    store = _database(database)
    if not _available(store):
        return []
    with store.transaction(write=False) as connection:
        # 一条查询取得扫描和物品，避免并发提交时两次查询读到不同的扫描集合。
        records = connection.execute('''SELECT scans.id, scans.finished_at, scans.server,
                items.item_id, items.amount FROM (
            SELECT id, finished_at, server FROM storage_scans
                WHERE instance=? AND (? IS NULL OR finished_at>=?) AND (? IS NULL OR finished_at<=?)
                    AND (? IS NULL OR id<=?)
                ORDER BY finished_at DESC, id DESC LIMIT ?
            ) AS scans LEFT JOIN storage_items AS items ON items.scan_id=scans.id
            ORDER BY scans.finished_at, scans.id''', (instance, since, since, until, until, through_id, through_id, limit))
        rows = {}
        for record in records:
            row = rows.setdefault(record['id'], {'ts': record['finished_at'],
                                  'source': f"仓库统计（{record['server']}）"})
            if record['item_id'] is not None:
                row[record['item_id']] = record['amount']
        return list(rows.values())
