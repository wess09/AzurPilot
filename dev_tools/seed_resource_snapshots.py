"""
向 azurstats_local.db 插入随机资源快照数据，用于测试资源历史趋势图表的渲染效果。

生成的数据具有真实感：
- 每种资源有独立的基准值、趋势方向和波动幅度
- 包含随机 None 值（模拟某些时刻未检测到特定资源）
- 数据点均匀分布在指定时间范围内

用法：
    uv run python dev_tools/seed_resource_snapshots.py
    uv run python dev_tools/seed_resource_snapshots.py --count=200 --instance=alas
    uv run python dev_tools/seed_resource_snapshots.py --days=30 --interval=30
    uv run python dev_tools/seed_resource_snapshots.py --gap-prob=0.08  # 8% 概率出现空值
    uv run python dev_tools/seed_resource_snapshots.py --clear              # 先清空再插入
    uv run python dev_tools/seed_resource_snapshots.py --dry-run            # 只打印不写入
"""
import argparse
import math
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta

# 切换到项目根目录
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_project_root)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_DB = './config/azurstats_local.db'

# 每种资源的模拟参数 (base, trend_per_day, amplitude, min_val, max_val)
RESOURCE_PROFILES = {
    'oil':          (15000, -800,   3000,  2000,  30000),
    'coin':         (80000,  2000,  8000,  5000,  200000),
    'gem':          (40000,  50,    500,   30000, 50000),
    'pt':           (5000,   300,   1500,  0,     50000),
    'cube':         (800,    -5,    30,    10,    1500),
    'core':         (3000,   100,   400,   0,     8000),
    'medal':        (1500,   20,    200,   0,     5000),
    'merit':        (5000,   -100,  800,   0,     20000),
    'guild_coin':   (3000,   80,    500,   0,     10000),
    'action_point': (200,    -5,    40,    0,     400),
    'yellow_coin':  (500,    10,    80,    0,     2000),
    'purple_coin':  (50,     -1,    15,    0,     300),
}


def _generate_timeline(
    base: int, trend: float, amp: int, lo: int, hi: int,
    n: int, gap_prob: float, noise: float = 0.1,
) -> list:
    """生成一条带趋势、波动和空值的时间序列。"""
    values = []
    for i in range(n):
        if random.random() < gap_prob:
            values.append(None)
            continue
        # 基准 + 趋势 + 正弦波动 + 随机噪声
        t = i / (n - 1) if n > 1 else 0
        v = base + trend * t * n / 24 + amp * math.sin(t * math.pi * 2 * random.uniform(0.5, 2.0))
        v += random.gauss(0, amp * noise)
        v = max(lo, min(hi, int(round(v))))
        values.append(v)
    return values


