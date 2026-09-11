"""AzurStats 本地统计与掉落截图管理模块。

提供掉落记录（Drop Record）的截图保存、本地解析和数据存储功能。
支持将战斗掉落截图保存到本地文件系统，并通过 OCR 解析截图中的物品信息
存入 SQLite 数据库，用于大世界指挥喵 farming 等场景的统计分析。

主要组件：
    - DropImage: 掉落截图的上下文管理器，用于收集截图并在退出时提交。
    - AzurStats: 统计管理核心类，负责截图保存、本地数据解析和数据库操作。
"""

import threading
import os
import sqlite3
import time
import uuid
from datetime import datetime
from dataclasses import asdict

import inflection
import numpy as np
import cv2

from module.base.utils import area_pad, save_image
from module.logger import logger
from module.statistics.utils import pack
from module.base.device_id import get_device_id


class DropImage:
    """掉落截图上下文管理器，用于收集截图并在退出时统一提交。

    作为上下文管理器使用（with 语句），在退出时自动调用 AzurStats.commit()
    将收集到的截图进行保存和/或本地解析。

    Attributes:
        stat (AzurStats): 关联的 AzurStats 实例。
        genre (str): 掉落记录的分类标识（如 'opsi_meowfficer_farming'）。
        save (bool): 是否保存截图到本地文件系统。
        local (bool): 是否解析截图并存入本地数据库。
        info (str): 附加信息，会追加到保存的文件名中。
        images (list[np.ndarray]): 已收集的截图列表。
        combat_count (int): 战斗记录轮数，用于统计计算。

    Examples:
        >>> with azur_stats.new('opsi_meowfficer_farming') as drop:
        ...     drop.add(screenshot)
        # 退出 with 块时自动提交截图
    """

    def __init__(self, stat, genre, save, local, info=''):
        """
        Args:
            stat (AzurStats): 关联的 AzurStats 实例。
            genre (str): 掉落记录的分类标识。
            save (bool): 是否保存截图到本地文件系统。
            local (bool): 是否解析截图并存入本地数据库。
            info (str): 附加信息，追加到文件名。
        """
        self.stat = stat
        self.genre = str(genre)
        self.save = bool(save)
        self.local = bool(local)
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
        return self.save or self.local

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self:
            self.stat.commit(images=self.images, genre=self.genre,
                             save=self.save, local=self.local, info=self.info, combat_count=self.combat_count)


