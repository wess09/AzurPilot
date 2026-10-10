"""船坞卡片定位、多轮 OCR 与滚动截图的位置合并。

参考原计算器 OcrService / AutoScanService 的分层流程，适配 AP 的 1280×720 船坞。
"""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from module.runtime.mind_calculator import RARITIES, find_ship, highest_ships, normalize_name


@dataclass
class Card:
    """位置用于跨屏合并，舰船字段用于持久化与人工核对。"""
    x: int
    y: int
    col: int
    ship: dict
    quality: int = 0
    level_reliable: bool = False
    fleet: int = 0


def normalize_screenshot(image):
    """裁去可确认的黑边，沿用设备截图的 720p 坐标归一化。"""
    from PIL import Image, ImageOps
    from module.device.screenshot import Screenshot
    width, height = image.size
    if width * height > 20_000_000 or min(width, height) < 360:
        raise ValueError(f'截图尺寸 {width}×{height} 不适合识别，请上传清晰的完整模拟器截图')
    image = ImageOps.exif_transpose(image).convert('RGB')
    width, height = image.size
    pixels = np.array(image)
    # 四边同时加黑边时整体仍可能是 16:9，也需要检查有效区域。
    active = pixels.max(axis=2) > 20
    ys = np.flatnonzero(active.mean(axis=1) > .02)
    xs = np.flatnonzero(active.mean(axis=0) > .02)
    if not len(xs) or not len(ys):
        raise ValueError('截图为空或全黑，请等待船坞加载完成')
    cropped_width, cropped_height = int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1)
    paired_borders = ((xs[0] > 0) == (xs[-1] < width - 1)
                      and (ys[0] > 0) == (ys[-1] < height - 1))
    if paired_borders and abs(cropped_width / cropped_height - 16 / 9) <= .015:
        # 仅移除整行/整列几乎全黑的边缘，不能把缺失的游戏界面拉伸补齐。
        image = image.crop((int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1))
        width, height = image.size
    if abs(width / height - 16 / 9) > .015:
        raise ValueError(f'截图有效区域为 {width}×{height}，需要完整的 16:9 船坞画面；请去除窗口边框并保留游戏界面')
    if image.size != (1280, 720):
        image = Image.fromarray(Screenshot.resize_screenshot_to_720p(np.array(image)))
    return image


def grid_rows(pixels):
    """复用船坞扫描器的行间空白判定，并由已有网格间距补齐三行。"""
    from module.retire.dock import CARD_GRIDS
    from module.retire.scanner import DockScanner
    left, top, right, bottom = DockScanner.SCAN_ZONES['dock']
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    gaps = [(start, end) for start, end in _runs(np.std(gray[:, left:right], axis=1) < 20)
            if start >= top and 10 <= end - start <= 30]
    # 多个卡片行之间应有一致的间距；卡面内部的空白不能成为定位证据。
    pitch = int(CARD_GRIDS.delta[1])
    ends = [end for _, end in gaps if end < bottom - 30]
    aligned = [end for end in ends if any(abs(abs(end - other) - pitch) <= 6 for other in ends if end != other)]
    if not aligned:
        return []
    phase = round(float(np.median([end - round((end - aligned[0]) / pitch) * pitch for end in aligned]))) + 4
    while phase - pitch >= top:
        phase -= pitch
    return [y for y in range(phase, bottom, pitch) if top <= y and y + 185 <= 720]


def parse_level(text):
    import re
    text = ''.join(text).strip()
    match = re.fullmatch(r'(?:[Ll1I][VvYy][.\s]*)?([1-9]\d{0,2})', text)
    return int(match[1]) if match and int(match[1]) <= 125 else 0


def level_vote(texts, digit_count=0):
    """只接受位数吻合且至少两次一致的读数，不补猜百位。"""
    counts = Counter(value for text in texts if (value := parse_level(text)))
    compatible = {value: count for value, count in counts.items()
                  if not digit_count or len(str(value)) == digit_count}
    if not digit_count or not compatible:
        return 0, '等级未能通过数字位数核验'
    level = max(compatible, key=lambda value: compatible[value])
    if len(compatible) > 1 or compatible[level] < 2:
        return 0, '等级候选需核对：' + ' / '.join(map(str, sorted(counts)))
    return level, ''


