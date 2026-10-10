"""舰船经验效率统计模块。

统计舰船经验检测数据和战斗时间，包含每日经验效率统计，
用于预估升级时间。

功能：
- 记录每次战斗的经验获取量和战斗时间
- 计算每日经验效率（经验/小时）
- 预估达到目标等级所需时间
- 持久化统计数据到普通业务总库

继承自 LIST_SHIP_EXP 数据，复用经验数据定义。
"""

# 此文件用于统计舰船经验检测数据和战斗时间
# 包含每日经验效率统计，用于预估升级时间

from __future__ import annotations

import math
import time
import sqlite3
from pathlib import Path
from datetime import datetime, date
from typing import Any

from module.os.ship_exp_data import LIST_SHIP_EXP
from module.logger import logger
from module.config.time_source import now as current_time


class ShipExpStats:
    """舰船经验统计类。

    记录每场战斗时间和经验，统计每日效率（经验/小时），并保存舰船检测数据。
    """

    # 每个位置的每场战斗经验值
    EXP_PER_BATTLE = {
        1: 431,  # 旗舰
        2: 288, 3: 288, 4: 288, 5: 288, 6: 288  # 其他位置
    }
    AVG_EXP_PER_BATTLE = 312  # 平均每场经验
    BATTLES_PER_ROUND = 2     # 侵蚀1每轮默认2场战斗

    MAX_BATTLE_TIME_SAMPLES = 100  # 保留最近100场战斗时间样本
    MAX_DAILY_STATS_DAYS = 30      # 保留最近30天的统计

    def __init__(self, path: Path | None = None, instance_name: str | None = None, *, store=None):
        from module.persistence.database import get_database
        if path is not None:
            legacy = Path(path).absolute()
            directory = legacy.parents[3] / 'config' if legacy.parent.parent.name == 'cl1' else legacy.parent
            self.store = store or get_database(directory)
            self.store.add_legacy_source('ships', legacy)
            self._instance_name = instance_name or legacy.parent.name
        else:
            self.store = store or get_database()
            self._instance_name = instance_name or 'default'
        self._path = self.store.path
        self.data = self._load()
        self._battle_start_time: float | None = None


    def _load(self) -> dict[str, Any]:
        from module.persistence.snapshots import read_ship
        self._locked = False
        with self.store.transaction(write=False) as connection:
            data = read_ship(connection, self._instance_name)
        return {} if data is None else data


    def _save(self) -> None:
        """用总库事务替换当前实例经验快照，失败完整回滚。"""
        from module.persistence.snapshots import save_ship
        try:
            with self.store.transaction() as connection:
                save_ship(connection, self._instance_name, self.data)
        except (OSError, ValueError, TypeError, sqlite3.Error) as error:
            logger.warning(f'[统计-经验] 保存舰船经验失败: {type(error).__name__}')


    # ========== 战斗时间记录 ==========

    def on_battle_start(self) -> None:
        """战斗开始时调用（侵蚀1 / 耄耋相接等统一入口）。"""
        self._battle_start_time = time.time()

    def on_battle_end(
        self,
        fleet_index: int = 1,
        source: str = "cl1",
        record_daily_summary: bool = False,
    ) -> float | None:
        """战斗结束时调用，记录战斗耗时和经验。

        Args:
            fleet_index (int): 舰队索引（1-6），用于确定经验值。默认为 1。
            source (str): 战斗来源。"cl1" 表示侵蚀1练级，"meow" 表示耄耋相接。默认为 "cl1"。
            record_daily_summary (bool): 是否记录日报专用的精确侵蚀1事件。默认为 False。

        Returns:
            float | None: 本场战斗耗时（秒）。若未记录开始时间则返回 None。
        """
        if self._battle_start_time is None:
            return None

        duration = time.time() - self._battle_start_time
        self._battle_start_time = None

        # 过滤异常值 (太短或太长的战斗)
        if duration < 1 or duration > 300:
            logger.debug(f'战斗时长 {duration:.1f} 秒超出合理范围，不予记录')
            return duration

        # 记录战斗时间（根据来源分别统计）
        source = "meow" if source == "meow" else "cl1"
        self._record_battle_time(duration, source=source)

        # 计算本场经验 (使用平均值，因为每个位置经验不同)
        # 旗舰 431 + 其他位置 288*5 = 1871, 平均 312
        avg_exp = self.AVG_EXP_PER_BATTLE

        # 每日经验效率用于侵蚀1练级预估，避免被耄耋相接耗时混入。
        if source == "cl1" and record_daily_summary:
            from module.statistics.daily_summary_store import get_daily_summary_store

            get_daily_summary_store().record_cl1_battle_event(
                instance=self._instance_name,
                timestamp=current_time(),
                duration_seconds=duration,
                estimated_exp=avg_exp,
            )
        if source == "cl1":
            self._update_daily_stats(exp_gained=avg_exp, battle_duration=duration)

        logger.info(f'{source.upper()} 战斗已记录：{duration:.1f}s，经验：{avg_exp}')
        return duration

    def _record_battle_time(self, duration: float, source: str = "cl1") -> None:
        """记录单场战斗时间到样本列表中。

        Args:
            duration (float): 本场战斗时长（秒）。
            source (str): 战斗来源（"cl1" 或 "meow"）。默认为 "cl1"。
        """
        # 不同来源使用不同的键，避免侵蚀1与耄耋相接混合统计
        if source == "meow":
            key = 'meow_battle_times'
            default_avg = 52.0  # 默认值，后续会被真实样本覆盖
        else:
            key = 'battle_times'
            default_avg = 52.0

        if key not in self.data:
            self.data[key] = {'samples': [], 'average': default_avg}

        samples = self.data[key]['samples']
        samples.append(round(duration, 2))

        # 只保留最近N个样本
        if len(samples) > self.MAX_BATTLE_TIME_SAMPLES:
            self.data[key]['samples'] = samples[-self.MAX_BATTLE_TIME_SAMPLES:]
            samples = self.data[key]['samples']

        # 更新平均值
        if samples:
            self.data[key]['average'] = round(sum(samples) / len(samples), 2)

        self._save()

    def record_round_time(self, round_duration: float) -> None:
        """记录单轮侵蚀1时间到样本列表中。

        Args:
            round_duration (float): 单轮战斗耗时（秒）。
        """
        if 'round_times' not in self.data:
            self.data['round_times'] = {'samples': [], 'average': 120.0}

        samples = self.data['round_times']['samples']
        samples.append(round(round_duration, 2))

        # 只保留最近100个样本
        if len(samples) > 100:
            self.data['round_times']['samples'] = samples[-100:]
            samples = self.data['round_times']['samples']

        # 更新平均值
        if samples:
            self.data['round_times']['average'] = round(sum(samples) / len(samples), 2)

        self._save()

    # ========== 每日经验效率统计 ==========

    def _update_daily_stats(self, exp_gained: int, battle_duration: float) -> None:
        """更新每日统计数据，在每场战斗结束后累加到当天的统计。

        Args:
            exp_gained (int): 本场获得的经验值。
            battle_duration (float): 本场战斗耗时（秒）。
        """
        today = date.today().isoformat()  # "2026-01-01"

        if 'daily_stats' not in self.data:
            self.data['daily_stats'] = {}

        if today not in self.data['daily_stats']:
            self.data['daily_stats'][today] = {
                'total_run_time': 0.0,
                'total_exp_gained': 0,
                'battle_count': 0,
                'exp_per_hour': 0.0
            }

        stats = self.data['daily_stats'][today]
        stats['total_run_time'] += battle_duration
        stats['total_exp_gained'] += exp_gained
        stats['battle_count'] += 1

        # 计算每小时经验效率
        hours = stats['total_run_time'] / 3600
        if hours > 0:
            stats['exp_per_hour'] = round(stats['total_exp_gained'] / hours, 2)

        # 清理旧数据
        self._cleanup_old_daily_stats()

        self._save()

    def _cleanup_old_daily_stats(self) -> None:
        """清理超过保留天数的旧统计数据。"""
        if 'daily_stats' not in self.data:
            return

        dates = sorted(self.data['daily_stats'].keys(), reverse=True)
        if len(dates) > self.MAX_DAILY_STATS_DAYS:
            for old_date in dates[self.MAX_DAILY_STATS_DAYS:]:
                del self.data['daily_stats'][old_date]

    def get_average_battle_time(self) -> float:
        """获取平均每场战斗时间。

        Returns:
            float: 平均耗时（秒）。
        """
        return self.data.get('battle_times', {}).get('average', 52.0)

    def get_average_meow_battle_time(self) -> float:
        """获取耄耋相接平均每场战斗时间。

        Returns:
            float: 平均耗时（秒）。
        """
        return self.data.get('meow_battle_times', {}).get('average', self.get_average_battle_time())

    def get_average_round_time(self) -> float:
        """获取平均每轮侵蚀1时间。

        Returns:
            float: 平均耗时（秒）。
        """
        if 'round_times' in self.data and self.data['round_times'].get('samples'):
            return self.data['round_times']['average']
        return self.get_average_battle_time() * 2 + 15

    def get_exp_per_hour(self) -> float:
        """获取经验效率（经验/小时）。

        使用公式估算：平均每场经验 * 2 / 平均一轮时长。

        Returns:
            float: 每小时获取的经验值。
        """
        avg_round_time = self.get_average_round_time()
        if avg_round_time > 0:
            exp_per_hour = (
                self.AVG_EXP_PER_BATTLE
                * self.BATTLES_PER_ROUND
                * 3600
                / avg_round_time
            )
            return round(exp_per_hour, 2)

        return 22000.0  # 默认值

    def get_today_stats(self) -> dict[str, Any] | None:
        """获取今日统计数据。

        Returns:
            dict[str, Any] | None: 今日统计数据字典，若不存在则返回 None。
        """
        today = date.today().isoformat()
        if 'daily_stats' not in self.data:
            return None
        return self.data['daily_stats'].get(today)

    # ========== 舰船数据保存与进度计算 ==========

    def save_ship_data(
        self,
        ships: list[dict[str, Any]],
        target_level: int,
        fleet_index: int,
        battle_count_at_check: int
    ) -> None:
        """保存舰船经验检测数据。

        Args:
            ships (list[dict[str, Any]]): 舰船数据列表，每项包含 position, level, current_exp, total_exp。
            target_level (int): 目标等级。
            fleet_index (int): 舰队索引。
            battle_count_at_check (int): 检测时的战斗场次。
        """
        self.data['last_check_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.data['target_level'] = target_level
        self.data['fleet_index'] = fleet_index
        self.data['battle_count_at_check'] = battle_count_at_check
        self.data['ships'] = ships
        self._save()
        logger.info(f'[统计-经验] 舰船经验数据已保存: {len(ships)} 艘舰船，目标等级 {target_level}')

    def calculate_progress(
        self,
        ship: dict[str, Any],
        target_level: int,
        current_battle_count: int
    ) -> dict[str, Any]:
        """计算单艘舰船的升级进度。

        Args:
            ship (dict[str, Any]): 舰船数据字典（包含 position, level, current_exp, total_exp）。
            target_level (int): 目标等级。
            current_battle_count (int): 当前战斗场次。

        Returns:
            dict[str, Any]: 升级进度数据字典。
        """
        # 处理等级边界 (1-125)
        if target_level < 1:
            target_level = 1
        elif target_level > 125:
            target_level = 125

        target_exp = LIST_SHIP_EXP[target_level - 1]
        current_total_exp = ship.get('total_exp', 0)
        exp_needed = max(0, target_exp - current_total_exp)

        # 计算还需出击次数
        position = ship.get('position', 1)
        exp_per_battle = self.EXP_PER_BATTLE.get(position, 288)
        battles_needed = math.ceil(exp_needed / exp_per_battle) if exp_needed > 0 else 0

        # 计算已战斗场次 (自上次检测以来)
        battle_count_at_check = self.data.get('battle_count_at_check', 0)
        battles_done = max(0, current_battle_count - battle_count_at_check)

        # 计算预估时间 (经验值*2/平均一轮时长)
        avg_round_time = self.get_average_round_time()
        if avg_round_time > 0 and exp_needed > 0 and exp_per_battle > 0:
            ship_exp_per_hour = (
                exp_per_battle
                * self.BATTLES_PER_ROUND
                * 3600
                / avg_round_time
            )
            hours_needed = exp_needed / ship_exp_per_hour
            time_seconds = hours_needed * 3600
        else:
            time_seconds = 0

        return {
            'position': position,
            'level': ship.get('level', 0),
            'current_exp': ship.get('current_exp', 0),
            'total_exp': current_total_exp,
            'target_exp': target_exp,
            'battles_done': battles_done,
            'exp_needed': exp_needed,
            'battles_needed': battles_needed,
            'time_needed': self._format_time(time_seconds)
        }

    def get_all_progress(self, current_battle_count: int) -> list[dict[str, Any]]:
        """获取所有舰船的升级进度。

        Args:
            current_battle_count (int): 当前战斗场次。

        Returns:
            list[dict[str, Any]]: 所有舰船的进度数据列表。
        """
        ships = self.data.get('ships', [])
        target_level = self.data.get('target_level', 125)

        return [
            self.calculate_progress(ship, target_level, current_battle_count)
            for ship in ships
        ]

    @staticmethod
    def _format_time(seconds: float) -> str:
        """格式化时间显示为时分文本。

        Args:
            seconds (float): 秒数。

        Returns:
            str: 格式化后的时间字符串（例如 "1小时30分钟" 或 "45分钟"）。
        """
        if seconds <= 0:
            return "0分钟"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)

        if hours > 0:
            return f"{hours}小时{minutes}分钟"
        return f"{minutes}分钟"


