"""科研掉落全量检测：对一批截图跑一遍识别，输出逐张明细供核查。

与 `research_drop_import` 的区别是**不写库**，且连「模板库里没有的物品」也一并记下来
（正式链路里那些会以数字编号被丢弃）。所以它既能验证识别准确率，也能看出
「删模板 / 补模板」之后哪些物品改了身份。

用法：
    # 单进程跑整个目录
    uv run python -m dev_tools.research_drop_verify --folder "<截图目录>" --out log/verify.json
    # 分片并行（4 个进程各跑 1/4）
    uv run python -m dev_tools.research_drop_verify --folder "<目录>" --shard 1/4 --out log/v1.json

输出 JSON：
    {
      'folder': 截图目录, 'templates': 模板数, 'count': 解析张数,
      'records': [
          {'file': 文件名, 'frames': 帧数, 'queue': 是否队列页, 'project': 代号,
           'series': 期数, 'items': {模板名: 数量}, 'unknown': {数字编号: 数量},
           'shots': [{'items': ..., 'unknown': ...}, ...]},   # 逐收获帧的明细
          ...
      ]
    }
"""

import argparse
import json
import os
import sys
import time

from module.config import server as server_config
from module.logger import logger


def reset_unknown_templates(grid):
    """清掉上一张图建的「数字编号」临时模板。

    `ItemGrid.match_template` 匹配不到已知模板时会现场建一个数字编号的模板并留在内存里，
    单张图之间不清掉的话会一路累积（1986 张要建上千个），既拖慢匹配也让编号失去意义。

    Args:
        grid (ItemGrid): 科研自己的物品网格。
    """
    for name in [name for name in grid.templates if name.isdigit()]:
        grid.templates.pop(name, None)
        grid.colors.pop(name, None)
        grid.templates_hit.pop(name, None)


def analyze(parser, file):
    """解析一张截图，连未知物品一起记下来。

    Args:
        parser (ResearchDropParser): 科研掉落解析器。
        file (str): 截图路径。

    Returns:
        dict: 该图的识别明细；读图失败时只有 file 与 error。
    """
    from module.base.utils import load_image
    from module.research.assets import QUEUE_CHECK
    from module.statistics.utils import unpack

    name = os.path.basename(file)
    try:
        image = load_image(file)
    except Exception as e:
        return {'file': name, 'error': f'读图失败: {e}'}

    frames = []
    try:
        frames.extend(unpack(image))
    except Exception as e:
        return {'file': name, 'error': f'拆帧失败: {e}', 'frames': 0}

    queue_page = None
    for frame in frames:
        if QUEUE_CHECK.match(frame, offset=(10, 10)):
            queue_page = frame
            break

    project = ''
    series = 0
    if queue_page is not None:
        project = parser._read_project(queue_page)
        series = parser._read_series(queue_page)

    items = {}
    unknown = {}
    shots = []
    seen = set()
    for frame in frames:
        if frame is queue_page:
            continue
        key = id(frame)
        if key in seen:
            continue
        seen.add(key)
        try:
            got = parser.stats.stats_get_items(frame)
        except Exception:
            # 不是「获得道具」界面
            continue
        shot_items = {}
        shot_unknown = {}
        for item in got:
            if item.is_known_item():
                shot_items[item.name] = shot_items.get(item.name, 0) + item.amount
            else:
                shot_unknown[item.name] = shot_unknown.get(item.name, 0) + item.amount
        if shot_items or shot_unknown:
            shots.append({'items': shot_items, 'unknown': shot_unknown})
        for key_name, amount in shot_items.items():
            items[key_name] = items.get(key_name, 0) + amount
        for key_name, amount in shot_unknown.items():
            unknown[key_name] = unknown.get(key_name, 0) + amount

    return {
        'file': name,
        'frames': len(frames),
        'queue': queue_page is not None,
        'project': project,
        'series': series,
        'items': items,
        'unknown': unknown,
        'shots': shots,
    }


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--folder', action='append', default=[],
                        help='科研截图目录，可重复指定')
    parser.add_argument('--out', default=None, help='结果 JSON 的输出路径')
    parser.add_argument('--limit', type=int, default=0, help='只跑前 N 张（测速用）')
    parser.add_argument('--shard', default=None,
                        help='分片，形如 i/n（第 i 片，共 n 片），用于多进程并行')
    parser.add_argument('--server', default='cn', choices=['cn', 'en', 'jp', 'tw'],
                        help='游戏服务器，影响截图资源')
    args = parser.parse_args()

    server_config.server = args.server
    if not args.folder:
        parser.error('至少需要一个 --folder')

    files = []
    for folder in args.folder:
        if not os.path.isdir(folder):
            logger.warning(f'[科研检测] 目录不存在，跳过: {folder}')
            continue
        files.extend(sorted(
            os.path.join(folder, name) for name in os.listdir(folder)
            if name.lower().endswith('.png')
        ))
    if not files:
        logger.warning('[科研检测] 没有找到截图')
        return
    index, total = 0, 1
    if args.shard:
        index, total = (int(part) for part in args.shard.split('/'))
        files = files[index - 1::total]
        # 分片并行时多个进程会抢同一个日志文件（Windows 下报 PermissionError），
        # 给每个分片一个独立的名字
        logger.set_file_logger(f'research_drop_verify_{index}_{total}')
    if args.limit:
        files = files[:args.limit]
    logger.info(f'[科研检测] 共 {len(files)} 张'
                + (f'（分片 {index}/{total}）' if args.shard else ''))

    from module.statistics.research_drop import get_parser

    parser_ = get_parser()
    grid = parser_.stats.grid
    logger.info(f'[科研检测] 模板数 {len(grid.templates)}')

    records = []
    started = time.time()
    for i, file in enumerate(files):
        try:
            record = analyze(parser_, file)
        except Exception as e:
            record = {'file': os.path.basename(file), 'error': f'解析崩溃: {e}'}
        records.append(record)
        reset_unknown_templates(grid)
        if i % 50 == 0:
            spent = time.time() - started
            logger.info(f'[科研检测] ... {i}/{len(files)}，{spent:.0f}s，'
                        f'{spent / max(1, i):.2f}s/张')

    result = {
        'folder': args.folder,
        'templates': len(grid.templates),
        'count': len(records),
        'records': records,
    }
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        logger.info(f'[科研检测] 结果写入 {args.out}')
    logger.info(f'[科研检测] 完成，{len(records)} 张，'
                f'耗时 {time.time() - started:.0f}s')


if __name__ == '__main__':
    main()
