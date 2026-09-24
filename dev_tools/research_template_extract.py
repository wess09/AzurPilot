"""科研掉落模板提取工具。

从科研掉落截图目录中自动发现模板库缺失的物品，借助游戏 Lua 数据把 OCR
得到的中文标签还原成仓库命名规范的文件名，导出 96x96 素材与对照报告，
用于快速适配新一期科研。

典型用法：
    # 1. 只扫描，看看缺哪些（不写文件）
    uv run python -m dev_tools.research_template_extract \
        --folder <截图目录> --dry-run

    # 2. 导出素材与报告
    uv run python -m dev_tools.research_template_extract \
        --folder <screenshot_dir> \
        --folder <another_screenshot_dir> \
        --output ./log/research_templates

工作流程：
    截图 -> unpack 拆帧 -> 跳过队列页取收获帧 -> ItemGrid 模板匹配
      -> 未命中项收集「物品图像 + 中文标签 + 出现次数」
      -> 中文标签查 Lua 表得到英文名 -> 按仓库规范转文件名
      -> 导出 <名字>.png(96x96) + report.md + contact_sheet.png

命名规范（由 Lua 英文名推导，与 assets/stats/research_items/ 既有文件一致）：
    'T0 Twin 40mm Bofors STAAG Design'  -> Twin_40mm_Bofors_STAAG_T0
    'Prototype Tenrai T0 Design'        -> Prototype_Tenrai_T0
    'Blueprint - Orage'                 -> BlueprintOrage

注意事项：
    同一件道具在活动加成期会有不同底色（BONUS!/EVENT!/CATCHUP! 标记），
    ItemGrid 的颜色预筛选会把它们当成两件物品。仓库既有做法是存成多份
    模板（Xxx.png / Xxx_2.png / Xxx_3.png），Item.name 的 setter 会自动
    把数字后缀去掉，统计时仍归为同一件道具。本工具沿用这一约定。
"""

import argparse
import glob
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

import module.config.server as server


def _prescan_server() -> str:
    """在正式解析命令行前预读 --server。

    物品识别器在模块导入时就会读取 server 值，所以必须早于下面的 import。

    Returns:
        str: 服务器代号，缺省 'cn'。
    """
    argv = sys.argv
    for index, arg in enumerate(argv):
        if arg == '--server' and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith('--server='):
            return arg.split('=', 1)[1]
    return 'cn'


server.server = _prescan_server()

from dev_tools.utils import LuaLoader
from module.base.utils import crop_to_text, load_image, save_image
from module.logger import logger
from module.ocr.ocr import Ocr
from module.statistics.get_items import GetItemsStatistics, ITEM_GROUP
from module.statistics.utils import unpack

DEFAULT_TEMPLATE_FOLDER = './assets/stats/research_items'
# 模板名 -> 中文名/稀有度的静态表，供 WebUI 展示用，随模板一起提交
NAME_TABLE_PATH = './assets/stats/research_item_names.json'
# Lua 数据源候选路径，取第一个存在的。可用 --lua 显式指定。
LUA_FOLDER_CANDIDATES = (
    os.environ.get('ALAS_LUA_FOLDER', ''),
    '../AzurLaneLuaScripts',
    './AzurLaneLuaScripts',
)
LUA_REPO_URL = 'https://github.com/AzurLaneTools/AzurLaneLuaScripts'
# 物品标签在格子下方居中，左右各扩这么多像素。
# 相邻物品间距约 128px 而标签更宽，所以必然互相重叠，裁太宽会把邻居的字带进来。
LABEL_PAD_X = 65
LABEL_HEIGHT = 34
# 素材导出尺寸，与 assets/stats/research_items/ 一致
ITEM_SIZE = 96
# 与库内已有模板的相似度阈值。仓库里的模板名和 Lua 英文名并不总是一致
# （历史原因，例如 Type_99_Dive_Bomber_T3 vs Lua 的 Aichi D3A Type 99），
# 新素材若与某个已有模板足够像，说明是同一件（多半只是底色不同），
# 沿用既有名字既能避免错名，也顺带把底色变体归到同一名下。
LIBRARY_MATCH_SURE = 0.68
LIBRARY_MATCH_MAYBE = 0.58

# 采集口径的最低稀有度：4 = 金，5 = 彩
SCOPE_MIN_RARITY = 4
# 名字推导不出模板名的特例（没有 T 品阶后缀，规则覆盖不到）
SPECIAL_TEMPLATE_NAMES = {
    '心智单元': 'CognitiveChips',
}
# 少数物品在 Lua 的英文名里缺 'T0 Design' 后缀（如试作舰载型550mm鱼雷改），
# 由英文名推模板名的规则就失效了，中文名也进不了名称表——运行时只好显示模板名。
# 这几个按仓库命名约定手工补，写名称表时一并收录。
NAME_TABLE_OVERRIDES = {
    'Prototype_Triple_550mm_Improved_Ammo_Mod_Torpedo_Mount_T0': {
        'zh': '试作型三联装550mm鱼雷改（弹药调整）T0设计图',
        'en': 'Prototype Triple 550mm Improved (Ammo Mod) Torpedo Mount T0 Design',
        'rarity': 4,
    },
    # 库内名与 Lua 名差了实词（Standard 对 Performance），词元归一按规矩不能放这么松
    # （那样会把 40mm Bofors Type 5 认成 Hazemeyer）。游戏里 T0 火控雷达只此一件、
    # 库里也只有这一个 T0 火控雷达模板，所以手工补录。
    'High_Standard_Fire_Control_Radar_T0': {
        'zh': '高性能火控雷达T0设计图',
        'en': 'High Performance Fire Control Radar T0 Design',
        'rarity': 4,
    },
    # 心智单元与物资也没有 T 品阶后缀；它们是「心智/物资」口径里的两件物品，
    # 名称表里必须有中文名（稀有度取自 Lua：心智单元 4、物资 1）。
    'CognitiveChips': {
        'zh': '心智单元', 'en': 'Cognitive Chips', 'rarity': 4,
    },
    'Coins': {
        'zh': '物资', 'en': 'Coins', 'rarity': 1,
    },
}


