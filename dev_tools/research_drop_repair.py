"""用原截图重放科研掉落记录，订正库里因模板改名而失真的条目。

科研掉落在库里存的是**模板文件名**（如 `Prototype_Quadruple_610mm_Cruiser_Torpedo_Mount_T0`），
显示时再拿名称表翻成中文名。模板一旦改名，老记录里的名字就会照新表翻译，于是张冠李戴：
实测把「四联装610mm鱼雷（巡洋用）」显示成八期的彩装主炮、把九期的彩装 Ta 152C
显示成四期的天雷，两者都出现在「第 9 期」的收获里。

名字级的历史映射救不了：旧名 `Prototype_Triple_381mm_AA_Gun_T0` 一条就同时盖住了
两件不同的装备（三联装550mm鱼雷改 / 三联装419mm主炮MK.I），对着名字猜不出谁是谁。
所以订正只能重放原截图——拿当前模板库重新解析，覆盖那一条记录的掉落物。实测 5 条记录
的差异**全部**由改名解释，其余物品逐项一致。

用法：
    # 先看会改什么，不写库
    uv run python -m dev_tools.research_drop_repair --folder "D:/AzurPilot/screenshots/research" \
        --instance alas --dry-run
    # 真订正（数据库路径跟的是代码所在目录，不是当前目录，写别的部署要显式给 --db）
    uv run python -m dev_tools.research_drop_repair --folder "D:/AzurPilot/screenshots/research" \
        --instance alas --db "D:/AzurPilot/config/azurpilot.db"

判读输出：
- `可订正` —— 库里这条与重解析结果不同，逐项打印增删；
- `无差异` —— 一致，跳过；
- `缺截图` / `无掉落` —— 订正不了：前者只能找回截图，后者说明这张图本来没有掉落物；
- `引用了当前库里没有的名字` —— 收尾时汇总，多半就是改名残留，缺截图时只能人工判断。

只动 items，不动期数与项目代号：期数来自卡片角标，与模板名无关，重解析读不出角标时
会得到 0，覆盖反而会毁掉已有数据。新增记录请用 dev_tools/research_drop_import.py。
"""

import argparse
import os
import typing as t
from collections import Counter

from module.config import server as server_config
from module.logger import logger
from dev_tools.research_drop_import import file_time


def load_instance_entries(db, instance: str) -> t.Dict[str, t.Tuple[str, dict]]:
    """取实例的全部科研记录：imgid -> (月份分区, 条目)。

    工具要能发现「截图已经不在手上、名字却还是旧的」这类记录，所以月份列表取库自己的
    分区列表，而不是只按截图时间来推。

    Args:
        db (Cl1Database): 目标数据库。
        instance (str): ALAS 实例名。

    Returns:
        dict: {imgid: (月份, 条目)}。
    """
    found: t.Dict[str, t.Tuple[str, dict]] = {}
    for _, month in db._list_stats_rows(instance):
        year, number = month.split('-')
        for entry in db.get_research_drop(instance, int(year), int(number)):
            imgid = entry.get('imgid')
            if imgid:
                found.setdefault(imgid, (month, entry))
    return found


def current_item_names() -> set:
    """当前模板库认识的物品名（模板文件 ∪ 中文名称表）。

    用来找「库里这条记录引用的名字已经不在当前库里」的残留。

    Returns:
        set: 模板名集合。
    """
    import json

    from module.statistics.research_stats import NAME_TABLE_PATH
    from module.statistics.research_drop import ITEM_TEMPLATE_FOLDER

    names = set()
    if os.path.isdir(ITEM_TEMPLATE_FOLDER):
        names.update(os.path.splitext(name)[0] for name in os.listdir(ITEM_TEMPLATE_FOLDER))
    try:
        with open(NAME_TABLE_PATH, encoding='utf-8') as f:
            names.update(json.load(f).keys())
    except (OSError, ValueError):
        logger.warning(f'[科研订正] 名称表读不出来: {NAME_TABLE_PATH}')
    return names