def _clusters(values, gap):
    groups = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [round(float(np.median(group))) for group in groups]


def _runs(mask):
    edges = np.diff(np.pad(mask.astype(np.int8), (1, 1)))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def rarity_masks(pixels):
    """原工具的金、紫、蓝、灰 RGB 条件，使用有符号数防止差值溢出。"""
    red, green, blue = pixels.astype(np.int16).transpose(2, 0, 1)
    return {
        'SSR': (red > 200) & (green > 150) & (red - blue > 55) & (green - blue > 10),
        'SR': (blue > 200) & (blue - green > 60) & (red > 100) & (abs(red - blue) < 120),
        'R': (blue > 140) & (blue - red > 25) & (blue - green > 15),
        'N': (np.minimum(np.minimum(red, green), blue) > 150)
             & (np.maximum(np.maximum(red, green), blue) < 235)
             & (np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue) < 45),
    }


def color_rows(pixels):
    """找卡头的连续稀有度色带，排除卡面、文字条和画面边缘。"""
    from module.retire.dock import CARD_GRIDS
    columns = [round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0])) for col in range(7)]
    mask = np.logical_or.reduce(list(rarity_masks(pixels).values()))
    candidates = []
    for y in range(55, 536):
        spans = [(left, right) for left, right in _runs(mask[y, 80:1230]) if 90 <= right - left <= 150
                 and any(abs(left + 80 - x) <= 8 and abs(right + 80 - x - 138) <= 12 for x in columns)]
        if spans:
            candidates.append(y)
    rows = []
    for start, end in _runs(np.isin(np.arange(720), candidates)):
        if 2 <= end - start <= 10:
            rows.append(int(start))
    return rows


def detect_rows(image, ocr):
    """等级锚点作为色带检测的补充；只返回能容纳完整船名条的行。"""
    headers = []
    for text, box, score in ocr.det(np.array(image)):
        if score >= .7 and parse_level(text) and text.strip().lower().startswith(('lv', '1v', 'iy', 'ly')):
            y = min(point[1] for point in box)
            if 55 <= y <= 535:
                headers.append(round(y))
    return _clusters(headers, 20)


def _name_image(pixels):
    # 名称条的上下边界和婚舰粉色提取必须与舰队扫描保持一致。
    return _scanners()[1].pre_process(pixels)


def _digit_count(pixels):
    # LevelOcr 已按 L 的位置移除 Lv，不能再截去固定 25px 导致漏掉百位。
    # 卡框及立绘在字形底部可能连成横线，去除边缘两像素后再统计数字。
    if pixels.shape[0] <= 4 or not pixels.shape[1]:
        return 0
    mask = (pixels[2:-2] < 120).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    groups = []
    for left, top, width, height, area in sorted(stats[1:count], key=lambda item: item[0]):
        if groups and left < groups[-1][1]:
            group = groups[-1]
            group[1] = max(group[1], left + width)
            group[2] = min(group[2], top)
            group[3] = max(group[3], top + height)
            group[4] += area
        else:
            groups.append([left, left + width, top, top + height, area])
    # 字形的上下两段可能断开，按横坐标归并；细竖线 1 也属于有效数字。
    return sum(bottom - top >= 9 and 1 <= right - left <= 14 and area >= 12
               for left, right, top, bottom, area in groups)


@lru_cache(maxsize=1)
def _scanners():
    from module.retire.scanner import FleetNameScanner, FleetScanner
    from module.retire.ship_name import ShipNameMatcher
    return ShipNameMatcher('cn'), FleetNameScanner().ocr_model, FleetScanner()


@lru_cache(maxsize=1)
def _fleet_label():
    from pathlib import Path
    from PIL import Image
    return np.array(Image.open(Path(__file__).parents[2] / 'assets/ship/dock_fleet_label.png').convert('L'))


