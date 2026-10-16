"""科技扫描的稳定群组身份；保留同名舰和零科技舰，不使用心智计费目录。"""
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from module.runtime.fleet_tech import catalog
from module.runtime.mind_name import _similarity


def name_key(text):
    """仅规范标点及明确的兵装后缀字形，不删除小型、II 或 META 身份。"""
    text = unicodedata.normalize('NFKC', str(text)).casefold()
    text = re.sub(r'u(?=兵装)', 'μ', text)
    return ''.join(char for char in text if char.isalnum())


@lru_cache(maxsize=1)
def _surface_icon():
    return np.array(Image.open(Path(__file__).parents[2] / 'assets/ship/dock_battleship_icon.png').convert('L'))


@lru_cache(maxsize=1)
def _surface_icon_phases():
    # 相同字形的原生采样相位分别核实，不能靠降低阈值扩大舰种证据。
    return (_surface_icon(), np.array(Image.open(
        Path(__file__).parents[2] / 'assets/ship/dock_battleship_icon_phase.png').convert('L')))


def surface_icon(pixels, x, y):
    """大型炮舰字形（战列/战巡/超巡）；容忍原生像素相位，必须正向命中。"""
    white = (pixels[y:y + 30, x:x + 40].min(axis=2) > 205).astype(np.uint8) * 255
    return any(cv2.minMaxLoc(cv2.matchTemplate(white, template, cv2.TM_CCOEFF_NORMED))[1] >= .75
               for template in _surface_icon_phases())


def aviation_icon(pixels, x, y):
    """科技任务使用自己的阈值，保留心智识别原有参数。"""
    from module.runtime.mind_recognition import _aircraft_icon
    white = (pixels[y:y + 30, x:x + 40].min(axis=2) > 205).astype(np.uint8) * 255
    return cv2.minMaxLoc(cv2.matchTemplate(white, _aircraft_icon(), cv2.TM_CCOEFF_NORMED))[1] >= .8


