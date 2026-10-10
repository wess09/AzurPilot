"""AzurStats 本地统计与掉落截图管理模块。

提供掉落记录（Drop Record）的截图保存、本地解析和数据存储功能。
支持将战斗掉落截图保存到本地文件系统，并通过 OCR 解析截图中的物品信息
存入 SQLite 数据库，用于大世界指挥喵 farming 等场景的统计分析。

主要组件：
    - DropImage: 掉落截图的上下文管理器，用于收集截图并在退出时提交。
    - AzurStats: 统计管理核心类，负责截图保存、本地数据解析和数据库操作。
"""

import threading
import hashlib
from contextlib import closing
import os
import sqlite3
import time
import uuid
from datetime import datetime
from dataclasses import asdict

import numpy as np
import cv2

from module.base.utils import area_pad, save_image
from module.logger import logger
from module.statistics.drop_cleanup import cleanup_drop_screenshots_if_due
from module.statistics.utils import pack
from module.base.device_id import get_device_id


# 大世界掉落解析的适用范围（2026-09-25 定）：凡属大世界任务都解析入库，
# 只有侵蚀1练级除外——它的掉落只有黄币与低级材料，且另有「大世界总结」页
# 看战斗与行动力，再入库只会让掉落明细被它刷满。
# 判定用前缀而不是逐个列举任务名，将来新出的大世界任务自动纳入。
OPSI_DROP_GENRE_PREFIX = 'opsi_'
OPSI_DROP_GENRE_EXCLUDE = frozenset({'opsi_hazard1_leveling'})


