"""普通业务总库；导入本包不会创建文件或执行迁移。"""

from module.persistence.database import BusinessDatabase, get_database, initialize

__all__ = ['BusinessDatabase', 'get_database', 'initialize']
