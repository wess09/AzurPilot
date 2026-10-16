"""船坞心智单元计算：基础稀有度计费、最高等级合并与人工核对。"""
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from collections import defaultdict

RARITIES = ('UR', 'SSR', 'SR', 'R', 'N')
RARITY_NAMES = dict(zip(RARITIES, ('海上传奇', '超稀有', '精锐', '稀有', '普通')))
MIND_COSTS = {
    'N': (60, 120, 180, 300), 'R': (80, 160, 240, 400),
    'SR': (120, 240, 360, 600), 'SSR': (200, 400, 600, 1000), 'UR': (300, 600, 900, 1500),
}
RESULT_PATH = 'MindCalculatorScan.MindCalculator.Result'
SHIP_DATA_FILE = Path(__file__).parents[2] / 'assets/ship/ship_data.json'
SHIP_FIELDS = ('name', 'level', 'rarity', 'base_rarity', 'excluded', 'review', 'source', 'group_type', 'candidates')


@lru_cache(maxsize=1)
def catalog():
    """从共享舰船资料构建国服目录，改造按基础舰船稀有度计费。"""
    data = json.loads(SHIP_DATA_FILE.read_text(encoding='utf-8'))
    entries = {}
    for ship_id, row in data.items():
        if row['group_type'] is None or row['star_max'] is None or row['rarity_name'] not in RARITIES:
            continue
        # 剧情复制舰可能沿用模板群组，不能覆盖可获取舰船的身份与稀有度。
        if int(ship_id) // 10 != row['group_type'] and not (row['is_retrofit'] and int(ship_id) < 900000):
            continue
        name = row['name']['cn'].strip()
        name = re.sub(r'[.・]META$', '·META', name)
        base = data.get(str(row['retrofit_base_id']), row) if row['is_retrofit'] else row
        rarity = base['rarity_name']
        if rarity not in RARITIES:
            continue
        group = ('联动' if row['nationality'] >= 100 else '布里' if row['nationality'] == 98 else 'META' if row['nationality'] == 97
                 else '幼体' if row.get('is_child') else '方案' if row['group_type'] // 100 % 100 == 99 else '')
        info = dict(name=name, rarity=rarity, base_rarity=rarity,
                    base_name=base['name']['cn'].strip() if row['is_retrofit'] else name,
                    group=group, type=row['type_name'], group_type=row['group_type'],
                    nationality=row['nationality'], nation=base.get('nation_name', str(base['nationality'])),
                    scan_types=[row.get('type')], variant='child' if row.get('is_child') else
                    'mu' if '兵装' in name else '', retrofit_names=[])
        if row['is_retrofit']:
            info.update(group='改造', rarity=RARITIES[max(0, RARITIES.index(rarity) - 1)])
        entries[row['group_type'], name] = info
    for row in data.values():
        base = entries.get((row['group_type'], row['name']['cn'].strip()))
        if not base or row['is_retrofit']:
            continue
        for name in row.get('retrofit_names', []):
            # 游戏 Ship.getRarity() 在改造后升一档；费用仍取基础稀有度。
            entries[row['group_type'], name] = dict(base, name=name, group='改造',
                rarity=RARITIES[max(0, RARITIES.index(base['base_rarity']) - 1)])
    names = defaultdict(list)
    scan_types = defaultdict(set)
    retrofits = defaultdict(list)
    for info in entries.values():
        scan_types[info['group_type']].update(info['scan_types'])
        if info['group'] == '改造':
            retrofits[info['group_type']].append(info['name'])
    for info in entries.values():
        info['scan_types'] = sorted(value for value in scan_types[info['group_type']] if value is not None)
        info['retrofit_names'] = retrofits[info['group_type']]
        names[normalize_name(info['name'])].append(info)
    # 唯一名字保留旧查询键；重名的每个群组单独保存，任何查询都不能取默认项。
    ships = {info['name'] if len({row['group_type'] for row in names[normalize_name(info['name'])]}) == 1 else
             f'{info["group_type"]}:{info["name"]}': info for info in entries.values()}
    aliases = {}
    for candidates in names.values():
        if len({row['group_type'] for row in candidates}) > 1:
            use_type = len({row['type'] for row in candidates}) == len({row['group_type'] for row in candidates})
            suffixes = [row['type'] if use_type else row['nation'] for row in candidates]
            for row, suffix in zip(candidates, suffixes):
                if suffixes.count(suffix) > 1:
                    suffix += f' {row["group_type"]}'
                aliases[normalize_name(f'{row["name"]}（{suffix}）')] = [row]
    return dict(source='assets/ship/ship_data.json', updated_at='', ships=ships, names=dict(names), legacy_names=aliases)


def normalize_name(name):
    """规范化舰船名称以便匹配资料与合并重复项。"""
    return re.sub(r'[\s.·・．。]', '', unicodedata.normalize('NFKC', name)).casefold()


def highest_ships(ships):
    """同基础身份取最高等级；同级优先改造舰，II 型与 META 保留独立身份。"""
    output = {}
    for index, ship in enumerate(ships):
        if not 1 <= ship['level'] <= 125 and not (ship.get('review') and ship['level'] == 0):
            continue
        info = find_ship(ship['name'], ship.get('group_type'))
        key = base_key(info) if info else normalize_name(ship['name'])
        # 未确认的卡位不能按猜测身份合并，也不能覆盖已确认的最高等级。
        if (ship.get('review') or ship['name'].startswith('未识别舰船')
                or not info and (ship.get('group_type') is not None or find_ships(ship['name']))):
            key = f'unknown:{index}'
        if key not in output or preference(output[key]) < preference(ship):
            output[key] = ship
    return list(output.values())


def find_ships(name):
    """保留名字对应的全部身份；只规范标点，不消除特殊版本后缀。"""
    key = normalize_name(name)
    candidates = catalog()['names'].get(key, []) or catalog()['legacy_names'].get(key, [])
    exact = [ship for ship in candidates if ship['name'] == name]
    if exact:
        candidates = exact
    # 只补全画面明确显示的截断名；歧义名称留给人工核对。
    if not candidates and re.search(r'(?:\.{2,}|…+|⋯+)$', name):
        prefix = normalize_name(re.sub(r'(?:\.{2,}|…+|⋯+)$', '', name))
        if len(prefix) >= 2:
            candidates = [ship for ship in catalog()['ships'].values() if normalize_name(ship['name']).startswith(prefix)]
    return list({(ship['group_type'], ship['group'] == '改造'): ship for ship in candidates}.values())


def find_ship(name, group_type=None):
    """仅返回唯一且与群组一致的身份；歧义或矛盾均不猜测。"""
    candidates = find_ships(name)
    if group_type is not None:
        candidates = [ship for ship in candidates if type(group_type) is int and ship['group_type'] == group_type]
    return candidates[0] if len(candidates) == 1 else None


def editable_ship(ship):
    """持久字段白名单同时用于扫描、导入与导出，诊断字段不混入 API 入参。"""
    return {key: value for key, value in ship.items() if key in SHIP_FIELDS}


def preserve_exclusions(ships, previous):
    """重复扫描保留已确认身份的人工排除，不把歧义旧记录猜成某个群组。"""
    excluded = {base_key(info) for ship in previous if ship.get('excluded')
                and (info := find_ship(ship['name'], ship.get('group_type')))}
    pending = [enrich(ship) for ship in previous if ship.get('excluded')
               and find_ship(ship['name'], ship.get('group_type')) is None]
    uncertain = {info['group_type'] for ship in pending for info in find_ships(ship['name'])}
    output = []
    for ship in ships:
        info = find_ship(ship['name'], ship.get('group_type'))
        if info and base_key(info) in excluded:
            ship = dict(ship, excluded=True)
        elif info and info['group_type'] in uncertain:
            # 旧排除没有群组时，不知道用户排除的是哪艘；保留旧记录，
            # 新确认的候选身份等待明确计入，不能偷偷恢复收费。
            ship = dict(ship, review=True, source=f'旧人工排除身份未明确，请核对是否计入；{ship.get("source", "")}'[:200])
        output.append(ship)
    return [*output, *pending]


def revision(ships):
    """计算舰船清单的稳定版本摘要。"""
    return hashlib.sha256(json.dumps(ships, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def enrich(ship):
    """资料补全默认稀有度，保留用户明确指定的计费基础稀有度。"""
    item = dict(ship)
    info = find_ship(item['name'], item.get('group_type'))
    if info:
        item['name'] = info['name']
        item['rarity'] = info['rarity']
        item['base_rarity'] = item.get('base_rarity') or info['base_rarity']
        item['group'] = info['group']
        item['base_name'] = info['base_name']
        item['group_type'] = info['group_type']
        item['candidates'] = []
    else:
        item['group'] = ''
        item['base_name'] = re.sub(r'[.·・]?改$', '', item['name']).strip()
        if not item.get('base_rarity') and item['base_name'] == item['name']:
            item['base_rarity'] = item.get('rarity', '')
        candidates = find_ships(item['name'])
        if item.get('group_type') is not None or candidates:
            item['review'] = True
            item['group_type'] = None
            item['candidates'] = sorted({ship['group_type'] for ship in candidates})
            # 已丢失的历史身份不可恢复，人工排除和原始读数仍原样保留。
    item.setdefault('rarity', '')
    item.setdefault('base_rarity', '')
    item.setdefault('excluded', False)
    item.setdefault('review', False)
    item.setdefault('source', '')
    item.setdefault('group_type', None)
    item.setdefault('candidates', [])
    if item.get('level') == 0:
        item['review'] = True
    return item


def base_key(ship):
    """确定用于同名舰船合并的基础身份键。"""
    # META 身份不能与普通舰或改造舰合并。
    if ship.get('group_type') is not None:
        return f'group:{ship["group_type"]}'
    name = ship['name'] if ship['group'] == 'META' or 'meta' in ship['name'].casefold() else ship['base_name']
    return normalize_name(name)


def preference(ship):
    """最高等级优先，只有等级相同才优先保留已确认的改造身份。"""
    info = find_ship(ship['name'], ship.get('group_type'))
    return ship['level'], bool(info and info['group'] == '改造')


def calculate(ships):
    """等级只能推断觉醒阶段：116 级起已走完四阶，目标限定为 120 级。"""
    rows = [enrich(ship) for ship in ships]
    highest = {}
    for index, ship in enumerate(rows):
        name = ship['name']
        ship['automatic_excluded'] = ('兵装' in name or 'μ' in name.casefold()
                                      or ship['group'] in ('幼体', '联动', '布里'))
        if ship['excluded']:
            ship['status'] = 'excluded'
        elif ship['review'] or not 1 <= ship['level'] <= 125 or ship['base_rarity'] not in RARITIES:
            ship['status'] = 'review'
        elif ship['automatic_excluded']:
            ship['status'] = 'excluded'
        else:
            ship['status'] = 'merged'
            key = base_key(ship)
            previous = highest.get(key)
            if previous is None or preference(rows[previous]) < preference(ship):
                highest[key] = index
        ship['mind'] = ship['gold'] = 0
    summary = {rarity: dict(rarity=rarity, stages=[0] * 6, stage_mind=[0] * 4,
                           count=0, mind=0, gold=0) for rarity in RARITIES}
    for index in highest.values():
        ship = rows[index]
        ship['status'] = 'included'
        level, rarity = ship['level'], ship['base_rarity']
        stage = 0 if level <= 100 else 1 if level <= 105 else 2 if level <= 110 else 3 if level <= 115 else 4
        bucket = summary[rarity]
        bucket['stages'][stage if level < 120 else 5] += 1
        ship['mind'] = sum(MIND_COSTS[rarity][stage:])
        ship['gold'] = ship['mind'] * 10
        bucket['mind'] += ship['mind']
        bucket['gold'] += ship['gold']
        bucket['count'] += 1
        for remaining in range(stage, 4):
            bucket['stage_mind'][remaining] += MIND_COSTS[rarity][remaining]
    return dict(ships=rows, summary=list(summary.values()),
                mind=sum(row['mind'] for row in rows), gold=sum(row['gold'] for row in rows),
                included=len(highest), merged=sum(row['status'] == 'merged' for row in rows),
                excluded=sum(row['status'] == 'excluded' for row in rows),
                review=sum(row['status'] == 'review' for row in rows))


def recognize(image, source='', *, name_ocr=None, level_ocr=None, row_origins=None):
    """读取完整卡片；可靠结果直接计费，身份不明的条目保留核对提示。"""
    import numpy as np
    from module.retire.assets import DOCK_CHECK
    from module.runtime.mind_recognition import normalize_screenshot, recognize_cards
    from module.runtime.scan_metrics import CachedOcr, ScanMetrics
    from module.ocr.al_ocr import AlOcr, OcrSettings
    image = normalize_screenshot(image)
    pixels = np.array(image)
    left, top, right, bottom = DOCK_CHECK.area
    # Button.match 的反向模板参数对纯色输入可能返回 1，先排除没有文字的页头。
    if pixels[top:bottom, left:right].std() < 10 or not DOCK_CHECK.match(pixels, offset=(0, 0)):
        raise ValueError('截图未显示完整船坞界面，请上传包含顶部“船坞”标识及舰船卡片的游戏截图')
    settings = OcrSettings('onnx', 'cpu', False, 'standard')
    metrics = ScanMetrics()
    name_ocr = CachedOcr(name_ocr or AlOcr(name='ppocr_v6', settings=settings, save_debug_images=False), metrics, 'name_ocr')
    level_ocr = CachedOcr(level_ocr or AlOcr(name='azur_lane', settings=settings, save_debug_images=False), metrics, 'level_ocr')
    cards = recognize_cards(image, source, name_ocr=name_ocr, level_ocr=level_ocr, row_origins=row_origins, metrics=metrics)
    for card in cards:
        if not card.level_reliable:
            location = f'第 {sorted({item.y for item in cards}).index(card.y) + 1} 行第 {card.col + 1} 列'
            card.ship.update(level=0, review=True,
                             source=f'{card.ship["source"]}；{location}等级未确认，待人工核对'[:200])
    return [editable_ship(ship) for ship in highest_ships([card.ship for card in cards])]


def detect_rows(image, ocr):
    """兼容等级锚点检测入口。"""
    from module.runtime.mind_recognition import detect_rows as locate
    return locate(image, ocr)
