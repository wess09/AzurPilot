import csv
import shutil

from tqdm import tqdm

from module.base.decorator import cached_property
from module.base.utils import load_image
from module.logger import logger
from module.ocr.al_ocr import AlOcr
from module.ocr.ocr import Ocr
from module.statistics.battle_status import BattleStatusStatistics
from module.statistics.campaign_bonus import CampaignBonusStatistics
from module.statistics.get_items import GetItemsStatistics
from module.statistics.utils import *


class DropStatistics:
    DROP_FOLDER = './screenshots'
    TEMPLATE_FOLDER = 'item_templates'
    TEMPLATE_BASIC = './assets/stats_basic'
    CNOCR_CONTEXT = 'cpu'
    CSV_FILE = 'drop_result.csv'
    CSV_OVERWRITE = True
    CSV_ENCODING = 'utf-8'

    def __init__(self):
        AlOcr.CNOCR_CONTEXT = DropStatistics.CNOCR_CONTEXT
        Ocr.SHOW_LOG = False
        if not os.path.exists(self.template_folder):
            shutil.copytree(DropStatistics.TEMPLATE_BASIC, self.template_folder)

        self.battle_status = BattleStatusStatistics()
        self.get_items = GetItemsStatistics()
        self.campaign_bonus = CampaignBonusStatistics()
        self.get_items.load_template_folder(self.template_folder)

    @property
    def template_folder(self):
        return os.path.join(DropStatistics.DROP_FOLDER, DropStatistics.TEMPLATE_FOLDER)

    @property
    def csv_file(self):
        return os.path.join(DropStatistics.DROP_FOLDER, DropStatistics.CSV_FILE)

    @staticmethod
    def drop_folder(campaign):
        return os.path.join(DropStatistics.DROP_FOLDER, campaign)

    @cached_property
    def csv_overwrite_check(self):
        """移除已存在的 CSV 文件，此方法仅执行一次。"""
        if DropStatistics.CSV_OVERWRITE:
            if os.path.exists(self.csv_file):
                logger.info(f'Remove existing csv file: {self.csv_file}')
                os.remove(self.csv_file)
        return True

    def parse_template(self, file):
        """从单个文件中提取模板，新模板会分配自增 ID。"""
        images = unpack(load_image(file))
        for image in images:
            if self.get_items.appear_on(image):
                self.get_items.extract_template(image, folder=self.template_folder)
            if self.campaign_bonus.appear_on(image):
                self.campaign_bonus.extract_template(image, folder=self.template_folder)

    def parse_drop(self, file):
        """解析单个截图文件，提取掉落数据。

        Args:
            file (str): 截图文件路径。

        Yields:
            list: 每行为 [时间戳, 关卡, 敌人名称, 掉落类型, 物品名, 数量]。
        """
        ts = os.path.splitext(os.path.basename(file))[0]
        campaign = os.path.basename(os.path.abspath(os.path.join(file, '../')))
        images = unpack(load_image(file))
        enemy_name = 'unknown'
        for image in images:
            if self.battle_status.appear_on(image):
                enemy_name = self.battle_status.stats_battle_status(image)
            if self.get_items.appear_on(image):
                for item in self.get_items.stats_get_items(image):
                    yield [ts, campaign, enemy_name, 'GET_ITEMS', item.name, item.amount]
            if self.campaign_bonus.appear_on(image):
                for item in self.campaign_bonus.stats_get_items(image):
                    yield [ts, campaign, enemy_name, 'CAMPAIGN_BONUS', item.name, item.amount]

    def extract_template(self, campaign):
        """从指定关卡文件夹中提取模板图像。

        Args:
            campaign (str): 关卡名称。
        """
        print('')
        logger.hr(f'Extract templates from {campaign}', level=1)
        for ts, file in tqdm(load_folder(self.drop_folder(campaign)).items()):
            try:
                self.parse_template(file)
            except ImageError as e:
                logger.warning(e)
                continue
            except Exception as e:
                logger.exception(e)
                logger.warning(f'Error on image {ts}')
                continue

    def extract_drop(self, campaign):
        """从指定关卡文件夹中解析掉落数据并写入 CSV。

        Args:
            campaign (str): 关卡名称。
        """
        print('')
        logger.hr(f'extract drops from {campaign}', level=1)
        _ = self.csv_overwrite_check

        with open(self.csv_file, 'a', newline='', encoding=DropStatistics.CSV_ENCODING) as csv_file:
            writer = csv.writer(csv_file)
            for ts, file in tqdm(load_folder(self.drop_folder(campaign)).items()):
                try:
                    rows = list(self.parse_drop(file))
                    writer.writerows(rows)
                except ImageError as e:
                    logger.warning(e)
                    continue
                except Exception as e:
                    logger.exception(e)
                    logger.warning(f'Error on image {ts}')
                    continue


if __name__ == '__main__':
    # 掉落截图文件夹，默认为 './screenshots'
    DropStatistics.DROP_FOLDER = './screenshots'
    # 模板文件夹，用于加载和保存模板
    # 路径为 {DROP_FOLDER}/{TEMPLATE_FOLDER}
    # 若文件夹不存在，会自动从 './assets/stats_basic' 复制
    DropStatistics.TEMPLATE_FOLDER = 'campaign_13_1_template'
    # 'cpu' 或 'gpu'，默认 'cpu'
    # 使用 'gpu' 可加速预测，但需安装 GPU 版本的 mxnet
    DropStatistics.CNOCR_CONTEXT = 'cpu'
    # 输出 CSV 文件名
    # 路径为 {DROP_FOLDER}/{CSV_FILE}
    DropStatistics.CSV_FILE = 'drop_results.csv'
    # 为 True 时，提取前删除已有文件
    DropStatistics.CSV_OVERWRITE = True
    # 通常为 'utf-8'
    # 导出到 Excel 中文乱码时使用 'gbk'
    DropStatistics.CSV_ENCODING = 'gbk'
    # DROP_FOLDER 下要导出的关卡名称列表
    # 路径为 {DROP_FOLDER}/{CAMPAIGN}
    # 以下仅为示例，请根据实际情况修改
    CAMPAIGNS = ['campaign_13_1']

    stat = DropStatistics()

    """
    步骤 1：
        取消注释以下代码并运行，运行后重新注释。
    """
    # for i in CAMPAIGNS:
    #     stat.extract_template(i)

    """
    步骤 2：
        前往 {DROP_FOLDER}/{TEMPLATE_FOLDER}
        手动重命名你感兴趣的模板文件。
    """
    pass

    """
    步骤 3：
        取消注释以下代码并运行，运行后重新注释。
        结果保存在 {DROP_FOLDER}/{CSV_FILE} 中。
    """
    for i in CAMPAIGNS:
        stat.extract_drop(i)
