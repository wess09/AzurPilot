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
from module.config.config import AzurLaneConfig
from module.config.deep import deep_get
from module.exception import ScriptError
from module.logger import logger
from module.statistics.utils import pack
from module.base.device_id import get_device_id


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
        return self.save or self.upload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self:
            self.stat.commit(images=self.images, genre=self.genre,
                             save=self.save, upload=self.upload, info=self.info, combat_count=self.combat_count)


class AzurStats:
    TIMEOUT = 20

    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig):
        """
        self.config = config

    meowofficer_farming_labels = ['侵蚀等级', '上次记录时间', '有效战斗轮数', '平均黄币/轮', '平均金菜/轮', '平均深渊/轮', '平均隐秘/轮']
    meowofficer_farming_map = [
        'OperationCoin',
        'Plate',
        'CoordinateAbyssal',
        'CoordinateObscure'
    ]
    unit_combat_count = {
        1: 2,
        2: 2,
        3: 2,
        4: 3,
        5: 3,
        6: 3
    }

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
        
    @staticmethod
    def get_meowofficer_farming():
        session = requests.Session()
        session.trust_env = False
        session.mount('http://', HTTPAdapter(max_retries=5))
        session.mount('https://', HTTPAdapter(max_retries=5))
        
        device_id = get_device_id()
        base_url = f'https://alas-statsapi.nanoda.work/api/data/opsi_items?device_id={device_id}&genre=opsi_meowfficer_farming'
        
        all_data = []
        limit = 1000
        offset = 0
        
        while True:
            try:
                resp = session.get(f'{base_url}&limit={limit}&offset={offset}', timeout=AzurStats.TIMEOUT)
                resp.raise_for_status()
                result = resp.json()
                data = result.get('data', [])
                all_data.extend(data)
                
                if len(data) < limit:
                    break
                offset += limit
            except Exception as e:
                logger.warning(f'拉取数据失败, {e}')
                return

        stats = {h: {'combat_count': 0, 'items': {k: 0 for k in AzurStats.meowofficer_farming_map}} for h in range(1, 7)}
        img_combat_counts = {}
        
        for row in all_data:
            imgid = row.get('imgid')
            h_level = row.get('hazard_level')
            if not h_level or h_level < 1 or h_level > 6:
                continue
                
            combat_count = row.get('combat_count', 0)
            if imgid not in img_combat_counts:
                img_combat_counts[imgid] = combat_count
                stats[h_level]['combat_count'] += combat_count
            
            item_name = row.get('item')
            amount = row.get('amount', 0)
            
            if item_name in stats[h_level]['items']:
                stats[h_level]['items'][item_name] += amount
                
        out_data = np.zeros((6, len(AzurStats.meowofficer_farming_labels)))
        current_time = int(datetime.timestamp(datetime.now()))
        
        for i in range(6):
            h = i + 1
            out_data[i, 0] = h
            out_data[i, 1] = current_time
            
            total_combat = stats[h]['combat_count']
            out_data[i, 2] = total_combat / AzurStats.unit_combat_count[h]
            
            for j, item in enumerate(AzurStats.meowofficer_farming_map):
                total_amount = stats[h]['items'][item]
                if total_combat > 0:
                    out_data[i, 3 + j] = total_amount / out_data[i, 2]
                else:
                    out_data[i, 3 + j] = 0
                    
        header = ','.join(AzurStats.meowofficer_farming_labels)
        np.savetxt('./log/azurstat_meowofficer_farming.csv', out_data, delimiter=',', header=header, comments='', fmt='%f', encoding='utf-8')
        logger.info('拉取并更新数据成功: azurstat_meowofficer_farming.csv')

    @property
    def _api(self):
        # method = self.config.DropRecord_API
        # if method == 'default':
        #     return 'https://azurstats.lyoko.io/api/upload/'
        # elif method == 'cn_gz_reverse_proxy':
        #     return 'https://image.tyy.akagiyui.com/api/upload'
        # elif method == 'cn_sh_reverse_proxy':
        #     return 'https://image.tyy.akagiyui.com/api/upload'
        # else:
        #     logger.critical('Invalid upload API, please check your settings')
        #     raise ScriptError('Invalid upload API')
        return 'https://alas-statsapi.nanoda.work/api/upload'

    def _upload(self, image, genre, filename, combat_count):
        """
        Args:
            image: Image to upload.
            genre (str):
            filename (str): 'xxx.png'

        Returns:
            bool: If success
        """
        output = io.BytesIO()
        Image.fromarray(image, mode='RGB').save(output, format='png')
        output.seek(0)
        files = {
            'file': (filename, output, 'image/png')
        }
        data = {
            'device_id': get_device_id(),
            'genre': genre,
            'combat_count': combat_count
        }
        session = requests.Session()
        session.trust_env = False
        session.mount('http://', HTTPAdapter(max_retries=5))
        session.mount('https://', HTTPAdapter(max_retries=5))
        try:
            resp = session.post(self._api, files=files, data=data, timeout=self.TIMEOUT)
        except Exception as e:
            logger.warning(f'Image upload failed, {e}')
            return False

        if resp.status_code == 200:
            logger.info(f'Image upload success')
            return True

        logger.warning(f'Image upload failed, unexpected server returns, '
                       f'status_code: {resp.status_code}, returns: {resp.text[:500]}')
        return False

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

    def commit(self, images, genre, save=False, upload=False, info='', combat_count=0):
        """
        Args:
            images (list): List of images in numpy array.
            genre (str):
            save (bool): If save image to local file system.
            upload (bool): If upload image to Azur Stats.
            info (str): Extra info append to filename.

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

    def new(self, genre, method='upload', info=''):
        """
        Args:
            genre (str):
            method (str): The method about save and upload image.
            info (str): Extra info append to filename.

        Returns:
            DropImage:
        """
        save = 'save' in method
        upload = 'upload' in method
        return DropImage(stat=self, genre=genre, save=save, upload=upload, info=info)