def print_diff(imgid: str, old: dict, new: dict):
    """打印一条记录的掉落物差异。

    Args:
        imgid (str): 掉落记录文件名。
        old (dict): 库里的 {物品模板名: 数量}。
        new (dict): 重解析得到的 {物品模板名: 数量}。
    """
    print(f'  {imgid}')
    for name in old:
        if name not in new:
            print(f'      - {name:<52} x{old[name]}')
    for name in new:
        if name not in old:
            print(f'      + {name:<52} x{new[name]}')
        elif new[name] != old[name]:
            print(f'      ~ {name:<52} x{old[name]} -> x{new[name]}')


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--folder', action='append', default=[],
                        help='科研截图目录，可重复指定')
    parser.add_argument('--instance', required=True,
                        help='订正哪个 ALAS 实例（如 alas），统计按实例隔离')
    parser.add_argument('--server', default='cn', choices=['cn', 'en', 'jp', 'tw'],
                        help='游戏服务器，影响截图资源')
    parser.add_argument('--db', default=None,
                        help='azurpilot.db 的路径；缺省用本仓库的 config/azurpilot.db。'
                             '要订正另一份部署的数据时显式指定——数据库路径跟的是'
                             '**代码所在目录**，不是当前工作目录')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印差异，不写库')
    args = parser.parse_args()

    server_config.server = args.server
    if not args.folder:
        parser.error('至少需要一个 --folder')

    files = []
    for folder in args.folder:
        if not os.path.isdir(folder):
            logger.warning(f'[科研订正] 目录不存在，跳过: {folder}')
            continue
        files.extend(sorted(
            os.path.join(folder, name) for name in os.listdir(folder)
            if name.lower().endswith('.png')
        ))
    if not files:
        logger.warning('[科研订正] 没有找到截图')
        return

    from pathlib import Path

    from module.base.utils import load_image
    from module.statistics.cl1_database import Cl1Database
    from module.statistics.research_drop import get_parser

    from module.persistence.database import get_database
    database = get_database(Path(args.db).absolute().parent) if args.db else get_database()
    if args.db and Path(args.db).name != 'azurpilot.db':
        database.add_legacy_source('cl1', args.db)
    db = Cl1Database(store=database)
    logger.info(f'[科研订正] 数据库 {db.db_path}')
    entries = load_instance_entries(db, args.instance)
    logger.info(f'[科研订正] 实例 {args.instance} 有 {len(entries)} 条记录，'
                f'待核对截图 {len(files)} 个'
                + ('（试跑，不写库）' if args.dry_run else ''))

    parser_ = get_parser()
    known = current_item_names()
    repaired: t.List[str] = []
    unchanged = 0
    missing = 0
    empty = 0
    failed = 0
    for file in files:
        imgid = os.path.basename(file)
        if imgid not in entries:
            # 目录里往往混着别的实例、或还没导入的截图，逐条打日志会淹掉差异
            missing += 1
            continue
        try:
            drop = parser_.parse([load_image(file)])
        except Exception as e:
            failed += 1
            logger.warning(f'[科研订正] 解析失败 {imgid}: {e}')
            continue
        if not drop.valid:
            empty += 1
            logger.warning(f'[科研订正] 这张图解析不出掉落物，跳过: {imgid}')
            continue

        old = dict(entries[imgid][1].get('items') or {})
        if old == drop.items:
            unchanged += 1
            continue
        print_diff(imgid, old, drop.items)
        if not args.dry_run:
            if db.update_research_drop_items(args.instance, imgid, drop.items):
                repaired.append(imgid)
            else:
                failed += 1
                logger.warning(f'[科研订正] 写回失败: {imgid}')
        else:
            repaired.append(imgid)

    # 收尾：还有哪些记录引用了当前库里没有的名字（多半就是改名残留）
    stale: t.Dict[str, t.List[str]] = {}
    for imgid, (month, entry) in entries.items():
        if imgid in repaired:
            continue
        unknown = sorted(name for name in (entry.get('items') or {})
                         if not name.isdigit() and name not in known)
        if unknown:
            stale[f'{month}/{imgid}'] = unknown

    logger.info(f'[科研订正] {"试跑" if args.dry_run else "订正"}完成：'
                f'可订正 {len(repaired)} 条、无差异 {unchanged} 条、'
                f'解析不出掉落 {empty} 条、失败 {failed} 条')
    if missing:
        logger.info(f'[科研订正] 另有 {missing} 张截图在库里没有对应记录，未动'
                    '（要补进库用 dev_tools/research_drop_import.py）')
    if stale:
        print(f'\n库里还有 {len(stale)} 条记录引用了当前模板库没有的名字'
              '（缺截图时只能人工判断或找回截图）：')
        for key, names in sorted(stale.items()):
            print(f'  {key}')
            for name in names:
                print(f'      {name}')
    if args.dry_run and repaired:
        print('\n以上为试跑结果，去掉 --dry-run 才会真正写库。')


if __name__ == '__main__':
    main()
