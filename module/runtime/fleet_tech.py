"""舰队科技目录、累计扫描证据与人工校正，均不操作游戏设备。"""
import copy
import hashlib
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from module.runtime.mind_calculator import normalize_name

RECORD_PATH = 'FleetTechScan.FleetTech.Record'
LEGACY_RECORD_PATH = 'MindCalculatorScan.MindCalculator.FleetTechRecord'
ROOT = Path(__file__).parents[2]


def read_record(data):
    """新记录优先；首次写入前只读兼容旧路径，不原地修改迁移备份。"""
    from module.config.deep import deep_get
    value = deep_get(data, RECORD_PATH, {}) or deep_get(data, LEGACY_RECORD_PATH, {})
    if not isinstance(value, dict):
        raise ValueError('舰船科技记录格式无效，已保留原始数据')
    return copy.deepcopy(value)


@lru_cache(maxsize=1)
def catalog():
    """把按群组生成的科技索引与现有共享舰船资料关联。"""
    index = json.loads((ROOT / 'assets/ship/fleet_tech.json').read_text(encoding='utf-8'))
    shared = json.loads((ROOT / 'assets/ship/ship_data.json').read_text(encoding='utf-8'))
    rows, aliases, points = [], defaultdict(set), defaultdict(int)
    for entry in index['ships']:
        gid = entry['group_type']
        base = shared[str(gid * 10 + 1)]
        row = dict(entry, name=base['name']['cn'], names=base['name'], nationality=base['nationality'],
                   rarity=('DR' if base['rarity_name'] in ('UR', 'DR') else 'PR') if entry['blueprint'] else base['rarity_name'],
                   type=base['type'], variant='child' if base.get('is_child') else
                   'mu' if 'μ兵装' in base['name']['cn'] else '', retrofit_names=[], scan_types=[base['type']])
        rows.append(row)
        if entry['technology']:
            points[str(row['nationality'])] += sum(entry['technology'][k] for k in ('pt_get', 'pt_upgrage', 'pt_level'))
        aliases[normalize_name(row['name'])].add(gid)
    # 改造名按真实群组归并，不能靠去掉“改”或相似名字猜测身份。
    known = {row['group_type'] for row in rows}
    by_group = {row['group_type']: row for row in rows}
    for ship_id, row in shared.items():
        gid = row['group_type']
        if gid not in known or int(ship_id) // 10 != gid:
            continue
        if row['type'] not in by_group[gid]['scan_types']:
            by_group[gid]['scan_types'].append(row['type'])
        for name in row.get('retrofit_names', []):
            aliases[normalize_name(name)].add(gid)
            by_group[gid]['retrofit_names'].append(name)
    names = {(row['name'], row['nationality'], row['type']) for row in rows}
    for row in rows:
        if (not row['variant'] and row['name'].startswith('小')
                and (row['name'][1:], row['nationality'], row['type']) in names):
            row['variant'] = 'child'
    for ship in shared.values():
        gid = ship['group_type']
        if gid not in by_group or not ship['is_retrofit']:
            continue
        row = by_group[gid]
        if (normalize_name(ship['name']['cn']) in {normalize_name(name) for name in row['retrofit_names']}
                and ship['type'] not in row['scan_types']):
            row['scan_types'].append(ship['type'])
    return dict(version=index['version'], updated_at=index['updated_at'], source_commit=index['source_commit'],
                ships=rows, nations=index['nations'], nation_points=dict(points), max_points=sum(points.values()),
                aliases={name: next(iter(ids)) for name, ids in aliases.items() if len(ids) == 1})


def public_catalog():
    """名称索引仅供服务端确认身份，不重复传给浏览器。"""
    return {key: value for key, value in catalog().items() if key != 'aliases'}