# ========== 单例模式和便捷函数 ==========

_stats_instances: dict[tuple[str, str], ShipExpStats] = {}


def get_ship_exp_stats(instance_name: str | None = None) -> ShipExpStats:
    """获取 ShipExpStats 单例实例。

    Args:
        instance_name (str | None): 实例名称，默认为 "default"。

    Returns:
        ShipExpStats: 舰船经验统计实例。
    """
    global _stats_instances
    from module.persistence.database import get_database
    key = (str(get_database().directory), instance_name or "default")
    if key not in _stats_instances:
        _stats_instances[key] = ShipExpStats(instance_name=instance_name)
    else:
        # 刷新数据
        _stats_instances[key].data = _stats_instances[key]._load()
    return _stats_instances[key]


def save_ship_exp_data(
    ships: list[dict[str, Any]],
    target_level: int,
    fleet_index: int,
    battle_count_at_check: int,
    instance_name: str | None = None
) -> None:
    """便捷函数：保存舰船经验检测数据。

    Args:
        ships (list[dict[str, Any]]): 舰船数据列表。
        target_level (int): 目标等级。
        fleet_index (int): 舰队索引。
        battle_count_at_check (int): 检测时的战斗场次。
        instance_name (str | None): 实例名称。
    """
    get_ship_exp_stats(instance_name=instance_name).save_ship_data(
        ships=ships,
        target_level=target_level,
        fleet_index=fleet_index,
        battle_count_at_check=battle_count_at_check
    )


def get_cl1_interval_summary(
    instance_name: str | None,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """便捷函数：获取指定实例的侵蚀1精确区间统计。"""
    from module.statistics.daily_summary_store import get_daily_summary_store

    return get_daily_summary_store().get_cl1_interval_summary(
        instance=instance_name or 'default', start=start, end=end
    )


__all__ = [
    'ShipExpStats',
    'get_ship_exp_stats',
    'save_ship_exp_data',
    'get_cl1_interval_summary',
]