def is_opsi_drop_genre(genre) -> bool:
    """判断某个掉落分类是否属于要解析的大世界任务。

    Args:
        genre (str): 掉落记录的分类标识，取自当前任务名（如 'opsi_abyssal'）。

    Returns:
        bool: 是否需要解析入库。
    """
    genre = str(genre or '')
    if not genre.startswith(OPSI_DROP_GENRE_PREFIX):
        return False
    return genre not in OPSI_DROP_GENRE_EXCLUDE


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

    def __init__(self, stat, genre, save, local, info='', analyze=False):
        """
        Args:
            stat (AzurStats): 关联的 AzurStats 实例。
            genre (str): 掉落记录的分类标识。
            save (bool): 是否保存截图到本地文件系统。
            local (bool): 是否解析截图并存入本地数据库。
            info (str): 附加信息，追加到文件名。
            analyze (bool): 是否在提交时走分类自己的解析链路（目前用于科研掉落）。
                与 local 的区别是它写的是 cl1_record.db，且不要求保存截图。
        """
        self.stat = stat
        self.genre = str(genre)
        self.save = bool(save)
        self.local = bool(local)
        self.analyze = bool(analyze)
        self.info = info
        self.images = []
        self.combat_count = 0

    def add(self, image):
        """添加单张掉落截图到暂存列表。

        Args:
            image (np.ndarray): 截图图像。
        """
        if self:
            self.images.append(image)
            logger.info(
                f'Drop record added, genre={self.genre}, amount={self.count}')

    def set_combat_count(self, count):
        """设置当前关联的战斗场次计数。

        Args:
            count (int): 战斗场次数。
        """
        self.combat_count = count

    def handle_add(self, main, before=None):
        """在添加截图前后执行等待，并截取当前屏幕保存。

        Args:
            main (ModuleBase): 游戏主模块对象。
            before (int | float | tuple, optional): 截图前的等待时间。默认为 None（使用配置值）。
        """
        if before is None:
            before = main.config.WAIT_BEFORE_SAVING_SCREEN_SHOT

        if self:
            main.handle_info_bar()
            main.device.sleep(before)
            main.device.screenshot()
            self.add(main.device.image)

    def clear(self):
        """清空已缓存的截图列表。"""
        self.images = []

    @property
    def count(self):
        """获取当前暂存截图数量。

        Returns:
            int: 截图张数。
        """
        return len(self.images)

    def __bool__(self):
        return self.save or self.local or self.analyze

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self:
            self.stat.commit(images=self.images, genre=self.genre, save=self.save,
                             local=self.local, info=self.info, combat_count=self.combat_count,
                             analyze=self.analyze)


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
        UNKNOWN_ITEM_FOLDER (str): 未识别物品的定位截图目录。

    Examples:
        >>> stats = AzurStats(config)
        >>> with stats.new('opsi_meowfficer_farming') as drop:
        ...     drop.handle_add(main)
        # 退出 with 块时自动提交并解析
    """

    TIMEOUT = 20
    LOCAL_DB = './config/azurstats_local.db'
    LOCAL_MEOW_CSV = './log/azurstat_meowofficer_farming.csv'
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
    def _meowofficer_farming_path(instance=None):
        """提供旧 CSV 路径，供迁移与显式导出工具定位。"""
        if instance is None:
            return AzurStats.LOCAL_MEOW_CSV
        # 不将实例名直接拼成路径，避免大小写、特殊字符和路径分隔符冲突。
        key = hashlib.sha256(f'{get_device_id()}\0{instance}'.encode('utf-8')).hexdigest()
        stem, suffix = os.path.splitext(AzurStats.LOCAL_MEOW_CSV)
        return f'{stem}.instance-{key}{suffix}'

    @staticmethod
    def load_meowofficer_farming(instance=None):
        """读取缓存保持刷新时间；实例缺失时仅重算该实例的明细。"""
        with AzurStats._database().transaction(write=False) as connection:
            rows = connection.execute('''SELECT hazard_level, recorded_at, effective_rounds,
                average_yellow_coin, average_plate, average_abyssal, average_obscure
                FROM farming_aggregates WHERE scope_key=? ORDER BY hazard_level''',
                (AzurStats._farming_scope(instance),)).fetchall()
        if len(rows) != 6:
            return AzurStats.get_meowofficer_farming(instance=instance)
        return np.array([tuple(row) for row in rows], dtype=float)

    @staticmethod
    def _database():
        from module.persistence.database import for_legacy_path
        database = for_legacy_path(AzurStats.LOCAL_DB, 'statistics')
        # 自定义旧缓存路径仅作为首次迁移来源；运行期间不再读写 CSV。
        if AzurStats.LOCAL_MEOW_CSV != './log/azurstat_meowofficer_farming.csv':
            from pathlib import Path
            path = Path(AzurStats.LOCAL_MEOW_CSV).absolute()
            for candidate in path.parent.glob(path.stem + '*.csv'):
                database.add_legacy_source('farming', candidate)
        return database

    @staticmethod
    def _ensure_local_db():
        AzurStats._database().ensure_ready()

    @staticmethod
    def _farming_scope(instance):
        if instance is None:
            return 'global'
        key = hashlib.sha256(f'{get_device_id()}\0{instance}'.encode('utf-8')).hexdigest()
        return 'instance-' + key

    @staticmethod
    def _insert_local_opsi_items(rows):
        if not rows:
            return 0
        from module.persistence.database import register_instance
        from module.persistence.snapshots import insert
        fields = ('imgid', 'instance', 'device_id', 'genre', 'server', 'zone', 'zone_type',
                  'zone_id', 'hazard_level', 'item', 'amount', 'tag', 'combat_count', 'created_at')
        with AzurStats._local_lock, AzurStats._database().transaction() as connection:
            for row in rows:
                register_instance(connection, row.get('instance'))
                insert(connection, 'opsi_items', {name: row.get(name) for name in fields})
        return len(rows)

    @staticmethod
    def _unseal_rows(rows):
        """物品明细直接来自原生列，保留调用方的列表结构。"""
        return rows

    @staticmethod
    def _load_local_opsi_items(device_id=None, genre='opsi_meowfficer_farming', instance=None, connection=None):
        if connection is None:
            AzurStats._ensure_local_db()
            with AzurStats._database().transaction(write=False) as conn:
                return AzurStats._load_local_opsi_items(device_id, genre, instance, connection=conn)
        query = 'SELECT * FROM opsi_items WHERE 1=1'
        params = []
        if device_id:
            query += ' AND device_id = ?'
            params.append(device_id)
        if genre:
            query += ' AND genre = ?'
            params.append(genre)
        if instance is not None:
            query += ' AND instance = ?'
            params.append(instance)
        query += ' ORDER BY id ASC'
        connection.row_factory = sqlite3.Row
        return AzurStats._unseal_rows([dict(row) for row in connection.execute(query, params).fetchall()])

    @staticmethod
    def load_opsi_drop_rows(instance=None, start=None, end=None, task=None, device_id=None):
        """读取大世界掉落明细，供统计页按时间窗口汇总。

        只取需要解析的大世界任务（见 is_opsi_drop_genre），侵蚀1练级的历史行
        即使存在也不会被算进来。查询条件里的任务范围直接由那套常量生成，
        避免在 SQL 里再抄一份规则。

        Args:
            instance (str): ALAS 实例名；None 表示不限实例。
            start (int): 起始时间戳（含，秒）；None 表示不限。
            end (int): 结束时间戳（不含，秒）；None 表示不限。
            task (str): 只看某个大世界任务（genre，如 'opsi_abyssal'）；None 表示全部。
            device_id (str): 设备标识，默认当前设备。

        Returns:
            list[dict]: opsi_items 明细行，按记录时间升序。
        """
        if device_id is None:
            device_id = get_device_id()
        AzurStats._ensure_local_db()
        pattern = OPSI_DROP_GENRE_PREFIX.replace('_', r'\_') + '%'
        query = "SELECT * FROM opsi_items WHERE device_id = ? AND genre LIKE ? ESCAPE '\\'"
        params = [device_id, pattern]
        for excluded in sorted(OPSI_DROP_GENRE_EXCLUDE):
            query += ' AND genre <> ?'
            params.append(excluded)
        if instance is not None:
            query += ' AND instance = ?'
            params.append(instance)
        if task:
            query += ' AND genre = ?'
            params.append(str(task))
        if start is not None:
            query += ' AND created_at >= ?'
            params.append(int(start))
        if end is not None:
            query += ' AND created_at < ?'
            params.append(int(end))
        query += ' ORDER BY created_at ASC, id ASC'
        try:
            with AzurStats._database().transaction(write=False) as conn:
                conn.row_factory = sqlite3.Row
                return AzurStats._unseal_rows([dict(row) for row in conn.execute(query, params).fetchall()])
        except sqlite3.Error:
            logger.warning('[统计-大世界] 读取掉落明细失败', exc_info=True)
            return []

    @staticmethod
    def _write_meowofficer_farming(data, instance=None, *, connection=None):
        """原子替换六个等级的汇总；刷新与明细读取可共享事务。"""
        from module.persistence.database import register_instance
        if connection is None:
            with AzurStats._database().transaction() as connection:
                return AzurStats._write_meowofficer_farming(data, instance, connection=connection)
        data = np.asarray(data)
        if data.shape != (6, len(AzurStats.meowofficer_farming_labels)) or not np.isfinite(data).all():
            raise ValueError('收益缓存需要六个等级的有限数值')
        if list(data[:, 0]) != [1, 2, 3, 4, 5, 6]:
            raise ValueError('收益缓存等级必须按 1 到 6 排列')
        register_instance(connection, instance)
        scope = AzurStats._farming_scope(instance)
        connection.execute('DELETE FROM farming_aggregates WHERE scope_key=?', (scope,))
        connection.executemany('''INSERT INTO farming_aggregates
            (scope_key,hazard_level,instance,device_id,source_kind,source_file,recorded_at,
             effective_rounds,average_yellow_coin,average_plate,average_abyssal,average_obscure)
            VALUES(?,?,?,?,'computed',NULL,?,?,?,?,?,?)''',
            [(scope, int(row[0]), instance, get_device_id(), int(row[1]), *map(float, row[2:])) for row in data])

    @staticmethod
    def get_meowofficer_farming(instance=None):
        """在同一个写事务中按原截图分组口径重算并提交缓存。"""
        with AzurStats._database().transaction() as connection:
            rows = connection.execute('''WITH selected AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY instance,device_id,imgid ORDER BY id) AS capture_row
                FROM opsi_items WHERE device_id=? AND genre='opsi_meowfficer_farming'
                    AND (? IS NULL OR instance=?) AND hazard_level BETWEEN 1 AND 6
            ) SELECT hazard_level,
                SUM(CASE WHEN capture_row=1 THEN COALESCE(combat_count,0) ELSE 0 END) AS combats,
                SUM(CASE WHEN substr(item,1,13)='OperationCoin' THEN COALESCE(amount,0) ELSE 0 END) AS coins,
                SUM(CASE WHEN substr(item,1,5)='Plate' THEN COALESCE(amount,0) ELSE 0 END) AS plates,
                SUM(CASE WHEN substr(item,1,17)='CoordinateAbyssal' THEN COALESCE(amount,0) ELSE 0 END) AS abyssal,
                SUM(CASE WHEN substr(item,1,17)='CoordinateObscure' THEN COALESCE(amount,0) ELSE 0 END) AS obscure
                FROM selected GROUP BY hazard_level''', (get_device_id(), instance, instance)).fetchall()
            out_data = np.zeros((6, len(AzurStats.meowofficer_farming_labels)))
            out_data[:, 0] = np.arange(1, 7)
            out_data[:, 1] = int(datetime.timestamp(datetime.now()))
            for row in rows:
                hazard = row['hazard_level']
                rounds = row['combats'] / AzurStats.unit_combat_count[hazard]
                out_data[hazard - 1, 2] = rounds
                amounts = [row[name] for name in ('coins', 'plates', 'abyssal', 'obscure')]
                out_data[hazard - 1, 3:] = np.array(amounts) / rounds if rounds > 0 else amounts
            AzurStats._write_meowofficer_farming(out_data, instance, connection=connection)
            logger.info(f'[Statistics] 本地统计数据更新成功: {instance or "全局共享"}')
            return out_data

    @staticmethod
    def get_meow_loot_monthly_totals(device_id=None, year=None, month=None, instance=None):
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
            instance: 实例名；省略时保留旧版全局汇总。

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
            """将物品名称归类到大世界月度统计项。

            Args:
                name (str): 物品名称。

            Returns:
                str | None: 统计项类别名，不匹配返回 None。
            """
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
        scope = ' AND instance = ?' if instance is not None else ''
        params = (month_start, month_end, device_id) + ((instance,) if instance is not None else ())
        try:
            with AzurStats._database().transaction(write=False) as conn:
                conn.row_factory = sqlite3.Row
                rows = AzurStats._unseal_rows([dict(row) for row in conn.execute(
                    "SELECT * FROM opsi_items "
                    "WHERE genre='opsi_meowfficer_farming' AND created_at >= ? AND created_at < ? "
                    f"AND device_id = ?{scope}",
                    params,
                ).fetchall()])
            # 物品与数量可能来自密文载荷，聚合在 Python 侧完成。
            for row in rows:
                try:
                    h = int(row.get('hazard_level'))
                except (TypeError, ValueError):
                    continue
                if h not in totals:
                    continue
                key = classify(str(row.get('item') or ""))
                if key is None:
                    continue
                try:
                    totals[h][key] += int(row.get('amount') or 0)
                except (TypeError, ValueError):
                    pass
        except Exception:
            logger.warning('[Statistics] 查询耄耋相接掉落总数失败', exc_info=True)
        return totals

    @staticmethod
    def get_meow_loot_available_months(device_id=None, limit=24, instance=None):
        """返回掉落明细库中存在耄耋相接数据的月份列表（从新到旧）。

        Args:
            device_id: 设备标识，默认当前设备。
            limit: 最多返回的月份数。
            instance: 实例名；省略时保留旧版全局月份列表。

        Returns:
            list[tuple[int, int]]: [(year, month), ...] 从新到旧。
        """
        if device_id is None:
            device_id = get_device_id()
        AzurStats._ensure_local_db()
        scope = ' AND instance = ?' if instance is not None else ''
        params = (device_id,) + ((instance,) if instance is not None else ()) + (limit,)
        try:
            with AzurStats._database().transaction(write=False) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT strftime('%Y-%m', created_at, 'unixepoch') AS ym "
                    "FROM opsi_items WHERE genre='opsi_meowfficer_farming' AND device_id = ? "
                    f"{scope} ORDER BY ym DESC LIMIT ?",
                    params,
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
    def _parse_local_opsi_items(image, imgid, genre, combat_count, filename=None, instance=None):
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
            row['instance'] = instance
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
                logger.warning(f'未识别物品截图生成失败, {type(e).__name__}')
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
                logger.warning(f'未识别物品截图保存失败, {type(e).__name__}')

        if saved:
            logger.info(f'发现未识别物品，截图已保存: {", ".join(saved)}')

    def _record_local(self, image, genre, filename, combat_count):
        if not is_opsi_drop_genre(genre):
            return False

        imgid = f"{os.path.splitext(os.path.basename(filename))[0][:8]}{uuid.uuid4().hex[:8]}"
        try:
            rows = self._parse_local_opsi_items(
                image, imgid, genre, combat_count, filename=filename, instance=self.config.config_name)
            if not rows:
                logger.warning('本地碧蓝统计解析跳过, no opsi item rows extracted')
                return False
            inserted = self._insert_local_opsi_items(rows)
            # 短猫的收益汇总只认自己那一类记录，其他大世界任务入库时不重算，
            # 免得每来一条要塞/每日记录都把整表重跑一遍。
            if genre == 'opsi_meowfficer_farming':
                self.get_meowofficer_farming(instance=self.config.config_name)
            logger.info(f'本地碧蓝统计解析成功，记录 {inserted} 条')
            return True
        except Exception as e:
            logger.warning(f'本地碧蓝统计解析失败, {type(e).__name__}')
            return False

    def _save(self, image, genre, filename):
        """将截图保存到指定类别的本地文件夹中。

        Args:
            image (np.ndarray): 待保存图像。
            genre (str): 子文件夹名称（分类）。
            filename (str): 保存的文件名。

        Returns:
            bool: 保存成功返回 True，失败返回 False。
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

    def commit(self, images, genre, save=False, local=False, info='', combat_count=0,
               analyze=False):
        """提交并处理一组掉落截图，执行保存、本地入库或专用解析。

        Args:
            images (list[np.ndarray]): 截图图像列表。
            genre (str): 掉落类型。
            save (bool): 是否将合并后的截图保存到本地硬盘。默认为 False。
            local (bool): 是否将截图解析存入本地 AzurStats 数据库。默认为 False。
            info (str): 附加到文件名中的额外说明信息。默认为空。
            combat_count (int): 战斗场次计数。默认为 0。
            analyze (bool): 是否交给分类专用的解析链路入库（如科研掉落）。默认为 False。

        Returns:
            bool: 是否成功提交处理。
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
                target=self._save, args=(image, genre, filename))
            save_thread.start()

        if local:
            logger.info(f'本地碧蓝统计解析开始，类型={genre}')
            with self._record_lock:
                self._record_local(image, genre, filename, combat_count)

        if analyze and genre == 'research':
            # 同步解析：一次约 1 秒，发生在领奖之后，不打断任何状态循环。
            # 解析失败只记日志，绝不影响领奖流程本身。
            try:
                from module.statistics.research_drop import record_research_drop
                record_research_drop(images, instance=self.config.config_name, imgid=filename)
            except Exception as e:
                logger.warning(f'[科研统计] 掉落解析失败，跳过本次记录: {type(e).__name__}')

        return True

    def new(self, genre, method=None, save=False, local=None, info=''):
        """创建新的掉落图片上下文管理器。

        Args:
            genre (str): 掉落类型（如 'campaign', 'research', 'opsi_obscure'）。
            method (str | bool, optional): 截图保存与上传方式。默认为 None。
            save (bool): 是否将图像保存至磁盘。默认为 False。
            local (bool | None): 是否解析存入本地数据库。为 None 时根据 genre 自动判定。
            info (str): 附加到文件名的字符串。默认为空。

        Returns:
            DropImage: 掉落图片收集与提交上下文对象。
        """
        # 掉落记录的每个提交周期都会走到这里，用它作为过期截图的清理时机
        # （内部有节流，不会每场战斗都扫目录）
        cleanup_drop_screenshots_if_due(self.config)

        method_value = None
        if isinstance(method, bool):
            save = save or method
            method = None
        if method is not None:
            method_value = str(method)
            save = save or 'save' in method_value
        if local is None:
            if is_opsi_drop_genre(genre):
                # 大世界掉落统计（2026-09-25 用户定，与科研同口径）：
                # 「保存」与「上传」都解析入库，区别只在要不要把截图落盘；
                # 只有「不记录」才不统计。侵蚀1练级不适用（见 is_opsi_drop_genre）。
                local = method_value != 'do_not'
            else:
                local = False
        # 科研掉落走独立解析链路（写 cl1_record.db）：只要用户没有显式关掉记录，
        # 存图与否都统计——save 档事后要能核对，upload 档就是不落盘只要数据。
        analyze = genre == 'research' and method_value != 'do_not'
        return DropImage(stat=self, genre=genre, save=save, local=local, info=info, analyze=analyze)