class FleetTechIdentity:
    """按群组建立多值名称索引，图标只消除有正向依据的舰种歧义。"""
    def __init__(self, ships=None):
        self.ships = {row['group_type']: row for row in (catalog()['ships'] if ships is None else ships)}
        self.names = defaultdict(list)
        for row in self.ships.values():
            self.names[name_key(row['name'])].append((row['group_type'], False))
            for name in row['retrofit_names']:
                self.names[name_key(name)].append((row['group_type'], True))
        self.families = defaultdict(set)
        self.ii_families = {key[:-2] for key in self.names if key.endswith('ii') and key[:-2] in self.names}
        for key, identities in self.names.items():
            stem = re.sub(r'μ兵装$|meta$|(?<!i)ii$', '', key)
            if any(self.ships[gid]['variant'] == 'child' for gid, _ in identities):
                stem = stem.removeprefix('小')
            self.families[stem].update(gid for gid, _ in identities)

    def needs_retry(self, info):
        key = name_key(info['name'])
        stem = re.sub(r'μ兵装$|meta$|(?<!i)ii$', '', key)
        if info.get('variant') == 'child':
            stem = stem.removeprefix('小')
        return len(self.families.get(stem, ())) > 1 or bool(info.get('variant'))

    def _info(self, gid, retrofit=False):
        row = self.ships[gid]
        base_rarity = {'PR': 'SSR', 'DR': 'UR'}.get(row['rarity'], row['rarity'])
        return dict(row, base_name=row['name'], base_rarity=base_rarity,
                    group='改造' if retrofit else 'META' if row['nationality'] == 97 else '',
                    name=row['retrofit_names'][0] if retrofit else row['name'])

    def candidates(self, texts, *, ellipsis=False):
        reads = [name_key(text) for text in texts]
        exact = {gid for read in reads for gid, _ in self.names.get(read, [])}
        if exact:
            return sorted(exact)
        ranked = [(max((_similarity(read, key, ellipsis) for read in reads), default=0), gid)
                  for key, ids in self.names.items() for gid, _ in ids]
        ranked.sort(reverse=True)
        return sorted({gid for score, gid in ranked if score >= .55 and ranked[0][0] - score <= .05})

    def match(self, texts, frame_rarity='', *, ellipsis=False, meta_frame=False,
              aviation=False, surface=False, fuzzy=False):
        reads = [name_key(text) for text in texts]
        require_meta = meta_frame or any(re.search(r'met[a-z0-9]?$', read) for read in reads)
        require_retrofit = any(read.endswith('改') for read in reads)
        require_mu = any('μ' in read or '兵装' in read for read in reads)
        ordinary_small = any(any(self.ships[gid]['variant'] != 'child' for gid, _ in self.names.get(read, []))
                             for read in reads if read.startswith('小'))
        require_child = any(read.startswith('小') for read in reads) and not ordinary_small
        require_ii = sum(read.endswith('ii') and read[:-2] in self.ii_families for read in reads) >= 2
        if (not require_ii and any(read.endswith('i') and not self.names.get(read)
                                  and read.rstrip('i') in self.ii_families
                                  and not re.search(r'(?<!i)ii$', read) for read in reads)):
            return None, '罗马后缀未确认，待核对'
        exact = Counter((gid, retrofit) for read in reads for gid, retrofit in self.names.get(read, []))

        def eligible(gid, retrofit):
            row = self.ships[gid]
            if require_meta != (row['nationality'] == 97) or require_retrofit and not retrofit:
                return False
            if require_mu and row['variant'] != 'mu' or require_child and row['variant'] != 'child':
                return False
            if require_ii and not name_key(row['name']).endswith('ii'):
                return False
            if aviation and not surface and not set(row['scan_types']).intersection((6, 7, 10, 17)):
                return False
            if surface and not aviation and not set(row['scan_types']).intersection((4, 5, 13, 18)):
                return False
            return True

        chosen = {(gid, retrofit) for gid, retrofit in exact if eligible(gid, retrofit)}
        if len({name_key(self.ships[gid]['name']) for gid, _ in chosen}) > 1 and frame_rarity:
            compatible = {item for item in chosen if self._info(*item)['base_rarity'] == frame_rarity}
            if len({gid for gid, _ in compatible}) == 1 and sum(exact[item] for item in compatible) >= 2:
                chosen = compatible
        # 同名同舰种不能以稀有度、排序、全收藏假设或最高等级猜测。
        gids = {gid for gid, _ in chosen}
        if len(gids) > 1 and len({self.ships[gid]['type'] for gid in gids}) == 1:
            return None, '同名同舰种需要人工确认'
        if len(gids) > 1:
            return None, '同名舰缺少能够唯一确认舰种的图标证据'
        if len(gids) == 1:
            gid = next(iter(gids))
            retrofit = any(item[0] == gid and item[1] for item in chosen)
            info = self._info(gid, retrofit)
            if len({item[0] for item in exact}) > 1 and sum(exact[item] for item in chosen) < 2:
                return None, '多轮身份后缀不一致，待核对'
            if ellipsis and self.needs_retry(info) and not (require_mu or require_child or require_ii):
                return None, '截断名称存在特殊版本候选，待核对'
            return info, f'群组 {gid}，船名与舰种证据确认'
        if not fuzzy:
            return None, '舰船群组未能唯一确认'
        ranked = []
        for key, identities in self.names.items():
            if not ellipsis and sum(sum('\u4e00' <= char <= '\u9fff' for char in read)
                                    > sum('\u4e00' <= char <= '\u9fff' for char in key) for read in reads) >= 2:
                # 汉字是名称内容，不能把反复出现的额外汉字当边框噪声丢弃。
                continue
            scores = sorted((_similarity(read, key, ellipsis or str(text).endswith(('..', '…', '⋯')))
                             for text, read in zip(texts, reads)), reverse=True)
            if len(scores) < 2 or scores[1] < .55:
                continue
            for gid, retrofit in identities:
                if eligible(gid, retrofit):
                    ranked.append((scores[1], gid, retrofit))
        ranked.sort(reverse=True)
        if not ranked:
            return None, '舰名文字不足或与群组目录不符，待核对'
        best = ranked[0][0]
        close = [item for item in ranked if best - item[0] <= .05]
        same_names = defaultdict(set)
        for _, gid, _ in close:
            same_names[name_key(self.ships[gid]['name'])].add(gid)
        if any(len(gids) > 1 for gids in same_names.values()):
            return None, '同名舰缺少唯一身份依据，需要人工确认'
        compatible = [item for item in close if self._info(item[1], item[2])['base_rarity'] == frame_rarity]
        if compatible:
            close = compatible
        if len({item[1] for item in close}) != 1:
            return None, '舰船群组存在多个候选，需要人工确认'
        _, gid, retrofit = close[0]
        info = self._info(gid, retrofit)
        if name_key(info['name'])[:-2] in self.ii_families and not require_ii:
            return None, '罗马后缀未确认，待核对'
        return info, f'群组 {gid}，多轮名称与舰种证据确认'
