import threading
import io
import json
import os
import time
from datetime import datetime

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
import numpy as np

from module.base.utils import save_image
from module.base.api_client import ApiClient
from module.config.config import AzurLaneConfig
from module.config.deep import deep_get
from module.exception import ScriptError
from module.logger import logger
from module.statistics.utils import pack
from AzurStats.azurstats import AzurStatsOpsi


class DropImage:
    def __init__(self, stat, genre, save, upload, info=''):
        """
        Args:
            stat (AzurStats):
            genre:
            save:
            upload:
        """
        self.stat = stat
        self.genre = str(genre)
        self.save = bool(save)
        self.upload = bool(upload)
        self.info = info
        self.images = []
        self.combat_count = 0

    def add(self, image):
        """
        Args:
            image (np.ndarray):
        """
        if self:
            self.images.append(image)
            logger.info(
                f'Drop record added, genre={self.genre}, amount={self.count}')

    def set_combat_count(self, count):
        self.combat_count = count

    def handle_add(self, main, before=None):
        """
        Handle wait before and after adding screenshot.

        Args:
            main (ModuleBase):
            before (int, float, tuple): Sleep before adding.
        """
        if before is None:
            before = main.config.WAIT_BEFORE_SAVING_SCREEN_SHOT

        if self:
            main.handle_info_bar()
            main.device.sleep(before)
            main.device.screenshot()
            self.add(main.device.image)

    def clear(self):
        self.images = []

    @property
    def count(self):
        return len(self.images)

    def __bool__(self):
        # Uncomment these if stats service re-run in the future
        # return self.save or self.upload

        return self.save

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self:
            logger.info('[Azurstat] 停止记录截图并提交')
            self.stat.commit(images=self.images, genre=self.genre,
                             save=self.save, upload=self.upload, info=self.info,
                             combat_count=self.combat_count)