def seed_snapshots(
    instance: str = "alas",
    count: int = 120,
    interval_minutes: int = 15,
    gap_prob: float = 0.05,
    dry_run: bool = False,
):
    """生成随机快照并写入数据库。

    Args:
        instance: 实例名
        count: 快照条数
        interval_minutes: 每条快照的时间间隔（分钟）
        gap_prob: 每条资源出现 None 的概率
        dry_run: 只打印不写入
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=interval_minutes * (count - 1))
    timestamps = [start_time + timedelta(minutes=interval_minutes * i) for i in range(count)]

    resource_keys = [
        'oil', 'coin', 'gem', 'pt', 'cube',
        'core', 'medal', 'merit', 'guild_coin',
        'action_point', 'yellow_coin', 'purple_coin',
    ]

    # 为每种资源生成时间序列
    series = {}
    for key in resource_keys:
        base, trend, amp, lo, hi = RESOURCE_PROFILES[key]
        series[key] = _generate_timeline(base, trend, amp, lo, hi, count, gap_prob)

    db_path = os.path.join(os.getcwd(), _DB)
    print(f"数据库: {db_path}")
    print(f"实例:     {instance}")
    print(f"数据条数: {count}")
    print(f"时间范围: {timestamps[0]:%Y-%m-%d %H:%M} ~ {timestamps[-1]:%Y-%m-%d %H:%M}")
    print(f"空值概率: {gap_prob:.0%}")
    print()

    if dry_run:
        # 预览前 5 条
        print(f"{'时间':<20} {'石油':>8} {'物资':>8} {'钻石':>8} {'活动Pt':>8} {'魔方':>6} "
              f"{'核心':>6} {'勋章':>6} {'功勋':>6} {'舰队币':>8} {'行动力':>6} {'黄币':>6} {'紫币':>6}")
        print("-" * 110)
        for i in range(min(5, count)):
            ts = timestamps[i].strftime("%m-%d %H:%M")
            vals = [ts] + [str(series[k][i]) if series[k][i] is not None else "  N/A" for k in resource_keys]
            print(" ".join(f"{v:>8}" for v in vals))
        print("... (dry-run, 未写入)")
        print(f"\n各资源范围预览:")
        for k in resource_keys:
            valid = [v for v in series[k] if v is not None]
            none_cnt = sum(1 for v in series[k] if v is None)
            if valid:
                print(f"  {k:>12}: {min(valid):>8} ~ {max(valid):<8}  (None: {none_cnt})")
            else:
                print(f"  {k:>12}: 全部为 None")
        return

    # 写入数据库
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resource_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance TEXT NOT NULL,
            ts TEXT NOT NULL,
            oil INTEGER, coin INTEGER, gem INTEGER, pt INTEGER, cube INTEGER,
            core INTEGER, medal INTEGER, merit INTEGER, guild_coin INTEGER,
            action_point INTEGER, yellow_coin INTEGER, purple_coin INTEGER
        )
    """)

    rows = []
    for i in range(count):
        rows.append((
            instance, timestamps[i].isoformat(),
            series['oil'][i], series['coin'][i], series['gem'][i], series['pt'][i],
            series['cube'][i], series['core'][i], series['medal'][i], series['merit'][i],
            series['guild_coin'][i], series['action_point'][i],
            series['yellow_coin'][i], series['purple_coin'][i],
        ))

    conn.executemany("""
        INSERT INTO resource_snapshots
            (instance, ts,
             oil, coin, gem, pt, cube,
             core, medal, merit, guild_coin,
             action_point, yellow_coin, purple_coin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    cursor = conn.execute("SELECT COUNT(*) FROM resource_snapshots WHERE instance=?", (instance,))
    total = cursor.fetchone()[0]
    conn.close()

    print(f"已写入 {len(rows)} 条记录到实例 '{instance}'（当前共 {total} 条）")
    print()
    print(f"各资源实际范围:")
    for k in resource_keys:
        valid = [v for v in series[k] if v is not None]
        none_cnt = sum(1 for v in series[k] if v is None)
        if valid:
            print(f"  {k:>12}: {min(valid):>8} ~ {max(valid):<8}  (None: {none_cnt})")
        else:
            print(f"  {k:>12}: 全部为 None")


def clear_snapshots(instance: str = "alas", dry_run: bool = False):
    """清空指定实例的快照数据。"""
    db_path = os.path.join(os.getcwd(), _DB)
    if not os.path.exists(db_path):
        print("数据库文件不存在，无需清空")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT COUNT(*) FROM resource_snapshots WHERE instance=?", (instance,))
    count = cursor.fetchone()[0]

    if dry_run:
        print(f"[DRY-RUN] 将清空实例 '{instance}' 的 {count} 条记录")
        conn.close()
        return

    conn.execute("DELETE FROM resource_snapshots WHERE instance=?", (instance,))
    conn.commit()
    conn.close()
    print(f"已清空实例 '{instance}' 的 {count} 条记录")


def main():
    parser = argparse.ArgumentParser(description="向 azurstats_local.db 插入随机资源快照测试数据")
    parser.add_argument("--instance", default="alas", help="实例名 (默认: alas)")
    parser.add_argument("--count", type=int, default=120, help="快照条数 (默认: 120, ≈ 30小时 @ 15min间隔)")
    parser.add_argument("--interval", type=int, default=15, help="快照间隔分钟数 (默认: 15)")
    parser.add_argument("--gap-prob", type=float, default=0.05, help="每条资源出现 None 的概率 (默认: 0.05)")
    parser.add_argument("--clear", action="store_true", help="先清空再插入")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    args = parser.parse_args()

    if args.clear:
        clear_snapshots(args.instance, dry_run=args.dry_run)

    seed_snapshots(
        instance=args.instance,
        count=args.count,
        interval_minutes=args.interval,
        gap_prob=args.gap_prob,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
