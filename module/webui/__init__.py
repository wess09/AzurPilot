# 必须最先导入，初始化日志目录
from module.logger import logger
import deploy.logger

deploy.logger.logger = logger
