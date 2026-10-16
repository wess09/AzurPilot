"""船坞卡片定位、多轮 OCR 与滚动截图的位置合并。

参考原计算器 OcrService / AutoScanService 的分层流程，适配 AP 的 1280×720 船坞。
"""
from collections import Counter, deque
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from module.runtime.mind_calculator import RARITIES, find_ship, find_ships, highest_ships, normalize_name

NAME_CORRECTIONS = {'酒句': '酒匂', '条鱼': '鲦鱼', '绦鱼': '鲦鱼', '四系乃': '四糸乃', '百雪': '白雪',
                    '杓鹊改': '杓鹬.改', '约克城iii': '约克城II', '列克星敦iii': '列克星敦II',
                    '北安普敦iii': '北安普敦II', '自凤': '白凤', '龙骥': '龙骧', '华甲改': '华甲.改'}


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
    name_reads: tuple = ()
    name_ellipsis: bool = False


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


@lru_cache(maxsize=1)
def _fleet_gray_label():
    from pathlib import Path
    from PIL import Image
    return np.array(Image.open(Path(__file__).parents[2] / 'assets/ship/dock_fleet_label_gray.png').convert('L'))


def _fleet_number(binary, reader):
    """比较全部编号模板；拒绝相近候选，避免首个过线模板抢先返回。"""
    scores = sorted((cv2.minMaxLoc(cv2.matchTemplate(binary, template.image, cv2.TM_CCOEFF_NORMED))[1], fleet)
                    for template, fleet in reader.templates.items())
    best, fleet = scores[-1]
    if best <= reader.TEMPLATE_SIMILARITY:
        return 0
    return fleet if best - scores[-2][0] >= .05 else -1


def fleet_status(region, reader):
    """复用编号与文字模板；冲突保留未知，不凭卡框颜色判断。"""
    binary = reader.pre_process(region)
    fleet = _fleet_number(binary, reader)
    # 透明蓝色徽标叠在立绘上时，绿通道会把背景连进数字；补读白字，
    # 仍使用原编号模板与相似度，不把蓝色背景或排序关系当作编队证据。
    white = cv2.threshold(region.min(axis=2), 205, 255, cv2.THRESH_BINARY)[1]
    white_fleet = _fleet_number(cv2.merge([white, white, white]), reader)
    if fleet < 0 or white_fleet < 0 or fleet > 0 and white_fleet > 0 and fleet != white_fleet:
        return -1
    score = cv2.minMaxLoc(cv2.matchTemplate(binary[20:42, :, 0], _fleet_label(), cv2.TM_CCOEFF_NORMED))[1]
    from module.base.utils import extract_white_letters
    gray = extract_white_letters(region, threshold=96)
    gray_score = cv2.minMaxLoc(cv2.matchTemplate(gray[20:42], _fleet_gray_label(), cv2.TM_CCOEFF_NORMED))[1]
    if max(score, gray_score) >= .75:
        return (fleet or white_fleet) or -1
    # 立绘细线也可能命中数字 1；编队编号必须同时有“编队”字形证据。
    return 0


def _has_name_ellipsis(region):
    """仅确认名称行右端独立的同基线双点，不能把汉字笔画当作截断。"""
    clean = _name_image(region)
    mask = (clean < 128).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = mask.shape
    dots = sorted((left, top, w, h, area) for left, top, w, h, area in stats[1:count]
                  if left >= width - 28 and top >= height - 4 and w <= 2 and h <= 3 and area <= 4)
    for first, second in zip(dots, dots[1:]):
        left, top, w, h, area = first
        right, other_top, other_w, other_h, other_area = second
        if (3 <= right - left <= 7 and right >= width - 20 and abs(top + h - other_top - other_h) <= 1
                and mask[:, left - 2:width - 10].sum() == area + other_area):
            # 双点应紧邻正文；短名右侧大块空白中的立绘亮点不能证明名称截断。
            if any(x + w <= left - 2 and left - x - w <= height + 1 and h >= 5 and area >= 8
                   for x, y, w, h, area in stats[1:count]):
                return True
    return False


