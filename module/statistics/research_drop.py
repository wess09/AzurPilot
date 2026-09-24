"""科研掉落解析。

从科研领奖时落盘的掉落记录中解析出「哪个科研项目产出了什么」，是科研统计的
数据入口，也是 WebUI 科研统计页的数据来源。

记录结构：一条掉落记录是一张 PNG，内含多帧（由 AzurStats.pack 垂直拼接）：
    - 第 0 帧：科研队列页，卡片上印着项目代号（如 D-737-MI）与系列角标（罗马数字）；
    - 第 1..n 帧：「获得道具」弹窗，是这次实际到手的东西。

**期数只看卡片上的罗马数字角标，不看项目代号**：同一个代号（G-531-MI、Q-051-MI…）
在每一期都存在，代号里没有期数信息。而掉落物也不能反推期数——只有彩装备与舰船图纸
是绑定期数的，金装备各期混着出（队列里还常常混着别期的「定向研发」项目）。
角标用 module/research/series.py 既有的 match_series 读，实测 896 张全对。

入口：
    record_research_drop() 由 AzurStats.commit() 在领奖时调用。
    模板库里缺某件物品时该物品会被跳过而不是记成乱码，
    补模板见 alas-research-stats 技能文档。
"""

import re
import typing as t
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from module.logger import logger

# 队列页卡片上的项目代号区域（1280x720 实测坐标）。
# 卡 3~5 因处于「等待进行」状态被半透明遮罩压暗而读不出来，但不影响结论：
# ALAS 是在点开第一个已完成项目领奖之前截的图，队列 FIFO，第 1 张卡即是刚完成的项目。
QUEUE_CARD_AREAS = (
    (55, 296, 232, 338),
    (288, 296, 468, 338),
    (545, 296, 715, 338),
    (782, 296, 955, 338),
    (1025, 296, 1190, 338),
)
# 卡 1 左上角的系列角标（罗马数字）区域。队列页的卡片是平的，没有透视缩放，
# 所以 scaling 固定 1.0（科研主页那 5 张卡是弧形排列，那套要按位置补缩放）。
# 区域比角标本身（35x26）留出余量：太贴边模板匹配会失败（实测裁到 40x36 就全读不出）。
SERIES_BADGE_AREA = (55, 118, 105, 160)
# 项目代号字表，与 module/research/project.py 的 OCR_RESEARCH 保持一致
RESEARCH_ALPHABET = '0123456789BCDEGHQTMIULRF-'
# 合法代号形如 D-737-MI
CODE_PATTERN = re.compile(r'^[A-Z0-9]-[0-9]{3}-[A-Z]{2}$')

ITEM_TEMPLATE_FOLDER = './assets/stats/research_items'

# 科研掉落的数量上限，只用于触发重识别（超限即认为读错）。
# 心智单元能到 100+，不能沿用大世界那边的 50 上限。
RESEARCH_AMOUNT_MAX = {'CognitiveChips': 300}
# 科研掉落的图纸（舰船图纸与全部装备图纸）一次都不超过 10 张。
# 超限即认为读错，交给 AmountOcr 重试并在仍超限时截断末位：
# 实测「真值 7 被读成 71」正是这样被修正回 7 的。
RESEARCH_SURE_MAX = 10
RESEARCH_SURE_PREFIXES = ('Blueprint',)
# 装备图纸的模板名以 _T<数字> 结尾，可能还带 _2/_3 变体后缀
RESEARCH_SURE_PATTERN = re.compile(r'_T\d+(_\d+)?$')


