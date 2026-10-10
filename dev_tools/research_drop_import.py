"""把一批科研掉落截图导入某个实例的掉落库。

ALAS 只在领奖时实时统计；手上已有的历史截图（自己留的、别人给的）可以用这个工具补进
统计里。导入时间取截图文件名里的毫秒时间戳（文件名不是时间戳时退到文件修改时间），
所以「今日/本月」与统计天数仍然落在真实的那几天，而不是导入这天。

用法：
    # 先看会导入什么，不写库
    uv run python -m dev_tools.research_drop_import --folder "<截图目录>" --instance 测试 --dry-run
    # 真导入
    uv run python -m dev_tools.research_drop_import --folder "<截图目录>" --instance 测试
    # 写另一份部署的数据（数据库路径跟代码所在目录，不是当前目录，所以要显式指定）
    uv run python -m dev_tools.research_drop_import --folder "<截图目录>" --instance 测试 \
        --db "D:/AzurPilot/config/azurpilot.db"

说明：
- 只有「队列页 + 获得道具」的截图会被导入；军部研究室主页那种多半没有掉落，归到「无掉落」。
  （科研主页领奖也可能带收获，那类记录没有队列页，期数会是 0，只在金装、心智/物资视图里出现。）
- 已经在库里的记录按 imgid 跳过，所以可以放心重跑；
- 只往本地 azurpilot.db 追加，不联网，也不碰别的实例。
"""

import argparse
import os
import typing as t
from collections import Counter
from datetime import datetime

from module.config import server as server_config
from module.logger import logger

RESEARCH_FOLDER_HINT = '截图目录里通常同时有「队列页+获得道具」和「军部研究室主页」两种图，' \
                       '后者没有掉落，会被跳过。'


def file_time(file: str) -> datetime:
    """取截图对应的时间：优先文件名里的毫秒时间戳，退到文件修改时间。

    Args:
        file (str): 截图路径。

    Returns:
        datetime: 该截图的时间。
    """
    stem = os.path.splitext(os.path.basename(file))[0]
    if stem.isdigit():
        try:
            return datetime.fromtimestamp(int(stem) / 1000)
        except (OverflowError, OSError, ValueError):
            pass
    return datetime.fromtimestamp(os.path.getmtime(file))


def existing_imgids(db, instance: str, months: t.Iterable[str]) -> set:
    """取实例在这些月份里已经记录过的 imgid。

    导入要可重跑：库里 `add_research_drop` 的去重只看最近 50 条，
    对一次几百上千条的历史导入不够，所以这里自己先查一遍。

    Args:
        db (Cl1Database): 目标数据库。
        instance (str): ALAS 实例名。
        months (list[str]): 'YYYY-MM' 列表。

    Returns:
        set: 已存在的 imgid 集合。
    """
    found = set()
    for month in sorted(set(months)):
        year, number = month.split('-')
        for entry in db.get_research_drop(instance, int(year), int(number)):
            if entry.get('imgid'):
                found.add(entry['imgid'])
    return found


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--folder', action='append', default=[],
                        help='科研截图目录，可重复指定')
    parser.add_argument('--instance', required=True,
                        help='写入哪个 ALAS 实例（如 测试），统计按实例隔离')
    parser.add_argument('--server', default='cn', choices=['cn', 'en', 'jp', 'tw'],
                        help='游戏服务器，影响截图资源')
    parser.add_argument('--db', default=None,
                        help='azurpilot.db 的路径；缺省用本仓库的 config/azurpilot.db。'
                             '要写另一份部署的数据时显式指定——数据库路径跟的是'
                             '**代码所在目录**，不是当前工作目录')
    parser.add_argument('--dry-run', action='store_true',
                        help='只解析并打印结果，不写库')
    args = parser.parse_args()

    server_config.server = args.server
    if not args.folder:
        parser.error('至少需要一个 --folder')

    files = []
    for folder in args.folder:
        if not os.path.isdir(folder):
            logger.warning(f'[科研导入] 目录不存在，跳过: {folder}')
            continue
        files.extend(sorted(
            os.path.join(folder, name) for name in os.listdir(folder)
            if name.lower().endswith('.png')
        ))
    if not files:
        logger.warning('[科研导入] 没有找到截图')
        return
    logger.info(f'[科研导入] 共 {len(files)} 个文件，目标实例 {args.instance}'
                + ('（试跑，不写库）' if args.dry_run else ''))

    from pathlib import Path

    from module.base.utils import load_image
    from module.statistics.cl1_database import Cl1Database
    from module.statistics.research_drop import get_parser

    # 单独建一个实例而不是用模块级的 db：默认连接运行入口选定的普通总库，
    # 想把数据写进另一份部署就必须显式指定，所以这里把路径打出来。
    from module.persistence.database import get_database
    database = get_database(Path(args.db).absolute().parent) if args.db else get_database()
    if args.db and Path(args.db).name != 'azurpilot.db':
        database.add_legacy_source('cl1', args.db)
    db = Cl1Database(store=database)
    logger.info(f'[科研导入] 数据库 {db.db_path}')

    parser_ = get_parser()
    if not args.dry_run:
        skipped_imgids = existing_imgids(
            db, args.instance, (file_time(file).strftime('%Y-%m') for file in files))
        if skipped_imgids:
            logger.info(f'[科研导入] 库里已有 {len(skipped_imgids)} 条同 imgid 记录，将跳过')

    written = 0
    empty = 0
    failed = 0
    duplicate = 0
    series_counter = Counter()
    item_counter: t.Counter = Counter()
    months = Counter()
    for index, file in enumerate(files):
        try:
            drop = parser_.parse([load_image(file)])
        except Exception as e:
            failed += 1
            logger.warning(f'[科研导入] 解析失败 {os.path.basename(file)}: {e}')
            continue
        if not drop.valid:
            # 军部研究室主页那种截图，本来就没有掉落物
            empty += 1
            continue
        stamp = file_time(file)
        imgid = os.path.basename(file)
        if not args.dry_run and imgid in skipped_imgids:
            duplicate += 1
            continue
        series_counter[drop.series] += 1
        item_counter.update(drop.items)
        months[stamp.strftime('%Y-%m')] += 1
        if not args.dry_run:
            db.add_research_drop(args.instance, drop.project, drop.series, drop.items,
                                 imgid=imgid, ts=stamp)
        written += 1
        if index % 200 == 0:
            logger.info(f'[科研导入] ... {index}/{len(files)}，已处理 {written} 条')

    logger.info(f'[科研导入] {"试跑统计" if args.dry_run else "导入完成"}：'
                f'掉落记录 {written} 条、无掉落 {empty} 个、重复跳过 {duplicate} 个、失败 {failed} 个')
    logger.info('[科研导入] 期数分布：'
                + '、'.join(f'{series or "未识别"}期 {count} 条'
                            for series, count in sorted(series_counter.items(), reverse=True)))
    logger.info('[科研导入] 月份分布：'
                + '、'.join(f'{month} {count} 条' for month, count in sorted(months.items())))
    logger.info('[科研导入] 掉落物前 12 项：'
                + '、'.join(f'{name} x{count}' for name, count in item_counter.most_common(12)))
    print(RESEARCH_FOLDER_HINT)


if __name__ == '__main__':
    main()