def _match_name(texts, frame_rarity, *, ellipsis=False):
    """复用舰队管理名单，只有精确命中或唯一截断补全才接受身份。"""
    matcher, _, _ = _scanners()
    candidates = {}
    votes = Counter()
    # 实机名称条核实过的形近字与罗马数字误读；不做编辑距离猜名。
    for text in texts:
        # 名称两侧的引号或顿号为字图残影；不删除中间字符或 II/META 后缀。
        text = text.strip().strip('、,，\'"‘’“”')
        text = NAME_CORRECTIONS.get(normalize_name(text), text)
        if ellipsis and not find_ship(text) and matcher.exact(text) is None:
            # OCR 可能漏读省略号；只有原图双点证据才补充截断标记，
            # 后续仍要求目录中唯一补全，多个身份不能据此前缀选取。
            text = text.rstrip(' .·・…⋯') + '..'
        info = find_ship(text)
        name, status = matcher.resolve(text)
        if info:
            candidates[normalize_name(info['name'])] = info
            votes[normalize_name(info['name'])] += 1
        elif status in ('exact', 'prefix') and not find_ships(name):
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
    raw = texts[0].strip().strip('、,，\'"‘’“”')
    if 'meta' in raw.casefold() and 'meta' not in info['name'].casefold() or raw.endswith('改') and not info['name'].endswith('改'):
        return None, '多轮船名身份不一致，请核对'
    return info, f'船名经名单校正：{raw} → {info["name"]}' if normalize_name(raw) != normalize_name(info['name']) else ''


def second_type_family(texts):
    """只筛选需要核对后缀的原舰/II 型家族，不据此推定当前卡片身份。"""
    for text in texts:
        base = find_ship(normalize_name(text).rstrip('i'))
        if base and find_ship(base['name'] + 'II'):
            return True
    return False


def meta_frame(pixels, x, y):
    """识别橙色 META 卡框的外沿；未命中不表示普通舰。

    Lua 的 shipRarity2bgPrint 对 META 使用独立卡框。外沿位于普通卡面
    左侧空隙，避开舰种标志和立绘中的红色；精锐 META 仍可走名字匹配。
    """
    red, green, blue = pixels[y + 25:y + 145, x - 9:x - 6].astype(np.int16).transpose(2, 0, 1)
    return bool(((red >= 70) & (red > green * 1.6) & (red > blue * 2)).mean() >= .1)


@lru_cache(maxsize=1)
def _aircraft_icon():
    from pathlib import Path
    from PIL import Image
    return np.array(Image.open(Path(__file__).parents[2] / 'assets/ship/dock_aircraft_icon.png').convert('L'))


def aircraft_icon(pixels, x, y):
    """只用白色飞机字形的正向模板区分相近名单候选。"""
    white = (pixels[y:y + 30, x:x + 40].min(axis=2) > 205).astype(np.uint8) * 255
    return cv2.minMaxLoc(cv2.matchTemplate(white, _aircraft_icon(), cv2.TM_CCOEFF_NORMED))[1] >= .85