def revision(record):
    """空记录也有稳定版本，供人工编辑进行并发保护。"""
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def merge_mind(record, ships):
    """累计已确认的正向证据；删除、排除计费及范围外缺失不会撤销历史。"""
    output = copy.deepcopy(record)
    observed = output.setdefault('observed', {})
    aliases = catalog()['aliases']
    from module.runtime.mind_calculator import find_ship
    known = {row['group_type'] for row in catalog()['ships']}
    for ship in ships:
        level = ship.get('level')
        if ship.get('review') or type(level) is not int or not 1 <= level <= 125:
            continue
        gid = ship.get('group_type')
        if gid is not None:
            if type(gid) is not int or gid not in known or find_ship(ship.get('name', ''), gid) is None:
                continue
        else:
            gid = aliases.get(normalize_name(ship.get('name', '')))
        if gid is None:
            continue
        key = str(gid)
        observed[key] = max(observed.get(key, 0), level)
    return output


def progress(record, group_type):
    """兼容旧记录，分别推导获得、等级和满星；无证据默认未获得。"""
    gid = str(group_type)
    manual = record.get('manual', {}).get(gid, {})
    observed = record.get('observed', {}).get(gid)
    automatic_level = record.get('current', {}).get(gid, observed)
    level = manual.get('level', automatic_level)
    acquire_level = manual.get('level') or automatic_level or 100
    acquire_lv120 = manual.get('lv120', acquire_level >= 120) if manual.get('level') else acquire_level >= 120
    if acquire_lv120 and acquire_level < 120:
        acquire_level = 120
    elif not acquire_lv120 and acquire_level >= 120:
        acquire_level = manual.get('level_toggle', {}).get('low', 100)
    automatic_owned = bool(automatic_level) and gid not in record.get('absent', [])
    owned = manual.get('owned', automatic_owned) is True
    full_star = manual.get('full_star')
    lv120 = owned and manual.get('lv120', bool(level and level >= 120)) is True
    if not owned:
        level, full_star, lv120 = None, False, False
    elif lv120 and (not level or level < 120):
        # 旧版允许单独录入 Lv.120；保留原始记录，同时消除显示矛盾。
        level = 120
    elif not lv120 and level and level >= 120:
        level = manual.get('level_toggle', {}).get('low', 100)
    # 仅按当前有效等级推导默认值；人工明确的满星/未满星仍优先，不回写历史。
    if owned and full_star is None and level and level > 100:
        full_star = True
    state = dict(group_type=group_type, owned=owned, level=level, full_star=full_star, lv120=lv120,
                 status='complete' if lv120 else 'unfinished' if owned else 'unowned',
                 manual=bool(manual), observed_level=observed, points=0)
    state.update(acquire_level=acquire_level, acquire_lv120=bool(acquire_lv120))
    pair = completion_levels(record, group_type, state)
    state['completion_target'] = pair['low'] if lv120 else pair['high']
    return state


def completion_levels(record, group_type, state):
    """旧版单独设置满级时也保留可用的原等级，不丢失人工历史。"""
    gid = str(group_type)
    manual = record.get('manual', {}).get(gid, {})
    pair = manual.get('level_toggle', {})
    level = state['level'] or 100
    if (type(pair.get('low')) is int and 1 <= pair['low'] < 120
            and type(pair.get('high')) is int and 120 <= pair['high'] <= 125
            and (not state['owned'] or level in pair.values())):
        return pair
    previous = manual.get('level', record.get('current', {}).get(gid, record.get('observed', {}).get(gid)))
    low = previous if type(previous) is int and 1 <= previous < 120 else 100
    return dict(low=low if state['lv120'] else level, high=level if state['lv120'] else 120)


def toggle(record, group_type, field, target):
    """事务内处理单击；等级切换的两个端点随人工记录持久化。"""
    state = progress(record, group_type)
    state_key = 'lv120' if field == 'complete' else 'full_star' if field == 'star' else 'owned'
    if bool(state[state_key]) == target:
        return
    entry = record.setdefault('manual', {}).setdefault(str(group_type), {})
    if field == 'owned':
        entry['owned'] = target
        if entry['owned'] and not entry.get('level'):
            entry['level'] = record.get('current', {}).get(str(group_type),
                                record.get('observed', {}).get(str(group_type), 100))
            entry['lv120'] = entry['level'] >= 120
    elif field == 'complete':
        pair = completion_levels(record, group_type, state)
        level = pair['high'] if target else pair['low']
        entry.update(owned=True, level=level, lv120=target, level_toggle=pair)
    elif field == 'star':
        entry['full_star'] = target
        if entry['full_star']:
            entry['owned'] = True
    else:
        raise ValueError('未知的科技记录切换操作')


