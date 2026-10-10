"""统计用例只允许向临时安装目录注入存储句柄。"""
import tempfile
from pathlib import Path
from module.statistics import opsi_secure


def install_store(case, folder):
    root = Path(folder).resolve()
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise RuntimeError('测试目录未隔离')
    (root / 'config').mkdir(exist_ok=True)
    from module.persistence.database import _directory
    token = _directory.set(root / 'config')
    case.addCleanup(_directory.reset, token)
    previous = opsi_secure._STORE
    store = opsi_secure.StatsStore(root)
    opsi_secure.set_store(store)
    case.addCleanup(opsi_secure.set_store, previous)
    return store
