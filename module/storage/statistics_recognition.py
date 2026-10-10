"""仓库材料的离线识别与滚动去重，不依赖设备或用户配置。"""

from dataclasses import dataclass
from functools import cached_property
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from module.base.utils import extract_white_letters, load_image
from module.statistics.amount_digits import DigitTemplates
from module.storage.amount_glyphs import StorageAmountGlyphs, native_glyph

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'assets/stats/storage_items/catalog.json'
GRID_AREA = (130, 65, 1235, 637)


class StorageRecognitionError(ValueError):
    """画面、物品或数量无法可靠确认，禁止提交本次快照。"""


class StorageNoProgressError(StorageRecognitionError):
    """页面只含已读行，需要再向下浏览以露出新行。"""


class StorageAmountGlyphError(StorageRecognitionError):
    """数量完整，但抗锯齿字形尚未达到匹配置信度。"""


@dataclass
class StorageCard:
    """完整材料格；未知物品仍保留图像供重叠行核对。"""
    area: tuple
    image: np.ndarray
    context: np.ndarray | None = None
    present: bool = True
    identifier: str | None = None
    amount: int | None = None
    comparison_amount: int | None = None


class StorageCatalog:
    """显式物品目录，复用既有模板并按物品合并模板变体。"""

    def __init__(self, path=CATALOG):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.items = data['items']
        self.servers = data['servers']
        self.templates = []
        fingerprint = hashlib.sha256(self.path.read_bytes())
        fingerprint.update((self.path.parent / 'amount_digits.png').read_bytes())
        fingerprint.update((self.path.parent / 'amount_glyphs.png').read_bytes())
        for item in self.items:
            for relative in item['templates']:
                path = ROOT / relative
                fingerprint.update(path.read_bytes())
                image = cv2.resize(load_image(str(path)), (96, 96), interpolation=cv2.INTER_AREA)
                self.templates.append((item['id'], image[14:70, 14:82].astype(np.float32),
                                       np.array(item['background'])))
        self.version = fingerprint.hexdigest()

    def _scores(self, icon, context=None, identifier=None):
        """保留原始模板和采样相位；已确认身份时只匹配该物品的变体。"""
        image = cv2.resize(icon, (96, 96), interpolation=cv2.INTER_AREA)
        color = image[5:13, 5:13].mean(axis=(0, 1))
        candidates = [image]
        if context is not None:
            # 128px 仓库图标缩到既有 96px 模板时，亚像素采样相位会变化。
            # 有界的原图偏移保留既有模板，而不是降低相似度门槛。
            candidates = [cv2.resize(context[y:y + 128, x:x + 128], (96, 96),
                                    interpolation=cv2.INTER_AREA)
                          for y in range(1, 4) for x in range(1, 4)]
        # 预转浮点，避免数千次匹配重复处理类型；缩放像素、搜索范围和门槛保持一致。
        candidates = [candidate.astype(np.float32) for candidate in candidates]
        scores = {}
        for candidate_id, template, template_color in self.templates:
            if identifier is not None and candidate_id != identifier:
                continue
            # SSR 和 UR 纸张图形几乎相同，另外核对稀有度底色。
            if np.max(np.abs(color - template_color)) > 45:
                continue
            score = max(cv2.minMaxLoc(cv2.matchTemplate(candidate[:74], template,
                                                       cv2.TM_CCOEFF_NORMED))[1]
                        for candidate in candidates)
            scores[candidate_id] = max(scores.get(candidate_id, -1.), score)
        return scores

    def identify(self, icon, context=None):
        """模板分数、次优差距与稀有度底色均通过才接受身份。"""
        scores = self._scores(icon, context)
        ranks = sorted(scores.items(), key=lambda entry: entry[1], reverse=True)
        if not ranks or ranks[0][1] < .78:
            return None
        first, score = ranks[0]
        margin = score - (ranks[1][1] if len(ranks) > 1 else 0.)
        if score < .90 or margin < .035:
            raise StorageRecognitionError(f'物品身份不确定：候选 {first}，相似度 {score:.3f}，差距 {margin:.3f}')
        return first

    def verify(self, card, reference):
        """同页仅核对已确认目标的模板和完整数量，不重跑整个目录。"""
        identifier = reference.identifier
        score = self._scores(card.image, card.context, identifier).get(identifier, -1.)
        if score < .90:
            raise StorageRecognitionError(f'{identifier} 的同页图标变化，相似度 {score:.3f}')
        card.identifier = identifier
        try:
            card.amount = self.read_amount(card.image)
        except StorageRecognitionError as error:
            raise StorageRecognitionError(f'{identifier}（位置 {card.area}）：{error}') from error
        if card.amount != reference.amount:
            raise StorageRecognitionError(f'{identifier} 的同页数量不一致：{reference.amount} → {card.amount}')

    def is_target_rarity(self, icon):
        """先筛目录中的金/彩底色，紫色等非目标格不执行模板及数量匹配。"""
        if is_purple(icon):
            return False
        image = cv2.resize(icon, (96, 96), interpolation=cv2.INTER_AREA)
        color = image[5:13, 5:13].mean(axis=(0, 1))
        return any(np.max(np.abs(color - background)) <= 45
                   for _, _, background in self.templates)

    @cached_property
    def digits(self):
        image = cv2.imread(str(self.path.parent / 'amount_digits.png'), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise StorageRecognitionError('仓库数字模板缺失')
        return DigitTemplates(image)

    @cached_property
    def gray_digits(self):
        return StorageAmountGlyphs(self.path.parent / 'amount_glyphs.png')

    def read_amount(self, icon):
        """只读取右下角原始像素；失败不回退为零，不截断猜数。"""
        image = extract_white_letters(icon[99:126, 25:127], threshold=96)
        try:
            return self._read_amount_mask(image < 100)
        except StorageAmountGlyphError:
            # 完整数字的灰边承载采样相位信息，二值化会把相同数字变成不同形状。
            # 固定原生字高的灰度模板另有严格误差/次优差距，不改变通用字形门槛。
            try:
                return self._read_amount_gray(image)
            except StorageAmountGlyphError:
                pass
            # 滚动停在亚像素位置时，抗锯齿灰边会改变二值字形。
            # 只接受至少两种有限阈值一致的完整读数，字形置信度与截断检查不变。
            candidates = []
            for threshold in (85, 90, 95, 110, 120, 125):
                try:
                    candidates.append(self._read_amount_mask(image < threshold))
                except StorageRecognitionError:
                    continue
            if len(candidates) >= 2 and len(set(candidates)) == 1:
                return candidates[0]
            raise

    @staticmethod
    def _amount_parts(binary):
        """先确认所有首末位、基线与间距，残缺数量不得进入任何字形兜底。"""
        binary = binary.astype(np.uint8)
        _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        parts = [(label, int(x), int(y), int(width), int(height))
                 for label, (x, y, width, height, area) in enumerate(stats[1:], 1)
                 if area >= 8 and height >= 5]
        parts.sort(key=lambda part: part[1])
        if not parts:
            raise StorageRecognitionError('仓库数量字形无法确认')
        last = parts[-1]
        baseline = last[2] + last[4]
        if not 3 <= binary.shape[1] - last[1] - last[3] <= 10 or not 21 <= baseline <= 26:
            raise StorageRecognitionError('仓库数量末位或基线不完整')
        selected = [last]
        for part in reversed(parts[:-1]):
            if abs(part[2] + part[4] - baseline) > 2:
                continue
            gap = selected[-1][1] - part[1] - part[3]
            if gap > 5:
                if gap < 10:
                    raise StorageRecognitionError('仓库数量首位可能残缺')
                break
            selected.append(part)
        for label, x, y, width, height in reversed(selected):
            # 仓库数量字高为 18–19px；破损首位不能被当成图标残影删掉。
            if not 17 <= height <= 21 or x == 0 or x + width >= binary.shape[1]:
                raise StorageRecognitionError('仓库数量存在截断或残缺字形')
        return labels, list(reversed(selected)), baseline

    def _read_amount_mask(self, binary):
        """核对完整字形、基线和间距后逐位读取。"""
        labels, parts, _ = self._amount_parts(binary)
        result = ''
        for label, x, y, width, height in parts:
            mask = (labels[y:y + height, x:x + width] == label).astype(np.uint8)
            digit, error, margin = self.digits.classify(mask)
            scores = [(error, margin)]
            if width <= height * .85 and self.digits.confident(scores):
                text = str(digit)
            else:
                text, scores = self.digits.split(mask)
            if not text or not self.digits.confident(scores):
                raise StorageAmountGlyphError('仓库数量字形无法确认')
            result += text
        if not result or result.startswith('0'):
            raise StorageRecognitionError('仓库数量格式无效')
        return int(result)

    def _read_amount_gray(self, image):
        """只匹配几何完整的单字形；粘连数字仍由既有有界拆分处理。"""
        _, parts, baseline = self._amount_parts(image < 100)
        result = ''
        for _, x, y, width, height in parts:
            if width > height * .85:
                raise StorageAmountGlyphError('仓库粘连数量字形无法确认')
            digit = self.gray_digits.classify(native_glyph(image, x, width, baseline))
            if digit is None:
                raise StorageAmountGlyphError('仓库灰度数量字形无法确认')
            result += str(digit)
        if not result or result.startswith('0'):
            raise StorageRecognitionError('仓库数量格式无效')
        return int(result)

    def snapshot_items(self, rows):
        """按物理位置去重后汇总；未发现的目录物品保留 None。"""
        amounts = {}
        for row in rows:
            for card in row:
                if card.identifier is not None:
                    amounts[card.identifier] = amounts.get(card.identifier, 0) + card.amount
        return [dict(id=item['id'], name=item['name'], group=item['group'],
                     amount=amounts.get(item['id'])) for item in self.items]


def detect_rows(image):
    """从方框推导网格，不把物品绑定到固定格子或纵坐标。"""
    if image.shape != (720, 1280, 3):
        raise StorageRecognitionError('仓库统计要求 1280×720 RGB 截图')
    x0, y0, x1, y1 = GRID_AREA
    edges = cv2.Canny(cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY), 70, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    rectangles = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if 127 <= width <= 130 and 127 <= height <= 130:
            rectangles.append((x + x0, y + y0))
    columns = []
    for x, _ in sorted(rectangles):
        if not columns or x - columns[-1] > 5:
            columns.append(x)
    if len(columns) != 7 or any(not 156 <= b - a <= 161 for a, b in zip(columns, columns[1:])):
        raise StorageRecognitionError('材料网格列数或间距不完整')
    starts = []
    for _, y in sorted(rectangles, key=lambda entry: entry[1]):
        if not starts or y - starts[-1] > 5:
            starts.append(y)
    rows = []
    for y in starts:
        # 贴着裁剪下沿的轮廓可能仍有 127px 高，但数量末行已被遮住。
        # 留给下一次滚动读取，不能把这种半格当成仓库末行或识别故障。
        if y - 1 < y0 or y + 133 > y1:
            continue
        matches = [x for x, row_y in rectangles if abs(row_y - y) <= 3]
        if not matches:
            continue
        row = []
        empty_started = False
        for x in columns:
            # 动画亮点会连通方框，其他格子推导出的格子仍须核对完整边框。
            border = edges[max(0, y - y0):y - y0 + 130, x - x0:x - x0 + 130]
            present = border.shape == (130, 130) and border[:3].mean() >= 30 and border[-4:].mean() >= 30
            if not present:
                # 末行空格须为连续尾部空位，不能还有被遮住的图标边缘。
                if border.shape != (130, 130) or border.mean() > 3:
                    raise StorageRecognitionError('材料行被遮挡或边框不完整')
                empty_started = True
            elif empty_started:
                raise StorageRecognitionError('材料行中间出现缺失格子')
            area = (x + 1, y + 1, x + 129, y + 129)
            row.append(StorageCard(area, image[y + 1:y + 129, x + 1:x + 129].copy(),
                                   image[y - 1:y + 133, x - 1:x + 133].copy(), present))
        rows.append(row)
    if not rows:
        raise StorageRecognitionError('未找到完整的材料行')
    return rows


def same_card(left, right):
    """重叠核对包含未知物品，不能只比较已知目标的名字。"""
    if left.present != right.present or left.identifier != right.identifier or left.amount != right.amount:
        return False
    if left.identifier is not None:
        # 已知格已经通过图标模板、次优差距及全部数量字形确认。
        # 虹彩或闪光不能推翻相同身份和完整数量；尚未读出数量的格子不能通过。
        return left.amount is not None
    if (left.comparison_amount is not None and right.comparison_amount is not None
            and left.comparison_amount != right.comparison_amount):
        return False
    # 方框轮廓可能因动画亮点相差 1–2px，允许有界对齐，避免同一物品被当成新行。
    score = cv2.minMaxLoc(cv2.matchTemplate(left.image, right.image[3:125, 3:125],
                                          cv2.TM_CCOEFF_NORMED))[1]
    if score >= .985:
        return True
    # 虹彩动画改变颜色，滚动亚像素位置改变抗锯齿；平滑后仍须高置信度结构一致。
    # 另查稀有度底色，避免灰度相近的不同等级物品被当成同一格。
    if np.max(np.abs(left.image[7:17, 7:17].mean(axis=(0, 1))
                     - right.image[7:17, 7:17].mean(axis=(0, 1)))) > 45:
        return False
    left_gray = cv2.cvtColor(left.image, cv2.COLOR_RGB2GRAY)
    right_gray = cv2.cvtColor(right.image, cv2.COLOR_RGB2GRAY)
    score = cv2.minMaxLoc(cv2.matchTemplate(left_gray, right_gray[3:125, 3:125],
                                          cv2.TM_CCOEFF_NORMED))[1]
    if score >= .985:
        return True
    left_smooth = cv2.GaussianBlur(left_gray, (7, 7), 0)
    right_smooth = cv2.GaussianBlur(right_gray, (7, 7), 0)
    score = cv2.minMaxLoc(cv2.matchTemplate(left_smooth, right_smooth[3:125, 3:125],
                                          cv2.TM_CCOEFF_NORMED))[1]
    if score >= .985:
        return True
    # 虹彩渐变属于低频背景，保留主体和数量边缘后仍用同一门槛核对。
    # 使用有符号浮点差分，不能将负边缘截成零而丢失区分不同蓝图的信息。
    left_gray, right_gray = left_gray.astype(np.float32), right_gray.astype(np.float32)
    left_detail = cv2.GaussianBlur(left_gray, (3, 3), 0) - cv2.GaussianBlur(left_gray, (31, 31), 0)
    right_detail = cv2.GaussianBlur(right_gray, (3, 3), 0) - cv2.GaussianBlur(right_gray, (31, 31), 0)
    score = cv2.minMaxLoc(cv2.matchTemplate(left_detail, right_detail[3:125, 3:125],
                                          cv2.TM_CCOEFF_NORMED))[1]
    if score >= .985:
        return True
    if left.comparison_amount is None or left.comparison_amount != right.comparison_amount:
        return False
    # 强虹彩还会改变主体亮度。只有两格完整数量独立确认一致后，才单独核对主体。
    # 排除共同边框和数量区，保留头像/ALL 图案；不能用相同数量替代身份匹配。
    left_detail = cv2.GaussianBlur(left_gray, (7, 7), 0) - cv2.GaussianBlur(left_gray, (31, 31), 0)
    right_detail = cv2.GaussianBlur(right_gray, (7, 7), 0) - cv2.GaussianBlur(right_gray, (31, 31), 0)
    score = cv2.minMaxLoc(cv2.matchTemplate(left_detail[9:103, 9:119], right_detail[12:100, 12:116],
                                          cv2.TM_CCOEFF_NORMED))[1]
    return score >= .97


def same_row(left, right):
    return len(left) == len(right) and all(same_card(a, b) for a, b in zip(left, right))


class StorageTraversal:
    """用标定行号或唯一重叠拼接；缺行、歧义或数量变化时拒绝。"""

    def __init__(self):
        self.rows = []
        self.pages = 0

    def append(self, rows, *, at_bottom=False, row_start=None):
        if row_start is not None:
            # 三行分页没有完整重叠，由已标定的滚动距离和首行纵坐标确认行号。
            if type(row_start) is not int or not 0 <= row_start <= len(self.rows):
                raise StorageRecognitionError('三行分页出现缺行或无效行号')
            count = len(self.rows) - row_start
            if count > len(rows) or not all(same_targets(a, b)
                                           for a, b in zip(self.rows[row_start:], rows[:count])):
                raise StorageRecognitionError('仓库末页重叠物品或数量不一致')
            if count == len(rows) and not at_bottom:
                raise StorageNoProgressError('滚动后未出现新行')
            self.rows[row_start:] = rows
            self.pages += 1
            return
        if not self.rows:
            self.rows.extend(rows)
            self.pages += 1
            return
        overlaps = []
        for count in range(1, min(len(self.rows), len(rows)) + 1):
            if all(same_row(a, b) for a, b in zip(self.rows[-count:], rows[:count])):
                overlaps.append(count)
        if len(overlaps) != 1:
            raise StorageRecognitionError('滚动后重叠行缺失或有歧义，无法确认是否漏读')
        count = overlaps[0]
        if count == len(rows):
            if not at_bottom:
                raise StorageNoProgressError('滚动后未出现新行')
            # 最后一次短距离拖到底可能只移动空白，不产生新完整行。
            # 已确认到底且整页唯一重叠时，只记复读，不再次累计数量。
        # 保存刚经唯一重叠核对的图像，避免后续页一直与更早的虹彩/采样相位比较。
        # 身份和数量仍须完全一致；歧义、无进度等失败路径不能修改已读行。
        self.rows[-count:] = rows[:count]
        self.rows.extend(rows[count:])
        self.pages += 1


def same_targets(left, right):
    """已验证物理行位置后，只复核统计目标与空格；忽略非目标动画。"""
    return len(left) == len(right) and all(
        (a.present, a.identifier, a.amount) == (b.present, b.identifier, b.amount)
        for a, b in zip(left, right))


def is_purple(icon):
    """两个上角共同确认紫色，避免虹彩动画的单角恰好呈紫色。"""
    image = cv2.resize(icon, (96, 96), interpolation=cv2.INTER_AREA)
    corners = np.array([image[5:13, x:x + 8] for x in (5, 83)], dtype=np.int16)
    red, green, blue = np.moveaxis(corners, -1, 0)
    purple = (blue - green >= 35) & (np.abs(red - green) <= 22)
    # 图案可能覆盖少量背景；每角要求至少半数像素通过，不能混色取均值伪造紫色。
    return bool(np.all(purple.mean(axis=(1, 2)) >= .5))


def _same_calibration_card(left, right):
    """只为运动标定核对主体；不以此确认统计身份或替代完整数量。"""
    if same_card(left, right):
        return True
    if (not left.present or not right.present or left.identifier != right.identifier
            or left.identifier is not None):
        return False
    if np.max(np.abs(left.image[7:17, 7:17].mean(axis=(0, 1))
                     - right.image[7:17, 7:17].mean(axis=(0, 1)))) > 45:
        return False
    # 开扫标定没有数量读数。排除共同边框及数字后，严格核对去除低频虹彩的主体；
    # 后续还须至少五列同位移且所有候选位移唯一，重复图标不能自行决定行号。
    details = []
    for card in (left, right):
        gray = cv2.cvtColor(card.image, cv2.COLOR_RGB2GRAY).astype(np.float32)
        details.append(cv2.GaussianBlur(gray, (7, 7), 0) - cv2.GaussianBlur(gray, (31, 31), 0))
    score = cv2.minMaxLoc(cv2.matchTemplate(details[0][9:103, 9:119], details[1][12:100, 12:116],
                                          cv2.TM_CCOEFF_NORMED))[1]
    return score >= .985


def calibrate_scroll(before, after, thumb_delta):
    """以至少五列完整格的唯一位移标定比例，保留单格图像匹配门槛。"""
    if len(before) < 2:
        raise StorageRecognitionError('滚动条标定需要至少两行完整材料')
    pairs = [(a, b) for a in before for b in after
             if len(a) == len(b) == 7 and all(card.present for card in a + b)]
    offsets = [a[0].area[1] - b[0].area[1] for a, b in pairs
               if sum(same_card(left, right) for left, right in zip(a, b)) >= 5]
    if not offsets:
        # 整格已能确认位移时保留数量等细节，不能让相同图标排列制造额外歧义。
        offsets = [a[0].area[1] - b[0].area[1] for a, b in pairs
                   if sum(_same_calibration_card(left, right) for left, right in zip(a, b)) >= 5]
    if not offsets or max(offsets) - min(offsets) > 2 or thumb_delta <= 0:
        raise StorageRecognitionError('滚动条距离标定缺少唯一完整重叠行')
    pitch = float(round(np.median([b[0].area[1] - a[0].area[1] for a, b in zip(before, before[1:])])))
    moved = float(np.median(offsets))
    if not 156 <= pitch <= 190 or not .5 * pitch <= moved <= 2 * pitch:
        raise StorageRecognitionError('滚动条标定的行距或移动距离无效')
    return pitch, moved / thumb_delta


def recognize_rows(image, catalog, *, rows=None, target_only=False):
    if rows is None:
        rows = detect_rows(image)
    for row in rows:
        for card in row:
            if not card.present:
                continue
            if target_only and not catalog.is_target_rarity(card.image):
                continue
            card.identifier = catalog.identify(card.image, card.context)
            if card.identifier is not None:
                try:
                    card.amount = catalog.read_amount(card.image)
                except StorageRecognitionError as error:
                    raise StorageRecognitionError(f'{card.identifier}（位置 {card.area}）：{error}') from error
            elif not target_only:
                # 未登记物品的完整数量只帮助核对同一格，不进入统计或推断其身份。
                try:
                    card.comparison_amount = catalog.read_amount(card.image)
                except StorageRecognitionError:
                    pass
    return rows


def verify_targets(rows, reference, catalog):
    """稳定页面的后续帧只复核目标，横向轮廓允许 2px 抖动。"""
    if len(rows) != len(reference):
        raise StorageRecognitionError('同页完整行数变化')
    for row_index, (row, previous) in enumerate(zip(rows, reference), 1):
        if len(row) != len(previous):
            raise StorageRecognitionError('同页材料列数变化')
        for column_index, (card, old) in enumerate(zip(row, previous), 1):
            # 动画亮点会让边框横坐标波动；纵向位置仍必须完全一致，避免接受滚动中的画面。
            position_changed = (card.area[1::2] != old.area[1::2]
                                or any(abs(card.area[index] - old.area[index]) > 2 for index in (0, 2)))
            if position_changed or card.present != old.present:
                raise StorageRecognitionError(
                    f'同页材料位置或空格变化：第 {row_index} 行第 {column_index} 列，'
                    f'位置 {old.area} → {card.area}，存在 {old.present} → {card.present}')
            if old.identifier is not None:
                catalog.verify(card, old)
    return rows