def research_amount_default_max(item_name: str) -> int:
    """科研掉落的默认数量上限。

    科研掉落的图纸只有舰船图纸（Blueprint*）与装备图纸（*_T<数字>）两类，
    一次都不超过 10 张；其余物品（心智单元、物资等）没有这个规律。

    Args:
        item_name (str): 物品模板名。

    Returns:
        int: 该物品的数量上限。
    """
    from module.statistics.item import DEFAULT_AMOUNT_MAX

    if item_name.startswith(RESEARCH_SURE_PREFIXES) or RESEARCH_SURE_PATTERN.search(item_name):
        return RESEARCH_SURE_MAX
    return DEFAULT_AMOUNT_MAX


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    """计算两串的编辑距离，超过 limit 时提前返回。

    Args:
        a (str): 字符串一。
        b (str): 字符串二。
        limit (int): 距离上限，超过即不再精确计算。

    Returns:
        int: 编辑距离；大于 limit 时返回 limit 以上的任意值。
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (char_a != char_b),
            ))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


@dataclass
class ResearchDrop:
    """一次科研领奖的解析结果。

    Attributes:
        project (str): 项目代号，如 'D-737-MI'；未能识别时为空串。
        series (int): 科研期数，1~9；未能识别时为 0。
        items (dict): {物品模板名: 数量}，如 {'BlueprintValparaiso': 1}。
    """

    project: str = ''
    series: int = 0
    items: t.Dict[str, int] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return bool(self.items)


class ResearchDropParser:
    """科研掉落记录解析器。

    加载一次模板库后复用，避免每次领奖都重新读 300 多个模板文件。

    Attributes:
        stats (GetItemsStatistics): 物品识别器，绑定到科研自己的物品网格。
        ocr (Ocr): 队列页项目代号识别器。
        lookup (dict): 项目代号 -> LIST_RESEARCH_PROJECT 条目。
    """

    def __init__(self):
        from module.base.button import Button
        from module.ocr.ocr import Ocr
        from module.research.project_data import LIST_RESEARCH_PROJECT
        from module.statistics.get_items import GetItemsStatistics
        from module.statistics.item import AmountOcr, ItemGrid

        Ocr.SHOW_LOG = False
        # 独立网格：科研有一套自己的物品模板，不能和战斗掉落共用全局网格，
        # 否则两边加载的模板会混在一起，且数量上限也按各自场景算。
        grid = ItemGrid(None, {}, template_area=(40, 21, 89, 70), amount_area=(60, 71, 91, 92))
        grid.load_template_folder(ITEM_TEMPLATE_FOLDER)
        grid.amount_max = dict(RESEARCH_AMOUNT_MAX)
        grid.amount_default_max = research_amount_default_max
        # 数量识别单独配一个开了碎片过滤的实例，不动全局 AMOUNT_OCR（战斗掉落那边的
        # 行为要原样保留）。科研的数量框紧挨物品图标，图标底部的白色纹理会被拼进数字：
        # 实测「图纸 1 张」被读成 71、超上限截断后又变成 7（六倍误差，14/14 复现），
        # 开过滤后读数与图上真值一致。委托收入与自律寻敌场景同样开着它。
        amount_ocr = AmountOcr([], threshold=96, name='RESEARCH_AMOUNT_OCR')
        amount_ocr.remove_fragments = True
        grid.amount_ocr = amount_ocr

        self.stats = GetItemsStatistics()
        self.stats.grid = grid
        self.ocr = Ocr(
            [Button(area=area, color=(255, 255, 255), button=area) for area in QUEUE_CARD_AREAS],
            threshold=64, alphabet=RESEARCH_ALPHABET, name='RESEARCH_QUEUE',
        )
        self.lookup = {project['name']: project for project in LIST_RESEARCH_PROJECT}

    def _correct_code(self, code: str) -> str:
        """把 OCR 出的项目代号纠正到合法代号。

        实测常见的单字母误读：I 被读成 T 或 L、D 被读成 O 或 1。
        只在编辑距离 1 以内接受纠正，避免把噪声串凑成某个项目。

        Args:
            code (str): OCR 原始结果。

        Returns:
            str: 纠正后的合法代号；无法确定时为空串。
        """
        if not CODE_PATTERN.match(code):
            return ''
        for name in self.lookup:
            if levenshtein(code, name, limit=1) <= 1:
                return name
        return ''

    def _read_project(self, image: np.ndarray) -> str:
        """从队列页读取本组掉落对应的科研项目代号。

        代号只用来记录「哪一次项目」，**不带期数信息**（同一个代号每期都有），
        期数一律走 `_read_series()`。

        Args:
            image (np.ndarray): 队列页截图。

        Returns:
            str: 项目代号；识别失败返回空串。
        """
        names = self.ocr.ocr(image)
        if not isinstance(names, list):
            names = [names]
        for raw in names:
            code = (raw or '').strip().upper()
            if not code:
                continue
            if code in self.lookup:
                return code
            fixed = self._correct_code(code)
            if fixed:
                logger.info(f'[科研统计] 项目代号 {code} 纠正为 {fixed}')
                return fixed
        logger.warning(f'[科研统计] 未能识别项目代号: {names}')
        return ''

    def _read_series(self, image: np.ndarray) -> int:
        """从队列页卡片 1 的角标读取科研期数。

        复用 module/research/series.py 的模板匹配（那里已经有 I~IX 的模板，
        本来是为科研主页的项目卡片写的）。

        Args:
            image (np.ndarray): 队列页截图。

        Returns:
            int: 期数 1~9；读不出来返回 0。
        """
        from module.base.utils import crop
        from module.research.series import match_series

        series = match_series(crop(image, SERIES_BADGE_AREA), scaling=1.0)
        if not series:
            logger.warning('[科研统计] 未能读出卡片角标的期数，本次记录不计入任何一期')
        return series

    def parse(self, images: t.Sequence[np.ndarray]) -> ResearchDrop:
        """解析一组科研掉落截图。

        Args:
            images (list): 掉落记录的各帧截图。

        Returns:
            ResearchDrop: 解析结果；完全无法识别时 items 为空。
        """
        from module.research.assets import QUEUE_CHECK
        from module.base.utils import load_image  # noqa: F401  保持与调用方一致的读图路径
        from module.statistics.utils import unpack

        drop = ResearchDrop()
        frames: t.List[np.ndarray] = []
        for image in images:
            try:
                frames.extend(unpack(image))
            except Exception as e:
                logger.warning(f'[科研统计] 跳过无法拆帧的截图: {e}')

        if not frames:
            return drop

        queue_page = None
        for frame in frames:
            if QUEUE_CHECK.match(frame, offset=(10, 10)):
                queue_page = frame
                break
        if queue_page is not None:
            drop.project = self._read_project(queue_page)
            drop.series = self._read_series(queue_page)
        else:
            logger.info('[科研统计] 本组截图没有队列页，只统计掉落物')

        seen = set()
        for frame in frames:
            if frame is queue_page:
                continue
            key = id(frame)
            if key in seen:
                continue
            seen.add(key)
            try:
                items = self.stats.stats_get_items(frame)
            except Exception:
                # 不是「获得道具」界面
                continue
            for item in items:
                if not item.is_known_item():
                    continue
                drop.items[item.name] = drop.items.get(item.name, 0) + item.amount

        return drop


_parser: t.Optional[ResearchDropParser] = None


def get_parser() -> ResearchDropParser:
    """取全局解析器实例（模板只加载一次）。

    Returns:
        ResearchDropParser: 解析器单例。
    """
    global _parser
    if _parser is None:
        _parser = ResearchDropParser()
    return _parser


def record_research_drop(images: t.Sequence[np.ndarray], instance: str, imgid: str = '') -> t.Optional[dict]:
    """解析一组科研掉落截图并写入本地库。

    Args:
        images (list): 掉落记录的各帧截图。
        instance (str): ALAS 实例名，统计按实例隔离。
        imgid (str): 掉落记录的文件名（时间戳），用于防止同一条记录重复入库。

    Returns:
        dict: 写入的条目；无有效掉落或重复时返回 None。
    """
    try:
        drop = get_parser().parse(images)
    except Exception as e:
        logger.warning(f'[科研统计] 解析失败，跳过本次记录: {e}')
        return None

    if not drop.valid:
        logger.info('[科研统计] 本次没有识别到已知物品，未入库')
        return None

    from module.statistics.cl1_database import db as cl1_db
    entry = cl1_db.add_research_drop(
        instance, drop.project, drop.series, drop.items, imgid=imgid)
    if entry is not None:
        detail = ', '.join(f'{name}x{amount}' for name, amount in drop.items.items())
        logger.info(f'[科研统计] {drop.project or "未知项目"} 记录入库: {detail}')
    return entry