class AzurStats:
    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig):
        """
        self.config = config

    @property
    def _user_agent(self):
        return f'Alas ({str(self.config.DropRecord_AzurStatsID)})'
    
    meowofficer_farming_labels = ['侵蚀等级', '上次记录时间', '有效战斗轮数', '平均黄币/轮', '平均金菜/轮', '平均深渊/轮', '平均隐秘/轮']
    meowofficer_farming_map = [
        'OperationCoin',
        'Plate',
        'CoordinateAbyssal',
        'CoordinateObscure'
    ]
    
    @staticmethod
    def load_meowofficer_farming():
        """
        Returns:
            np.ndarray: Stats.
        """
        try:
            data = np.loadtxt('./log/azurstat_meowofficer_farming.csv', delimiter=',', dtype=float, skiprows=1, encoding='utf-8')
            if data.shape[0] != 6:
                raise IndexError
        except Exception:
            data = np.zeros((6, len(AzurStats.meowofficer_farming_labels)))
            data[:, 0] = np.arange(1, 7)
            header = ','.join(AzurStats.meowofficer_farming_labels)
            np.savetxt('./log/azurstat_meowofficer_farming.csv', data, delimiter=',', header=header, comments='', fmt='%f', encoding='utf-8')
            data = np.loadtxt('./log/azurstat_meowofficer_farming.csv', delimiter=',', dtype=float, skiprows=1, encoding='utf-8')
        finally:
            return data
    
    def _save_meowofficer_farming(self, filename, items, hazard_level, delta_combat_count):
        all_data = self.load_meowofficer_farming()

        # Get view of the specific row
        row = all_data[hazard_level - 1]
        combat_count = int(row[2])
        data = row[3:]  # View of the stats part

        new_combat_count = combat_count + delta_combat_count

        if new_combat_count <= 0:
            return

        # Convert average to total
        data[:] = np.round(data * combat_count)

        # Add new items
        for item in items:
            for i, template in enumerate(AzurStats.meowofficer_farming_map):
                if item['item'].startswith(template):
                    data[i] += item['amount']

        # Convert total to new average
        data /= new_combat_count

        # Update metadata
        row[1] = int(datetime.now().timestamp())
        row[2] = new_combat_count

        logger.info(f'[Azurstat] [{filename}] 更新行数据: {row}')

        try:
            header = ','.join(AzurStats.meowofficer_farming_labels)
            np.savetxt('./log/azurstat_meowofficer_farming.csv', all_data, delimiter=',', header=header, comments='', fmt='%f', encoding='utf-8')
            logger.info(f'[Azurstat] [{filename}] 成功保存数据')
        except Exception as e:
            logger.error(f'Failed to save meowofficer farming data: {e}')

    def _upload(self, image, genre, filename, combat_count):
        """
        Args:
            image: Image to upload.
            genre (str):
            filename (str): 'xxx.png'

        Returns:
            bool: If success
        """
        allowed_genre = ['opsi_hazard1_leveling', 'opsi_meowfficer_farming']
        unit_combat_count = {
            1: 2,
            2: 2,
            3: 2,
            4: 3,
            5: 3,
            6: 3
        }
        limits = {
            'OperationCoin': 20000,
            'Coins': 500,
        }

        if genre not in allowed_genre:
            return False

        results = AzurStatsOpsi(image)
        record = results.DataParseRecords[0]
        if record.error or record.scene != 'OpsiItems':
            logger.info(f'[Azurstat] [{filename}] 该截图不包含有效信息')
            return False
        
        item = results.DataOpsiItems[0]

        logger.info(f'[Azurstat] [{filename}] 记录的战斗数: {combat_count}')
        if combat_count % unit_combat_count[item.hazard_level]:
            logger.info(f'[Azurstat] [{filename}] 此轮战斗不完整，忽略')
            return False
        
        combat_count //= unit_combat_count[item.hazard_level]
        
        items = [
            {
                'item': d.item,
                'amount': d.amount,
                'is_meow': d.tag == 'meow'
            } for d in results.DataOpsiItems
        ]
        
        for item in items:
            limit = limits.get(item['item'], 100)
            if item['amount'] > limit:
                logger.info(f'[Azurstat] [{filename}] 数据异常')
                return False
                

        logger.info(f'[Azurstat] [{filename}] items: {items}')
        
        if genre == 'opsi_meowfficer_farming':
            self._save_meowofficer_farming(filename, items, item.hazard_level, combat_count)

        body = {
            'zone': item.zone,
            'zone_type': item.zone_type,
            'zone_id': item.zone_id,
            'hazard_level': item.hazard_level,
            'combat_count': combat_count,
            'items': items
        }

        ApiClient.submit_azurstat(genre, body)
        return True

    def _save(self, image, genre, filename):
        """
        Args:
            image: Image to save.
            genre (str): Name of sub folder.
            filename (str): 'xxx.png'

        Returns:
            bool: If success
        """
        try:
            folder = os.path.join(
                str(self.config.DropRecord_SaveFolder), genre)
            os.makedirs(folder, exist_ok=True)
            file = os.path.join(folder, filename)
            save_image(image, file)
            logger.info(f'Image save success, file: {file}')
            return True
        except Exception as e:
            logger.exception(e)

        return False

    def commit(self, images, genre, save=False, upload=False, info='', combat_count=-1):
        """
        Args:
            images (list): List of images in numpy array.
            genre (str):
            save (bool): If save image to local file system.
            upload (bool): If upload image to Azur Stats.
            info (str): Extra info append to filename.
            combat_count (int): Combat count.


        Returns:
            bool: If commit.
        """
        if len(images) == 0:
            return False

        save, upload = bool(save), bool(upload)
        logger.info(
            f'Drop record commit, genre={genre}, amount={len(images)}, save={save}, upload={upload}')
        image = pack(images)
        now = int(time.time() * 1000)

        if info:
            filename = f'{now}_{info}.png'
        else:
            filename = f'{now}.png'

        if save:
            save_thread = threading.Thread(
                target=self._save, args=(image, genre, filename))
            save_thread.start()

        if upload:
            upload_thread = threading.Thread(
                target=self._upload, args=(image, genre, filename, combat_count))
            upload_thread.start()

        return True

    def new(self, genre, method='do_not', info=''):
        """
        Args:
            genre (str):
            method (str): The method about save and upload image.
            info (str): Extra info append to filename.

        Returns:
            DropImage:
        """
        logger.info('[Azurstat] 开始记录截图')
        save = 'save' in method
        upload = 'upload' in method
        return DropImage(stat=self, genre=genre, save=save, upload=upload, info=info)