def merge_scan(record, ships, *, min_level, max_level, reached_bottom, filters_clear,
               physical_count, expected_count, updated_at):
    """科技扫描按群组合并；仅完整、无过滤、无疑点且数量吻合时确认缺失。"""
    output = copy.deepcopy(record)
    known = {row['group_type'] for row in catalog()['ships']}
    seen, reviews = {}, []
    for ship in ships:
        gid, level = ship.get('group_type'), ship.get('level')
        if type(level) is int and 1 <= level <= 125 and not min_level <= level <= max_level:
            continue
        if (ship.get('review') or type(gid) is not int or gid not in known
                or type(level) is not int or not 1 <= level <= 125):
            reviews.append(copy.deepcopy(ship))
            continue
        if min_level <= level <= max_level:
            seen[str(gid)] = max(seen.get(str(gid), 0), level)
    complete = (min_level == 1 and max_level == 125 and reached_bottom and filters_clear
                and type(expected_count) is int and physical_count == expected_count and not reviews)
    observed = output.setdefault('observed', {})
    current = output.setdefault('current', {})
    for gid, level in seen.items():
        previous = current.get(gid, observed.get(gid, 0))
        # 局部范围可能只读到低级副本，不能据此降低范围外的既有最高等级。
        current[gid] = level if complete or gid in output.get('absent', []) else max(previous, level)
        observed[gid] = max(observed.get(gid, 0), level)
    absent = {str(gid) for gid in known} - seen.keys() if complete else set(output.get('absent', [])) - seen.keys()
    output['absent'] = sorted(absent, key=int)
    evidence = sorted(((int(gid), level) for gid, level in seen.items()))
    output['last_scan'] = dict(min_level=min_level, max_level=max_level, complete=bool(complete),
                               reached_bottom=bool(reached_bottom), filters_clear=bool(filters_clear),
                               physical_count=physical_count, expected_count=expected_count,
                               matched_count=len(seen), review_count=len(reviews), updated_at=updated_at,
                               fingerprint=revision(evidence), ships=evidence)
    output['review_ships'] = reviews
    output['version'] = 2
    return output


def ship_type(value):
    """导驱与风帆各形态共用界面分类，但每条加成仅累计一次。"""
    return 1 if value in (20, 21) else 22 if value in (22, 23, 24) else value


def report(record):
    """按确认状态计算科技点、舰船加成及已录入的阵营科技加成。"""
    rows, bonuses = [], defaultdict(lambda: defaultdict(int))
    confirmed_points = completed = pending_star = 0

    def add(types, attr, value):
        for target in {ship_type(t) for t in types}:
            bonuses[str(target)][str(attr)] += value

    for info in catalog()['ships']:
        row = progress(record, info['group_type'])
        owned, full_star, lv120 = row['owned'], row['full_star'], row['lv120']
        tech = info['technology']
        if tech:
            if owned:
                row['points'] += tech['pt_get']
                add(tech['add_get_shiptype'], tech['add_get_attr'], tech['add_get_value'])
                pending_star += full_star is None
            if full_star:
                row['points'] += tech['pt_upgrage']
            if lv120:
                row['points'] += tech['pt_level']
                add(tech['add_level_shiptype'], tech['add_level_attr'], tech['add_level_value'])
                completed += 1
        confirmed_points += row['points']
        rows.append(row)
    levels = record.get('nations', {})
    for key, value in levels.items():
        if value and key in catalog()['nations']:
            for types, attr, amount in catalog()['nations'][key][value - 1]:
                add(types, attr, amount)
    return dict(revision=revision(record), ships=rows, nation_levels=levels,
                bonuses={t: dict(attrs) for t, attrs in bonuses.items()}, confirmed_points=confirmed_points,
                completed=completed, pending_star=pending_star, last_scan=record.get('last_scan'),
                review_ships=record.get('review_ships', []))
