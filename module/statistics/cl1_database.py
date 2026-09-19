"""CL1 数据库模块。

使用 SQLite 本地存储战斗统计和掉落数据，支持 AES 加密传输。
提供设备识别、数据序列化和与 AzurStats 云端同步的功能。
"""

# -*- coding: utf-8 -*-
import sqlite3
import json
import os
from contextlib import closing, contextmanager, suppress
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256
from collections import defaultdict
from module.base.device_id import get_device_id, get_old_device_id
from module.config.time_source import now as current_time
from module.logger import logger


class Cl1Database:
    @staticmethod
    def _coerce_int(value: Any) -> int:
        """严格转换为 int；无效输入由调用方按上下文捕获处理。"""
        return int(value)

    @staticmethod
    def _coerce_float(value: Any) -> float:
        """严格转换为 float；无效输入由调用方按上下文捕获处理。"""
        return float(value)

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
                    self._coerce_int(value or 0)
                    for value in devices.get("meow", {}).values()
                )
            return self._coerce_int(
                devices.get("meow", {}).get(str(self._coerce_int(hazard_level)), 0) or 0
            )
        return self._coerce_int(devices.get("cl1", 0) or 0)

    def add_siren_research_device(
        self, instance: str, source: str = "cl1", hazard_level: int = None
    ) -> None:
        """记录一次塞壬研究装置（吊机）出现。

        Args:
            instance: 实例名称
            source: 数据来源 (cl1 / meow)
            hazard_level: 侵蚀等级（耄耋相接专用）
        """
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)

            devices = self._normalize_siren_research_devices(data)
            if source == "cl1":
                devices["cl1"] = devices.get("cl1", 0) + 1
            elif source == "meow":
                meow = devices.get("meow", {})
                key = str(self._coerce_int(hazard_level or 0))
                meow[key] = int(meow.get(key, 0) or 0) + 1
                devices["meow"] = meow
            data["siren_research_devices"] = devices

            entries = data.get("siren_research_device_entries", [])
            if not isinstance(entries, list):
                entries = []
            entries.append({
                "ts": datetime.now().isoformat(),
                "source": source,
                "hazard_level": self._coerce_int(hazard_level or 0) if source == "meow" else None,
            })
            if len(entries) > 5000:
                entries = entries[-5000:]
            data["siren_research_device_entries"] = entries

            self._save_stats_in_connection(conn, instance, month, data)

    """
    CL1 明文 SQLite 数据库管理类。
    所有实例共享一个数据库文件；旧版 encrypted_blob 仅用于自动解密迁移。
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._manage_legacy_db_path = db_path is None
        if db_path is None:
            project_root = Path(__file__).resolve().parents[2]
            self.db_dir = project_root / "config"
            self.db_path = self.db_dir / "cl1_data.db"
        else:
            self.db_path = db_path
            self.db_dir = self.db_path.parent

        self._ensure_dir()
        if self._manage_legacy_db_path:
            self._move_legacy_db()
        self._init_db()
        self._legacy_decryption_keys = self._get_legacy_decryption_keys()
        self._migrate_encrypted_rows()
        if self._manage_legacy_db_path:
            self._auto_migrate()

    def _ensure_dir(self):
        try:
            self.db_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"[Statistics] 创建数据库目录失败: {e}")

    def _init_db(self):
        """初始化数据库表，并兼容旧版 encrypted_blob 结构。"""
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cl1_data (
                        instance TEXT,
                        month TEXT,
                        data_json TEXT,
                        encrypted_blob BLOB,
                        PRIMARY KEY (instance, month)
                    )
                """)
                cursor.execute("PRAGMA table_info(cl1_data)")
                columns = {row[1] for row in cursor.fetchall()}
                if "data_json" not in columns:
                    cursor.execute("ALTER TABLE cl1_data ADD COLUMN data_json TEXT")
                if "encrypted_blob" not in columns:
                    cursor.execute("ALTER TABLE cl1_data ADD COLUMN encrypted_blob BLOB")
                conn.commit()
        except Exception as e:
            logger.exception(f"初始化 CL1 数据库失败: {e}")

    def _derive_key(self, device_id: str) -> bytes:
        """基于 device_id 派生 256 位 AES 密钥"""
        salt = b"AlasCl1SecureStorage"  # 固定盐
        return PBKDF2(
            device_id.encode(), salt, dkLen=32, count=1000, hmac_hash_module=SHA256
        )

    def _get_legacy_decryption_keys(self) -> List[bytes]:
        """生成旧密文迁移时可尝试的解密密钥。"""
        device_ids = []
        with suppress(Exception):
            device_ids.append(get_device_id())
        old_id = get_old_device_id()
        if old_id:
            device_ids.append(old_id)

        keys = []
        seen = set()
        for device_id in device_ids:
            if not device_id or device_id in seen:
                continue
            seen.add(device_id)
            keys.append(self._derive_key(device_id))
        return keys

    def _migrate_encrypted_rows(self):
        """将旧版 AES-GCM 密文行迁移为明文 JSON。"""
        try:
            with self._stats_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT instance, month, data_json, encrypted_blob
                    FROM cl1_data
                    WHERE encrypted_blob IS NOT NULL
                      AND length(encrypted_blob) > 0
                    """
                )
                rows = cursor.fetchall()

                if not rows:
                    return

                logger.info(f"[Statistics] 开始解密旧版 CL1 数据库，条目数: {len(rows)}")
                updated_rows = []
                clear_rows = []
                failed_rows = []
                for instance, month, data_json, blob in rows:
                    if self._deserialize_data(data_json) is not None:
                        clear_rows.append((instance, month))
                        continue

                    data = self._decrypt(blob)
                    if data is None:
                        failed_rows.append((instance, month))
                        continue

                    updated_rows.append((self._serialize_data(data), instance, month))

                if updated_rows:
                    cursor.executemany(
                        """
                        UPDATE cl1_data
                        SET data_json = ?, encrypted_blob = NULL
                        WHERE instance = ? AND month = ?
                        """,
                        updated_rows,
                    )
                if clear_rows:
                    cursor.executemany(
                        """
                        UPDATE cl1_data
                        SET encrypted_blob = NULL
                        WHERE instance = ? AND month = ?
                        """,
                        clear_rows,
                    )

                migrated = len(updated_rows) + len(clear_rows)
                if migrated:
                    logger.info(f"[Statistics] 旧版 CL1 数据库解密迁移完成，条目数: {migrated}")
                if failed_rows:
                    logger.warning(
                        f"[Statistics] 旧版 CL1 数据库有 {len(failed_rows)} 条记录解密失败"
                    )
        except Exception as e:
            logger.error(f"[Statistics] 解密旧版 CL1 数据库失败: {e}")

    def _move_legacy_db(self):
        """将旧位置的 CL1 数据库移动到 config 目录后再初始化表结构。"""
        project_root = Path(__file__).resolve().parents[2]
        old_db_dir = project_root / "log" / "cl1"
        old_db_path = old_db_dir / "cl1_data.db"

        if old_db_path.exists() and not self.db_path.exists():
            import shutil

            try:
                shutil.move(str(old_db_path), str(self.db_path))
                logger.info(
                    f"已移动旧版 CL1 数据库: {old_db_path} -> {self.db_path}"
                )
            except Exception as e:
                logger.error(f"[Statistics] 移动旧版 CL1 数据库失败: {e}")

    def _serialize_data(self, data: Dict[str, Any]) -> str:
        """将统计数据序列化为明文 JSON。"""
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def _deserialize_data(self, data_json: Optional[str]) -> Optional[Dict[str, Any]]:
        """从明文 JSON 读取统计数据。"""
        if not data_json:
            return None
        try:
            data = json.loads(data_json)
        except Exception as e:
            logger.warning(f"[Statistics] 读取 CL1 明文 JSON 失败: {e}")
            return None
        return data if isinstance(data, dict) else None

    def _decrypt_payload(self, blob: bytes, key: bytes) -> Dict[str, Any]:
        nonce = blob[:16]
        tag = blob[16:32]
        ciphertext = blob[32:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return json.loads(plaintext.decode("utf-8"))

    def _decrypt_with_key(self, blob: bytes, key: bytes) -> Optional[Dict[str, Any]]:
        """辅助方法：使用指定密钥进行解密"""
        if not blob or len(blob) < 32:
            return None
        try:
            return self._decrypt_payload(blob, key)
        except Exception:
            return None

    def _decrypt(self, blob: bytes) -> Optional[Dict[str, Any]]:
        """尝试解密旧版 AES-GCM 数据。"""
        if not blob or len(blob) < 32:
            return None
        for key in self._legacy_decryption_keys:
            data = self._decrypt_with_key(blob, key)
            if data is not None:
                return data
        return None

    def get_stats(self, instance: str, month: str) -> Dict[str, Any]:
        """获取指定实例和月份的统计数据"""
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json, encrypted_blob FROM cl1_data WHERE instance = ? AND month = ?",
                    (instance, month),
                )
                row = cursor.fetchone()
                if row:
                    data = self._deserialize_data(row[0])
                    if data is not None:
                        return data
                    if row[1] and isinstance(data := self._decrypt(row[1]), dict):
                        try:
                            with self._stats_transaction() as write_conn:
                                data = self._get_stats_in_connection(write_conn, instance, month)
                                self._save_stats_in_connection(write_conn, instance, month, data)
                        except Exception:
                            # 迁移只是读取时的可选维护，保存失败仍返回已经解密的数据。
                            logger.warning(f"[Statistics] 旧数据迁移未落盘: {instance} {month}")
                        return data
        except Exception as e:
            logger.error(f"[Statistics] 查询统计数据失败 {instance} {month}: {e}")

        return self._empty_data(month)

    def _empty_data(self, month: str) -> Dict[str, Any]:
        return {
            "battle_count": 0,
            "akashi_encounters": 0,
            "akashi_ap": 0,
            "akashi_ap_entries": [],
            "yellow_coin_snapshots": [],
            "coins_snapshots": [],
            # 耄耋相接数据
            "meow_battle_raw_count": 0,
            "meow_battle_count": 0,
            "meow_round_times": [],
            "meow_battle_times": [],  # 耄耋相接单场战斗时间
            "meow_hazard_stats": {},  # 按侵蚀等级拆分统计
            # 塞壬研究装置（吊机）
            "siren_research_devices": {"cl1": 0, "meow": {}},
            "siren_research_device_entries": [],
            # 委托收益数据
            "commission_income_entries": [],
            # 钻石委托历史记录（按月份归档）
            "gem_commission_entries": [],
            # 当前运行中的钻石委托（不按月归档，持久化用）
            "running_gem_commissions": [],
        }

    def _normalize_meow_round_times(
        self, round_times: List[Any]
    ) -> List[Dict[str, Any]]:
        """兼容旧格式耄耋相接轮次样本，统一为字典结构。"""
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
        """提取耄耋相接轮次耗时，兼容旧格式浮点样本。"""
        return [
            entry["duration"] for entry in self._normalize_meow_round_times(round_times)
        ]

    @staticmethod
    def _get_meow_battles_per_round(hazard_level: Optional[int]) -> Optional[int]:
        """根据侵蚀等级返回每轮战斗次数。"""
        return 2 if hazard_level in {2, 3} else 3 if hazard_level in {4, 5, 6} else None

    def _normalize_meow_hazard_stats(
        self, data: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """兼容旧格式的分级耄耋相接统计结构。"""
        raw_stats = data.get("meow_hazard_stats", {})
        if not isinstance(raw_stats, dict):
            return {}

        normalized: Dict[str, Dict[str, Any]] = {}
        for hazard_key, bucket in raw_stats.items():
            try:
                hazard_level = int(hazard_key)
            except (TypeError, ValueError):
                continue
            if hazard_level not in {2, 3, 4, 5, 6} or not isinstance(bucket, dict):
                continue

            round_times = bucket.get("round_times", [])
            if not isinstance(round_times, list):
                round_times = []
            normalized_round_times: List[float] = []
            for entry in round_times:
                if isinstance(entry, (int, float)):
                    normalized_round_times.append(float(entry))
                elif isinstance(entry, dict) and isinstance(
                    duration := entry.get("duration"), (int, float)
                ):
                    normalized_round_times.append(float(duration))

            battle_times = bucket.get("battle_times", [])
            if not isinstance(battle_times, list):
                battle_times = []
            normalized_battle_times: List[float] = []
            for entry in battle_times:
                if isinstance(entry, (int, float)):
                    normalized_battle_times.append(float(entry))
                elif isinstance(entry, dict) and isinstance(
                    duration := entry.get("duration"), (int, float)
                ):
                    normalized_battle_times.append(float(duration))

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
                # 耄耋相接明石统计：遇见次数与购买体力（按侵蚀等级拆分）
                "akashi_encounters": int(bucket.get("akashi_encounters", 0) or 0),
                "akashi_ap": int(bucket.get("akashi_ap", 0) or 0),
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
        if not isinstance(bucket.get("akashi_encounters"), int):
            bucket["akashi_encounters"] = int(bucket.get("akashi_encounters", 0) or 0)
        if not isinstance(bucket.get("akashi_ap"), int):
            bucket["akashi_ap"] = int(bucket.get("akashi_ap", 0) or 0)
        return bucket

    def _infer_meow_battles_per_round(
        self, round_times: List[Any]
    ) -> Tuple[Optional[int], Optional[float]]:
        """从耄耋相接样本推断每轮战斗数。"""
        hazard_levels = []
        for entry in round_times:
            if isinstance(entry, dict):
                hazard_level = entry.get("hazard_level")
                if hazard_level in {2, 3, 4, 5, 6}:
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
    ) -> Tuple[int, float, bool]:
        """兼容旧数据并修正耄耋相接真实战斗场次与等效轮次。"""
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

        need_backfill = (
            raw_battle_count is None
            or estimated_from_rounds is not None
            and current_raw > 0
            and current_raw < int(estimated_from_rounds * 0.85)
        )

        if need_backfill:
            candidates = [
                candidate
                for candidate in [current_raw, estimated_from_rounds, by_battle_times]
                if candidate is not None
            ]
            raw_battle_count = max(candidates, default=int(round(effective_rounds)))
            data["meow_battle_raw_count"] = int(raw_battle_count)
            should_save = True

            if inferred_divisor in {2, 3} and effective_rounds > 0:
                data["meow_battle_count"] = round(
                    raw_battle_count / inferred_divisor, 2
                )
                effective_rounds = float(data["meow_battle_count"])
        else:
            raw_battle_count = current_raw

        if raw_battle_count > 0 and effective_rounds > 0:
            ratio = raw_battle_count / effective_rounds
            if ratio > 5:
                divisor_for_fix = inferred_divisor if inferred_divisor in {2, 3} else 3
                fixed_rounds = round(raw_battle_count / divisor_for_fix, 2)
                if abs(fixed_rounds - effective_rounds) > 0.01:
                    data["meow_battle_count"] = fixed_rounds
                    effective_rounds = float(fixed_rounds)
                    should_save = True

        return int(raw_battle_count), effective_rounds, should_save

    def _list_stats_rows(self, instance: Optional[str] = None) -> List[Tuple[str, str]]:
        """列出数据库中已有的实例与月份。"""
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
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
            logger.error(f"[Statistics] 列出统计数据失败: {e}")
            return []

    def backfill_meow_stats(
        self, instance: str, year: int = None, month: int = None
    ) -> bool:
        """显式回填指定月份的耄耋相接统计。

        仅在主动调用时落盘，避免读取统计时产生写入副作用。
        """
        if year is None or month is None:
            now = datetime.now()
            year = now.year
            month = now.month

        month_key = f"{year:04d}-{month:02d}"
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month_key)
            round_times = data.get("meow_round_times", [])
            battle_times = data.get("meow_battle_times", [])
            effective_rounds = float(data.get("meow_battle_count", 0) or 0)

            _, _, changed = self._reconcile_meow_counts(
                data=data,
                effective_rounds=effective_rounds,
                round_times=round_times,
                battle_times=battle_times,
            )
            if changed:
                self._save_stats_in_connection(conn, instance, month_key, data)
        return changed

    def backfill_all_meow_stats(self, instance: Optional[str] = None) -> Dict[str, int]:
        """批量回填数据库内已有月份的耄耋相接统计。"""
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
        """显式替换整个月份快照；失败必须传递给调用方。

        此接口不合并旧快照。增量修改必须在 _stats_transaction 中读取并
        调用 _save_stats_in_connection，不能将 get_stats 的结果传回此处。
        """
        try:
            with self._stats_transaction() as conn:
                self._save_stats_in_connection(conn, instance, month, data)
        except Exception as e:
            logger.error(f"[Statistics] 保存统计数据失败 {instance} {month}: {e}")
            raise

    @contextmanager
    def _stats_transaction(self):
        """读取前取得 SQLite 写锁，跨线程和进程串行化整个读改写过程。

        连接上下文负责提交及异常回滚，closing 保证提交失败也释放连接。
        """
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                yield conn

    def _save_stats_in_connection(self, conn, instance, month, data):
        """在调用方事务中写入单个月份，不自行提交。"""
        conn.execute(
            """
            INSERT INTO cl1_data (instance, month, data_json, encrypted_blob)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(instance, month) DO UPDATE SET
                data_json = excluded.data_json,
                encrypted_blob = NULL
            """,
            (instance, month, self._serialize_data(data)),
        )

    def _get_stats_in_connection(self, conn, instance, month):
        """事务中的读取不能把数据库错误或损坏行当成空数据覆盖。"""
        row = conn.execute(
            "SELECT data_json, encrypted_blob FROM cl1_data WHERE instance = ? AND month = ?",
            (instance, month),
        ).fetchone()
        if row is None:
            return self._empty_data(month)
        data = self._deserialize_data(row[0])
        if data is None and row[1]:
            data = self._decrypt(row[1])
        if not isinstance(data, dict):
            raise ValueError(f"统计数据无法解码: {instance} {month}")
        return data

    def increment_battle_count(self, instance: str, delta: int = 1):
        """增加战斗次数"""
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            data["battle_count"] = data.get("battle_count", 0) + delta
            self._save_stats_in_connection(conn, instance, month, data)

    def increment_akashi_encounter(self, instance: str):
        """增加明石奇遇次数"""
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            data["akashi_encounters"] = data.get("akashi_encounters", 0) + 1
            self._save_stats_in_connection(conn, instance, month, data)

    def add_akashi_ap_entry(
        self, instance: str, amount: int, base: int, count: int, source: str
    ):
        """记录明石行动力购买条目"""
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)

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
            self._save_stats_in_connection(conn, instance, month, data)

    def add_ap_snapshot(self, instance: str, ap_current: int, source: str = "cl1", distance: int = None, ap_total: int = None):
        """记录行动力快照（真实剩余体力），并计算资产

        Args:
            instance: 实例名称
            ap_current: 当前行动力剩余
            source: 数据来源标记 (cl1 / meow 等)
            distance: 海里数（可选）
            ap_total: 总体力（含行动力箱子）
        """
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            now = datetime.now()

            # CL5 效率：1700 / 30 ≈ 56.67
            cl5_efficiency = 1700.0 / 30.0

            # 获取最近的黄币值
            yellow_coin = 0
            yellow_coin_snapshots = data.get("yellow_coin_snapshots", [])
            if yellow_coin_snapshots:
                with suppress(ValueError, TypeError, IndexError, KeyError):
                    yellow_coin = int(yellow_coin_snapshots[-1].get("yellow_coin", 0))

            # 资产按可用总体力计算，包含行动力箱子。
            ap_current = self._coerce_int(ap_current)
            if ap_total is not None:
                ap_total = self._coerce_int(ap_total)
            ap_for_asset = ap_total if ap_total is not None else ap_current
            asset = ap_for_asset * cl5_efficiency + yellow_coin

            snapshot = {
                "ts": now.isoformat(),
                "ap": ap_current,
                "yellow_coin": yellow_coin,
                "asset": round(asset, 2),
                "source": source,
            }
            if distance is not None:
                snapshot["distance"] = self._coerce_int(distance)
            if ap_total is not None:
                snapshot["ap_total"] = ap_total

            snapshots = data.get("ap_snapshots", [])
            snapshots.append(snapshot)
            data["ap_snapshots"] = snapshots
            self._save_stats_in_connection(conn, instance, month, data)

    def get_last_ap_snapshot(self, instance: str) -> Optional[Dict[str, Any]]:
        """获取最近一次行动力快照，优先读取当前月份，必要时回退到历史月份。"""
        current_month = datetime.now().strftime("%Y-%m")
        current_data = self.get_stats(instance, current_month)
        snapshots = current_data.get("ap_snapshots", [])
        if snapshots:
            return snapshots[-1]

        rows = self._list_stats_rows(instance=instance)
        for _, month_key in reversed(rows):
            if month_key == current_month:
                continue
            data = self.get_stats(instance, month_key)
            snapshots = data.get("ap_snapshots", [])
            if snapshots:
                return snapshots[-1]

        return None

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
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            data["last_ap_notification"] = {
                "ts": datetime.now().isoformat(),
                "ap": self._coerce_int(ap_current),
            }
            self._save_stats_in_connection(conn, instance, month, data)

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
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            yellow_coin = self._coerce_int(yellow_coin)

            snapshot = {
                "ts": datetime.now().isoformat(),
                "yellow_coin": yellow_coin,
                "source": source,
            }

            snapshots = data.get("yellow_coin_snapshots", [])
            if snapshots:
                with suppress(ValueError, TypeError, IndexError, KeyError):
                    if self._coerce_int(snapshots[-1].get("yellow_coin", -1)) == yellow_coin:
                        return
            snapshots.append(snapshot)
            data["yellow_coin_snapshots"] = snapshots
            self._save_stats_in_connection(conn, instance, month, data)

    def add_coins_snapshot(
        self,
        instance: str,
        yellow_coins: int,
        purple_coins: int = None,
        source: str = "cl1",
    ):
        """记录凭证快照（作战补给凭证/特别兑换凭证）

        Args:
            instance: 实例名称
            yellow_coins: 当前作战补给凭证（黄币）数量
            purple_coins: 当前特别兑换凭证（紫币）数量，None 表示不记录（如 hazard 循环不知道真实值）
            source: 数据来源标记 (cl1 / meow 等)
        """
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            yellow_coins = self._coerce_int(yellow_coins)
            purple_coins = self._coerce_int(purple_coins) if purple_coins is not None else None

            snapshot = {
                "ts": datetime.now().isoformat(),
                "yellow_coins": yellow_coins,
                "source": source,
            }
            if purple_coins is not None:
                snapshot["purple_coins"] = purple_coins

            snapshots = data.get("coins_snapshots", [])
            if snapshots:
                with suppress(ValueError, TypeError, IndexError, KeyError):
                    last = snapshots[-1]
                    if self._coerce_int(last.get("yellow_coins", -1)) == yellow_coins:
                        if (
                            purple_coins is not None
                            and self._coerce_int(last.get("purple_coins", -1)) == purple_coins
                        ):
                            return
                        if purple_coins is None and "purple_coins" not in last:
                            return
            snapshots.append(snapshot)
            # 保留最近 500 条记录，避免数据过大
            if len(snapshots) > 500:
                snapshots = snapshots[-500:]
            data["coins_snapshots"] = snapshots
            self._save_stats_in_connection(conn, instance, month, data)

    def async_add_coins_snapshot(
        self,
        instance: str,
        yellow_coins: int,
        purple_coins: int = None,
        source: str = "cl1",
    ):
        """异步记录凭证快照"""
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_coins_snapshot, instance, yellow_coins, purple_coins, source
        )

    def migrate_from_json(self, json_path: Path, instance: str):
        """从 JSON 文件迁移数据到数据库"""
        if not json_path.exists():
            return

        logger.info(f"[Statistics] 开始从 JSON 迁移 CL1 数据: {json_path}, instance={instance}")
        try:
            with json_path.open("r", encoding="utf-8") as f:
                old_data = json.load(f)

            if not isinstance(old_data, dict):
                return

            # JSON 格式比较杂乱，需要按月份归档
            # 格式可能是: {"2026-02": 10, "2026-02-akashi": 1, "2026-02-akashi-ap": 120, "2026-02-akashi-ap-entries": [...]}
            months = {
                key[:7]
                for key in old_data
                if len(key) >= 7 and key[4] == "-"
            }

            for month in months:
                # 首先检查数据库是否已有数据，避免覆盖
                with self._stats_transaction() as conn:
                    c = conn.cursor()
                    c.execute(
                        "SELECT 1 FROM cl1_data WHERE instance = ? AND month = ?",
                        (instance, month),
                    )
                    if c.fetchone():
                        logger.info(
                            f"[Statistics] 数据库中已存在 {instance} {month}，跳过迁移"
                        )
                        continue

                    new_stats = self._empty_data(month)
                    new_stats["battle_count"] = old_data.get(month, 0)
                    new_stats["akashi_encounters"] = old_data.get(f"{month}-akashi", 0)
                    new_stats["akashi_ap"] = old_data.get(f"{month}-akashi-ap", 0)
                    new_stats["akashi_ap_entries"] = old_data.get(
                        f"{month}-akashi-ap-entries", []
                    )

                    self._save_stats_in_connection(conn, instance, month, new_stats)
                logger.info(f"[Statistics] 已迁移 {instance} {month}")

            # 迁移成功后可以删除 JSON 或重命名 (此处建议重命名为 .bak 以防万一)
            bak_path = json_path.with_suffix(".json.bak")
            json_path.replace(bak_path)
            logger.info(f"[Statistics] 已将旧 JSON 重命名为 {bak_path}")

        except Exception as e:
            logger.exception(f"从 JSON 迁移 CL1 数据失败: {e}")

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
                    f"Moved old CL1数据库 from {old_db_path} to {self.db_path}"
                )
            except Exception as e:
                logger.error(f"[统计-数据库] 移动旧CL1数据库失败: {e}")

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
            logger.error(f"[统计-数据库] 自动迁移扫描错误: {e}")

    # ========== 耄耋相接数据记录方法 ==========

    def increment_meow_battle_count(
        self, instance: str, hazard_level: int = None, delta: float = None
    ):
        """增加耄耋相接有效战斗轮数

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
                delta = self._coerce_float(delta)
            except Exception:
                delta = 1
        elif hazard_level in {2, 3, 4, 5, 6}:
            battles_per_round = self._get_meow_battles_per_round(hazard_level)
            delta = (1 / battles_per_round) if battles_per_round else 1
        else:
            delta = 1  # 默认直接加1

        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            data["meow_battle_raw_count"] = data.get("meow_battle_raw_count", 0) + 1
            data["meow_battle_count"] = data.get("meow_battle_count", 0) + delta

            if hazard_level in {2, 3, 4, 5, 6}:
                hazard_stats = self._normalize_meow_hazard_stats(data)
                bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
                bucket["battle_raw_count"] = int(bucket.get("battle_raw_count", 0) or 0) + 1
                bucket["effective_rounds"] = float(
                    bucket.get("effective_rounds", 0) or 0
                ) + delta
                data["meow_hazard_stats"] = hazard_stats

            self._save_stats_in_connection(conn, instance, month, data)

    def add_meow_round_time(
        self, instance: str, duration: float, hazard_level: int = None
    ):
        """记录耄耋相接单轮战斗时间

        Args:
            instance: 实例名称
            duration: 战斗耗时（秒）
            hazard_level: 侵蚀等级，用于计算出击轮次（2-6）
        """
        # 验证 hazard_level 是否在有效范围内
        if hazard_level is not None and hazard_level not in {2, 3, 4, 5, 6}:
            logger.debug(f"Invalid hazard_level {hazard_level}, ignoring")
            hazard_level = None

        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)

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

            if hazard_level in {2, 3, 4, 5, 6}:
                hazard_stats = self._normalize_meow_hazard_stats(data)
                bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
                round_times = bucket.get("round_times", [])
                round_times.append(round(duration, 2))
                if len(round_times) > 100:
                    round_times = round_times[-100:]
                bucket["round_times"] = round_times
                data["meow_hazard_stats"] = hazard_stats

            self._save_stats_in_connection(conn, instance, month, data)

    def add_meow_battle_time(
        self, instance: str, duration: float, hazard_level: int = None
    ):
        """记录耄耋相接单场战斗时间

        Args:
            instance: 实例名称
            duration: 战斗耗时（秒）
            hazard_level: 侵蚀等级（2-6），用于分级统计
        """
        if hazard_level is not None and hazard_level not in {2, 3, 4, 5, 6}:
            logger.debug(f"Invalid hazard_level {hazard_level}, ignoring")
            hazard_level = None

        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)

            if "meow_battle_times" not in data:
                data["meow_battle_times"] = []

            times = data["meow_battle_times"]
            times.append(round(duration, 2))

            # 只保留最近100个样本
            if len(times) > 100:
                times = times[-100:]

            data["meow_battle_times"] = times

            if hazard_level in {2, 3, 4, 5, 6}:
                hazard_stats = self._normalize_meow_hazard_stats(data)
                bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
                battle_times = bucket.get("battle_times", [])
                battle_times.append(round(duration, 2))
                if len(battle_times) > 100:
                    battle_times = battle_times[-100:]
                bucket["battle_times"] = battle_times
                data["meow_hazard_stats"] = hazard_stats

            self._save_stats_in_connection(conn, instance, month, data)

    def increment_meow_akashi_encounter(self, instance: str, hazard_level: int):
        """记录一次耄耋相接明石事件（按侵蚀等级拆分）。

        Args:
            instance: 实例名称
            hazard_level: 侵蚀等级（2-6）
        """
        if hazard_level not in {2, 3, 4, 5, 6}:
            logger.debug(f"Invalid hazard_level {hazard_level}, ignoring")
            return

        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            hazard_stats = self._normalize_meow_hazard_stats(data)
            bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
            bucket["akashi_encounters"] = bucket.get("akashi_encounters", 0) + 1
            data["meow_hazard_stats"] = hazard_stats
            self._save_stats_in_connection(conn, instance, month, data)

    def add_meow_akashi_ap(self, instance: str, hazard_level: int, amount: int):
        """记录耄耋相接明石商店购买的体力（按侵蚀等级拆分）。

        Args:
            instance: 实例名称
            hazard_level: 侵蚀等级（2-6）
            amount: 购买的体力数量
        """
        if hazard_level not in {2, 3, 4, 5, 6}:
            logger.debug(f"Invalid hazard_level {hazard_level}, ignoring")
            return

        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return
        if amount <= 0:
            return

        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            hazard_stats = self._normalize_meow_hazard_stats(data)
            bucket = self._ensure_meow_hazard_bucket(hazard_stats, hazard_level)
            bucket["akashi_ap"] = int(bucket.get("akashi_ap", 0) or 0) + amount
            data["meow_hazard_stats"] = hazard_stats
            self._save_stats_in_connection(conn, instance, month, data)

    def get_meow_stats(
        self, instance: str, year: int = None, month: int = None,
        hazard_level: int = None,
    ) -> Dict[str, Any]:
        """获取耄耋相接统计数据

        Args:
            instance: 实例名称
            year: 年份，默认当前年
            month: 月份，默认当前月
            hazard_level: 侵蚀等级，传入时只返回对应等级的数据

        Returns:
            耄耋相接统计数据字典
        """
        if year is None or month is None:
            now = datetime.now()
            year = now.year
            month = now.month
        key = f"{year:04d}-{month:02d}"

        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, key)

            round_times = data.get("meow_round_times", [])
            battle_times = data.get("meow_battle_times", [])
            normalized_round_times = self._normalize_meow_round_times(round_times)

            effective_rounds = float(data.get("meow_battle_count", 0) or 0)
            battle_count, effective_rounds, changed = self._reconcile_meow_counts(
                data=data,
                effective_rounds=effective_rounds,
                round_times=round_times,
                battle_times=battle_times,
            )

            if changed:
                self._save_stats_in_connection(conn, instance, key, data)

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
            hl = entry.get("hazard_level")
            if hl in {2, 3, 4, 5, 6}:
                hazard_sample_total += 1
            if hl in {3, 5}:
                hazard_round_samples[hl].append(entry["duration"])

        by_hazard: Dict[str, Dict[str, Any]] = {}
        for hl in (3, 5):
            key_name = str(hl)
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
            hz_round_times = hz_round_times or hazard_round_samples[hl]

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
                            len(hazard_round_samples[hl])
                            / hazard_sample_total
                        )
                    )
                )
                estimated = True

            battles_per_round = self._get_meow_battles_per_round(hl) or 1
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
                "hazard_level": hl,
                "battle_count": hz_battle_count,
                "effective_rounds": round(hz_effective_rounds, 2),
                "avg_round_time": hz_avg_round_time,
                "avg_battle_time": hz_avg_battle_time,
                "sample_count": len(hz_round_times),
                "source": source,
                "akashi_encounters": int(bucket.get("akashi_encounters", 0) or 0),
                "akashi_ap": int(bucket.get("akashi_ap", 0) or 0),
            }

        # 计算塞壬研究装置（吊机）数据
        siren_research_devices = self.get_siren_research_device_count(
            data, source="meow", hazard_level=hazard_level
        )
        siren_research_rate = 0.0
        target_rounds = effective_rounds
        if hazard_level is not None:
            hl_key = str(hazard_level)
            if hl_key in by_hazard:
                target_rounds = float(by_hazard[hl_key].get("effective_rounds", 0) or 0)
        if target_rounds > 0:
            siren_research_rate = round(siren_research_devices / target_rounds, 4)

        result = {
            "month": key,
            "battle_count": battle_count,
            "effective_rounds": round(effective_rounds, 2),
            "round_times": round_times,
            "avg_round_time": avg_round_time,
            "battle_times": battle_times,
            "avg_battle_time": avg_battle_time,
            "siren_research_devices": siren_research_devices,
            "siren_research_rate": siren_research_rate,
            "by_hazard": by_hazard,
        }

        # 请求指定侵蚀等级时，将该等级数据提升到顶层
        if hazard_level is not None and (hl_data := by_hazard.get(str(hazard_level))):
            result["battle_count"] = hl_data["battle_count"]
            result["effective_rounds"] = hl_data["effective_rounds"]
            result["avg_round_time"] = hl_data["avg_round_time"]
            result["avg_battle_time"] = hl_data["avg_battle_time"]
            result["akashi_encounters"] = hl_data["akashi_encounters"]
            result["akashi_ap"] = hl_data["akashi_ap"]

        return result

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
        self, instance: str, ap_current: int, source: str = "cl1", distance: int = None, ap_total: int = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(self.add_ap_snapshot, instance, ap_current, source, distance, ap_total)

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

    def async_get_meow_stats(self, instance: str, year: int = None, month: int = None, hazard_level: int = None):
        from module.base.async_executor import async_executor

        return async_executor.submit(self.get_meow_stats, instance, year, month, hazard_level)

    def async_add_siren_research_device(
        self, instance: str, source: str = "cl1", hazard_level: int = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_siren_research_device, instance, source, hazard_level
        )

    def async_increment_meow_akashi_encounter(self, instance: str, hazard_level: int):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.increment_meow_akashi_encounter, instance, hazard_level
        )

    def async_add_meow_akashi_ap(self, instance: str, hazard_level: int, amount: int):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_meow_akashi_ap, instance, hazard_level, amount
        )

    # ========== 委托收益数据记录方法 ==========

    @staticmethod
    def _commission_month_keys(now):
        """运行记录仅搜索当前月和上月，结算仍归档到系统当前月。"""
        return now.strftime("%Y-%m"), (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    @staticmethod
    def _running_commissions_from_months(data, months):
        commissions = []
        seen = set()
        # 沿用读取列表的上月优先去重规则，随后按完成时间排序。
        for month in reversed(months):
            source = data[month].get("running_gem_commissions", [])
            if not isinstance(source, list):
                continue
            for commission in source:
                if not isinstance(commission, dict):
                    continue
                identity = (commission.get("name"), commission.get("create_time"))
                if identity not in seen:
                    seen.add(identity)
                    commissions.append(commission)
        return sorted(commissions, key=lambda item: item.get("finish_time", ""))

    def _append_gem_commission_entry(self, data, duration_hour, reward, now):
        entry = {
            "ts": now.isoformat(),
            "duration": self._coerce_int(duration_hour),
            "reward": self._coerce_int(reward),
            "success": self._coerce_int(reward) > 0,
        }
        entries = data.get("gem_commission_entries", [])
        entries.append(entry)
        data["gem_commission_entries"] = entries[-5000:]

    def _settle_running_in_months(
        self, data, months, now, reward, name=None, duration_hour=None, create_time=None,
    ):
        """仅修改事务内的月份快照，保持当前月优先和三字段精确匹配。"""
        for month in months:
            commissions = data[month].get("running_gem_commissions", [])
            if not isinstance(commissions, list):
                continue
            commissions.sort(key=lambda item: item.get("finish_time", ""))
            for index, commission in enumerate(commissions):
                if name is not None and commission.get("name") != name:
                    continue
                if duration_hour is not None and commission.get("duration") != duration_hour:
                    continue
                if create_time is not None and commission.get("create_time") != create_time:
                    continue
                removed = commissions.pop(index)
                data[month]["running_gem_commissions"] = commissions
                self._append_gem_commission_entry(data[months[0]], removed["duration"], reward, now)
                return removed, month
        return None, None

    def _save_commission_months(self, conn, instance, data, months, changed):
        # 先写运行记录来源月，后写归档月；两次写入必须共同提交或共同回滚。
        for month in reversed(months):
            if month in changed:
                self._save_stats_in_connection(conn, instance, month, data[month])

    def add_commission_income(
        self,
        instance: str,
        items: Dict[str, int],
        commission_count: int = 1,
        screenshots: Optional[List[str]] = None,
        *,
        gem_duration: Optional[int] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """记录收益，并在同一事务中结算匹配的钻石委托。

        截图仍保存相对路径；记录格式、5000 条上限和当前月归档不变。
        gem_duration 来自奖励识别，匹配最早到期的同时间长度委托。
        返回已结算的运行记录，未匹配到时仅保存收益并返回 None。
        """
        now = datetime.now()
        months = self._commission_month_keys(now)
        completed_at = completed_at or current_time()
        entry = {
            "ts": now.isoformat(),
            "items": {k: self._coerce_int(v) for k, v in items.items() if v > 0},
            "commission_count": self._coerce_int(commission_count),
            "screenshots": [str(path) for path in (screenshots or [])],
        }
        removed = None
        with self._stats_transaction() as conn:
            read_months = months if gem_duration is not None else months[:1]
            data = {month: self._get_stats_in_connection(conn, instance, month) for month in read_months}
            entries = data[months[0]].get("commission_income_entries", [])
            entries.append(entry)
            data[months[0]]["commission_income_entries"] = entries[-5000:]
            changed = {months[0]}
            if gem_duration is not None:
                for commission in self._running_commissions_from_months(data, months):
                    if commission.get("duration") != gem_duration:
                        continue
                    try:
                        finish_time = datetime.fromisoformat(commission["finish_time"])
                    except (KeyError, TypeError, ValueError):
                        logger.warning(f"钻石委托完成时间无效，跳过结算: {commission}")
                        continue
                    if finish_time > completed_at:
                        continue
                    removed, source_month = self._settle_running_in_months(
                        data, months, now, items.get("Gem", 0),
                        name=commission.get("name"), duration_hour=gem_duration,
                        create_time=commission.get("create_time"),
                    )
                    if source_month is not None:
                        changed.add(source_month)
                    break
            self._save_commission_months(conn, instance, data, months, changed)
        return removed

    def get_commission_reward_stats(self, instance: str):
        """
        获取委托奖励统计

        Returns:
            {
                "today": {...},
                "week": {...},
                "month": {...},
            }
        """
        now = datetime.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())

        entries = []

        entries.extend(
            self.get_commission_income(
                instance,
                year=now.year,
                month=now.month,
            )
        )

        # 周跨月
        if week_start.month != now.month or week_start.year != now.year:
            prev_month_date = now.replace(day=1) - timedelta(days=1)
            entries.extend(
                self.get_commission_income(
                    instance,
                    year=prev_month_date.year,
                    month=prev_month_date.month,
                )
            )

        result = {
            "today": defaultdict(int),
            "week": defaultdict(int),
            "month": defaultdict(int),
        }

        for entry in entries:
            try:
                ts = datetime.fromisoformat(entry.get("ts", ""))
                items = entry.get("items", {})

                if not isinstance(items, dict):
                    continue

                for item, value in items.items():
                    value = self._coerce_int(value)

                    if ts.year == now.year and ts.month == now.month:
                        result["month"][item] += value

                    if ts.date() == today:
                        result["today"][item] += value

                    if week_start <= ts.date() <= today:
                        result["week"][item] += value

            except Exception:
                continue

        # 保留常用字段，兼容旧代码
        for period in ("today", "week", "month"):
            result[period].setdefault("Gem", 0)
            result[period].setdefault("Cube", 0)

        return {
            "today": dict(result["today"]),
            "week": dict(result["week"]),
            "month": dict(result["month"]),
        }

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
            year = year or now.year
            month = month or now.month

        month_key = f"{year:04d}-{month:02d}"
        data = self.get_stats(instance, month_key)
        return data.get("commission_income_entries", [])

    # ========== 钻石委托奖励统计 ==========

    def add_gem_commission(
        self,
        instance: str,
        duration_hour: int,
        reward: int = 0,
    ):
        """记录一次钻石委托结算结果。

        Args:
            instance: 实例名称
            duration_hour: 委托时长（2 / 4 / 8）
            reward: 获得钻石数量，0 表示失败
        """
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)

            self._append_gem_commission_entry(data, duration_hour, reward, datetime.now())
            self._save_stats_in_connection(conn, instance, month, data)

    def get_gem_commissions(
        self,
        instance: str,
        year: int = None,
        month: int = None,
    ) -> List[Dict[str, Any]]:
        """获取指定月份钻石委托记录。"""
        if year is None or month is None:
            now = datetime.now()
            year = year or now.year
            month = month or now.month

        month_key = f"{year:04d}-{month:02d}"
        data = self.get_stats(instance, month_key)
        return data.get("gem_commission_entries", [])

    def get_gem_commission_stats(
        self, instance: str, period: str = "month"
    ) -> Dict[str, Dict[str, Any]]:
        """获取钻石委托统计。

        Args:
            instance: 实例名称
            period: 统计周期，today / week / month

        Returns:
            {
                2: {"count": N, "success": N, "reward": N, "rate": 0.0},
                4: {...},
                8: {...},
            }
        """
        if period not in ("today", "week", "month"):
            period = "month"

        now = datetime.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())

        entries = list(self.get_gem_commissions(instance, now.year, now.month))

        if week_start.month != now.month or week_start.year != now.year:
            prev = now.replace(day=1) - timedelta(days=1)
            entries.extend(self.get_gem_commissions(instance, prev.year, prev.month))

        def _bucket():
            return {
                2: {"count": 0, "success": 0, "reward": 0},
                4: {"count": 0, "success": 0, "reward": 0},
                8: {"count": 0, "success": 0, "reward": 0},
            }

        result = {
            "today": _bucket(),
            "week": _bucket(),
            "month": _bucket(),
        }

        for entry in entries:
            try:
                ts = datetime.fromisoformat(entry.get("ts", ""))
                duration = self._coerce_int(entry.get("duration", 0))
                reward = self._coerce_int(entry.get("reward", 0))
                success = bool(entry.get("success", False))

                if duration not in (2, 4, 8):
                    continue

                periods = []
                if ts.year == now.year and ts.month == now.month:
                    periods.append(result["month"])
                if ts.date() == today:
                    periods.append(result["today"])
                if week_start <= ts.date() <= today:
                    periods.append(result["week"])

                for period_data in periods:
                    item = period_data[duration]
                    item["count"] += 1
                    item["reward"] += reward
                    if success:
                        item["success"] += 1
            except Exception:
                continue

        for period_data in result.values():
            for item in period_data.values():
                count = item["count"]
                item["rate"] = round(item["success"] * 100 / count, 1) if count else 0.0

        return result[period]

    # ========== 钻石委托运行列表持久化 ==========

    def save_running_gem_commissions(
        self,
        instance: str,
        commissions: List[Dict[str, Any]],
    ):
        """保存运行中的钻石委托列表。"""
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            data["running_gem_commissions"] = commissions
            self._save_stats_in_connection(conn, instance, month, data)

    def get_running_gem_commissions(
        self,
        instance: str,
    ) -> List[Dict[str, Any]]:
        """获取运行中的钻石委托列表。

        合并当前月和上一个月的列表，覆盖跨月仍在执行的委托。
        """
        months = self._commission_month_keys(datetime.now())
        data = {month: self.get_stats(instance, month) for month in months}
        return self._running_commissions_from_months(data, months)

    def add_running_gem_commission(
        self,
        instance: str,
        commission: Dict[str, Any],
    ):
        """新增一条运行中的钻石委托（仅写入当前月）。"""
        month = datetime.now().strftime("%Y-%m")
        with self._stats_transaction() as conn:
            data = self._get_stats_in_connection(conn, instance, month)
            commissions = data.get("running_gem_commissions", [])
            # 去重：同 name + create_time 不重复添加
            if not any(
                c.get("name") == commission.get("name")
                and c.get("create_time") == commission.get("create_time")
                for c in commissions
            ):
                commissions.append(commission)
                commissions.sort(key=lambda item: item.get("finish_time", ""))
                data["running_gem_commissions"] = commissions
                self._save_stats_in_connection(conn, instance, month, data)

    def pop_running_gem_commission(
        self,
        instance: str,
        name: str = None,
        duration_hour: int = None,
        create_time: str = None,
    ) -> Optional[Dict[str, Any]]:
        """从运行中钻石委托列表中弹出一条记录。

        提供 create_time 时按 name、duration、create_time 精确匹配，避免
        同名同时长的历史残留记录与本次结算错配。调用方已在奖励页面
        确认委托完成，因此不再判断 finish_time。
        优先从当前月读写；当前月为空则回退到上月并写回上月。
        """
        months = self._commission_month_keys(datetime.now())
        with self._stats_transaction() as conn:
            for month in months:
                data = self._get_stats_in_connection(conn, instance, month)
                commissions = data.get("running_gem_commissions", [])
                if not isinstance(commissions, list) or not commissions:
                    continue
                commissions.sort(key=lambda item: item.get("finish_time", ""))
                for index, commission in enumerate(commissions):
                    if name is not None and commission.get("name") != name:
                        continue
                    if duration_hour is not None and commission.get("duration") != duration_hour:
                        continue
                    if create_time is not None and commission.get("create_time") != create_time:
                        continue
                    removed = commissions.pop(index)
                    data["running_gem_commissions"] = commissions
                    self._save_stats_in_connection(conn, instance, month, data)
                    return removed
        return None

    def settle_gem_commission(
        self, instance: str, reward: int = 0, *, name: str = None,
        duration_hour: int = None, create_time: str = None,
    ) -> Optional[Dict[str, Any]]:
        """在一个 SQLite 事务中将运行委托移至当前月的结算记录。"""
        now = datetime.now()
        months = self._commission_month_keys(now)
        with self._stats_transaction() as conn:
            data = {month: self._get_stats_in_connection(conn, instance, month) for month in months}
            removed, source_month = self._settle_running_in_months(
                data, months, now, reward, name, duration_hour, create_time,
            )
            if removed is not None:
                self._save_commission_months(conn, instance, data, months, {source_month, months[0]})
        return removed

    def settle_expired_gem_commissions(
        self, instance: str, now: datetime = None
    ) -> int:
        """领取完成后批量结算未获钻石的到期委托，失败时整体回滚。

        游戏时间只决定到期条件；归档月和时间戳沿用系统当前时间。
        """
        now = now or current_time()
        settled_at = datetime.now()
        months = self._commission_month_keys(settled_at)
        settled = 0
        with self._stats_transaction() as conn:
            data = {month: self._get_stats_in_connection(conn, instance, month) for month in months}
            changed = set()
            for commission in self._running_commissions_from_months(data, months):
                try:
                    finish_time = datetime.fromisoformat(commission["finish_time"])
                except (KeyError, TypeError, ValueError):
                    logger.warning(f"钻石委托完成时间无效，跳过结算: {commission}")
                    continue
                if finish_time > now:
                    continue
                removed, source_month = self._settle_running_in_months(
                    data, months, settled_at, 0, name=commission.get("name"),
                    duration_hour=commission.get("duration"), create_time=commission.get("create_time"),
                )
                if removed is not None:
                    changed.update((source_month, months[0]))
                    settled += 1
            self._save_commission_months(conn, instance, data, months, changed)
        return settled

    def async_add_commission_income(
        self,
        instance: str,
        items: Dict[str, int],
        commission_count: int = 1,
        screenshots: Optional[List[str]] = None,
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(
            self.add_commission_income, instance, items, commission_count, screenshots
        )

    def async_get_commission_income(
        self, instance: str, year: int = None, month: int = None
    ):
        from module.base.async_executor import async_executor

        return async_executor.submit(self.get_commission_income, instance, year, month)


# 单例实例
db = Cl1Database()
