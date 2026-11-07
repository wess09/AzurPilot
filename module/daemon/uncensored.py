"""游戏去和谐处理。

通过 ADB 推送 localization.txt 文件到模拟器，启用游戏内置的
本地化皮肤显示。从 Git 仓库拉取最新补丁资源并部署到设备。
"""

import shutil

from deploy.git import GitManager
from deploy.utils import *
from module.handler.login import LoginHandler
from module.logger import logger

localization_txt = """
Localization = true
Localization_skin = true
""".strip() + '\n'


class AzurLaneUncensored(LoginHandler):
    """游戏去和谐补丁部署器。"""

    def create_level1_uncensored(self):
        """创建一级去和谐 localization.txt 配置文件。"""
        logger.info('创建1级无删减')
        folder = './files'
        try:
            shutil.rmtree(folder)
        except FileNotFoundError:
            pass
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'localization.txt'), 'w', encoding='utf-8') as f:
            f.write(localization_txt)

    def run(self):
        """执行去和谐补丁更新与推送流程。

        1. 生成或更新去和谐补丁文件
        2. 通过 ADB push 推送文件到模拟器应用目录
        3. 重启游戏客户端以生效
        """
        if self.config.AzurLaneUncensored_Repository == 'https://gitee.com/LmeSzinc/AzurLaneUncensored':
            self.config.AzurLaneUncensored_Repository = 'https://e.coding.net/llop18870/alas/AzurLaneUncensored.git'

        repo = self.config.AzurLaneUncensored_Repository
        folder = './.venv/AzurLaneUncensored'

        logger.hr('更新 AzurLane无删减', level=1)
        logger.info('[守护-无删减] 首次使用需要较长时间')
        manager = GitManager()
        manager.config['GitExecutable'] = os.path.abspath(manager.config['GitExecutable'])
        manager.config['AdbExecutable'] = os.path.abspath(manager.config['AdbExecutable'])
        os.makedirs(folder, exist_ok=True)
        prev = os.getcwd()

        # 切换到补丁临时目录
        os.chdir(folder)
        self.create_level1_uncensored()
        # manager.git_repository_init(
        #     repo=repo,
        #     source='origin',
        #     branch='master',
        #     proxy=manager.config['GitProxy'],
        #     keep_changes=False
        # )

        logger.hr('推送无删减文件', level=1)
        logger.info('[守护-无删减] 推送需要几秒钟')
        command = ['push', 'files', f'/sdcard/Android/data/{self.device.package}']
        logger.info(f'[守护-无删减] 命令: {command}')
        self.device.adb_command(command, timeout=30)
        logger.info('[守护-无删减] 推送成功')

        # 返回项目根目录
        os.chdir(prev)
        logger.hr('重启碧蓝航线', level=1)
        self.config.override(Error_HandleError=True)
        self.device.app_stop()
        self.device.app_start()
        self.handle_app_login()

        logger.info('[守护-无删减] 完成')


if __name__ == '__main__':
    AzurLaneUncensored('alas', task='AzurLaneUncensored').run()