def fleet_status(region, reader):
    """复用舰队编号模板；只有“编队”文字证据才能标记未知编队。"""
    binary = reader.pre_process(region)
    fleet = reader._match(binary)
    if fleet:
        return fleet
    score = cv2.minMaxLoc(cv2.matchTemplate(binary[20:42, :, 0], _fleet_label(), cv2.TM_CCOEFF_NORMED))[1]
    return -1 if score >= .75 else 0


def _match_name(texts, frame_rarity):
    """复用舰队管理名单，只有精确命中或唯一截断补全才接受身份。"""
    matcher, _, _ = _scanners()
    candidates = {}
    votes = Counter()
    # 实机名称条核实过的形近字与罗马数字误读；不做编辑距离猜名。
    corrections = {'酒句': '酒匂', '条鱼': '鲦鱼', '绦鱼': '鲦鱼', '四系乃': '四糸乃', '百雪': '白雪',
                   '杓鹊改': '杓鹬.改', '约克城iii': '约克城II', '列克星敦iii': '列克星敦II'}
    for text in texts:
        text = corrections.get(normalize_name(text), text)
        info = find_ship(text)
        name, status = matcher.resolve(text)
        if info:
            candidates[normalize_name(info['name'])] = info
            votes[normalize_name(info['name'])] += 1
        elif status in ('exact', 'prefix'):
            info = find_ship(name) or dict(name=name, rarity=frame_rarity, base_rarity='')
            candidates[normalize_name(name)] = info
            votes[normalize_name(name)] += 1
    # 原彩色复读偶尔漏掉 II；只有另外两次都读到后缀才接受 II 身份。
    if len(candidates) == 2:
        for key in list(candidates):
            if key + 'ii' in candidates and votes[key + 'ii'] >= 2 and votes[key] == 1:
                del candidates[key]
                break
    if len(candidates) != 1:
        return None, '船名未能唯一匹配国服名单'
    info = next(iter(candidates.values()))
    raw = texts[0].strip()
    if 'meta' in raw.casefold() and 'meta' not in info['name'].casefold() or raw.endswith('改') and not info['name'].endswith('改'):
        return None, '多轮船名身份不一致，请核对'
    return info, f'船名经名单校正：{raw} → {info["name"]}' if normalize_name(raw) != normalize_name(info['name']) else ''