def in_stats_scope(zh_name: str, rarity: Optional[int]) -> bool:
    """判断物品是否属于「金/彩图纸 + 心智单元」这一采集口径。

    统计只关心金/彩的装备图纸与舰船图纸，外加心智单元；紫蓝图纸、改造图纸、
    定向蓝图、物资等一律不补模板。模板库保持精简，识别结果也不会被杂项干扰。

    Args:
        zh_name (str): Lua 里的中文名，如 '试作型四联装533毫米鱼雷Si 270T0设计图'。
        rarity (int): Lua 里的稀有度；未知时传 None。

    Returns:
        bool: 是否属于该口径。
    """
    if not zh_name:
        return False
    if zh_name in SPECIAL_TEMPLATE_NAMES:
        return True
    if rarity is None or rarity < SCOPE_MIN_RARITY:
        return False
    # 装备图纸 = '...T0设计图'，舰船图纸 = '蓝图：XXX'。
    # 用 startswith 而不是 in，是为了把 '定向蓝图・七期'、'高级定向蓝图・二期'
    # 这类兑换券挡在外面——它们名字里也有「蓝图」，但不是掉落图纸。
    return zh_name.endswith('设计图') or zh_name.startswith('蓝图')


# 每期的彩装设计图（2~9 期各一件）。这份名单来自用户；Lua 里只有八期那件出现在
# 项目的 drop_client 中（其余彩装用通用占位符发放），所以只能手工登记。
RAINBOW_DESIGN_SERIES = {
    13012: 2, 13019: 3, 13030: 4, 13031: 5, 13038: 6, 13043: 7, 13049: 8, 13061: 9,
}


def load_item_series(folder: str) -> Dict[int, int]:
    """物品 id -> 科研期数，供名称表记录「这件物品属于哪一期」。

    只收**绑期数**的两类：船图纸（`蓝图：XXX`）与彩装图纸（2~9 期各一件）。
    金装备图纸虽然也在各期的 drop_client 里，但实际掉落是各期混着出的，
    登记期数只会让人误以为它属于某一期，所以不收。

    船图纸与 1~8 期大部分装备图纸的来源是 `sharecfg/technology_data_template.lua`
    各期项目的 `drop_client`（项目的 `blueprint_version` 就是期数）；
    彩装图纸不在里面（用通用占位符发放），期数取自 RAINBOW_DESIGN_SERIES。

    Args:
        folder (str): Lua 数据源目录。

    Returns:
        dict: {物品 id: 期数}；只在能唯一确定期数时收录。
    """
    try:
        tech = LuaLoader(folder, server='zh-CN').load('sharecfg/technology_data_template.lua')
        items = LuaLoader(folder, server='zh-CN').load('sharecfgdata/item_data_statistics.lua')
    except Exception as e:
        logger.warning(f'[科研模板] 读取科研项目表失败，名称表将不带期数: {e}')
        return {}
    found: Dict[int, set] = {}
    for key, value in tech.items():
        if key == 'all':
            continue
        series = int(value.get('blueprint_version', 0) or 0)
        for entry in value.get('drop_client', {}).values():
            iid = list(entry.values())[1]
            if iid == 1:
                iid = 59001  # 物资在项目表里记作 1，物品表里是 59001
            if not (items.get(iid, {}).get('name') or '').startswith('蓝图'):
                continue
            found.setdefault(iid, set()).add(series)
    series_by_id = {}
    for iid, series in found.items():
        # 一条船图纸会出现在多期的 drop_client 里——科研项目会「额外赠送」别期的图纸
        # （用户确认过这个机制，有上限）。赠礼只会指向更早的期，所以取最小期数即它本尊的期。
        series_by_id[iid] = min(series)
    series_by_id.update(RAINBOW_DESIGN_SERIES)
    return series_by_id


# 少数舰船的中文名是 {namecode:XXX} 占位符（见 resolve_ship_placeholder），
# 正常路径已能还原；这里的别名只在标签被截断得只剩两字时兜底。
# 别名用 2 字前缀，因为标签常缺字成「马克其」「古图：马克」。
BLUEPRINT_ZH_ALIASES = {
    '高梁': 'Takahashi',
    '马克': 'Max Immelmann',
}


def ascii_fold(text: str) -> str:
    """把带变音符号的拉丁字母折成纯 ASCII。

    Args:
        text (str): 原始文本，如 'Valparaíso'。

    Returns:
        str: 折迭结果，如 'Valparaiso'。
    """
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')


def fold_text(text: str) -> str:
    """折成小写纯 ASCII，用于跨语言的名称比对。

    Args:
        text (str): 原始文本。

    Returns:
        str: 只含小写字母与数字的串。
    """
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', text.lower())


def name_tokens(text: str, loose: bool = False) -> frozenset:
    """把名称拆成词集合，用于跨命名风格的匹配。

    仓库里的模板名和 Lua 英文名常常词序不同、多一个 Mount/Mark 之类的词，
    例如 533mm_Quadruple_Torpedo_Mount_T3 对 T3 Quadruple 533mm Torpedo Design。
    按词集合比对比按字符串比对宽容得多。品阶标记（T0/T3）保留，
    否则 T2/T3 两个版本会撞在一起。

    loose=True 再放松一档：忽略大小写、丢掉 Mount 这类通用词，并归一已知的拼写差异
    （Reppuu/Reppu）。实测库里 144 个老模板名因此对不上 Lua 名，其中 36 个能这样唯一对回，
    它们的稀有度也就进得了名称表（没有稀有度的物品在任何视图里都是隐形的）。
    只放开到这一步：再松就会把 40mm Bofors Type 5 认成 Hazemeyer 这类近邻。

    Args:
        text (str): 名称文本。
        loose (bool): 是否忽略通用词与大小写、拼写差异。

    Returns:
        frozenset: 词集合；无法解析时为空集。
    """
    text = re.sub(r'\bdesign\b', ' ', (text or '').lower())
    if loose:
        # 先把下划线换成空格：模板名是下划线分隔的，而 `_` 在正则里算词字符，
        # 直接对 'gun_mount_t0' 跑 \bmount\b 是匹配不上的（踩过：36 个候选只对上 8 个）。
        text = text.replace('_', ' ').replace('reppuu', 'reppu')
        text = re.sub(r'\bmount\b', ' ', text)
    return frozenset(re.findall(r'[a-z0-9]+', text))