class AzurStats:
    """AzurStats 统计管理核心类，负责掉落截图的保存、解析和数据存储。

    提供两种数据处理路径：
        - 远程上传（已废弃）：将截图提交到远程 AzurStats 服务。
        - 本地处理：将截图中的物品信息解析后存入 SQLite 数据库，
          并生成统计汇总 CSV 文件（如指挥喵 farming 统计）。

    线程安全：
        使用 _local_lock 和 _record_lock 两个线程锁保护数据库写入操作，
        支持多线程并发调用。

    类属性:
        TIMEOUT (int): 请求超时时间（秒）。
        LOCAL_DB (str): 本地 SQLite 数据库路径。
        LOCAL_MEOW_CSV (str): 指挥喵 farming 统计 CSV 路径。
        LOCAL_GENRES (set): 需要本地处理的记录分类集合。

    Examples:
        >>> stats = AzurStats(config)
        >>> with stats.new('opsi_meowfficer_farming') as drop:
        ...     drop.handle_add(main)
        # 退出 with 块时自动提交并解析
    """

    TIMEOUT = 20
    LOCAL_DB = './config/azurstats_local.db'
    LOCAL_MEOW_CSV = './log/azurstat_meowofficer_farming.csv'
    LOCAL_GENRES = {'opsi_meowfficer_farming'}
    # 未识别物品的定位截图保存目录（随 screenshots/ 一起被 git 忽略）
    UNKNOWN_ITEM_FOLDER = './screenshots/unknown_items'
    _local_lock = threading.Lock()
    _record_lock = threading.Lock()

    def __init__(self, config):
        """
        Args:
            config:
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
            data = np.loadtxt(AzurStats.LOCAL_MEOW_CSV, delimiter=',', dtype=float, skiprows=1, encoding='utf-8')
            if data.shape[0] != 6:
                raise IndexError
        except Exception:
            data = np.zeros((6, len(AzurStats.meowofficer_farming_labels)))
            data[:, 0] = np.arange(1, 7)
            header = ','.join(AzurStats.meowofficer_farming_labels)
            os.makedirs(os.path.dirname(AzurStats.LOCAL_MEOW_CSV), exist_ok=True)
            np.savetxt(AzurStats.LOCAL_MEOW_CSV, data, delimiter=',', header=header, comments='', fmt='%f', encoding='utf-8')
            data = np.loadtxt(AzurStats.LOCAL_MEOW_CSV, delimiter=',', dtype=float, skiprows=1, encoding='utf-8')
        return data

    @staticmethod
    def _ensure_local_db():
        os.makedirs(os.path.dirname(AzurStats.LOCAL_DB), exist_ok=True)
        with sqlite3.connect(AzurStats.LOCAL_DB) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS opsi_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    imgid TEXT NOT NULL,
                    server TEXT,
                    zone TEXT,
                    zone_type TEXT,
                    zone_id INTEGER,
                    hazard_level INTEGER,
                    item TEXT,
                    amount INTEGER,
                    tag TEXT,
                    device_id TEXT,
                    genre TEXT,
                    combat_count INTEGER,
                    created_at INTEGER
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_opsi_items_device_genre ON opsi_items(device_id, genre)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_opsi_items_imgid ON opsi_items(imgid)')
            conn.commit()

    @staticmethod
    def _insert_local_opsi_items(rows):
        if not rows:
            return 0

        AzurStats._ensure_local_db()
        with AzurStats._local_lock:
            with sqlite3.connect(AzurStats.LOCAL_DB) as conn:
                conn.executemany('''
                    INSERT INTO opsi_items (
                        imgid, server, zone, zone_type, zone_id, hazard_level,
                        item, amount, tag, device_id, genre, combat_count, created_at
                    ) VALUES (
                        :imgid, :server, :zone, :zone_type, :zone_id, :hazard_level,
                        :item, :amount, :tag, :device_id, :genre, :combat_count, :created_at
                    )
                ''', rows)
                conn.commit()
        return len(rows)

    @staticmethod
    def _load_local_opsi_items(device_id=None, genre='opsi_meowfficer_farming'):
        AzurStats._ensure_local_db()
        query = 'SELECT * FROM opsi_items WHERE 1=1'
        params = []
        if device_id:
            query += ' AND device_id = ?'
            params.append(device_id)
        if genre:
            query += ' AND genre = ?'
            params.append(genre)
        query += ' ORDER BY id ASC'

        with sqlite3.connect(AzurStats.LOCAL_DB) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _write_meowofficer_farming(data):
        header = ','.join(AzurStats.meowofficer_farming_labels)
        os.makedirs(os.path.dirname(AzurStats.LOCAL_MEOW_CSV), exist_ok=True)
        np.savetxt(
            AzurStats.LOCAL_MEOW_CSV,
            data,
            delimiter=',',
            header=header,
            comments='',
            fmt='%f',
            encoding='utf-8',
        )

    @staticmethod
    def get_meowofficer_farming():
        all_data = AzurStats._load_local_opsi_items(
            device_id=get_device_id(),
            genre='opsi_meowfficer_farming',
        )
        out_data = np.zeros((6, len(AzurStats.meowofficer_farming_labels)))
        img_combat_counts = {}

        for row in all_data:
            imgid = row.get('imgid')
            h_level = row.get('hazard_level')
            if not h_level or h_level < 1 or h_level > 6:
                continue
                
            combat_count = row.get('combat_count', 0)
            if imgid not in img_combat_counts:
                img_combat_counts[imgid] = combat_count
                out_data[h_level - 1, 2] += combat_count
            
            item_name = row.get('item')
            amount = row.get('amount', 0)
            
            for i, item_prefix in enumerate(AzurStats.meowofficer_farming_map):
                if item_name.startswith(item_prefix):
                    out_data[h_level - 1, 3 + i] += amount
                    break
        current_time = int(datetime.timestamp(datetime.now()))

        for i in range(6):
            h = i + 1
            out_data[i, 0] = h
            out_data[i, 1] = current_time
            out_data[i, 2] /= AzurStats.unit_combat_count[h]

            if out_data[i, 2] > 0:
                for j in range(3, len(AzurStats.meowofficer_farming_labels)):
                    out_data[i, j] /= out_data[i, 2]

        AzurStats._write_meowofficer_farming(out_data)
        logger.info('[Statistics] 本地统计数据更新成功: azurstat_meowofficer_farming.csv')

    @staticmethod
    def get_meow_loot_monthly_totals(device_id=None, year=None, month=None):
        """按侵蚀等级汇总指定月份（默认本月）的耄耋相接掉落总数。

        从本地掉落明细库 opsi_items 汇总，供统计页
        「本月/历史耄耋相接收获」表格使用。分类口径：
        Plate 为金菜（装备强化板）、GearDesignPlan*T5 为彩图纸、
        OrdnanceTestingReport*T4 为金机密、CoordinateObscure 为隐秘、
        CoordinateAbyssal 为深渊、CatT3 为金猫箱。

        Args:
            device_id: 设备标识，默认当前设备。
            year: 年份，默认当前年。
            month: 月份（1-12），默认当前月。

        Returns:
            dict[int, dict[str, int]]: 侵蚀等级(1-6) → 分类计数字典，
                键为 Plate / GearDesignPlanT5 / OrdnanceTestingReportT4 /
                CoordinateObscure / CoordinateAbyssal / CatT3。
        """
        if year is None or month is None:
            now = datetime.now()
            year, month = now.year, now.month
        month_start = int(datetime(year, month, 1).timestamp())
        if month == 12:
            month_end = int(datetime(year + 1, 1, 1).timestamp())
        else:
            month_end = int(datetime(year, month + 1, 1).timestamp())
        if device_id is None:
            device_id = get_device_id()
        AzurStats._ensure_local_db()

        # 分类规则：前缀 + 可选等级后缀（彩图纸只取 T5、金机密只取 T4）
        def classify(name: str):
            if name.startswith("CatT3"):
                return "CatT3"
            if name.startswith("GearDesignPlan") and name.endswith("T5"):
                return "GearDesignPlanT5"
            if name.startswith("OrdnanceTestingReport") and name.endswith("T4"):
                return "OrdnanceTestingReportT4"
            if name.startswith("CoordinateObscure"):
                return "CoordinateObscure"
            if name.startswith("CoordinateAbyssal"):
                return "CoordinateAbyssal"
            if name.startswith("Plate"):
                return "Plate"
            return None

        keys = (
            "Plate",
            "GearDesignPlanT5",
            "OrdnanceTestingReportT4",
            "CoordinateObscure",
            "CoordinateAbyssal",
            "CatT3",
        )
        totals = {h: {k: 0 for k in keys} for h in range(1, 7)}
        try:
            with sqlite3.connect(AzurStats.LOCAL_DB) as conn:
                rows = conn.execute(
                    "SELECT hazard_level, item, SUM(amount) FROM opsi_items "
                    "WHERE genre='opsi_meowfficer_farming' AND created_at >= ? AND created_at < ? "
                    "AND device_id = ? GROUP BY hazard_level, item",
                    (month_start, month_end, device_id),
                ).fetchall()
            for h_raw, item, total in rows:
                try:
                    h = int(h_raw)
                except (TypeError, ValueError):
                    continue
                if h not in totals or not total:
                    continue
                key = classify(str(item or ""))
                if key is None:
                    continue
                try:
                    totals[h][key] += int(total)
                except (TypeError, ValueError):
                    pass
        except Exception:
            logger.warning('[Statistics] 查询耄耋相接掉落总数失败', exc_info=True)
        return totals

    @staticmethod
    def get_meow_loot_available_months(device_id=None, limit=24):
        """返回掉落明细库中存在耄耋相接数据的月份列表（从新到旧）。

        Args:
            device_id: 设备标识，默认当前设备。
            limit: 最多返回的月份数。

        Returns:
            list[tuple[int, int]]: [(year, month), ...] 从新到旧。
        """
        if device_id is None:
            device_id = get_device_id()
        AzurStats._ensure_local_db()
        try:
            with sqlite3.connect(AzurStats.LOCAL_DB) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT strftime('%Y-%m', created_at, 'unixepoch') AS ym "
                    "FROM opsi_items WHERE genre='opsi_meowfficer_farming' AND device_id = ? "
                    "ORDER BY ym DESC LIMIT ?",
                    (device_id, limit),
                ).fetchall()
        except Exception:
            logger.warning('[Statistics] 查询耄耋相接掉落月份列表失败', exc_info=True)
            return []
        months = []
        for (ym,) in rows:
            try:
                y_str, m_str = ym.split("-")
                months.append((int(y_str), int(m_str)))
            except (ValueError, AttributeError):
                continue
        return months

    @staticmethod
    def _ensure_local_parser():
        from module.azur_stats.scene.operation_siren import SceneOperationSiren
        return SceneOperationSiren

    @staticmethod
    def _parse_local_opsi_items(image, imgid, genre, combat_count, filename=None):
        SceneOperationSiren = AzurStats._ensure_local_parser()
        scene = SceneOperationSiren()
        scene.load_file(image)
        scene.__dict__['imgid'] = imgid
        rows = []
        created_at = int(time.time())
        device_id = get_device_id()

        for item in scene.parse_scene():
            row = asdict(item)
            row['imgid'] = imgid
            row['device_id'] = device_id
            row['genre'] = genre
            row['combat_count'] = int(combat_count or 0)
            row['created_at'] = created_at
            rows.append(row)

        if filename and any(str(row['item']).isdigit() for row in rows):
            AzurStats._save_unknown_item_images(scene, filename)

        return rows

    @staticmethod
    def _save_unknown_item_images(scene, filename):
        """保存含未识别物品的掉落截图。

        未识别物品（模板匹配失败、只有数字代号）需要人工辨认后补模板，
        这里把该结算截图另存一份并在未知物品所在格子画红框，存到
        ``screenshots/unknown_items/``，便于事后核对物品位置。

        Args:
            scene (SceneOperationSiren): 已完成 parse_scene() 的场景对象。
            filename (str): 掉落记录文件名，用于生成保存文件名。
        """
        group = scene.auto_search_item_group
        stem = os.path.splitext(os.path.basename(filename))[0]
        saved = []
        for index, image in enumerate(scene.images):
            if not scene.is_opsi_reward(image):
                continue
            try:
                scene._auto_search_get_items_load(image)
                # 数量已在解析阶段识别过，这里只需要物品名
                group.predict(image, name=True, amount=False, tag=False)
            except Exception as e:
                logger.warning(f'未识别物品截图生成失败, {e}')
                continue

            items = [item for item in group.items if not item.is_known_item()]
            if not items:
                continue

            marked = image.copy()
            for item in items:
                area = area_pad(item.area, pad=4)
                cv2.rectangle(marked, area[:2], area[2:], (255, 0, 0), 3)
                cv2.putText(marked, str(item.name), (area[0], area[1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            code = '_'.join(sorted({str(item.name) for item in items}))
            suffix = f'_{index}' if len(scene.images) > 1 else ''
            file = os.path.join(
                AzurStats.UNKNOWN_ITEM_FOLDER, f'{stem}_未知物品{code}{suffix}.png')
            try:
                os.makedirs(AzurStats.UNKNOWN_ITEM_FOLDER, exist_ok=True)
                save_image(marked, file)
                saved.append(file)
            except Exception as e:
                logger.warning(f'未识别物品截图保存失败, {e}')

        if saved:
            logger.info(f'发现未识别物品，截图已保存: {", ".join(saved)}')

    def _record_local(self, image, genre, filename, combat_count):
        if genre not in ['opsi_meowfficer_farming']:
            return False

        imgid = f"{os.path.splitext(os.path.basename(filename))[0][:8]}{uuid.uuid4().hex[:8]}"
        try:
            rows = self._parse_local_opsi_items(
                image, imgid, genre, combat_count, filename=filename)
            if not rows:
                logger.warning('本地碧蓝统计解析跳过, no opsi item rows extracted')
                return False
            inserted = self._insert_local_opsi_items(rows)
            self.get_meowofficer_farming()
            logger.info(f'本地碧蓝统计解析成功，行数={inserted}')
            return True
        except Exception as e:
            logger.warning(f'本地碧蓝统计解析失败, {e}')
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
            logger.info(f'图片保存成功，文件: {file}')
            return True
        except Exception as e:
            logger.exception(e)

        return False

    @staticmethod
    def _drop_save_image(images, genre):
        """选取落盘用的掉落截图。

        耄耋相接的掉落记录由两张截图组成：结算奖励页（掉落内容）与
        大世界区域页（仅提供区域名、危险等级）。区域信息在 commit()
        解析时从内存中的截图取得，落盘只需保留结算页，避免截图文件里
        混入区域页、打开时看到两张拼在一起的画面。

        Args:
            images (list[np.ndarray]): 本次掉落记录收集到的截图。
            genre (str): 掉落记录分类。

        Returns:
            np.ndarray: 待保存的图像。
        """
        if genre not in AzurStats.LOCAL_GENRES or len(images) <= 1:
            return pack(images)

        # is_opsi_reward() 会把匹配位置缓存在按钮对象上，而该位置随后会
        # 被解析路径用作物品网格的下边界，因此这里用完立即还原。
        from module.os_handler.assets import AUTO_SEARCH_REWARD

        prev_offset = AUTO_SEARCH_REWARD._button_offset
        try:
            scene = AzurStats._ensure_local_parser()()
            reward = [image for image in images if scene.is_opsi_reward(image)]
        except Exception as e:
            logger.warning(f'结算页筛选失败，保存完整掉落截图, {e}')
            return pack(images)
        finally:
            AUTO_SEARCH_REWARD._button_offset = prev_offset

        if not reward:
            logger.warning('未识别到结算奖励页，保存完整掉落截图')
            return pack(images)

        if len(reward) < len(images):
            logger.info(f'掉落截图落盘仅保留结算页 {len(reward)}/{len(images)} 帧')
        return pack(reward)

    def commit(self, images, genre, save=False, local=False, info='', combat_count=0):
        """
        Args:
            images (list): List of images in numpy array.
            genre (str):
            save (bool): If save image to local file system.
            local (bool): If parse image into local AzurStats storage.
            info (str): Extra info append to filename.

        Returns:
            bool: If commit.
        """
        if len(images) == 0:
            return False

        save, local = bool(save), bool(local)
        logger.info(
            f'Drop record commit, genre={genre}, amount={len(images)}, save={save}, local={local}')
        image = pack(images)
        now = int(time.time() * 1000)

        if info:
            filename = f'{now}_{info}.png'
        else:
            filename = f'{now}.png'

        if save:
            save_thread = threading.Thread(
                target=self._save,
                args=(self._drop_save_image(images, genre), genre, filename))
            save_thread.start()

        if local:
            logger.info(f'本地碧蓝统计解析开始，类型={genre}')
            with self._record_lock:
                self._record_local(image, genre, filename, combat_count)

        return True

    def new(self, genre, method=None, save=False, local=None, info=''):
        """
        Args:
            genre (str):
            method (str): The method about save and upload image.
            save (bool): Whether to save the image.
            local (bool): Whether to use local processing. If None, determined by genre.
            info (str): Extra info append to filename.

        Returns:
            DropImage:
        """
        method_value = None
        if isinstance(method, bool):
            save = save or method
            method = None
        if method is not None:
            method_value = str(method)
            save = save or 'save' in method_value
        if local is None:
            if method_value is None:
                local = genre in self.LOCAL_GENRES
            else:
                local = 'upload' in method_value and genre in self.LOCAL_GENRES
        return DropImage(stat=self, genre=genre, save=save, local=local, info=info)

    @staticmethod
    def opsi_save_method(task_command, method):
        """大世界掉落记录方式定制：仅耄耋相接任务允许本地保存截图。

        侵蚀1练级、每日、隐秘、深渊等任务频率高、截图量大，
        本地保存会占用大量磁盘。这些任务即使配置了保存模式，
        也保留其上传等行为、仅去掉本地保存。

        Args:
            task_command: 任务名（如 'OpsiMeowfficerFarming'）。
            method: DropRecord_OpsiRecord 配置值。

        Returns:
            str: 过滤后的记录方式。
        """
        genre = inflection.underscore(task_command)
        if genre != 'opsi_meowfficer_farming' and method and 'save' in str(method):
            return str(method).replace('save_and_upload', 'upload').replace('save', 'do_not')
        return method