def recognize_cards(image, source='', *, name_ocr=None, level_ocr=None, row_origins=None):
    """识别连续三行；自动扫描与上传共用相同网格、名单和等级校验。"""
    from module.ocr.al_ocr import AlOcr, OcrSettings
    from module.retire.dock import CARD_GRIDS
    from module.runtime.mind_level import dock_level_reader
    image = normalize_screenshot(image)
    settings = OcrSettings('onnx', 'cpu', False, 'standard')
    name_ocr = name_ocr or AlOcr(name='ppocr_v6', settings=settings)
    level_ocr = level_ocr or AlOcr(name='azur_lane', settings=settings)
    _, _, fleet_reader = _scanners()
    level_reader = dock_level_reader()
    pixels = np.array(image)
    rows = list(row_origins) if row_origins is not None else grid_rows(pixels)
    if not rows:
        rows = detect_rows(image, name_ocr) or color_rows(pixels)
    rows = _clusters([y for y in rows if 55 <= y and y + 185 <= 720], 20)
    if not rows:
        raise ValueError('未能定位船坞卡片，请上传加载完成、包含完整船名和等级的船坞截图')
    boxes, name_images, frame_rarities, fleets = [], [], [], []
    prepared = []
    for y in rows:
        for col in range(7):
            x = round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))
            raw_level = pixels[y:y + 32, x + 74:x + 138]
            masks = rarity_masks(pixels[y:y + 5, x:x + 138])
            rarity = max(masks, key=lambda key: masks[key].sum())
            frame_rarity = rarity if masks[rarity].mean() >= .3 else ''
            body = pixels[y + 35:y + 150, x:x + 138]
            if not frame_rarity and cv2.cvtColor(body, cv2.COLOR_RGB2GRAY).std() < 20:
                continue
            boxes.append((x, y, col))
            frame_rarities.append(frame_rarity)
            name_images.append(pixels[y + 160:y + 190, x - 10:x + 142])
            prepared.append(level_reader.prepare(raw_level))
            region = pixels[y + 117:y + 162, x:x + 35]
            fleets.append(fleet_status(region, fleet_reader))
    if not boxes:
        raise ValueError('船坞卡片为空或尚未加载')
    names = name_ocr.ocr_for_single_lines([_name_image(region) for region in name_images])
    values = [level_reader.read(glyphs) for glyphs, _, _ in prepared]
    unresolved = [index for index, value in enumerate(values) if not value]
    level_notes = [''] * len(values)
    if unresolved:
        clean_levels = [prepared[index][1] for index in unresolved]
        digit_reads = [level_ocr.ocr_for_single_lines(clean_levels),
                       level_ocr.ocr_for_single_lines([prepared[index][2] for index in unresolved]),
                       level_ocr.ocr_for_single_lines([cv2.resize(region, None, fx=2, fy=2)
                                                       for region in clean_levels]),
                       level_ocr.ocr_for_single_lines([cv2.resize(prepared[index][2], None, fx=2, fy=2)
                                                       for index in unresolved])]
        for position, index in enumerate(unresolved):
            values[index], level_notes[index] = level_vote([reads[position] for reads in digit_reads],
                                                     len(prepared[index][0]))
    cards = []
    for index, (x, y, col) in enumerate(boxes):
        candidates = [str(names[index]).strip()]
        info, name_note = _match_name(candidates, frame_rarities[index])
        # 同一名称存在 II 型时，即使首读命中基础型也核对后缀，避免错并舰船。
        has_second_type = info and find_ship(info['name'] + 'II')
        if not info or has_second_type:
            region = name_images[index]
            reader = _scanners()[1]
            color = region[reader.TEXT_ROWS[0]:reader.TEXT_ROWS[1], reader.TEXT_LEFT:]
            candidates.extend(name_ocr.ocr_for_single_lines([color, cv2.resize(_name_image(region), None, fx=2, fy=2,
                                                                               interpolation=cv2.INTER_CUBIC)]))
            info, name_note = _match_name(candidates, frame_rarities[index])
        value, level_note = values[index], level_notes[index]
        name = info['name'] if info else candidates[0]
        if not name or all(not char.isalnum() for char in name):
            name = f'未识别舰船（第 {rows.index(y) + 1} 行第 {col + 1} 列）'
        notes = [note for note in (name_note, level_note) if note]
        reliable = bool(value and not level_note)
        base_rarity = info.get('base_rarity', '') if info else ''
        # 名单身份、等级和基础稀有度均已确认才直接计费；不能以改造卡框猜基础稀有度。
        review = not (info and reliable and base_rarity in RARITIES)
        ship = dict(name=name[:100], level=value, rarity=info['rarity'] if info else frame_rarities[index],
                    base_rarity=base_rarity, excluded=False, review=review,
                    source='；'.join([source, *notes]).strip('；')[:200])
        quality = (4 if info else 0) + (2 if reliable else 0)
        cards.append(Card(x, y, col, ship, quality, reliable, fleets[index]))
    return cards


class ScanPolicy:
    """编队置顶与普通舰分别核对降序，只有完整、确定的三行才能早停。"""
    def __init__(self, min_level=95, max_level=120, sorted_desc=False):
        if type(min_level) is not int or type(max_level) is not int or not 1 <= min_level <= max_level <= 125:
            raise ValueError('扫描等级范围必须满足 1 ≤ 最低等级 ≤ 最高等级 ≤ 125')
        self.min_level, self.max_level = min_level, max_level
        self.sorted_desc = sorted_desc
        self.sort_valid = True

    def can_stop(self, cards, slots):
        if not self.sorted_desc or not self.sort_valid:
            return False
        ordered = [card for card, _ in sorted(slots, key=lambda item: (item[1], item[0].col))]
        previous, ordinary = None, False
        for card in ordered:
            if card.fleet < 0 or not card.level_reliable:
                return False
            if card.fleet:
                if ordinary:
                    self.sort_valid = False
                    return False
            elif not ordinary:
                ordinary, previous = True, None
            if previous is not None and card.ship['level'] > previous:
                self.sort_valid = False
                return False
            previous = card.ship['level']
        rows = {}
        for card in cards:
            rows.setdefault(card.y, []).append(card)
        return (len(rows) == 3 and all({card.col for card in row} == set(range(7)) for row in rows.values())
                and all(card.fleet == 0 and card.level_reliable
                        and card.ship['level'] < self.min_level for card in cards))