def to_template_name(en_name: str) -> str:
    """把游戏英文物品名转成仓库模板文件名。

    Args:
        en_name (str): Lua 数据里的英文名，如 'T0 Twin 40mm Bofors STAAG Design'。

    Returns:
        str: 仓库命名，如 'Twin_40mm_Bofors_STAAG_T0'；无法解析时返回空串。

    Examples:
        >>> to_template_name('T0 Twin 40mm Bofors STAAG Design')
        'Twin_40mm_Bofors_STAAG_T0'
        >>> to_template_name('Prototype Tenrai T0 Design')
        'Prototype_Tenrai_T0'
        >>> to_template_name('Blueprint - Orage')
        'BlueprintOrage'
    """
    name = ascii_fold(en_name.strip())

    # 舰船蓝图：Blueprint - <ShipName>
    if name.startswith('Blueprint - '):
        ship = re.sub(r'[^A-Za-z0-9]', '', name[len('Blueprint - '):])
        return f'Blueprint{ship}' if ship else ''

    # 装备图纸：T<n> 可能在开头（'T0 Xxx Design'）或结尾（'Xxx T0 Design'）
    match = re.match(r'^T(\d)\s+(.+?)(?:\s+Design)?$', name)
    if match:
        tier, body = match.group(1), match.group(2)
    else:
        match = re.match(r'^(.+?)\s+T(\d)(?:\s+Design)?$', name)
        if not match:
            return ''
        body, tier = match.group(1), match.group(2)

    body = re.sub(r'[^A-Za-z0-9]+', '_', body).strip('_')
    return f'{body}_T{tier}' if body else ''


def load_ship_names() -> Dict[str, str]:
    """读舰船数据表的「归一化英文名 -> 中文名」对照。

    少数舰船在 Lua 的 zh-CN 里是 {namecode:XXX} 占位符，舰船数据表里有完整的中英对照。

    Returns:
        dict: fold_text(英文名) -> 中文名。
    """
    path = './assets/ship/ship_data.json'
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            ships = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    variants = {}
    for entry in ships.values():
        names = entry.get('name') or {}
        en_name = (names.get('en') or '').strip()
        zh_name = (names.get('cn') or '').strip()
        if not en_name or not zh_name:
            continue
        # 同一条船的 μ兵装/改 等变体与本体共用英文名，优先收本体
        if '(' in zh_name or '（' in zh_name:
            variants.setdefault(fold_text(en_name), zh_name)
            continue
        out.setdefault(fold_text(en_name), zh_name)
    for key, zh_name in variants.items():
        out.setdefault(key, zh_name)
    return out


def resolve_ship_placeholder(zh_name: str, en_name: str, ships: Dict[str, str]) -> str:
    """把 {namecode:XXX} 占位符换成真实中文名。

    Args:
        zh_name (str): Lua 的中文名，可能含占位符。
        en_name (str): Lua 的英文名，蓝图形如 'Blueprint - Max Immelmann'。
        ships (dict): 舰船数据表的英文名 -> 中文名对照。

    Returns:
        str: 可展示的中文名；查不到时原样返回。
    """
    if not zh_name or 'namecode' not in zh_name:
        return zh_name
    ship = en_name.split(' - ', 1)[-1] if ' - ' in en_name else ''
    hit = ships.get(fold_text(ship))
    if not hit:
        return zh_name
    return f'蓝图：{hit}' if zh_name.startswith('蓝图') else hit


def find_lua_folder(explicit: Optional[str] = None) -> str:
    """定位游戏 Lua 数据源目录。

    Args:
        explicit (str): 命令行显式指定的路径，优先使用。

    Returns:
        str: 存在的目录路径；都找不到返回空串。
    """
    for folder in (explicit, *LUA_FOLDER_CANDIDATES):
        if folder and os.path.isdir(folder):
            return folder
    return ''


