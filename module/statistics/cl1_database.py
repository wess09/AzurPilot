# -*- coding: utf-8 -*-
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256

from module.base.device_id import get_device_id
from module.logger import logger

class Cl1Database:
    """
    CL1 数据加密 SQLite 数据库管理类。
    所有实例共享一个数据库文件，但数据经过 AES-GCM 加密，并由 device_id 保护。
    """
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            project_root = Path(__file__).resolve().parents[2]
            self.db_dir = project_root / 'config'
            self.db_path = self.db_dir / 'cl1_data.db'
        else:
            self.db_path = db_path
            self.db_dir = self.db_path.parent

        self._ensure_dir()
        self._init_db()
        self._encryption_key = self._derive_key()
        self._auto_migrate()

    def _ensure_dir(self):
        try:
            self.db_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create database directory: {e}")

    def _init_db(self):
        """初始化数据库表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 存储各实例、月份的加密数据
                # encrypted_blob 包含 nonce + tag + ciphertext
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cl1_data (
                        instance TEXT,
                        month TEXT,
                        encrypted_blob BLOB,
                        PRIMARY KEY (instance, month)
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.exception(f"Failed to initialize CL1 database: {e}")

    def _derive_key(self) -> bytes:
        """基于 device_id 派生 256 位 AES 密钥"""
        device_id = get_device_id()
        salt = b'AlasCl1SecureStorage' # 固定盐
        return PBKDF2(device_id.encode(), salt, dkLen=32, count=1000, hmac_hash_module=SHA256)

    def _encrypt(self, data: Dict[str, Any]) -> bytes:
        """使用 AES-GCM 加密数据"""
        try:
            cipher = AES.new(self._encryption_key, AES.MODE_GCM)
            ciphertext, tag = cipher.encrypt_and_digest(json.dumps(data).encode('utf-8'))
            # 拼接: nonce (16) + tag (16) + ciphertext
            return cipher.nonce + tag + ciphertext
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return b""

    def _decrypt(self, blob: bytes) -> Optional[Dict[str, Any]]:
        """使用 AES-GCM 解密数据，并验证完整性"""
        if not blob or len(blob) < 32:
            return None
        try:
            nonce = blob[:16]
            tag = blob[16:32]
            ciphertext = blob[32:]
            cipher = AES.new(self._encryption_key, AES.MODE_GCM, nonce=nonce)
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            return json.loads(plaintext.decode('utf-8'))
        except (ValueError, KeyError) as e:
            logger.error(f"Decryption failed (Tamper detected or Wrong key): {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected decryption error: {e}")
            return None

    def get_stats(self, instance: str, month: str) -> Dict[str, Any]:
        """获取指定实例和月份的统计数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT encrypted_blob FROM cl1_data WHERE instance = ? AND month = ?", 
                             (instance, month))
                row = cursor.fetchone()
                if row:
                    data = self._decrypt(row[0])
                    if data:
                        return data
        except Exception as e:
            logger.error(f"Failed to query stats for {instance} {month}: {e}")
        
        return self._empty_data(month)

    def _empty_data(self, month: str) -> Dict[str, Any]:
        return {
            'battle_count': 0,
            'akashi_encounters': 0,
            'akashi_ap': 0,
            'akashi_ap_entries': [],
            # 短猫数据
            'meow_battle_raw_count': 0,
            'meow_battle_count': 0,
            'meow_round_times': [],
            'meow_battle_times': [],  # 短猫单场战斗时间
            # 委托收益数据
            'commission_income_entries': [],
        }

    def _normalize_meow_round_times(self, round_times: List[Any]) -> List[Dict[str, Any]]:
        """兼容旧格式短猫轮次样本，统一为字典结构。"""
        normalized_times = []
        for entry in round_times:
            if isinstance(entry, dict) and 'duration' in entry:
                normalized_times.append(entry)
            elif isinstance(entry, (int, float)):
                normalized_times.append({'duration': float(entry), 'hazard_level': None})

        return normalized_times

    def _extract_meow_round_durations(self, round_times: List[Any]) -> List[float]:
        """提取短猫轮次耗时，兼容旧格式浮点样本。"""
        return [entry['duration'] for entry in self._normalize_meow_round_times(round_times)]

    def _infer_meow_battles_per_round(self, round_times: List[Any]) -> Tuple[Optional[int], Optional[float]]:
        """从短猫样本推断每轮战斗数。"""
        hazard_levels = []
        for entry in round_times:
            if isinstance(entry, dict):
                hazard_level = entry.get('hazard_level')
                if hazard_level in [2, 3, 4, 5, 6]:
                    hazard_levels.append(hazard_level)

        if not hazard_levels:
            return None, None

        battles_per_round_samples = [2 if hazard_level in [2, 3] else 3 for hazard_level in hazard_levels]
        inferred_battles_per_round = sum(battles_per_round_samples) / len(battles_per_round_samples)
        inferred_divisor = 2 if inferred_battles_per_round < 2.5 else 3
        return inferred_divisor, inferred_battles_per_round

    def _estimate_meow_raw_battle_count(self, effective_rounds: float, inferred_battles_per_round: Optional[float]) -> Optional[int]:
        """由等效轮次反推真实战斗场次。"""
        if effective_rounds <= 0:
            return None
        if inferred_battles_per_round is not None:
            return int(round(effective_rounds * inferred_battles_per_round))
        return int(round(effective_rounds * 3))

    def _reconcile_meow_counts(
        self,
        data: Dict[str, Any],
        effective_rounds: float,
        round_times: List[Any],
        battle_times: List[Any],
        instance: Optional[str] = None,
        month_key: Optional[str] = None,
        persist: bool = False,
    ) -> Tuple[int, float, bool]:
        """兼容旧数据并修正短猫真实战斗场次与等效轮次。"""
        inferred_divisor, inferred_battles_per_round = self._infer_meow_battles_per_round(round_times)
        estimated_from_rounds = self._estimate_meow_raw_battle_count(effective_rounds, inferred_battles_per_round)

        raw_battle_count = data.get('meow_battle_raw_count')
        current_raw = int(raw_battle_count) if raw_battle_count is not None else 0
        by_battle_times = len(battle_times) if battle_times else 0
        should_save = False

        need_backfill = raw_battle_count is None
        if estimated_from_rounds is not None and current_raw > 0:
            if current_raw < int(estimated_from_rounds * 0.85):
                need_backfill = True

        if need_backfill:
            candidates = [candidate for candidate in [current_raw, estimated_from_rounds, by_battle_times] if candidate is not None]
            raw_battle_count = max(candidates) if candidates else int(round(effective_rounds))
            data['meow_battle_raw_count'] = int(raw_battle_count)
            should_save = True

            if inferred_divisor in [2, 3] and effective_rounds > 0:
                data['meow_battle_count'] = round(int(raw_battle_count) / inferred_divisor, 2)
                effective_rounds = float(data['meow_battle_count'])
        else:
            raw_battle_count = current_raw

        if int(raw_battle_count) > 0 and effective_rounds > 0:
            ratio = float(raw_battle_count) / float(effective_rounds)
            if ratio > 5:
                divisor_for_fix = inferred_divisor if inferred_divisor in [2, 3] else 3
                fixed_rounds = round(int(raw_battle_count) / divisor_for_fix, 2)
                if abs(fixed_rounds - effective_rounds) > 0.01:
                    data['meow_battle_count'] = fixed_rounds
                    effective_rounds = float(fixed_rounds)
                    should_save = True

        if should_save and persist and instance and month_key:
            self.save_stats(instance, month_key, data)

        return int(raw_battle_count), effective_rounds, should_save

    def _list_stats_rows(self, instance: Optional[str] = None) -> List[Tuple[str, str]]:
        """列出数据库中已有的实例与月份。"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if instance:
                    cursor.execute(
                        "SELECT instance, month FROM cl1_data WHERE instance = ? ORDER BY month",
                        (instance,),
                    )
                else:
                    cursor.execute("SELECT instance, month FROM cl1_data ORDER BY instance, month")
                return [(row[0], row[1]) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to list stats rows: {e}")
            return []

    def backfill_meow_stats(self, instance: str, year: int = None, month: int = None) -> bool:
        """显式回填指定月份的短猫统计。

        仅在主动调用时落盘，避免读取统计时产生写入副作用。
        """
        if year is None or month is None:
            now = datetime.now()
            year = now.year
            month = now.month

        month_key = f"{year:04d}-{month:02d}"
        data = self.get_stats(instance, month_key)
        round_times = data.get('meow_round_times', [])
        battle_times = data.get('meow_battle_times', [])
        effective_rounds = float(data.get('meow_battle_count', 0) or 0)

        _, _, changed = self._reconcile_meow_counts(
            data=data,
            effective_rounds=effective_rounds,
            round_times=round_times,
            battle_times=battle_times,
            instance=instance,
            month_key=month_key,
            persist=True,
        )
        return changed

    def backfill_all_meow_stats(self, instance: Optional[str] = None) -> Dict[str, int]:
        """批量回填数据库内已有月份的短猫统计。"""
        rows = self._list_stats_rows(instance=instance)
        result = {'checked': 0, 'updated': 0}

        for row_instance, month_key in rows:
            if len(month_key) != 7 or month_key[4] != '-':
                continue

            try:
                year = int(month_key[:4])
                month = int(month_key[5:7])
            except ValueError:
                continue

            result['checked'] += 1
            if self.backfill_meow_stats(row_instance, year, month):
                result['updated'] += 1

        return result

    def save_stats(self, instance: str, month: str, data: Dict[str, Any]):
        """保存统计数据"""
        try:
            blob = self._encrypt(data)
            if not blob:
                return
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO cl1_data (instance, month, encrypted_blob) 
                    VALUES (?, ?, ?)
                    ON CONFLICT(instance, month) DO UPDATE SET encrypted_blob = excluded.encrypted_blob
                ''', (instance, month, blob))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save stats for {instance} {month}: {e}")

    def increment_battle_count(self, instance: str, delta: int = 1):
        """增加战斗次数"""
        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)
        data['battle_count'] = data.get('battle_count', 0) + delta
        self.save_stats(instance, month, data)

    def increment_akashi_encounter(self, instance: str):
        """增加明石奇遇次数"""
        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)
        data['akashi_encounters'] = data.get('akashi_encounters', 0) + 1
        self.save_stats(instance, month, data)

    def add_akashi_ap_entry(self, instance: str, amount: int, base: int, count: int, source: str):
        """记录明石行动力购买条目"""
        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)
        
        entry = {
            'ts': datetime.now().isoformat(),
            'amount': amount,
            'base': base,
            'count': count,
            'source': source
        }
        
        entries = data.get('akashi_ap_entries', [])
        entries.append(entry)
        data['akashi_ap_entries'] = entries
        
        data['akashi_ap'] = data.get('akashi_ap', 0) + amount
        self.save_stats(instance, month, data)

    def add_ap_snapshot(self, instance: str, ap_current: int, source: str = 'cl1'):
        """记录行动力快照（真实剩余体力）

        Args:
            instance: 实例名称
            ap_current: 当前行动力剩余
            source: 数据来源标记 (cl1 / meow 等)
        """
        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)

        snapshot = {
            'ts': datetime.now().isoformat(),
            'ap': int(ap_current),
            'source': source,
        }

        snapshots = data.get('ap_snapshots', [])
        snapshots.append(snapshot)
        data['ap_snapshots'] = snapshots
        self.save_stats(instance, month, data)

    def migrate_from_json(self, json_path: Path, instance: str):
        """从 JSON 文件迁移数据到数据库"""
        if not json_path.exists():
            return
        
        logger.info(f"Migrating CL1 data from {json_path} for instance {instance}")
        try:
            with json_path.open('r', encoding='utf-8') as f:
                old_data = json.load(f)
            
            if not isinstance(old_data, dict):
                return

            # JSON 格式比较杂乱，需要按月份归档
            # 格式可能是: {"2026-02": 10, "2026-02-akashi": 1, "2026-02-akashi-ap": 120, "2026-02-akashi-ap-entries": [...]}
            months = set()
            for key in old_data.keys():
                if len(key) >= 7 and key[4] == '-':
                    months.add(key[:7])
            
            for month in months:
                # 首先检查数据库是否已有数据，避免覆盖
                with sqlite3.connect(self.db_path) as conn:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM cl1_data WHERE instance = ? AND month = ?", (instance, month))
                    if c.fetchone():
                        logger.info(f"Data for {instance} {month} already exists in DB, skipping migration")
                        continue

                new_stats = self._empty_data(month)
                new_stats['battle_count'] = old_data.get(month, 0)
                new_stats['akashi_encounters'] = old_data.get(f"{month}-akashi", 0)
                new_stats['akashi_ap'] = old_data.get(f"{month}-akashi-ap", 0)
                new_stats['akashi_ap_entries'] = old_data.get(f"{month}-akashi-ap-entries", [])
                
                self.save_stats(instance, month, new_stats)
                logger.info(f"Successfully migrated {instance} {month}")

            # 迁移成功后可以删除 JSON 或重命名 (此处建议重命名为 .bak 以防万一)
            bak_path = json_path.with_suffix('.json.bak')
            json_path.replace(bak_path)
            logger.info(f"Retired old JSON to {bak_path}")

        except Exception as e:
            logger.exception(f"Failed to migrate CL1 data from JSON: {e}")

    def _auto_migrate(self):
        """
        初始化时自动扫描 log/cl1 下的所有实例并迁移旧数据
        """
        project_root = Path(__file__).resolve().parents[2]
        old_db_dir = project_root / 'log' / 'cl1'
        old_db_path = old_db_dir / 'cl1_data.db'

        if old_db_path.exists() and not self.db_path.exists():
            import shutil
            try:
                shutil.move(str(old_db_path), str(self.db_path))
                logger.info(f"Moved old CL1 database from {old_db_path} to {self.db_path}")
            except Exception as e:
                logger.error(f"Failed to move old CL1 database: {e}")

        if not old_db_dir.exists():
            return
            
        # logger.info(f"Scanning for legacy CL1 data in {old_db_dir}...")
        try:
            for instance_dir in old_db_dir.iterdir():
                if instance_dir.is_dir():
                    json_file = instance_dir / 'cl1_monthly.json'
                    if json_file.exists():
                        # logger.info(f"Found legacy data for instance: {instance_dir.name}")
                        self.migrate_from_json(json_file, instance_dir.name)
        except Exception as e:
            logger.error(f"Error during auto migration scan: {e}")

    # ========== 短猫数据记录方法 ==========

    def increment_meow_battle_count(self, instance: str, hazard_level: int = None, delta: float = None):
        """增加短猫有效战斗轮数

        Args:
            instance: 实例名称
            hazard_level: 侵蚀等级，用于换算有效战斗轮数（2-3: 每轮2次, 4-6: 每轮3次）
            delta: 直接指定增加的有效轮数，用于向后兼容。如果提供此参数，则忽略 hazard_level
        """
        # 根据侵蚀等级换算有效战斗轮数
        # 侵蚀2-3: 每轮2次战斗 -> 有效轮数 = 战斗次数 / 2
        # 侵蚀4-6: 每轮3次战斗 -> 有效轮数 = 战斗次数 / 3
        if delta is not None:
            # 直接使用 delta，保持向后兼容
            pass
        elif hazard_level is not None and hazard_level in [2, 3, 4, 5, 6]:
            if hazard_level in [2, 3]:
                delta = 0.5  # 2次战斗算1轮
            else:  # 4, 5, 6
                delta = 1 / 3  # 3次战斗算1轮
        else:
            delta = 1  # 默认直接加1

        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)
        data['meow_battle_raw_count'] = data.get('meow_battle_raw_count', 0) + 1
        data['meow_battle_count'] = data.get('meow_battle_count', 0) + delta
        self.save_stats(instance, month, data)

    def add_meow_round_time(self, instance: str, duration: float, hazard_level: int = None):
        """记录短猫单轮战斗时间

        Args:
            instance: 实例名称
            duration: 战斗耗时（秒）
            hazard_level: 侵蚀等级，用于计算出击轮次（2-6）
        """
        # 验证 hazard_level 是否在有效范围内
        if hazard_level is not None and hazard_level not in [2, 3, 4, 5, 6]:
            logger.debug(f'Invalid hazard_level {hazard_level}, ignoring')
            hazard_level = None

        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)

        normalized_times = self._normalize_meow_round_times(data.get('meow_round_times', []))

        # 保存为字典，包含时长和侵蚀等级
        new_entry = {
            'duration': round(duration, 2),
            'hazard_level': hazard_level
        }
        normalized_times.append(new_entry)

        # 只保留最近100个样本
        if len(normalized_times) > 100:
            normalized_times = normalized_times[-100:]

        data['meow_round_times'] = normalized_times
        self.save_stats(instance, month, data)

    def add_meow_battle_time(self, instance: str, duration: float):
        """记录短猫单场战斗时间

        Args:
            instance: 实例名称
            duration: 战斗耗时（秒）
        """
        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)

        if 'meow_battle_times' not in data:
            data['meow_battle_times'] = []

        times = data['meow_battle_times']
        times.append(round(duration, 2))

        # 只保留最近100个样本
        if len(times) > 100:
            times = times[-100:]

        data['meow_battle_times'] = times
        self.save_stats(instance, month, data)

    def get_meow_stats(self, instance: str, year: int = None, month: int = None) -> Dict[str, Any]:
        """获取短猫统计数据

        Args:
            instance: 实例名称
            year: 年份，默认当前年
            month: 月份，默认当前月

        Returns:
            短猫统计数据字典
        """
        if year is None or month is None:
            now = datetime.now()
            year = now.year
            month = now.month
        key = f"{year:04d}-{month:02d}"

        data = self.get_stats(instance, key)

        round_times = data.get('meow_round_times', [])
        battle_times = data.get('meow_battle_times', [])

        effective_rounds = float(data.get('meow_battle_count', 0) or 0)
        battle_count, effective_rounds, _ = self._reconcile_meow_counts(
            data=data,
            effective_rounds=effective_rounds,
            round_times=round_times,
            battle_times=battle_times,
            instance=instance,
            month_key=key,
            persist=True,
        )

        round_durations = self._extract_meow_round_durations(round_times)

        # 计算平均每轮时间
        avg_round_time = 0.0
        if round_durations:
            avg_round_time = round(sum(round_durations) / len(round_durations), 2)

        # 计算平均单场战斗时间
        avg_battle_time = 0.0
        if battle_times:
            avg_battle_time = round(sum(battle_times) / len(battle_times), 2)

        return {
            'month': key,
            'battle_count': battle_count,
            'effective_rounds': round(effective_rounds, 2),
            'round_times': round_times,
            'avg_round_time': avg_round_time,
            'battle_times': battle_times,
            'avg_battle_time': avg_battle_time,
        }
    def async_get_stats(self, instance: str, month: str):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.get_stats, instance, month)

    def async_save_stats(self, instance: str, month: str, data: Dict[str, Any]):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.save_stats, instance, month, data)

    def async_increment_battle_count(self, instance: str, delta: int = 1):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.increment_battle_count, instance, delta)

    def async_increment_akashi_encounter(self, instance: str):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.increment_akashi_encounter, instance)

    def async_add_akashi_ap_entry(self, instance: str, amount: int, base: int, count: int, source: str):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.add_akashi_ap_entry, instance, amount, base, count, source)

    def async_add_ap_snapshot(self, instance: str, ap_current: int, source: str = 'cl1'):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.add_ap_snapshot, instance, ap_current, source)

    def async_increment_meow_battle_count(self, instance: str, hazard_level: int = None, delta: float = None):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.increment_meow_battle_count, instance, hazard_level, delta)

    def async_add_meow_round_time(self, instance: str, duration: float, hazard_level: int = None):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.add_meow_round_time, instance, duration, hazard_level)

    def async_add_meow_battle_time(self, instance: str, duration: float):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.add_meow_battle_time, instance, duration)

    def async_get_meow_stats(self, instance: str, year: int = None, month: int = None):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.get_meow_stats, instance, year, month)

    # ========== 委托收益数据记录方法 ==========

    def add_commission_income(self, instance: str, items: Dict[str, int], commission_count: int = 1):
        """记录一次委托收益

        Args:
            instance: 实例名称
            items: 物品字典，如 {'Gem': 30, 'Cube': 1, 'Chip': 10, 'Oil': 500, 'Coin': 800}
            commission_count: 本次结算的委托数量
        """
        month = datetime.now().strftime('%Y-%m')
        data = self.get_stats(instance, month)

        entry = {
            'ts': datetime.now().isoformat(),
            'items': {k: int(v) for k, v in items.items() if v > 0},
            'commission_count': int(commission_count),
        }

        entries = data.get('commission_income_entries', [])
        entries.append(entry)
        if len(entries) > 5000:
            entries = entries[-5000:]
        data['commission_income_entries'] = entries
        self.save_stats(instance, month, data)

    def get_commission_income(self, instance: str, year: int = None, month: int = None) -> List[Dict[str, Any]]:
        """获取指定月份的委托收益条目列表

        Args:
            instance: 实例名称
            year: 年份，默认当前年
            month: 月份，默认当前月

        Returns:
            委托收益条目列表，每个条目包含 ts, items, commission_count
        """
        if year is None or month is None:
            now = datetime.now()
            if year is None:
                year = now.year
            if month is None:
                month = now.month

        month_key = f"{year:04d}-{month:02d}"
        data = self.get_stats(instance, month_key)
        return data.get('commission_income_entries', [])

    def async_add_commission_income(self, instance: str, items: Dict[str, int], commission_count: int = 1):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.add_commission_income, instance, items, commission_count)

    def async_get_commission_income(self, instance: str, year: int = None, month: int = None):
        from module.base.async_executor import async_executor
        return async_executor.submit(self.get_commission_income, instance, year, month)


# 单例实例
db = Cl1Database()

