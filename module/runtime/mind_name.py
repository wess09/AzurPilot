"""心智扫描在 OCR 复读后对照 Lua 生成的国服名单补全身份。"""
from difflib import SequenceMatcher
from functools import lru_cache

from module.runtime.mind_calculator import catalog, find_ship, normalize_name


MIN_NAME_SIMILARITY = .55


def _key(text):
    return ''.join(char for char in normalize_name(text) if char.isalnum())


@lru_cache(maxsize=1)
def _names(names):
    # 缓存键跟随共享目录，测试或资料重载后不会继续使用旧名单。
    return tuple((name, _key(name)) for name in names)


def _similarity(read, name, truncated):
    if not read:
        return 0.
    # 名称条容不下长名时，省略号可能也被 OCR 漏读。四字以上的
    # 连续前缀或原图明确的截断允许补全，身份后缀仍由候选与图像区分。
    score = SequenceMatcher(None, read, name, autojunk=False).ratio()
    if len(name) > len(read) and (truncated or len(read) >= 4):
        # 截断处之前也可能有形近字；只比较可见长度，不能用缺失尾部
        # 把有方向的读数误判为低匹配度，也不凭该分数消除身份歧义。
        score = max(score, SequenceMatcher(None, read, name[:len(read)], autojunk=False).ratio())
    return score


def match_lua_name(texts, frame_rarity='', *, ellipsis=False, meta_frame=False, aviation=False):
    """返回相似度不低的名单身份；低分、冲突或同分无证据时保留核对。

    卡框只用于区分相近的完整名单候选，计费稀有度始终取 Lua 资料。
    多轮读数至少两次支持同一候选，避免一次偶然命中决定身份；
    裁边补读可能丢字，不让新增的低质量读数盖过已有双读证据。
    """
    reads = [_key(text) for text in texts]
    if not reads or max(map(len, reads)) < 2:
        return None, '船名有效文字不足，待核对'
    ships = catalog()['ships']
    names = _names(tuple(dict.fromkeys(info['name'] for info in ships.values())))
    exact = {_key(info['name']) for text in texts if (info := find_ship(text))}
    exact.update(key for _, key in names if key in reads)
    if len(exact) > 1:
        return None, '多轮船名身份不一致，请核对'
    # 不能把可见的 META、改造或未确认罗马后缀当作噪声删掉。
    require_meta = meta_frame or any('meta' in read for read in reads)
    require_retrofit = any(read.endswith('改') for read in reads)
    if not require_meta:
        for read in reads:
            for suffix in ('m', 'me', 'met'):
                if read.endswith(suffix) and find_ship(read[:-len(suffix)] + '·META'):
                    return None, 'META 后缀未确认，待核对'
    for read in reads:
        if read.endswith('i'):
            base = find_ship(read.rstrip('i'))
            if base and find_ship(base['name'] + 'II'):
                return None, '罗马后缀未确认，待核对'
    ranked = []
    for info in ships.values():
        name, key = info['name'], _key(info['name'])
        if require_meta and info['group'] != 'META' or require_retrofit and info['group'] != '改造':
            continue
        scores = sorted((_similarity(read, key, ellipsis or text.endswith(('..', '…', '⋯')))
                         for text, read in zip(texts, reads)), reverse=True)
        score = scores[min(1, len(scores) - 1)]
        ranked.append((score, info))
    ranked.sort(key=lambda item: (-item[0], item[1]['name']))
    if not ranked or ranked[0][0] < MIN_NAME_SIMILARITY:
        score = ranked[0][0] if ranked else 0
        return None, f'国服 Lua 名单匹配度较低（{score:.0%}），待核对'
    best = ranked[0][0]
    close = [(score, info) for score, info in ranked if best - score <= .05]
    same_names = {}
    for _, info in close:
        same_names.setdefault(_key(info['name']), set()).add(info['group_type'])
    if any(len(ids) > 1 for ids in same_names.values()):
        return None, '同名舰缺少唯一群组证据，待核对'
    matching_rarity = [(score, info) for score, info in close if info['rarity'] == frame_rarity]
    if matching_rarity:
        close = matching_rarity
    if aviation:
        # 航母、航战、潜母图标均含飞机字形，不能据此进一步细分。
        # 改造别名沿用基础舰种；战列改造可能转为航战，不能据基础舰种排除。
        close = [(score, info) for score, info in close
                 if info['type'] in ('正航', '轻航', '航战', '潜母')
                 or info['group'] == '改造' and info['type'] == '战列']
        if not close:
            return None, '国服 Lua 名单候选与航空图标不一致，待核对'
    # 改造的同名别名属于同一身份，不能把它们算作身份冲突。
    identities = {(info['group_type'], info['group'], info['name'].casefold().endswith('ii'))
                  for _, info in close}
    if len(identities) != 1:
        return None, '国服 Lua 名单存在相近身份候选，待核对：' + ' / '.join(info['name'] for _, info in close[:3])
    info = close[0][1]
    if info['name'].casefold().endswith('ii') and sum(read.endswith('ii') for read in reads) < 2:
        return None, '罗马后缀未确认，待核对'
    return info, f'船名经国服 Lua 名单匹配确认：{info["name"]}'
