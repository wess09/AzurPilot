"""数据备份与归档模块。

提供数据库和用户配置的每日自动备份、压缩存档与历史备份过期清理功能。
"""

from module.base.runtime_params import BACKUP_KEEP_DAYS
import json
import shutil

from datetime import datetime, timedelta
from pathlib import Path

from module.logger import logger


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / 'config'
BACKUP_ROOT = ROOT_DIR / 'AzurPilot_Data_Backup'


DATABASE_FILES = ('azurpilot.db',)


def configuration_directory():
    """使用运行入口选择的实际目录，同时保留测试显式目录注入。"""
    from module.persistence.database import DEFAULT_DIRECTORY, get_database
    return get_database().directory if CONFIG_DIR.absolute() == DEFAULT_DIRECTORY else CONFIG_DIR.absolute()


def backup(enable=True, keep_days=BACKUP_KEEP_DAYS):
    """按现有开关和保留天数备份，全部完成后发布当日目录。"""
    if not enable:
        logger.info('每日备份已关闭，跳过备份')
        return
    date = datetime.now().strftime('%Y-%m-%d')
    backup_dir = BACKUP_ROOT / date
    if backup_dir.exists():
        logger.info(f'今日备份已存在，跳过备份：{backup_dir}')
        return
    from uuid import uuid4
    temporary = BACKUP_ROOT / ('.' + date + '-' + uuid4().hex)
    temporary.mkdir(parents=True)
    try:
        files = backup_database(temporary) + backup_config(temporary)
        create_backup_info(temporary, files)
        temporary.rename(backup_dir)
    except BaseException:
        # 只清理本次在备份根目录中创建的临时目录。
        if temporary.resolve().parent == BACKUP_ROOT.resolve():
            shutil.rmtree(temporary)
        raise
    clean_backup(keep_days=keep_days)
    logger.info(f'每日备份完成，共备份 {len(files)} 个文件')


def backup_database(backup_dir):
    """通过 SQLite 备份接口保存已提交 WAL，包括全部普通业务表。"""
    from module.persistence.database import get_database
    database = get_database(configuration_directory())
    target = backup_dir / 'azurpilot.db'
    database.backup(target)
    marker = backup_dir / 'azurpilot.migrated'
    shutil.copy2(database.marker, marker)
    return [{'name': path.name, 'size': path.stat().st_size} for path in (target, marker)]


def backup_config(backup_dir):
    """锁定安全存储后取得一致快照；外部安全密钥不自动导出。"""
    from contextlib import ExitStack
    from module.config.transaction import config_transaction
    from module.runtime.account_vault import OPERATIONS
    from module.persistence.migration import snapshot_database
    files = []
    config_dir = configuration_directory()
    candidates = set(config_dir.glob('*.json')) | set(config_dir.glob('*/config.db'))
    candidates.update(config_dir.glob('*/account.destroyed'))
    if (config_dir / 'deploy.yaml').exists():
        candidates.add(config_dir / 'deploy.yaml')
    candidates.update((config_dir / 'scheduler').glob('*.sqlite3'))
    for folder in ('stock-exchange', 'opsi_secure'):
        candidates.update(path for path in (config_dir / folder).rglob('*') if path.is_file())
    candidates = sorted((path for path in candidates if not path.name.startswith('template')
                         and not path.name.endswith(('.lock', '-wal', '-shm', '-journal'))), key=str)
    with OPERATIONS, ExitStack() as locks:
        # 与行动力采集保持安全库、注册目录、注册状态的锁顺序。
        for path in candidates:
            if path.suffix in ('.sqlite3', '.db'):
                locks.enter_context(config_transaction(path))
        for path in (config_dir / 'stock-exchange', config_dir / 'stock-exchange' / 'registry.json'):
            locks.enter_context(config_transaction(path))
        for path in candidates:
            if path.suffix not in ('.sqlite3', '.db') and not path.is_relative_to(config_dir / 'stock-exchange'):
                locks.enter_context(config_transaction(path))
        for path in candidates:
            if path.is_symlink() or not path.resolve().is_relative_to(config_dir.resolve()):
                raise ValueError('备份源不能越出配置目录')
            relative = path.relative_to(config_dir)
            target = backup_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in ('.sqlite3', '.db'):
                snapshot_database(path.absolute(), target)
            else:
                shutil.copy2(path, target)
            files.append({'name': str(relative), 'size': target.stat().st_size})
    return files


def sqlite_backup(source, target):
    """只读备份 SQLite；不会创建或改写源文件。"""
    from module.persistence.migration import snapshot_database
    snapshot_database(Path(source).absolute(), Path(target))


def create_backup_info(backup_dir, files):
    """创建备份信息元数据文件。

    Args:
        backup_dir (Path): 备份目录路径。
        files (list): 已备份文件信息列表。
    """
    info = {
        'backup_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'file_count': len(files),
        'files': files,
    }

    with open(backup_dir / 'backup_info.json', 'w', encoding='utf-8') as f:
        json.dump(
            info,
            f,
            indent=4,
            ensure_ascii=False,
        )


def clean_backup(keep_days=BACKUP_KEEP_DAYS):
    """清理超过保留天数的历史备份目录。

    Args:
        keep_days (int): 历史备份保留天数。小于 1 时按 1 天处理，
            避免把「只保留今天」误配成清空全部备份。
    """
    if not BACKUP_ROOT.exists():
        return

    keep_days = max(int(keep_days), 1)
    expire_date = datetime.now().date() - timedelta(days=keep_days)

    for folder in BACKUP_ROOT.iterdir():
        if not folder.is_dir():
            continue

        try:
            folder_date = datetime.strptime(folder.name, '%Y-%m-%d').date()
        except ValueError:
            continue

        if folder_date >= expire_date:
            continue

        try:
            if folder.is_symlink() or folder.resolve().parent != BACKUP_ROOT.resolve():
                raise ValueError('备份清理目标越界')
            shutil.rmtree(folder)
            logger.info(f'已删除过期备份：{folder.name}')
        except Exception as e:
            logger.warning(f'删除过期备份失败：{folder.name}，{e}')