def estimate_scroll(previous, current):
    """用重叠区域核验正负位移；没有唯一证据时终止而不猜测漏页。"""
    before = cv2.cvtColor(previous[65:640, 85:1225], cv2.COLOR_RGB2GRAY).astype(np.float32)[:, ::8]
    after = cv2.cvtColor(current[65:640, 85:1225], cv2.COLOR_RGB2GRAY).astype(np.float32)[:, ::8]
    if np.mean(np.abs(before - after)) < 1:
        return 0
    scores = []
    for shift in range(-454, 455):
        if shift > 0:
            a, b = before[shift:][::2], after[:-shift][::2]
        elif shift < 0:
            a, b = before[:shift][::2], after[-shift:][::2]
        else:
            a, b = before[::2], after[::2]
        # 背景黑色不能占据大部分匹配权重，船名和卡面共同提供证据。
        active = np.maximum(a, b) > 35
        error = float(np.abs(a - b)[active].mean()) if active.sum() > 300 else float('inf')
        scores.append((error, shift))
    scores.sort()
    best, shift = scores[0]
    other = min(score for score, candidate in scores if abs(candidate - shift) > 10)
    if best > 20 or other < best + 2:
        raise ValueError('相邻船坞截图没有明确的重叠位移，停止扫描以免漏船')
    return shift


class ScanMerger:
    """按格子核验滚动，输出时再对同名舰船取最高等级。"""
    def __init__(self):
        self.previous = None
        self.offset = 0
        self.slots = []

    def advance(self, image):
        """中间截图只累计位移，保证三排推进始终有重叠区域可核验。"""
        pixels = np.array(normalize_screenshot(image))
        shift = estimate_scroll(self.previous, pixels) if self.previous is not None else 0
        self.offset += shift
        self.previous = pixels.copy()
        return shift

    def add(self, image, cards):
        shift = self.advance(image)
        offset = self.offset
        if cards and self.slots:
            from module.retire.dock import CARD_GRIDS
            # 像素配准有约一像素误差，逐页累加会把重叠行误当新行。
            # 用同一船坞网格的行间距校正误差，仍以实际位移决定跨过几行。
            pitch = int(CARD_GRIDS.delta[1])
            origin = self.slots[0][1]
            top = min(card.y for card in cards) + offset
            correction = origin + round((top - origin) / pitch) * pitch - top
            if abs(correction) > 12:
                raise ValueError('滚动像素位移与船坞行间距不一致，停止扫描以免遗漏或重复')
            offset += correction
        self.offset = offset
        for card in cards:
            absolute_y = card.y + self.offset
            existing = next((item for item in self.slots if item[0].col == card.col and abs(item[1] - absolute_y) <= 12), None)
            if existing:
                previous = existing[0]
                if previous.quality < card.quality:
                    existing[0] = card
                selected = existing[0]
                if previous.ship['name'] != card.ship['name'] or previous.ship['level'] != card.ship['level']:
                    selected.ship['source'] = (selected.ship['source'] + '；跨屏读数不一致，请核对')[:200]
                    selected.ship['review'] = True
                if previous.level_reliable and card.level_reliable and previous.ship['level'] != card.ship['level']:
                    selected.level_reliable = False
            else:
                self.slots.append([card, absolute_y])
        return shift

    def ships(self, min_level=1, max_level=125):
        return highest_ships([card.ship for card, _ in sorted(self.slots, key=lambda item: (item[1], item[0].col))
                              if card.level_reliable and min_level <= card.ship['level'] <= max_level])
