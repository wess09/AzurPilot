"""普通总库的离线迁移、检查、备份和实例数据导入导出。"""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from module.persistence.database import VERSION, get_database, initialize, register_instance
from module.persistence.snapshots import read_month, read_ship, save_month, save_ship
from module.scheduler.store import ProgramStore


def check(database):
    """只读检查正式库，不根据旧源创建数据库。"""
    with closing(sqlite3.connect(database.path.as_uri() + '?mode=ro', uri=True)) as connection:
        if connection.execute('PRAGMA user_version').fetchone()[0] != VERSION:
            raise ValueError('总库版本不受支持')
        if not connection.execute('SELECT 1 FROM storage_migrations WHERE version=?', (VERSION,)).fetchone():
            raise ValueError('总库缺少迁移完成记录')
        if connection.execute('SELECT MAX(version) FROM storage_migrations').fetchone()[0] != VERSION:
            raise ValueError('总库迁移版本与 user_version 不一致')
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('总库完整性检查失败')
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('总库外键检查失败')
        tables = connection.execute("SELECT name,strict FROM pragma_table_list WHERE schema='main' AND type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        if len(tables) != 56 or any(strict != 1 for _, strict in tables):
            raise ValueError('总库表结构与 v1 不符')
        return {name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name, _ in tables}


def export_statistics(database, instance, target):
    """显式导出统计快照；缺失整份舰船记录用 None 表示。"""
    with database.transaction(write=False) as connection:
        months = {row[0]: read_month(connection, instance, row[0]) for row in connection.execute(
            'SELECT month FROM cl1_months WHERE instance=? ORDER BY month', (instance,))}
        data = dict(version=VERSION, instance=instance, months=months, ship_exp=read_ship(connection, instance))
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError('导出目标已存在')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=True)
            file.flush()
            os.fsync(file.fileno())
        if target.exists():
            raise FileExistsError('导出目标已存在')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def import_statistics(database, instance, source):
    """一个事务补入显式导出文件，不覆盖目标已有月份或舰船记录。"""
    data = json.loads(Path(source).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'version', 'instance', 'months', 'ship_exp'}:
        raise ValueError('统计导入格式无效')
    if data['version'] != VERSION or data['instance'] != instance or not isinstance(data['months'], dict):
        raise ValueError('统计版本或实例不匹配')
    if any(not isinstance(snapshot, dict) for snapshot in data['months'].values()) or (data['ship_exp'] is not None and not isinstance(data['ship_exp'], dict)):
        raise ValueError('统计快照必须是对象')
    with database.transaction() as connection:
        register_instance(connection, instance)
        for month, snapshot in data['months'].items():
            if read_month(connection, instance, month) is not None:
                raise FileExistsError('目标月份已存在，导入已回滚')
            save_month(connection, instance, month, snapshot)
        if data['ship_exp'] is not None:
            if read_ship(connection, instance) is not None:
                raise FileExistsError('目标舰船记录已存在，导入已回滚')
            save_ship(connection, instance, data['ship_exp'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, help='实际配置目录；默认使用当前安装配置目录')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate', help='停止旧 worker 后执行首次迁移；保留原件和恢复备份')
    commands.add_parser('check', help='只读检查正式库的版本、表结构、完整性和外键')
    backup = commands.add_parser('backup', help='导出包含已提交 WAL 的普通总库快照')
    backup.add_argument('--output', type=Path, required=True)
    for name, description in (
        ('export-instance', '导出单实例调度切片，包含运行状态和观察值'),
        ('restore-instance', '恢复同名调度切片，拒绝覆盖已有调度数据'),
        ('export-statistics', '显式导出单实例月度和舰船快照为 JSON'),
        ('import-statistics', '补入显式导出的统计快照，拒绝覆盖已有记录'),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument('--instance', required=True)
        command.add_argument('--output' if name.startswith('export') else '--input', type=Path, required=True)
    args = parser.parse_args(argv)
    database = get_database(args.config_dir)
    if args.command == 'check':
        print(json.dumps(check(database), ensure_ascii=False, indent=2, sort_keys=True))
        return
    database = initialize(database.directory)
    if args.command == 'migrate':
        check(database)
    elif args.command == 'backup':
        if args.output.exists():
            raise FileExistsError('备份目标已存在')
        database.backup(args.output)
    elif args.command == 'export-instance':
        if args.output.exists():
            raise FileExistsError('导出目标已存在')
        ProgramStore(store=database).backup(args.instance, args.output)
    elif args.command == 'restore-instance':
        ProgramStore(store=database).restore(args.instance, args.input)
    elif args.command == 'export-statistics':
        export_statistics(database, args.instance, args.output)
    elif args.command == 'import-statistics':
        import_statistics(database, args.instance, args.input)
    print('已完成：' + args.command)


if __name__ == '__main__':
    main()