def recognize_cards(image, source='', *, name_ocr=None, level_ocr=None, row_origins=None, identity=None, metrics=None):
    """识别连续三行；自动扫描与上传共用相同网格、名单和等级校验。"""
    from module.ocr.al_ocr import AlOcr, OcrSettings
    from module.retire.dock import CARD_GRIDS
    from module.runtime.mind_level import dock_level_reader
    if identity is None:
        from module.runtime.mind_identity import MindIdentity
        identity = MindIdentity()
    image = normalize_screenshot(image)
    settings = OcrSettings('onnx', 'cpu', False, 'standard')
    # 连续扫描不逐字图写盘；需要诊断时可显式传入保留调试图的识别器。
    name_ocr = name_ocr or AlOcr(name='ppocr_v6', settings=settings, save_debug_images=False)
    level_ocr = level_ocr or AlOcr(name='azur_lane', settings=settings, save_debug_images=False)
    _, _, fleet_reader = _scanners()
    level_reader = dock_level_reader()
    prepare_level = metrics.wrap(level_reader.prepare, 'level_prepare') if metrics else level_reader.prepare
    read_level = metrics.wrap(level_reader.read, 'level_template') if metrics else level_reader.read
    reread_level = metrics.wrap(level_reader.reread, 'level_native_reread') if metrics else level_reader.reread
    pixels = np.array(image)
    rows = list(row_origins) if row_origins is not None else grid_rows(pixels)
    if not rows:
        rows = detect_rows(image, name_ocr) or color_rows(pixels)
    rows = _clusters([y for y in rows if 55 <= y and y + 185 <= 720], 20)
    if not rows:
        raise ValueError('未能定位船坞卡片，请上传加载完成、包含完整船名和等级的船坞截图')
    boxes, name_images, frame_rarities, fleets = [], [], [], []
    prepared, raw_levels = [], []
    for y in rows:
        for col in range(7):
            x = round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))
            raw_level = pixels[y:y + 32, x + 74:x + 138]
            masks = rarity_masks(pixels[y:y + 5, x:x + 138])
            # 蓝色条件也包含紫色像素；先剔除已满足精锐条件的像素，
            # 避免少量蓝色边缘使同一紫框从 SR 波动为 R。
            masks['R'] &= ~masks['SR']
            rarity = max(masks, key=lambda key: masks[key].sum())
            frame_rarity = rarity if masks[rarity].mean() >= .3 else ''
            body = pixels[y + 35:y + 150, x:x + 138]
            if not frame_rarity and cv2.cvtColor(body, cv2.COLOR_RGB2GRAY).std() < 20:
                continue
            boxes.append((x, y, col))
            frame_rarities.append(frame_rarity)
            name_images.append(pixels[y + 160:y + 190, x - 10:x + 142])
            prepared.append(prepare_level(raw_level))
            raw_levels.append(raw_level)
            region = pixels[y + 117:y + 162, x:x + 35]
            fleets.append(fleet_status(region, fleet_reader))
    if not boxes:
        raise ValueError('船坞卡片为空或尚未加载')
    names = name_ocr.ocr_for_single_lines([_name_image(region) for region in name_images])
    retry_names = metrics.wrap(name_ocr.ocr_for_single_lines, 'name_reread') if metrics else name_ocr.ocr_for_single_lines
    values = [read_level(glyphs) for glyphs, _, _ in prepared]
    for index, value in enumerate(values):
        if not value and prepared[index][0]:
            values[index] = reread_level(raw_levels[index], len(prepared[index][0]))
    unresolved = [index for index, value in enumerate(values) if not value]
    level_notes = [''] * len(values)
    if unresolved:
        clean_levels = [prepared[index][1] for index in unresolved]
        digit_reads = [level_ocr.ocr_for_single_lines(clean_levels),
                       level_ocr.ocr_for_single_lines([prepared[index][2] for index in unresolved])]
        if not getattr(identity, 'continuous', False):
            digit_reads.extend([level_ocr.ocr_for_single_lines([cv2.resize(region, None, fx=2, fy=2)
                                                             for region in clean_levels]),
                                level_ocr.ocr_for_single_lines([cv2.resize(prepared[index][2], None, fx=2, fy=2)
                                                               for index in unresolved])])
        for position, index in enumerate(unresolved):
            values[index], level_notes[index] = level_vote([reads[position] for reads in digit_reads],
                                                     len(prepared[index][0]))
    cards = []
    for index, (x, y, col) in enumerate(boxes):
        candidates = [str(names[index]).strip()]
        ellipsis = _has_name_ellipsis(name_images[index])
        is_meta = meta_frame(pixels, x, y)
        context = {}
        if identity is not None:
            from module.runtime.fleet_tech_identity import aviation_icon, surface_icon
            context = dict(meta_frame=is_meta, aviation=aviation_icon(pixels, x, y),
                           surface=surface_icon(pixels, x, y))

        def match_names(texts, rarity, *, ellipsis=False):
            return identity.match(texts, rarity, ellipsis=ellipsis, **context) if identity is not None \
                else _match_name(texts, rarity, ellipsis=ellipsis)

        info, name_note = match_names(candidates, frame_rarities[index], ellipsis=ellipsis)
        if not getattr(identity, 'continuous', False) and info and is_meta and info.get('group') != 'META':
            # META 名称条可能只容纳普通舰全名；不能让该精确前缀绕过边框证据。
            info = None
        # 同一名称存在 II 型时，即使首读命中基础型也核对后缀，避免错并舰船。
        has_second_type = (not getattr(identity, 'continuous', False)
                           and info and find_ship(info['name'] + 'II'))
        if not info or has_second_type or identity is not None and identity.needs_retry(info):
            region = name_images[index]
            reader = _scanners()[1]
            color = region[reader.TEXT_ROWS[0]:reader.TEXT_ROWS[1], reader.TEXT_LEFT:]
            candidates.extend(retry_names([color, cv2.resize(_name_image(region), None, fx=2, fy=2,
                                                                               interpolation=cv2.INTER_CUBIC)]))
            info, name_note = match_names(candidates, frame_rarities[index], ellipsis=ellipsis)
        if not info and second_type_family(candidates):
            # 实图中细罗马字形经平滑放大可能并成 I；只对未确认家族补充不平滑的字图。
            clean = _name_image(name_images[index])
            candidates.extend(retry_names([
                cv2.resize(clean, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
                for scale in (2, 3)]))
            info, name_note = match_names(candidates, frame_rarities[index], ellipsis=ellipsis)
        if (not getattr(identity, 'continuous', False) and info and find_ship(info['name'] + 'II')
                and any(normalize_name(text).endswith('i') and second_type_family([text]) for text in candidates)):
            # 原图出现未确认的罗马后缀时，不能因另一次漏读后缀而接受基础型。
            # 行定位的采样相位可裁掉细字下缘；仍用共享 19px 预处理，
            # 只补读原名称区下移两像素的字图，保留两次 II 投票要求。
            clean = _name_image(name_images[index][2:])
            candidates.extend(retry_names([
                cv2.resize(clean, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
                for scale in (2, 3)]))
            info, name_note = match_names(candidates, frame_rarities[index], ellipsis=ellipsis)
            if info and find_ship(info['name'] + 'II'):
                info, name_note = None, '罗马后缀未确认，不能将存疑读数当作基础型舰船'
        family_base = next((base for text in candidates
                            if (base := find_ship(normalize_name(text).rstrip('i')))
                            and find_ship(base['name'] + 'II')), None)
        frame_conflict = (info and family_base and info.get('group_type') == family_base.get('group_type')
                          and frame_rarities[index] and frame_rarities[index] != info.get('rarity'))
        if (not getattr(identity, 'continuous', False) and family_base and (not info or frame_conflict) and not ellipsis
                and not any('..' in text or '…' in text or '⋯' in text for text in candidates)):
            # 婚舰卡框可被读成额外 I；仅裁掉两侧空白并核实完整 II 双读，
            # 不把 III 字符串改成 II，也不以稀有度决定身份。
            second = find_ship(family_base['name'] + 'II')
            allowed = {family_base['group_type'], second['group_type']}
            conflicting = any(item['group_type'] not in allowed for text in candidates
                              if (item := find_ship(text)) is not None)
            confirmed_second = None
            for shift in (0, 1, -1) if not conflicting else ():
                region = pixels[y + 160 + shift:y + 190 + shift, x - 10:x + 142]
                clean = _name_image(region)[:, 8:-8]
                rereads = retry_names([cv2.resize(clean, None, fx=scale, fy=scale,
                                                 interpolation=cv2.INTER_NEAREST) for scale in (2, 3)])
                candidates.extend(rereads)
                proof = [match_names([text], frame_rarities[index])[0] for text in rereads]
                if all(item and item.get('group_type') == second['group_type'] for item in proof):
                    confirmed_second = proof[0]
                    break
            info = confirmed_second
            name_note = '两路完整 II 后缀确认' if info else '罗马后缀未确认，不能将存疑读数当作基础型舰船'
        if not info and len(normalize_name(candidates[0])) == 1 and not ellipsis:
            # 单字名的细笔画在采样相位变化后容易并线；只收缩空白边缘，
            # 使用共享字图的平滑放大补读，两个精确读数一致才接受身份。
            retry_reads = retry_names([
                cv2.resize(_name_image(name_images[index][shift:])[:, margin:-margin], None,
                           fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                for shift in (0, 2, 4) for margin in (4, 8) for scale in (2, 3)])
            previous_note = name_note
            candidates.extend(retry_reads)
            info, name_note = match_names(candidates, frame_rarities[index])
            confirmed = [match_names([text], frame_rarities[index])[0] for text in retry_reads]
            if not info or not any(all(item and item['name'] == info['name'] for item in confirmed[start:start+2])
                                   for start in range(0, len(confirmed)-1, 2)):
                info, name_note = None, previous_note
        if (not info and not ellipsis and not second_type_family(candidates)
                and 2 <= len(normalize_name(candidates[0])) <= 6
                and not any('..' in text or '…' in text or '⋯' in text for text in candidates)):
            # 短名距卡框仍有空白；原色复读可能把婚舰边框读成额外字母。
            # 只在失败后去掉两侧各六像素，长名/截断名不收缩；两张
            # 原色字图必须分别精确确认同一身份，不删 OCR 字符猜名字。
            reader = _scanners()[1]
            region = name_images[index][reader.TEXT_ROWS[0]:reader.TEXT_ROWS[1], reader.TEXT_LEFT:]
            retry_reads = retry_names([
                cv2.resize(region[:, 6:-6], None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
                for scale in (2, 3)])
            previous_note = name_note
            candidates.extend(retry_reads)
            info, name_note = match_names(candidates, frame_rarities[index])
            confirmed = [match_names([text], frame_rarities[index])[0] for text in retry_reads]
            if not info or sum(bool(item and item['name'] == info['name']) for item in confirmed) < 2:
                info, name_note = None, previous_note
        if getattr(identity, 'extended_retries', True) and (not info or identity.needs_retry(info)):
            # 特殊版本不能因首读遗漏“小”或兵装后缀而并入普通舰；有限相位复读仍取原字图。
            candidates.extend(retry_names([
                cv2.resize(_name_image(name_images[index][shift:]), None, fx=2, fy=2,
                           interpolation=cv2.INTER_NEAREST)
                for shift in (1, 2, 3, 4)]))
            info, name_note = match_names(candidates, frame_rarities[index], ellipsis=ellipsis)
        if not getattr(identity, 'continuous', False) and info and is_meta and info.get('group') != 'META':
            info = None
        stroke_shifts = (0, 1, -1, 2, -2, 3, -3, 4, -4) if getattr(identity, 'extended_retries', True) else ()
        if (not info and not ellipsis and not is_meta and not second_type_family(candidates)
                and 2 <= len(normalize_name(candidates[0])) <= 6 and hasattr(identity, 'stroke_shifts')
                and not any('..' in text or '…' in text or '⋯' in text for text in candidates)):
            stroke_shifts = identity.stroke_shifts(candidates)
        if stroke_shifts and not info and '同名同舰种' not in name_note:
            # 小字抗锯齿会丢失细笔画或粘连罗马后缀；只对失败读数做有界复读。
            # 两种笔画处理都独立确认同一群组后才采用，不替换任何特定舰名。
            kernel = np.ones((2, 2), np.uint8)
            for shift in stroke_shifts:
                region = pixels[y + 160 + shift:y + 190 + shift, x - 10:x + 142]
                clean = cv2.resize(_name_image(region), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                rereads = retry_names([cv2.erode(clean, kernel), cv2.dilate(clean, kernel)])
                proof = [match_names([text], frame_rarities[index], ellipsis=ellipsis)[0] for text in rereads]
                if (all(proof) and len({item['group_type'] for item in proof}) == 1
                        and (not frame_rarities[index] or proof[0]['base_rarity'] == frame_rarities[index]
                             or proof[0].get('group') in ('改造', 'META'))):
                    candidates.extend(rereads)
                    info, name_note = match_names(candidates, frame_rarities[index], ellipsis=ellipsis)
                    if info:
                        break
        if not info:
            if identity is not None:
                matched, match_note = identity.match(candidates, frame_rarities[index], ellipsis=ellipsis,
                                                    fuzzy=True, **context)
            else:
                from module.runtime.mind_name import match_lua_name
                matched, match_note = match_lua_name(candidates, frame_rarities[index], ellipsis=ellipsis,
                                                     meta_frame=is_meta, aviation=aircraft_icon(pixels, x, y))
            if matched:
                info, name_note = matched, match_note
            elif '罗马后缀未确认' not in name_note:
                name_note = match_note
        value, level_note = values[index], level_notes[index]
        name = info['name'] if info else candidates[0]
        if not name or all(not char.isalnum() for char in name):
            name = f'舰名未读到（第 {rows.index(y) + 1} 行第 {col + 1} 列）'
        # 持久来源描述已确认的身份状态；实际 OCR 原文放在卡位诊断中，
        # 不让同一身份的标点、形近字或复读路径改变正常清单的来源提示。
        identity_note = (name_note if '自动回填' in name_note else
                         f'船名经国服名单确认：{info["name"]}') if info else name_note
        if metrics and '自动回填' in name_note:
            metrics.counts['name_catalog_fallback'] += 1
        notes = [note for note in (identity_note, level_note) if note]
        reliable = bool(value and not level_note)
        base_rarity = info.get('base_rarity', '') if info else ''
        # 名单身份、等级和基础稀有度均已确认才直接计费；不能以改造卡框猜基础稀有度。
        review = not (info and reliable and base_rarity in RARITIES)
        ship = dict(name=name[:100], level=value, rarity=info['rarity'] if info else frame_rarities[index],
                    base_rarity=base_rarity, excluded=False, review=review,
                    source='；'.join([source, *notes]).strip('；')[:200])
        if identity is not None:
            ship.update(group_type=info.get('group_type') if info else None,
                        type=info.get('type') if info else None,
                        candidates=identity.candidates(candidates, ellipsis=ellipsis) if not info else [],
                        identity_ambiguous='同名同舰种' in name_note or '需要阵营证据' in name_note)
        quality = (4 if info else 0) + (2 if reliable else 0)
        cards.append(Card(x, y, col, ship, quality, reliable, fleets[index], tuple(candidates), ellipsis))
    return cards


class ScanPolicy:
    """编队置顶与普通舰分别核对降序，只有完整、确定的三行才能早停。"""
    def __init__(self, min_level=95, max_level=125, sorted_desc=False):
        if type(min_level) is not int or type(max_level) is not int or not 1 <= min_level <= max_level <= 125:
            raise ValueError('扫描等级范围必须满足 1 ≤ 最低等级 ≤ 最高等级 ≤ 125')
        self.min_level, self.max_level = min_level, max_level
        self.sorted_desc = sorted_desc
        self.sort_valid = True

    def sort_issue(self, slots):
        """只检查候选读数，不改变累计排序状态，便于合并前获取新帧复核。"""
        conflicts = self.sort_conflicts(slots)
        return conflicts[0][1] if conflicts else ''

    def sort_conflicts(self, slots):
        """指出冲突涉及的两侧卡片，不猜哪一张的等级或编队标记读错。"""
        if not self.sorted_desc:
            return []
        ordered = [card for card, _ in sorted(slots, key=lambda item: (item[1], item[0].col))]
        previous, ordinary = None, False
        conflicts = []
        for card in ordered:
            location = f'{card.y}px 行第 {card.col + 1} 列（{card.ship["name"]}）'
            if card.fleet < 0 or not card.level_reliable:
                conflicts.append((card, f'{location}的编队或等级未确认'))
                previous, ordinary = None, False
                continue
            if card.fleet:
                if ordinary:
                    note = f'{location}在普通舰之后出现编队标记'
                    conflicts.append((card, note))
                    if previous is not None:
                        conflicts.append((previous, note))
                    # 冲突只涉及交界的两张卡；不能让一次标记误读污染后续编队。
                    previous, ordinary = None, False
            elif not ordinary:
                ordinary, previous = True, None
            if previous is not None and card.ship['level'] > previous.ship['level']:
                note = f'{location}的等级高于同段前一艘'
                conflicts.extend(((previous, note), (card, note)))
            previous = card
        return conflicts

    def _recent_slots(self, slots):
        """历史疑点保留在原卡位；早停只使用最后一个疑点之后的连续证据。"""
        ordered = sorted(slots, key=lambda item: (item[1], item[0].col))
        doubtful = {id(card) for card, _ in self.sort_conflicts(ordered)}
        last = max((index for index, (card, _) in enumerate(ordered) if id(card) in doubtful), default=-1)
        return ordered[last + 1:]

    def can_stop(self, cards, slots):
        recent = self._recent_slots(slots)
        self.sort_valid = self._current_confirmed(cards, slots, recent)
        return not self.stop_reason(cards, slots)

    @staticmethod
    def _current_confirmed(cards, slots, recent):
        if not cards or not slots:
            return False
        # 重叠页可能保留前一帧质量相同的 Card 对象；依据物理卡位而非对象身份。
        offset = max(y for _, y in slots) - max(card.y for card in cards)
        return all(any(old.col == card.col and abs(y - card.y - offset) <= 12 for old, y in recent)
                   for card in cards)

    def stop_reason(self, cards, slots):
        """返回拒绝早停的证据，空字符串表示完整三行已确认越过下限。"""
        if not self.sorted_desc:
            return '尚未确认等级降序'
        recent = self._recent_slots(slots)
        if not self._current_confirmed(cards, slots, recent):
            return '当前页包含未确认编队、等级或排序卡位'
        if issue := self.sort_issue(recent):
            return f'当前连续船位排序待核对：{issue}'
        rows = {}
        for card in cards:
            rows.setdefault(card.y, []).append(card)
        if (len(cards) != 21 or len(rows) != 3
                or any({card.col for card in row} != set(range(7)) for row in rows.values())):
            return '当前页不足完整三行七列'
        if any(card.fleet != 0 for card in cards):
            return '当前页仍有置顶编队或未知编队'
        if any(not card.level_reliable for card in cards):
            return '当前页等级待核对'
        if any(card.ship['level'] >= self.min_level for card in cards):
            return f'当前页仍有不低于 {self.min_level} 级的舰船'
        return ''


class ScrollMotion:
    """用独立滑块运动约束重复卡片的候选，不把触控距离当成真实位移。"""

    def __init__(self, row_pitch=180):
        self.thumb = None
        self.ratios = deque(maxlen=8)
        self.row_pitch = row_pitch
        self.strict_bounds = True

    def bounds(self, thumb, drag):
        self.strict_bounds = True
        gesture_bounds = None
        if drag is not None:
            extent = abs(drag[0]) + 6
            if drag[1] and extent < self.row_pitch / 2:
                # 小距离按住拖动不能跨越整行别名；保留零和反向候选，
                # 最终位移仍须图像唯一确认，不依赖滑块的亚像素移动。
                # 手势幅度仅用于排除重复画面的整行别名，不能证明真实位移
                # 的硬上限；唯一重叠图像仍按原阈值确认，不能因滚动惯性误拒。
                self.strict_bounds = False
                gesture_bounds = (-int(extent), int(extent))
        if thumb is None or self.thumb is None or drag is None:
            return gesture_bounds
        delta = np.asarray(thumb[[0, -1]]) - self.thumb
        # 两个端点必须同向移动；长度变化或单端闪光不能证明船坞滚动。
        if not (np.all(delta >= 1) or np.all(delta <= -1)) or abs(delta[0] - delta[1]) > 2:
            return gesture_bounds
        if gesture_bounds is not None and not (np.all(delta >= 2) or np.all(delta <= -2)):
            # 小校正的一像素端点变化仍可能来自采样，不能升级为独立硬约束。
            return gesture_bounds
        distance, held = drag
        direction = 1 if delta.mean() > 0 else -1
        if distance * direction <= 0 and gesture_bounds is None:
            return None
        self.strict_bounds = True
        # 已确认的滑块运动只能由自身标定限制，不能再被手势长度裁短。
        # 454 是既有重叠匹配范围，不增加图像阈值或搜索跨度。
        low, high = 1., 454.
        if len(self.ratios) >= 2:
            ratio = float(np.median(self.ratios))
            expected = abs(float(delta.mean())) * ratio
            tolerance = ratio * 1.5 + expected * .1 + 6
            low, high = max(low, expected - tolerance), min(high, expected + tolerance)
        elif not held:
            return None
        if low > high:
            return None
        lower, upper = int(np.ceil(low)), int(np.floor(high))
        return (lower, upper) if direction > 0 else (-upper, -lower)

    def accept(self, thumb, moved, *, hinted=False):
        if thumb is not None and self.thumb is not None and moved and not hinted:
            ends = thumb[[0, -1]] - self.thumb
            delta = float(np.mean(ends))
            coherent = (np.all(ends >= 1) or np.all(ends <= -1)) and abs(ends[0] - ends[1]) <= 2
            if coherent and abs(delta) >= 2 and delta * moved > 0 and abs(moved) >= 40:
                self.ratios.append(abs(moved / delta))
        self.thumb = np.asarray(thumb[[0, -1]]).copy() if thumb is not None else None


def estimate_scroll(previous, current, bounds=None, check_zero=False):
    """用重叠区域核验正负位移；没有唯一证据时终止而不猜测漏页。"""
    # 先取原有采样列再转浮点，使内层逐位移比较读取连续内存；候选和阈值不变。
    before = cv2.cvtColor(previous[65:640, 85:1225], cv2.COLOR_RGB2GRAY)[:, ::8].astype(np.float32)
    after = cv2.cvtColor(current[65:640, 85:1225], cv2.COLOR_RGB2GRAY)[:, ::8].astype(np.float32)
    if not check_zero and np.mean(np.abs(before - after)) < 1 and (bounds is None or bounds[0] <= 0 <= bounds[1]):
        return 0
    scores = []
    for shift in range(-454, 455):
        if bounds is not None and not bounds[0] <= shift <= bounds[1]:
            continue
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
    if not scores:
        raise ValueError('滚动条运动与船坞卡片位移不一致')
    scores.sort()
    best, shift = scores[0]
    other = min((score for score, candidate in scores if abs(candidate - shift) > 10), default=float('inf'))
    if best > 20 or other < best + 2:
        raise ValueError('相邻船坞截图没有明确的重叠位移，停止扫描以免漏船')
    return shift


class ScanMerger:
    """按格子核验滚动，输出时再对同名舰船取最高等级。"""
    def __init__(self, group_identity=False):
        self.previous = None
        self.offset = 0
        self.slots = []
        self.group_identity = group_identity
        self.motion_hint_used = False

    def advance(self, image, bounds=None, after_drag=False, strict_bounds=True):
        """中间截图只累计位移，保证三排推进始终有重叠区域可核验。"""
        pixels = np.array(normalize_screenshot(image))
        self.motion_hint_used = False
        shift = 0
        if self.previous is not None:
            try:
                shift = estimate_scroll(self.previous, pixels, check_zero=after_drag)
            except ValueError:
                if bounds is None:
                    raise
                shift = estimate_scroll(self.previous, pixels, bounds=bounds, check_zero=True)
                self.motion_hint_used = True
            else:
                if strict_bounds and bounds is not None and not bounds[0] <= shift <= bounds[1]:
                    raise ValueError('卡片位移与独立滚动证据不一致')
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
                if selected.fleet < 0 <= card.fleet and card.level_reliable:
                    # 同一物理船位的新帧补齐编队证据，保留原人工核对标记。
                    selected.fleet = card.fleet
                name_conflict = previous.ship['name'] != card.ship['name']
                before_gid, after_gid = previous.ship.get('group_type'), card.ship.get('group_type')
                if self.group_identity or previous.ship.get('group_type') is not None or card.ship.get('group_type') is not None:
                    # 相同群组的改造名、后缀读法不同不构成身份冲突；不同群组不能互相覆盖。
                    name_conflict = before_gid is not None and after_gid is not None and before_gid != after_gid
                level_conflict = (previous.ship['level'] and card.ship['level']
                                  and previous.ship['level'] != card.ship['level'])
                if name_conflict or level_conflict:
                    selected.ship['source'] = (selected.ship['source'] + '；跨屏读数不一致，请核对')[:200]
                    selected.ship['review'] = True
                    if name_conflict and (self.group_identity or before_gid is not None or after_gid is not None):
                        selected.ship['candidates'] = sorted({before_gid, after_gid})
                        selected.ship['group_type'] = None
                        selected.ship['identity_ambiguous'] = True
                if level_conflict and previous.level_reliable and card.level_reliable:
                    selected.level_reliable = False
            else:
                self.slots.append([card, absolute_y])
        return shift

    def ships(self, min_level=1, max_level=125):
        # 疑难卡位必须进入核对清单；不能按存疑身份/等级静默过滤或计费。
        ships = [card.ship if card.level_reliable else dict(card.ship, level=0, review=True)
                 for card, _ in sorted(self.slots, key=lambda item: (item[1], item[0].col))
                 if not card.level_reliable or card.ship['review'] and not self.group_identity
                 or min_level <= card.ship['level'] <= max_level]
        if not self.group_identity:
            return highest_ships(ships)
        confirmed, reviews = {}, []
        for ship in ships:
            gid = ship.get('group_type')
            if ship.get('review') or gid is None:
                reviews.append(ship)
            elif gid not in confirmed or ship['level'] > confirmed[gid]['level']:
                confirmed[gid] = ship
        return [*confirmed.values(), *reviews]