class LuaItemNames:
    """游戏物品中英文名对照表，数据来自解密后的 Lua 脚本。

    Attributes:
        folder (str): Lua 数据源目录。
        by_zh (dict): 中文名 -> (id, 英文名)。
        candidates (list): 全部 (id, 英文名, 中文名)，供前缀搜索。
    """

    def __init__(self, folder: str):
        """
        Args:
            folder (str): Lua 数据源目录，需包含 sharecfgdata/item_data_statistics.lua。
        """
        self.folder = folder
        zh = LuaLoader(folder, server='zh-CN').load('sharecfgdata/item_data_statistics.lua')
        en = LuaLoader(folder, server='en-US').load('sharecfgdata/item_data_statistics.lua')
        # 索引前先把 {namecode:XXX} 还原成真实译名：截图标签上写的是译名（「蓝图：大山」），
        # 而 Lua 里存的是占位符（「蓝图：{namecode:299}」）。不还原就一个候选都搜不到，
        # 实测九期的高梁/马克斯、七期的大山、六期的兴登堡/菲利克斯·舒尔茨全是这种。
        ships = load_ship_names()
        self.by_zh: Dict[str, Tuple[str, str]] = {}
        self.candidates: List[Tuple[str, str, str]] = []
        for item_id, data in zh.items():
            zh_name = (data.get('name') or '').strip()
            en_name = (en.get(item_id, {}).get('name') or '').strip()
            if not zh_name:
                continue
            zh_name = resolve_ship_placeholder(zh_name, en_name, ships)
            self.by_zh.setdefault(zh_name, (item_id, en_name))
            self.candidates.append((item_id, en_name, zh_name))
        # 模板名 -> (稀有度, 英文名, 中文名)。稀有度是分辨彩/金的唯一可靠依据：
        # 名字前缀靠不住（'试作型三联装203mmSKC主炮T0' 是金，加个「改」才是彩）。
        self.by_template: Dict[str, Tuple[int, str, str]] = {}
        self.by_template_id: Dict[str, int] = {}
        for item_id, data in zh.items():
            en_name = (en.get(item_id, {}).get('name') or '').strip()
            template = to_template_name(en_name)
            if template:
                self.by_template.setdefault(template, (
                    data.get('rarity'), en_name, (data.get('name') or '').strip()))
                self.by_template_id.setdefault(template, item_id)
        # 物品 id -> 科研期数，写名称表时带上，供「每期收益」按固定清单展示
        self.series_by_id = load_item_series(folder)
        logger.info(f'[科研模板] 加载 Lua 物品名 {len(self.candidates)} 条，'
                    f'带期数的 {len(self.series_by_id)} 件')

    @staticmethod
    def _rank(hits: List[Tuple[str, str, str]], text: str = '') -> List[Tuple[str, str]]:
        """给命中的候选排序：先按数字命中数，再按名字长度。

        口径数字（152mm / 533mm）OCR 比汉字可靠得多，是区分同族装备的强特征，
        所以数字命中的候选优先；同分时名字越短越可能是本尊。

        Args:
            hits (list): [(id, 英文名, 中文名), ...]
            text (str): 原始标签文本，用于提取数字特征。

        Returns:
            list[tuple]: [(英文名, 中文名), ...]
        """
        # 口径几乎都是 3 位；'3801' 取 '380' 才能对上，且避免 'B-38' 的 '38' 混进来
        numbers = LuaItemNames._extract_numbers(text)

        def sort_key(item):
            zh_name = item[2]
            cand = LuaItemNames._extract_numbers(zh_name)
            exact = sum(1 for a in numbers if a in cand)
            fuzzy = sum(1 for a in numbers for b in cand if a in b or b in a)
            return (-exact, -fuzzy, len(zh_name))

        hits = sorted(hits, key=sort_key)
        return [(en_name, zh_name) for _, en_name, zh_name in hits]

    def search_by_zh(self, text: str) -> Tuple[List[Tuple[str, str]], bool]:
        """从带噪声的中文标签里搜出候选物品。

        截图里的标签会被相邻物品挤压，中文 OCR 也常认错字，所以不能要求
        整串匹配。这里按「连续中文片段 -> 逐步截短 -> 字符重叠率」三级降级。

        Args:
            text (str): OCR 得到的标签文本，可能含噪声字符。

        Returns:
            tuple: (候选列表, 是否精确命中)。第二项为 False 表示只靠模糊匹配兜到
                候选，标签信息不足以断定是哪一件，调用方不应据此给出文件名建议。
        """
        chunks = sorted(re.findall(r'[一-鿿]{2,}', text), key=len, reverse=True)
        if not chunks:
            return [], False

        # 零级：标签里的拉丁型号（VIT-2 / BF-109G）在英文名里直接定位
        latin = [t for t in re.findall(r'[A-Za-z][A-Za-z0-9]*[-]?[A-Za-z0-9]*', text) if len(t) >= 3]
        for token in sorted(latin, key=len, reverse=True):
            hits = [c for c in self.candidates if token.lower() in c[1].lower()]
            if hits:
                return self._rank(hits, text), True

        # 一级：片段整串命中。命中一族（'三联装' 能命中几十个）不算结论，
        # 必须靠数字/型号筛到唯一一个才敢给建议名。
        # 同一个标签会切出多段（'蓝图：大山' -> ['蓝图', '大山']），要挑最有信息量的那段：
        # '蓝图' 能命中好几百件，'大山' 只命中一件，拿前者排名等于瞎猜。
        best: Optional[Tuple[str, List[Tuple[str, str, str]]]] = None
        for chunk in chunks:
            hits = [c for c in self.candidates if chunk in c[2]]
            if hits and (best is None or len(hits) < len(best[1])):
                best = (chunk, hits)
        if best is not None:
            ranked = self._rank(best[1], text)
            return ranked, (len(best[1]) == 1 or self._narrow_to_one(text, best[1]))

        # 二级：逐步截短，容忍尾部噪声
        for chunk in chunks:
            for size in range(len(chunk) - 1, 2, -1):
                hits = [c for c in self.candidates if chunk[:size] in c[2]]
                if hits:
                    return self._rank(hits, text), True

        # 三级：最长公共子串，容忍 OCR 错字（'式作型' vs '试作型'）。
        # 用子串而不是字符集重叠，是因为字符集分不出 '作型四联' 该配四联装还是三联装。
        scored = []
        for _, en_name, zh_name in self.candidates:
            common = self._longest_common_substring(text, zh_name)
            if common >= 3:
                scored.append((-common, len(zh_name), en_name, zh_name))
        scored.sort()
        return [(en_name, zh_name) for _, _, en_name, zh_name in scored[:20]], False

    @staticmethod
    def _extract_numbers(text: str) -> List[str]:
        """提取口径数字。

        口径几乎都是 3 位（152mm / 533mm），优先取 3 位可以避开 'B-38' 切出 '38'
        这类噪声；没有 3 位时（55mm 防空）再退到 2 位。

        Args:
            text (str): 中文名或标签文本。

        Returns:
            list[str]: 数字串列表。
        """
        return re.findall(r'\d{3}', text) or re.findall(r'\d{2}', text)

    @staticmethod
    def _narrow_to_one(text: str, hits: List[Tuple[str, str, str]]) -> bool:
        """判断标签里的数字/型号能否把候选筛到唯一一个。

        Args:
            text (str): 原始标签文本。
            hits (list): 一级匹配命中的候选 [(id, 英文名, 中文名), ...]。

        Returns:
            bool: True 表示能唯一定位。
        """
        numbers = LuaItemNames._extract_numbers(text)
        latin = [t for t in re.findall(r'[A-Za-z][A-Za-z0-9]*', text) if len(t) >= 3]
        if not numbers and not latin:
            return False
        matched = 0
        for _, en_name, zh_name in hits:
            blob = f'{zh_name} {en_name} {' '.join(LuaItemNames._extract_numbers(zh_name))}'
            if all(n in blob for n in numbers) and all(t.lower() in en_name.lower() for t in latin):
                matched += 1
                if matched > 1:
                    return False
        return matched == 1

    @staticmethod
    def _longest_common_substring(a: str, b: str) -> int:
        """求两串的最长公共子串长度（滚动数组，避免构造完整 DP 表）。

        Args:
            a (str): 标签文本。
            b (str): 候选中文名。

        Returns:
            int: 最长公共子串长度。
        """
        if not a or not b:
            return 0
        prev = [0] * (len(b) + 1)
        best = 0
        for char_a in a:
            cur = [0] * (len(b) + 1)
            for index, char_b in enumerate(b):
                if char_a == char_b:
                    cur[index + 1] = prev[index] + 1
                    if cur[index + 1] > best:
                        best = cur[index + 1]
            prev = cur
        return best

    def _guess_blueprint(self, ship: str) -> Tuple[str, List[str]]:
        """由船名片段推测蓝图模板文件名。

        Args:
            ship (str): 中文船名片段，可能带噪声或缺字。

        Returns:
            tuple: (建议文件名, 备选列表)。
        """
        # 别名表优先：这些船在 Lua 里是 {namecode:XXX} 占位符
        for zh_alias, en_ship in BLUEPRINT_ZH_ALIASES.items():
            if zh_alias in ship or ship in zh_alias:
                return f'Blueprint{en_ship.replace(" ", "")}', []

        for _, en_name, zh_name in self.candidates:
            if en_name.startswith('Blueprint - ') and ship in zh_name:
                return to_template_name(en_name), []

        # 缺字/错字降级：逐级截短
        # 不许退到单字：'马' 会命中文不对题的 '蓝图：马可波罗'
        for size in range(len(ship) - 1, 1, -1):
            for _, en_name, zh_name in self.candidates:
                if en_name.startswith('Blueprint - ') and ship[:size] in zh_name:
                    return to_template_name(en_name), []
        return '', []

    def guess_template_name(self, label_text: str) -> Tuple[str, List[str], bool]:
        """由截图中文标签推测模板文件名。

        蓝图类名字唯一，直接确定；装备类可能命中多个候选（标签被相邻物品
        挤压、OCR 错字），全部列出交给人工判断。

        Args:
            label_text (str): OCR 得到的中文标签。

        Returns:
            tuple: (建议文件名, 备选文件名列表, 是否精确)。第三项为 False 时名字只是
                一族里排名最靠前的那个，必须人工对照 contact_sheet 确认后再入库。
        """
        clean = re.sub(r'[^一-鿿]', '', label_text)
        if not clean:
            return '', [], False

        # 蓝图标签形如 '蓝图：高梁'；被挤压时可能缺字成 '图：暴风雨'，
        # 或多出左侧邻居的残字成 '梁蓝图：邓肯'，所以用包含关系而非前缀判断。
        if '蓝图' in clean:
            ship = clean.split('蓝图', 1)[1]
        elif clean[:1] == '图' or clean[1:2] == '图':
            ship = clean.split('图', 1)[1]
        else:
            ship = ''
        if ship:
            name, alternatives = self._guess_blueprint(ship)
            return name, alternatives, bool(name)

        hits, exact = self.search_by_zh(label_text)
        names = []
        for en_name, zh_name in hits:
            # 心智单元没有 T 品阶后缀，命名规则推不出名字，走特例表
            name = to_template_name(en_name) or SPECIAL_TEMPLATE_NAMES.get(zh_name, '')
            if name and name not in names:
                names.append(name)
        if not names:
            return '', [], False
        # 模糊命中时仍给排名第一的建议名（绝大多数情况是对的），但把整族候选列出
        # 并标记待确认：错一个名字会污染模板库，宁可让人多看一眼。
        return names[0], (names[1:6] if exact else names[:6]), exact


