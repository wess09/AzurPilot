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

from module.base.device_id import get_device_id, get_old_device_id
from module.logger import logger


class Cl1Database:
    def _empty_siren_research_devices(self) -> dict:
        return {"cl1": 0, "meow": {}}

    def _normalize_siren_research_devices(self, data: dict) -> dict:
        devices = data.get("siren_research_devices")
        if not isinstance(devices, dict):
            devices = self._empty_siren_research_devices()
        try:
            devices["cl1"] = int(devices.get("cl1", 0) or 0)
        except (TypeError, ValueError):
            devices["cl1"] = 0
        meow = devices.get("meow")
        if not isinstance(meow, dict):
            meow = {}
        normalized_meow = {}
        for key, value in meow.items():
            try:
                normalized_meow[str(int(key))] = int(value or 0)
            except (TypeError, ValueError):
                continue
        devices["meow"] = normalized_meow
        data["siren_research_devices"] = devices
        return devices

    def get_siren_research_device_count(
        self, data: dict, source: str = "cl1", hazard_level: int = None
    ) -> int:
        devices = self._normalize_siren_research_devices(data)
        if source == "meow":
            if hazard_level is None:
                return sum(
                    int(value or 0) for value in devices.get("meow", {}).values()
                )
            return int(devices.get("meow", {}).get(str(int(hazard_level)), 0) or 0)
        return int(devices.get("cl1", 0) or 0)

    """
    CL1 数据加密 SQLite 数据库管理类。
    所有实例共享一个数据库文件，但数据经过 AES-GCM 加密，并由 device_id 保护。
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            project_root = Path(__file__).resolve().parents[2]
            self.db_dir = project_root / "config"
            self.db_path = self.db_dir / "cl1_data.db"
        else:
            self.db_path = db_path
            self.db_dir = self.db_path.parent

        self._ensure_dir()
        self._init_db()
        self._encryption_key = self._derive_key(get_device_id())
        self._check_key_migration()
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
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cl1_data (
                        instance TEXT,
                        month TEXT,
                        encrypted_blob BLOB,
                        PRIMARY KEY (instance, month)
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.exception(f"Failed to initialize CL1 database: {e}")

    def _derive_key(self, device_id: str) -> bytes:
        """基于 device_id 派生 256 位 AES 密钥"""
        salt = b"AlasCl1SecureStorage"  # 固定盐
        return PBKDF2(
            device_id.encode(), salt, dkLen=32, count=1000, hmac_hash_module=SHA256
        )

    def _check_key_migration(self):
        """
        探测 device_id 变更并进行全库重加密迁移
        """
        old_id = get_old_device_id()
        if not old_id:
            return

        logger.info("Starting local database migration (Device ID changed)...")
        old_key = self._derive_key(old_id)

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT instance, month, encrypted_blob FROM cl1_data")
                rows = cursor.fetchall()

                if not rows:
                    return

                logger.info(f"Re-encrypting {len(rows)} entries with new key...")
                updated_rows = []
                for instance, month, blob in rows:
                    # 1. 用旧密钥解密
                    data = self._decrypt_with_key(blob, old_key)
                    if data:
                        # 2. 用新密钥重加密 (self._encrypt 使用的是当前 self._encryption_key)
                        new_blob = self._encrypt(data)
                        updated_rows.append((new_blob, instance, month))

                # 批量写回
                if updated_rows:
                    cursor.executemany(
                        "UPDATE cl1_data SET encrypted_blob = ? WHERE instance = ? AND month = ?",
                        updated_rows,
                    )
                    conn.commit()
                    logger.info("Local database migration completed successfully.")
        except Exception as e:
            logger.error(f"Failed to migrate database to new device_id: {e}")

    def _decrypt_with_key(self, blob: bytes, key: bytes) -> Optional[Dict[str, Any]]:
        """辅助方法：使用指定密钥进行解密"""
        if not blob or len(blob) < 32:
            return None
        try:
            nonce = blob[:16]
            tag = blob[16:32]
            ciphertext = blob[32:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            return json.loads(plaintext.decode("utf-8"))
        except Exception:
            return None

    def _encrypt(self, data: Dict[str, Any]) -> bytes:
        """使用 AES-GCM 加密数据"""
        try:
            cipher = AES.new(self._encryption_key, AES.MODE_GCM)
            ciphertext, tag = cipher.encrypt_and_digest(
                json.dumps(data).encode("utf-8")
            )
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
            return json.loads(plaintext.decode("utf-8"))
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
                cursor.execute(
                    "SELECT encrypted_blob FROM cl1_data WHERE instance = ? AND month = ?",
                    (instance, month),
                )
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
            "battle_count": 0,
            "akashi_encounters": 0,
            "akashi_ap": 0,
            "akashi_ap_entries": [],
            "yellow_coin_snapshots": [],
            "coins_snapshots": [],
            # 短猫数据
            "meow_battle_raw_count": 0,
            "meow_battle_count": 0,
            "meow_round_times": [],
            "meow_battle_times": [],  # 短猫单场战斗时间
            "meow_hazard_stats": {},  # 按侵蚀等级拆分统计
            # 委托收益数据
            "commission_income_entries": [],
        }

    def _normalize_meow_round_times(
        self, round_times: List[Any]
    ) -> List[Dict[str, Any]]:
        """兼容旧格式短猫轮次样本，统一为字典结构。"""
        normalized_times = []
        for entry in round_times:
            if isinstance(entry, dict) and "duration" in entry:
                normalized_times.append(entry)
            elif isinstance(entry, (int, float)):
                normalized_times.append(
                    {"duration": float(entry), "hazard_level": None}
                )

        return normalized_times

    def _extract_meow_round_durations(self, round_times: List[Any]) -> List[float]:
        """提取短猫轮次耗时，兼容旧格式浮点样本。"""
        return [
            entry["duration"] for entry in self._normalize_meow_round_times(round_times)
        ]

    @staticmethod
    def _get_meow_battles_per_round(hazard_level: Optional[int]) -> Optional[int]:
        """根据侵蚀等级返回每轮战斗次数。"""
        if hazard_level in [2, 3]:
            return 2
        if hazard_level in [4, 5, 6]:
            return 3
        return None

    def _normalize_meow_hazard_stats(
        self, data: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """兼容旧格式的分级短猫统计结构。"""
        raw_stats = data.get("meow_hazard_stats", {})
        if not isinstance(raw_stats, dict):
            return {}

        normalized: Dict[str, Dict[str, Any]] = {}
        for hazard_key, bucket in raw_stats.items():
            try:
                hazard_level = int(hazard_key)
            except (TypeError, ValueError):
                continue
            if hazard_level not in [2, 3, 4, 5, 6] or not isinstance(bucket, dict):
                continue

            round_times = bucket.get("round_times", [])
            if not isinstance(round_times, list):
                round_times = []
            normalized_round_times: List[float] = []
            for entry in round_times:
                if isinstance(entry, (int, float)):
                    normalized_round_times.append(float(entry))
                elif isinstance(entry, dict) and isinstance(
                    entry.get("duration"), (int, float)
                ):
                    normalized_round_times.append(float(entry.get("duration")))

            battle_times = bucket.get("battle_times", [])
            if not isinstance(battle_times, list):
                battle_times = []
            normalized_battle_times: List[float] = []
            for entry in battle_times:
                if isinstance(entry, (int, float)):
                    normalized_battle_times.append(float(entry))
                elif isinstance(entry, dict) and isinstance(
                    entry.get("duration"), (int, float)
                ):
                    normalized_battle_times.append(float(entry.get("duration")))

            try:
                battle_raw_count = int(bucket.get("battle_raw_count", 0) or 0)
            except Exception:
                battle_raw_count = 0

            try:
                effective_rounds = float(bucket.get("effective_rounds", 0) or 0)
            except Exception:
                effective_rounds = 0.0

            normalized[str(hazard_level)] = {
                "battle_raw_count": max(0, battle_raw_count),
                "effective_rounds": max(0.0, effective_rounds),
                "round_times": normalized_round_times,
                "battle_times": normalized_battle_times,
            }

        return normalized

    def _ensure_meow_hazard_bucket(
        self, hazard_stats: Dict[str, Dict[str, Any]], hazard_level: int
    ) -> Dict[str, Any]:
        """确保指定侵蚀等级的统计桶存在。"""
        key = str(hazard_level)
        bucket = hazard_stats.get(key)
        if not isinstance(bucket, dict):
            bucket = {
                "battle_raw_count": 0,
                "effective_rounds": 0.0,
                "round_times": [],
                "battle_times": [],
            }
            hazard_stats[key] = bucket

        if not isinstance(bucket.get("round_times"), list):
            bucket["round_times"] = []
        if not isinstance(bucket.get("battle_times"), list):
            bucket["battle_times"] = []
        return bucket

    def _infer_meow_battles_per_round(
        self, round_times: List[Any]
    ) -> Tuple[Optional[int], Optional[float]]:
        """从短猫样本推断每轮战斗数。"""
        hazard_levels = []
        for entry in round_times:
            if isinstance(entry, dict):
                hazard_level = entry.get("hazard_level")
                if hazard_level in [2, 3, 4, 5, 6]:
                    hazard_levels.append(hazard_level)

        if not hazard_levels:
            return None, None

        battles_per_round_samples = [
            2 if hazard_level in [2, 3] else 3 for hazard_level in hazard_levels
        ]
        inferred_battles_per_round = sum(battles_per_round_samples) / len(
            battles_per_round_samples
        )
        inferred_divisor = 2 if inferred_battles_per_round < 2.5 else 3
        return inferred_divisor, inferred_battles_per_round

    def _estimate_meow_raw_battle_count(
        self, effective_rounds: float, inferred_battles_per_round: Optional[float]
    ) -> Optional[int]:
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
        inferred_divisor, inferred_battles_per_round = (
            self._infer_meow_battles_per_round(round_times)
        )
        estimated_from_rounds = self._estimate_meow_raw_battle_count(
            effective_rounds, inferred_battles_per_round
        )

        raw_battle_count = data.get("meow_battle_raw_count")
        current_raw = int(raw_battle_count) if raw_battle_count is not None else 0
        by_battle_times = len(battle_times) if battle_times else 0
        should_save = False

        need_backfill = raw_battle_count is None
        if estimated_from_rounds is not None and current_raw > 0:
            if current_raw < int(estimated_from_rounds * 0.85):
                need_backfill = True

        if need_backfill:
            candidates = [
                candidate
                for candidate in [current_raw, estimated_from_rounds, by_battle_times]
                if candidate is not None
            ]
            raw_battle_count = (
                max(candidates) if candidates else int(round(effective_rounds))
            )
            data["meow_battle_raw_count"] = int(raw_battle_count)
            should_save = True

            if inferred_divisor in [2, 3] and effective_rounds > 0:
                data["meow_battle_count"] = round(
                    int(raw_battle_count) / inferred_divisor, 2
                )
                effective_rounds = float(data["meow_battle_count"])
        else:
            raw_battle_count = current_raw

        if int(raw_battle_count) > 0 and effective_rounds > 0:
            ratio = float(raw_battle_count) / float(effective_rounds)
            if ratio > 5:
                divisor_for_fix = inferred_divisor if inferred_divisor in [2, 3] else 3
                fixed_rounds = round(int(raw_battle_count) / divisor_for_fix, 2)
                if abs(fixed_rounds - effective_rounds) > 0.01:
                    data["meow_battle_count"] = fixed_rounds
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
                    cursor.execute(
                        "SELECT instance, month FROM cl1_data ORDER BY instance, month"
                    )
                return [(row[0], row[1]) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to list stats rows: {e}")
            return []

    def backfill_meow_stats(
        self, instance: str, year: int = None, month: int = None
    ) -> bool:
        """显式回填指定月份的短猫统计。

        仅在主动调用时落盘，避免读取统计时产生写入副作用。
        """
        if year is None or month is None:
            now = datetime.now()
            year = now.year
            month = now.month

        month_key = f"{year:04d}-{month:02d}"
        data = self.get_stats(instance, month_key)
        round_times = data.get("meow_round_times", [])
        battle_times = data.get("meow_battle_times", [])
        effective_rounds = float(data.get("meow_battle_count", 0) or 0)

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
        result = {"checked": 0, "updated": 0}

        for row_instance, month_key in rows:
            if len(month_key) != 7 or month_key[4] != "-":
                continue

            try:
                year = int(month_key[:4])
                month = int(month_key[5:7])
            except ValueError:
                continue

            result["checked"] += 1
            if self.backfill_meow_stats(row_instance, year, month):
                result["updated"] += 1

        return result

    def save_stats(self, instance: str, month: str, data: Dict[str, Any]):
        """保存统计数据"""
        try:
            blob = self._encrypt(data)
            if not blob:
                return
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO cl1_data (instance, month, encrypted_blob) 
                    VALUES (?, ?, ?)
                    ON CONFLICT(instance, month) DO UPDATE SET encrypted_blob = excluded.encrypted_blob
                """,
                    (instance, month, blob),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save stats for {instance} {month}: {e}")

    def increment_battle_count(self, instance: str, delta: int = 1):
        """增加战斗次数"""
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)
        data["battle_count"] = data.get("battle_count", 0) + delta
        self.save_stats(instance, month, data)

    def increment_akashi_encounter(self, instance: str):
        """增加明石奇遇次数"""
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)
        data["akashi_encounters"] = data.get("akashi_encounters", 0) + 1
        self.save_stats(instance, month, data)

    def add_akashi_ap_entry(
        self, instance: str, amount: int, base: int, count: int, source: str
    ):
        """记录明石行动力购买条目"""
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)

        entry = {
            "ts": datetime.now().isoformat(),
            "amount": amount,
            "base": base,
            "count": count,
            "source": source,
        }

        entries = data.get("akashi_ap_entries", [])
        entries.append(entry)
        data["akashi_ap_entries"] = entries

        data["akashi_ap"] = data.get("akashi_ap", 0) + amount
        self.save_stats(instance, month, data)

    def add_ap_snapshot(self, instance: str, ap_current: int, source: str = "cl1", distance: int = None):
        """记录行动力快照（真实剩余体力），并计算虚拟资产

        Args:
            instance: 实例名称
            ap_current: 当前行动力剩余
            source: 数据来源标记 (cl1 / meow 等)
            distance: 海里数（可选）
        """
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)
        now = datetime.now()

        # 计算虚拟资产
        # 虚拟资产 = AP × (1700/30) + YellowCoins + (到月底时间/10分钟) × (1700/30)
        from calendar import monthrange

        year, month_num = now.year, now.month
        last_day = monthrange(year, month_num)[1]
        month_end = datetime(year, month_num, last_day, 23, 59, 59)
        time_to_month_end_sec = (month_end - now).total_seconds()

        # CL5 效率：1700 / 30 ≈ 56.67
        cl5_efficiency = 1700.0 / 30.0
        virtual_asset_added = (time_to_month_end_sec / 600.0) * cl5_efficiency

        # 获取最近的黄币值
        yellow_coin = 0
        yellow_coin_snapshots = data.get("yellow_coin_snapshots", [])
        if yellow_coin_snapshots:
            try:
                yellow_coin = int(yellow_coin_snapshots[-1].get("yellow_coin", 0))
            except Exception:
                pass

        # 资产 = AP × 效率 + 黄币
        asset = ap_current * cl5_efficiency + yellow_coin
        # 虚拟资产 = 资产 + 时间加成
        virtual_asset = asset + virtual_asset_added

        snapshot = {
            "ts": now.isoformat(),
            "ap": int(ap_current),
            "yellow_coin": int(yellow_coin),
            "asset": round(asset, 2),
            "virtual_asset": round(virtual_asset, 2),
            "source": source,
        }
        if distance is not None:
            snapshot["distance"] = int(distance)

        snapshots = data.get("ap_snapshots", [])
        snapshots.append(snapshot)
        data["ap_snapshots"] = snapshots
        self.save_stats(instance, month, data)

    def get_last_ap_notification(self, instance: str) -> Optional[Dict[str, Any]]:
        """获取最近一次成功推送时记录的行动力值。"""
        current_month = datetime.now().strftime("%Y-%m")
        current_data = self.get_stats(instance, current_month)
        last_notification = current_data.get("last_ap_notification")
        if isinstance(last_notification, dict) and "ap" in last_notification:
            return last_notification

        rows = self._list_stats_rows(instance=instance)
        for _, month_key in reversed(rows):
            if month_key == current_month:
                continue
            data = self.get_stats(instance, month_key)
            last_notification = data.get("last_ap_notification")
            if isinstance(last_notification, dict) and "ap" in last_notification:
                return last_notification

        return None

    def set_last_ap_notification(self, instance: str, ap_current: int):
        """记录最近一次成功推送时的行动力值。"""
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)
        data["last_ap_notification"] = {
            "ts": datetime.now().isoformat(),
            "ap": int(ap_current),
        }
        self.save_stats(instance, month, data)

    def add_yellow_coin_snapshot(
        self, instance: str, yellow_coin: int, source: str = "dashboard"
    ):
        """记录黄币快照（用于统计页分时叠加曲线）

        Args:
            instance: 实例名称
            yellow_coin: 当前黄币
            source: 数据来源标记
        """
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)

        snapshot = {
            "ts": datetime.now().isoformat(),
            "yellow_coin": int(yellow_coin),
            "source": source,
        }

        snapshots = data.get("yellow_coin_snapshots", [])
        if snapshots:
            try:
                if int(snapshots[-1].get("yellow_coin", -1)) == int(yellow_coin):
                    return
            except Exception:
                pass
        snapshots.append(snapshot)
        data["yellow_coin_snapshots"] = snapshots
        self.save_stats(instance, month, data)

    def add_coins_snapshot(
        self,
        instance: str,
        yellow_coins: int,
        purple_coins: int = 0,
        source: str = "cl1",
    ):
        """记录凭证快照（作战补给凭证/特别兑换凭证）

        Args:
            instance: 实例名称
            yellow_coins: 当前作战补给凭证（黄币）数量
            purple_coins: 当前特别兑换凭证（紫币）数量
            source: 数据来源标记 (cl1 / meow 等)
        """
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)

        snapshot = {
            "ts": datetime.now().isoformat(),
            "yellow_coins": int(yellow_coins),
            "purple_coins": int(purple_coins),
            "source": source,
        }

        snapshots = data.get("coins_snapshots", [])
        if snapshots:
            try:
                last = snapshots[-1]
                if int(last.get("yellow_coins", -1)) == int(yellow_coins) and int(
                    last.get("purple_coins", -1)
                ) == int(purple_coins):
                    return
            except Exception:
                pass
        snapshots.append(snapshot)
        # 保留最近 500 条记录，避免数据过大
        if len(snapshots) > 500:
            snapshots = snapshots[-500:]
        data["coins_snapshots"] = snapshots
        self.save_stats(instance, month, data)

    def async_add_coins_snapshot(
        self,
        instance: str,
        yellow_coins: int,
        purple_coins: int = 0,
        source: str = "cl1",
    ):
        """异步记录凭证快照"""
        return async_executor.submit(
            self.add_coins_snapshot, instance, yellow_coins, purple_coins, source
        )

    def migrate_from_json(self, json_path: Path, instance: str):
        """从 JSON 文件迁移数据到数据库"""
        if not json_path.exists():
            return

        logger.info(f"Migrating CL1 data from {json_path} for instance {instance}")
        try:
            with json_path.open("r", encoding="utf-8") as f:
                old_data = json.load(f)

            if not isinstance(old_data, dict):
                return

            # JSON 格式比较杂乱，需要按月份归档
            # 格式可能是: {"2026-02": 10, "2026-02-akashi": 1, "2026-02-akashi-ap": 120, "2026-02-akashi-ap-entries": [...]}
            months = set()
            for key in old_data.keys():
                if len(key) >= 7 and key[4] == "-":
                    months.add(key[:7])

            for month in months:
                # 首先检查数据库是否已有数据，避免覆盖
                with sqlite3.connect(self.db_path) as conn:
                    c = conn.cursor()
                    c.execute(
                        "SELECT 1 FROM cl1_data WHERE instance = ? AND month = ?",
                        (instance, month),
                    )
                    if c.fetchone():
                        logger.info(
                            f"Data for {instance} {month} already exists in DB, skipping migration"
                        )
                        continue

                new_stats = self._empty_data(month)
                new_stats["battle_count"] = old_data.get(month, 0)
                new_stats["akashi_encounters"] = old_data.get(f"{month}-akashi", 0)
                new_stats["akashi_ap"] = old_data.get(f"{month}-akashi-ap", 0)
                new_stats["akashi_ap_entries"] = old_data.get(
                    f"{month}-akashi-ap-entries", []
                )

                self.save_stats(instance, month, new_stats)
                logger.info(f"Successfully migrated {instance} {month}")

            # 迁移成功后可以删除 JSON 或重命名 (此处建议重命名为 .bak 以防万一)
            bak_path = json_path.with_suffix(".json.bak")
            json_path.replace(bak_path)
            logger.info(f"Retired old JSON to {bak_path}")

        except Exception as e:
            logger.exception(f"Failed to migrate CL1 data from JSON: {e}")

    def _auto_migrate(self):
        """
        初始化时自动扫描 log/cl1 下的所有实例并迁移旧数据
        """
        project_root = Path(__file__).resolve().parents[2]
        old_db_dir = project_root / "log" / "cl1"
        old_db_path = old_db_dir / "cl1_data.db"

        if old_db_path.exists() and not self.db_path.exists():
            import shutil

            try:
                shutil.move(str(old_db_path), str(self.db_path))
                logger.info(
                    f"Moved old CL1 database from {old_db_path} to {self.db_path}"
                )
            except Exception as e:
                logger.error(f"Failed to move old CL1 database: {e}")

        if not old_db_dir.exists():
            return

        # logger.info(f"Scanning for legacy CL1 data in {old_db_dir}...")
        try:
            for instance_dir in old_db_dir.iterdir():
                if instance_dir.is_dir():
                    json_file = instance_dir / "cl1_monthly.json"
                    if json_file.exists():
                        # logger.info(f"Found legacy data for instance: {instance_dir.name}")
                        self.migrate_from_json(json_file, instance_dir.name)
        except Exception as e:
            logger.error(f"Error during auto migration scan: {e}")

    # ========== 短猫数据记录方法 ==========

    def increment_meow_battle_count(
        self, instance: str, hazard_level: int = None, delta: float = None
    ):
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
            try:
                delta = float(delta)
            except Exception:
                delta = 1
        elif hazard_level is not None and hazard_level in [2, 3, 4, 5, 6]:
            battles_per_round = self._get_meow_battles_per_round(hazard_level)
            delta = (1 / battles_per_round) if battles_per_round else 1
        else:
            delta = 1  # 默认直接加1

        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)
        data["meow_battle_raw_count"] = data.get("meow_battle_raw_count", 0) + 1
        data["meow_battle_count"] = data.get("meow_battle_count", 0) + delta

        if hazard_level in [2, 3, 4, 5, 6]:
            hazard_stats = self._normalize_meow_hazard_stats(data)
            bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
            bucket["battle_raw_count"] = int(bucket.get("battle_raw_count", 0) or 0) + 1
            bucket["effective_rounds"] = float(
                bucket.get("effective_rounds", 0) or 0
            ) + float(delta)
            data["meow_hazard_stats"] = hazard_stats

        self.save_stats(instance, month, data)

    def add_meow_round_time(
        self, instance: str, duration: float, hazard_level: int = None
    ):
        """记录短猫单轮战斗时间

        Args:
            instance: 实例名称
            duration: 战斗耗时（秒）
            hazard_level: 侵蚀等级，用于计算出击轮次（2-6）
        """
        # 验证 hazard_level 是否在有效范围内
        if hazard_level is not None and hazard_level not in [2, 3, 4, 5, 6]:
            logger.debug(f"Invalid hazard_level {hazard_level}, ignoring")
            hazard_level = None

        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)

        normalized_times = self._normalize_meow_round_times(
            data.get("meow_round_times", [])
        )

        # 保存为字典，包含时长和侵蚀等级
        new_entry = {"duration": round(duration, 2), "hazard_level": hazard_level}
        normalized_times.append(new_entry)

        # 只保留最近100个样本
        if len(normalized_times) > 100:
            normalized_times = normalized_times[-100:]

        data["meow_round_times"] = normalized_times

        if hazard_level in [2, 3, 4, 5, 6]:
            hazard_stats = self._normalize_meow_hazard_stats(data)
            bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
            round_times = bucket.get("round_times", [])
            round_times.append(round(duration, 2))
            if len(round_times) > 100:
                round_times = round_times[-100:]
            bucket["round_times"] = round_times
            data["meow_hazard_stats"] = hazard_stats

        self.save_stats(instance, month, data)

    def add_meow_battle_time(
        self, instance: str, duration: float, hazard_level: int = None
    ):
        """记录短猫单场战斗时间

        Args:
            instance: 实例名称
            duration: 战斗耗时（秒）
            hazard_level: 侵蚀等级（2-6），用于分级统计
        """
        if hazard_level is not None and hazard_level not in [2, 3, 4, 5, 6]:
            logger.debug(f"Invalid hazard_level {hazard_level}, ignoring")
            hazard_level = None

        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)

        if "meow_battle_times" not in data:
            data["meow_battle_times"] = []

        times = data["meow_battle_times"]
        times.append(round(duration, 2))

        # 只保留最近100个样本
        if len(times) > 100:
            times = times[-100:]

        data["meow_battle_times"] = times

        if hazard_level in [2, 3, 4, 5, 6]:
            hazard_stats = self._normalize_meow_hazard_stats(data)
            bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
            battle_times = bucket.get("battle_times", [])
            battle_times.append(round(duration, 2))
            if len(battle_times) > 100:
                battle_times = battle_times[-100:]
            bucket["battle_times"] = battle_times
            data["meow_hazard_stats"] = hazard_stats

        self.save_stats(instance, month, data)

    def get_meow_stats(
        self, instance: str, year: int = None, month: int = None
    ) -> Dict[str, Any]:
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

        round_times = data.get("meow_round_times", [])
        battle_times = data.get("meow_battle_times", [])
        normalized_round_times = self._normalize_meow_round_times(round_times)

        effective_rounds = float(data.get("meow_battle_count", 0) or 0)
        battle_count, effective_rounds, _ = self._reconcile_meow_counts(
            data=data,
            effective_rounds=effective_rounds,
            round_times=round_times,
            battle_times=battle_times,
            instance=instance,
            month_key=key,
            persist=True,
        )

        round_durations = [entry["duration"] for entry in normalized_round_times]

        # 计算平均每轮时间
        avg_round_time = 0.0
        if round_durations:
            avg_round_time = round(sum(round_durations) / len(round_durations), 2)

        # 计算平均单场战斗时间
        avg_battle_time = 0.0
        if battle_times:
            avg_battle_time = round(sum(battle_times) / len(battle_times), 2)

        # 按侵蚀等级拆分统计（重点展示 3 级与 5 级）
        hazard_stats = self._normalize_meow_hazard_stats(data)
        hazard_sample_total = 0
        hazard_round_samples: Dict[int, List[float]] = {3: [], 5: []}
        for entry in normalized_round_times:
            hazard_level = entry.get("hazard_level")
            if hazard_level in [2, 3, 4, 5, 6]:
                hazard_sample_total += 1
            if hazard_level in [3, 5]:
                hazard_round_samples[hazard_level].append(entry["duration"])

        by_hazard: Dict[str, Dict[str, Any]] = {}
        for hazard_level in [3, 5]:
            key_name = str(hazard_level)
            bucket = hazard_stats.get(key_name, {})

            try:
                hz_battle_count = int(bucket.get("battle_raw_count", 0) or 0)
            except Exception:
                hz_battle_count = 0

            try:
                hz_effective_rounds = float(bucket.get("effective_rounds", 0) or 0)
            except Exception:
                hz_effective_rounds = 0.0

            hz_round_times = (
                bucket.get("round_times", [])
                if isinstance(bucket.get("round_times"), list)
                else []
            )
            hz_round_times = [
                float(v) for v in hz_round_times if isinstance(v, (int, float))
            ]
            if not hz_round_times:
                hz_round_times = hazard_round_samples[hazard_level]

            hz_battle_times = (
                bucket.get("battle_times", [])
                if isinstance(bucket.get("battle_times"), list)
                else []
            )
            hz_battle_times = [
                float(v) for v in hz_battle_times if isinstance(v, (int, float))
            ]

            estimated = False
            if hz_battle_count <= 0 and hazard_sample_total > 0 and battle_count > 0:
                hz_battle_count = int(
                    round(
                        battle_count
                        * (
                            len(hazard_round_samples[hazard_level])
                            / hazard_sample_total
                        )
                    )
                )
                estimated = True

            battles_per_round = self._get_meow_battles_per_round(hazard_level) or 1
            if hz_effective_rounds <= 0 and hz_battle_count > 0:
                hz_effective_rounds = hz_battle_count / battles_per_round
                estimated = True

            hz_avg_round_time = 0.0
            if hz_round_times:
                hz_avg_round_time = round(sum(hz_round_times) / len(hz_round_times), 2)

            hz_avg_battle_time = 0.0
            if hz_battle_times:
                hz_avg_battle_time = round(
                    sum(hz_battle_times) / len(hz_battle_times), 2
                )
            elif hz_avg_round_time > 0:
                hz_avg_battle_time = round(hz_avg_round_time / battles_per_round, 2)

            source = "exact"
            if estimated and not bucket:
                source = "estimated"
            if (
                hz_battle_count <= 0
                and hz_effective_rounds <= 0
                and hz_avg_round_time <= 0
            ):
                source = "none"

            by_hazard[key_name] = {
                "hazard_level": hazard_level,
                "battle_count": hz_battle_count,
                "effective_rounds": round(hz_effective_rounds, 2),
                "avg_round_time": hz_avg_round_time,
                "avg_battle_time": hz_avg_battle_time,
                "sample_count": len(hz_round_times),
                "source": source,
            }

        return {
            "month": key,
            "battle_count": battle_count,
            "effective_rounds": round(effective_rounds, 2),
            "round_times": round_times,
            "avg_round_time": avg_round_time,
            "battle_times": battle_times,
            "avg_battle_time": avg_battle_time,
            "by_hazard": by_hazard,
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

    def async_add_akashi_ap_entry(
        self, instance: str, amount: int, base: int, count: int, source: str
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_akashi_ap_entry, instance, amount, base, count, source
        )

    def async_add_ap_snapshot(
        self, instance: str, ap_current: int, source: str = "cl1", distance: int = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(self.add_ap_snapshot, instance, ap_current, source, distance)

    def async_set_last_ap_notification(self, instance: str, ap_current: int):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.set_last_ap_notification, instance, ap_current
        )

    def async_add_yellow_coin_snapshot(
        self, instance: str, yellow_coin: int, source: str = "dashboard"
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_yellow_coin_snapshot, instance, yellow_coin, source
        )

    def async_increment_meow_battle_count(
        self, instance: str, hazard_level: int = None, delta: float = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.increment_meow_battle_count, instance, hazard_level, delta
        )

    def async_add_meow_round_time(
        self, instance: str, duration: float, hazard_level: int = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_meow_round_time, instance, duration, hazard_level
        )

    def async_add_meow_battle_time(
        self, instance: str, duration: float, hazard_level: int = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_meow_battle_time, instance, duration, hazard_level
        )

    def async_get_meow_stats(self, instance: str, year: int = None, month: int = None):
        from module.base.async_executor import async_executor

        return async_executor.submit(self.get_meow_stats, instance, year, month)

    # ========== 委托收益数据记录方法 ==========

    def add_commission_income(
        self, instance: str, items: Dict[str, int], commission_count: int = 1
    ):
        """记录一次委托收益

        Args:
            instance: 实例名称
            items: 物品字典，如 {'Gem': 30, 'Cube': 1, 'Chip': 10, 'Oil': 500, 'Coin': 800}
            commission_count: 本次结算的委托数量
        """
        month = datetime.now().strftime("%Y-%m")
        data = self.get_stats(instance, month)

        entry = {
            "ts": datetime.now().isoformat(),
            "items": {k: int(v) for k, v in items.items() if v > 0},
            "commission_count": int(commission_count),
        }

        entries = data.get("commission_income_entries", [])
        entries.append(entry)
        if len(entries) > 5000:
            entries = entries[-5000:]
        data["commission_income_entries"] = entries
        self.save_stats(instance, month, data)

    def get_commission_income(
        self, instance: str, year: int = None, month: int = None
    ) -> List[Dict[str, Any]]:
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
        return data.get("commission_income_entries", [])

    def async_add_commission_income(
        self, instance: str, items: Dict[str, int], commission_count: int = 1
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_commission_income, instance, items, commission_count
        )

    def async_get_commission_income(
        self, instance: str, year: int = None, month: int = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(self.get_commission_income, instance, year, month)


# 单例实例
db = Cl1Database()