@dataclass
class MissingItem:
    """一个模板库未覆盖的物品。

    Attributes:
        key (str): 扫描期内的临时编号（ItemGrid 自动分配）。
        image (np.ndarray): 96x96 的物品图，直接对应模板文件的像素内容。
        label (np.ndarray): 中文标签截图，可能被相邻物品挤压。
        count (int): 出现次数。
        first_file (str): 首次出现的截图文件名。
        label_text (str): 标签 OCR 结果，扫描结束后回填。
        suggestion (str): 推测的模板文件名，扫描结束后回填。
        alternatives (list): 其他候选文件名，供人工判断。
        zh_name (str): 学名（Lua 里的中文名），用于判断采集口径。
    """

    key: str
    image: np.ndarray
    label: np.ndarray
    count: int = 0
    first_file: str = ''
    label_text: str = ''
    suggestion: str = ''
    alternatives: List[str] = None
    needs_review: bool = True
    rarity: Optional[int] = None
    zh_name: str = ''
    library_score: float = 0.0


class ResearchTemplateScanner:
    """科研掉落模板缺失扫描器。

    扫描截图目录，用现有模板库匹配收获帧，把未命中的物品收集起来，
    结合 Lua 数据给出命名建议。

    Attributes:
        template_folder (str): 现有模板库目录。
        stats (GetItemsStatistics): 复用仓库既有的物品识别器。
        lua (LuaItemNames): 名称对照表，可为 None（此时不做命名推测）。
    """

    def __init__(self, template_folder: str = DEFAULT_TEMPLATE_FOLDER,
                 lua_folder: Optional[str] = None):
        """
        Args:
            template_folder (str): 现有模板库目录。
            lua_folder (str): Lua 数据源目录，None 表示自动探测。
        """
        Ocr.SHOW_LOG = False
        self.template_folder = template_folder
        self.stats = GetItemsStatistics()
        self.stats.load_template_folder(template_folder)
        self._known_templates = set(ITEM_GROUP.templates.keys())
        # 库内模板的 49x49 裁剪图，用于判断新素材是不是某件已有道具的新底色
        self._library = {
            name: ITEM_GROUP.templates[name]
            for name in self._known_templates if not name.isdigit()
        }
        self.lua: Optional[LuaItemNames] = None
        folder = find_lua_folder(lua_folder)
        if folder:
            try:
                self.lua = LuaItemNames(folder)
            except Exception as e:
                logger.warning(f'[科研模板] Lua 数据加载失败，跳过命名推测: {e}')
        else:
            logger.warning('[科研模板] 未找到 Lua 数据源，跳过命名推测。'
                           f'用 --lua 指定，或设 ALAS_LUA_FOLDER；'
                           f'数据源可从 {LUA_REPO_URL} 取得')
        self.items: Dict[str, MissingItem] = {}
        self.frames_scanned = 0
        self.files_scanned = 0

    def scan_file(self, file: str) -> int:
        """扫描单个截图文件的所有收获帧。

        Args:
            file (str): 截图文件路径。

        Returns:
            int: 本文件新增的未命中物品数。
        """
        try:
            frames = unpack(load_image(file))
        except Exception as e:
            logger.warning(f'[科研模板] 跳过无法读取的截图 {file}: {e}')
            return 0

        self.files_scanned += 1
        added = 0
        # 第 0 帧是队列列表页，收获从第 1 帧开始
        for frame in frames[1:]:
            self.frames_scanned += 1
            try:
                self.stats._stats_get_items_load(frame)
                ITEM_GROUP._load_image(frame)
            except Exception:
                # 不是「获得道具」界面，跳过
                continue
            for item in ITEM_GROUP.items:
                key = str(ITEM_GROUP.match_template(item.image))
                if not key.isdigit():
                    continue  # 命中已知模板
                if key in self.items:
                    self.items[key].count += 1
                    continue
                self.items[key] = MissingItem(
                    key=key,
                    image=item.image.copy(),
                    label=self._crop_label(frame, item),
                    count=1,
                    first_file=os.path.basename(file),
                )
                added += 1
        return added

    @staticmethod
    def _crop_label(frame: np.ndarray, item) -> np.ndarray:
        """裁出物品下方的中文标签。

        Args:
            frame (np.ndarray): 收获帧截图。
            item (Item): ItemGrid 识别出的物品。

        Returns:
            np.ndarray: 标签区域图像；越界时返回空图。
        """
        x1, _, x2, y2 = item._button.area
        center = (x1 + x2) // 2
        left = max(0, center - LABEL_PAD_X)
        right = min(frame.shape[1], center + LABEL_PAD_X)
        top = min(frame.shape[0], y2 - 2)
        bottom = min(frame.shape[0], y2 + LABEL_HEIGHT)
        if bottom <= top or right <= left:
            return np.zeros((4, 4, 3), np.uint8)
        return frame[top:bottom, left:right].copy()

    def _match_library(self, image) -> Tuple[str, float]:
        """把新素材与库内已有模板比相似度。

        Args:
            image (np.ndarray): 96x96 的物品图。

        Returns:
            tuple: (最像的库内模板名, 相似度)；库为空时返回 ('', 0.0)。
        """
        if not self._library:
            return '', 0.0
        target = cv2.matchTemplate
        probe = image[21:70, 40:89]
        best_name, best_score = '', 0.0
        for name, template in self._library.items():
            score = float(target(probe, template, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best_name, best_score = name, score
        return best_name, best_score

    def resolve_names(self):
        """批量 OCR 标签并推测模板文件名。"""
        if not self.items:
            return

        ocr = Ocr([], lang='cnocr', letter=(255, 255, 255), threshold=100, name='LABEL')
        batch = [self.items[key].label for key in self.items]
        try:
            images = [crop_to_text(ocr.pre_process(img)) for img in batch]
            results = ocr.cnocr.atomic_ocr_for_single_lines(images, ocr.alphabet)
            texts = [''.join(result) for result in results]
        except Exception as e:
            logger.warning(f'[科研模板] 标签 OCR 失败: {e}')
            return

        for key, text in zip(self.items, texts):
            entry = self.items[key]
            entry.label_text = (text or '').strip()
            entry.alternatives = []

            # 库内同款优先级最高：同一件道具换个底色出现时，直接沿用既有命名
            library_name, score = self._match_library(entry.image)
            if library_name and score >= LIBRARY_MATCH_MAYBE:
                # 库内名可能带 _2/_3 变体后缀，那只表示"它是第 N 份模板"。
                # 新素材要接着往后排，所以剥掉后缀只留基名，交给 dedupe 统一分配。
                base, _, suffix = library_name.rpartition('_')
                if base and suffix.isdigit():
                    library_name = base
                entry.suggestion = library_name
                entry.library_score = round(score, 3)
                entry.needs_review = score < LIBRARY_MATCH_SURE
                logger.info(f'[科研模板] {key} 与库内 {library_name} 相似度 {score:.3f}，沿用该命名')
                continue

            if self.lua is not None and entry.label_text:
                suggestion, others, exact = self.lua.guess_template_name(entry.label_text)
                entry.suggestion = suggestion
                entry.alternatives = others
                entry.needs_review = not exact
            if self.lua is not None:
                hit = self.lua.by_template.get(entry.suggestion)
                if hit is not None:
                    entry.rarity = hit[0]
                    entry.zh_name = hit[2]

    def keep_scope(self) -> List[str]:
        """按采集口径裁剪缺口列表，原地删除不相关的条目。

        Returns:
            list[str]: 被丢弃的条目名，供日志说明。
        """
        dropped = []
        for key in list(self.items):
            entry = self.items[key]
            if in_stats_scope(entry.zh_name, entry.rarity):
                continue
            dropped.append(entry.suggestion or f'unknown_{key}')
            del self.items[key]
        return dropped

    def _reserved_indices(self) -> Dict[str, int]:
        """统计库内已有名字占用的最大后缀。

        同一件道具换了底色（活动加成期的 BONUS!/EVENT! 标记）会出现颜色预筛选
        拦不住的新变体，这时它确实需要新素材，但绝不能覆盖库里已有的那份——
        所以要接着既有后缀往后排。

        Returns:
            dict: 基名 -> 已被占用的最大后缀（无后缀记为 1）。
        """
        reserved: Dict[str, int] = {}
        if not os.path.isdir(self.template_folder):
            return reserved
        for filename in os.listdir(self.template_folder):
            stem = os.path.splitext(filename)[0]
            base, _, suffix = stem.rpartition('_')
            if base and suffix.isdigit():
                reserved[base] = max(reserved.get(base, 1), int(suffix))
            else:
                reserved[stem] = max(reserved.get(stem, 0), 1)
        return reserved

    def dedupe_suggestions(self) -> Dict[str, int]:
        """给同一命名建议的多个模板分配 _2 / _3 后缀。

        Returns:
            dict: 临时编号 -> 最终文件名（不含扩展名）。
        """
        used = self._reserved_indices()
        final: Dict[str, int] = {}
        for key in sorted(self.items, key=lambda k: int(k)):
            entry = self.items[key]
            base = entry.suggestion or f'unknown_{key}'
            seen = used.get(base, 0) + 1
            used[base] = seen
            final[key] = seen
        names = {}
        for key in sorted(self.items, key=lambda k: int(k)):
            entry = self.items[key]
            base = entry.suggestion or f'unknown_{key}'
            index = final[key]
            names[key] = base if index == 1 else f'{base}_{index}'
        return names

    def export(self, output: str) -> Tuple[List[str], str]:
        """导出素材、对照图与报告。

        Args:
            output (str): 输出目录。

        Returns:
            tuple: (写出的文件路径列表, Markdown 报告文本)。
        """
        os.makedirs(output, exist_ok=True)
        # 上次运行的残留会让新旧编号混在一个目录里，先清掉。
        # 只清 unknown_ 前缀：本工具在 Lua 数据缺失时才会产出这种名字。
        for stale in glob.glob(os.path.join(output, 'unknown_*.png')):
            try:
                os.remove(stale)
            except OSError:
                pass
        names = self.dedupe_suggestions()
        written = []

        for key in sorted(self.items, key=lambda k: int(k)):
            entry = self.items[key]
            path = os.path.join(output, f'{names[key]}.png')
            # 必须用 save_image(PIL) 而不是 cv2.imencode：后者按 BGR 语义把数据
            # 转成 RGB 存进 PNG，而库内既有模板是 PIL 原样存的，两条路产出的
            # 通道相反，新模板会永远匹配不上（实测相似度只有 0.49）。
            save_image(entry.image, path)
            written.append(path)

        sheet = os.path.join(output, 'contact_sheet.png')
        self._save_contact_sheet(sheet, names)
        written.append(sheet)

        self.write_name_table(names)

        report = self._build_report(names)
        report_path = os.path.join(output, 'report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        written.append(report_path)

        logger.info(f'[科研模板] 已导出 {len(written)} 个文件到 {output}')
        return written, report

    def write_name_table(self, exported: Dict[str, int] = None):
        """把模板名 -> 中文名/稀有度写成仓库资源。

        前端展示要用中文名，但运行时不该依赖 Lua 数据源（用户机器上不一定有），
        所以在这里离线生成一份静态表随模板一起提交。缺 Lua 时跳过，不破坏已有表。

        Args:
            exported (dict): 本次导出的「临时编号 -> 文件名」，它们即将入库，
                表里要一并收录，否则会漏掉刚补的那批。

        Returns:
            None
        """
        if self.lua is None:
            return
        ships = self._load_ship_names()
        # 词集合索引，兜住词序不同/多一个词/大小写与拼写差异的命名风格。
        # 同一组词对应多件物品时按有歧义丢弃——宁可留空显示模板名，也不要认错给错稀有度。
        by_tokens = {}
        ambiguous = set()
        for template, (rarity, en_name, zh_name) in self.lua.by_template.items():
            tokens = name_tokens(template, loose=True)
            if not tokens:
                continue
            if tokens in by_tokens:
                ambiguous.add(tokens)
                continue
            by_tokens[tokens] = (rarity, en_name, zh_name)
        for tokens in ambiguous:
            by_tokens.pop(tokens, None)

        stems = {os.path.splitext(name)[0] for name in os.listdir(self.template_folder)
                 if name.lower().endswith('.png')}
        if exported:
            stems.update(exported.values())

        table = {}
        for stem in sorted(stems):
            base, _, suffix = stem.rpartition('_')
            key = base if base and suffix.isdigit() else stem

            hit = self.lua.by_template.get(key)
            if hit is not None:
                rarity, en_name, zh_name = hit
            elif key in NAME_TABLE_OVERRIDES:
                # 英文名缺品阶后缀的少数物品，Lua 推不出来，走手工补录
                table[stem] = dict(NAME_TABLE_OVERRIDES[key])
                continue
            else:
                # 词集合归一后兜底：老模板名与 Lua 名只差词序/大小写/多一个 Mount 时靠这里对上，
                # 稀有度一并取到——没有稀有度的物品在任何视图里都是隐形的。
                tokens = name_tokens(key, loose=True)
                fallback = by_tokens.get(tokens)
                if fallback is None:
                    continue
                rarity, en_name, zh_name = fallback

            zh_name = self._resolve_namecode(zh_name, en_name, ships)
            if zh_name:
                entry = {'zh': zh_name, 'en': en_name, 'rarity': rarity}
                # 期数只对「绑期数」的物品有意义（船图纸与彩装图纸），
                # 金装备各期混着出，登记了反而会让人误以为它属于某一期。
                # 用 Lua 那边的模板名查 id：走词元兜底时库内名字与 Lua 名不同（缺 Mount、
                # 词序或大小写差异），拿库内名字查会把「蓝图：马可波罗」这类船图纸漏掉期数。
                lua_template = to_template_name(en_name) or key
                series = self.lua.series_by_id.get(self.lua.by_template_id.get(lua_template, 0))
                if series:
                    entry['series'] = series
                table[stem] = entry
        path = NAME_TABLE_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(table, f, ensure_ascii=False, indent=1, sort_keys=True)
        logger.info(f'[科研模板] 名称表已更新 {path}，共 {len(table)} 条')

    @staticmethod
    def _load_ship_names() -> Dict[str, str]:
        """读舰船数据表的「归一化英文名 -> 中文名」对照，实现见模块级 load_ship_names()。

        Returns:
            dict: fold_text(英文名) -> 中文名。
        """
        return load_ship_names()

    @staticmethod
    def _resolve_namecode(zh_name: str, en_name: str, ships: Dict[str, str]) -> str:
        """把 {namecode:XXX} 占位符换成真实中文名，实现见模块级 resolve_ship_placeholder()。

        Args:
            zh_name (str): Lua 的中文名，可能含占位符。
            en_name (str): Lua 的英文名，蓝图形如 'Blueprint - Max Immelmann'。
            ships (dict): 舰船数据表的英文名 -> 中文名对照。

        Returns:
            str: 可展示的中文名；查不到时原样返回。
        """
        return resolve_ship_placeholder(zh_name, en_name, ships)

    def _save_contact_sheet(self, path: str, names: Dict[str, int]):
        """生成「图标 + 中文标签 + 建议名」对照图。

        Args:
            path (str): 输出路径。
            names (dict): dedupe_suggestions() 的结果。
        """
        keys = sorted(self.items, key=lambda k: int(k))
        cell_w, cell_h = 150, 236
        columns = 5
        rows = []
        for start in range(0, len(keys), columns):
            cells = []
            for key in keys[start:start + columns]:
                entry = self.items[key]
                cell = np.full((cell_h, cell_w, 3), 45, np.uint8)
                cell[4:100, 27:123] = cv2.resize(entry.image, (ITEM_SIZE, ITEM_SIZE))
                label = entry.label
                if label.shape[0] > 44:
                    label = label[:44]
                if label.shape[1] > cell_w:
                    left = (label.shape[1] - cell_w) // 2
                    label = label[:, left:left + cell_w]
                cell[104:104 + label.shape[0], 0:label.shape[1]] = label
                # 顶层写建议名（ASCII），避免 cv2.putText 画不出中文
                cv2.putText(cell, names[key][:20], (6, 196), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(cell, f'x{entry.count}', (6, 220), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (120, 220, 120), 1, cv2.LINE_AA)
                cells.append(np.hstack([cell, np.full((cell_h, 6, 3), 95, np.uint8)]))
            row = np.hstack(cells)
            target_w = columns * (cell_w + 6)
            if row.shape[1] < target_w:
                row = np.hstack([row, np.full((cell_h, target_w - row.shape[1], 3), 45, np.uint8)])
            rows.append(np.vstack([row, np.full((8, row.shape[1], 3), 95, np.uint8)]))
        image = np.vstack(rows)
        ok, buf = cv2.imencode('.png', image)
        if ok:
            buf.tofile(path)

    def _build_report(self, names: Dict[str, int]) -> str:
        """生成 Markdown 报告。

        Args:
            names (dict): dedupe_suggestions() 的结果。

        Returns:
            str: 报告文本。
        """
        keys = sorted(self.items, key=lambda k: int(k))
        lines = [
            '# 科研掉落模板缺失报告',
            '',
            f'- 扫描截图：{self.files_scanned} 个文件，{self.frames_scanned} 个收获帧',
            f'- 现有模板库：`{self.template_folder}`',
            f'- 缺失物品：{len(keys)} 种',
            '',
            '## 清单',
            '',
            '| # | 建议文件名 | 稀有度 | 置信 | 中文标签(OCR) | 出现次数 | 首次出现 | 备选 |',
            '|---|---|---|---|---|---|---|---|',
        ]
        for key in keys:
            entry = self.items[key]
            alternatives = ' / '.join(entry.alternatives) if entry.alternatives else ''
            if entry.library_score:
                confidence = f'库内同款 {entry.library_score:.2f}'
                if entry.needs_review:
                    confidence = '**' + confidence + '**'
            else:
                confidence = '确定' if not entry.needs_review else '**待确认**'
            rarity = {5: '彩', 4: '金'}.get(entry.rarity, '—')
            lines.append(
                f'| {key} | `{names[key]}` | {rarity} | {confidence} | {entry.label_text or "—"} '
                f'| {entry.count} | {entry.first_file} | {alternatives or "—"} |'
            )
        unresolved = [k for k in keys if self.items[k].needs_review]
        if unresolved:
            lines += [
                '',
                '## 待人工命名',
                '',
                '下面这些的名字没能从 Lua 数据唯一确定（可能是标签被挤压、OCR 认错字，',
                '或同族装备太多）。请对照 `contact_sheet.png` 和上面的标签挑一个，',
                '**确认后再复制进 assets**：',
                '',
                '```',
                *[f'{names[k]}.png' for k in unresolved],
                '```',
            ]
        lines += [
            '',
            '## 落库方式',
            '',
            '确认命名后，把 png 复制进 `assets/stats/research_items/`，重跑本工具',
            '应显示 0 种缺失。同一件道具的不同底色（BONUS!/EVENT!/CATCHUP!）',
            '会带 `_2` / `_3` 后缀，这是仓库既有约定，统计时 `Item.name` 会自动归一。',
            '',
        ]
        return '\n'.join(lines)


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--folder', action='append', default=[],
                        help='科研掉落截图目录，可重复指定')
    parser.add_argument('--output', default='./log/research_templates',
                        help='素材与报告输出目录')
    parser.add_argument('--template-folder', default=DEFAULT_TEMPLATE_FOLDER,
                        help='现有模板库目录')
    parser.add_argument('--lua', default=None,
                        help='游戏 Lua 数据源目录，缺省则自动探测')
    parser.add_argument('--server', default='cn', choices=['cn', 'en', 'jp', 'tw'],
                        help='游戏服务器，影响截图资源')
    parser.add_argument('--scope', default='all', choices=['all', 'rare'],
                        help='rare: 只收集金/彩装备图纸、金/彩舰船图纸与心智单元，'
                             '紫蓝图纸、改造图纸、定向蓝图等一律跳过')
    parser.add_argument('--dry-run', action='store_true',
                        help='只扫描并打印报告，不写任何文件')
    args = parser.parse_args()

    server.server = args.server

    if not args.folder:
        parser.error('至少需要一个 --folder')

    scanner = ResearchTemplateScanner(
        template_folder=args.template_folder, lua_folder=args.lua)

    for folder in args.folder:
        if not os.path.isdir(folder):
            logger.warning(f'[科研模板] 目录不存在，跳过: {folder}')
            continue
        files = sorted(
            os.path.join(folder, name) for name in os.listdir(folder)
            if name.lower().endswith('.png')
        )
        logger.info(f'[科研模板] 扫描 {folder}，共 {len(files)} 个文件')
        for file in files:
            scanner.scan_file(file)

    scanner.resolve_names()

    if args.scope == 'rare':
        dropped = scanner.keep_scope()
        logger.info(f'[科研模板] 按采集口径跳过 {len(dropped)} 种：'
                    + '、'.join(dropped[:12])
                    + ('…' if len(dropped) > 12 else ''))

    if not scanner.items:
        logger.info('[科研模板] 模板库已覆盖全部物品，无需补模板')
        # 名称表描述的是整个模板库，与本次有没有缺口无关，
        # 所以这条路径也要刷新，否则补完模板后前端的中文名会缺一批。
        if not args.dry_run:
            scanner.write_name_table()
        return

    if args.dry_run:
        names = scanner.dedupe_suggestions()
        logger.info(f'[科研模板] 发现 {len(scanner.items)} 种缺失物品：')
        for key in sorted(scanner.items, key=lambda k: int(k)):
            entry = scanner.items[key]
            logger.info(f'  {names[key]:40s} x{entry.count:<4d} 标签={entry.label_text!r} '
                        f'备选={entry.alternatives}')
        return

    _, report = scanner.export(args.output)
    print(report)


if __name__ == '__main__':
    main()
