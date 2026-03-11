import csv
import glob
import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

import module.config.server as server
from module.logger import logger
from module.ocr.ocr import Ocr

# 残留污染常见符号（不含半角点和中点，避免误伤“.改”“娜娜·阿丝达”）
SYMBOLS = set('`~_"\'“”‘’—–―‖，,。；;：:！？!?（）()[]【】<>《》…•ˇ′=|^*')
ALLOWED_RE = re.compile(r'^[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9\-\.·]+$')


def _normalize_for_match(name: str) -> str:
    text = (name or '').strip()
    text = text.strip('`~_"\'“”‘’—–―‖，,。.；;：:！？!?（）()[]【】<>《》…|=^*')
    text = re.sub(r'["\'“”‘’`~_—–―‖，,。.；;：:！？!?（）()\[\]【】<>《》…|=^*]', '', text)
    text = re.sub(r'\s+', '', text)
    return text


def _normalize_wiki_name(name: str) -> str:
    s = (name or '').strip()
    # 处理“名称重复两遍”，例如 杜威杜威
    if len(s) % 2 == 0:
        half = len(s) // 2
        if s[:half] == s[half:]:
            s = s[:half]
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'（[^）]*）', '', s)
    return _normalize_for_match(s)


def _has_residual_symbol(name: str) -> bool:
    if not name:
        return False
    if any(ch in SYMBOLS for ch in name):
        return True
    return not bool(ALLOWED_RE.match(name))


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _pick_best_fuzzy(target: str, candidates: List[str]) -> Tuple[str, float]:
    best_name = ''
    best_score = 0.0
    for cand in candidates:
        score = _similarity(target, cand)
        if score > best_score:
            best_score = score
            best_name = cand
    return best_name, best_score


def _rescan_vote_match(name: str, level: int, wiki_lib: Dict[str, str], wiki_keys: List[str]) -> Tuple[str, str, float]:
    """对 unresolved 名称做定向补扫式投票融合。

    由于后处理阶段没有截图上下文，这里用多种归一化候选替代“补扫”，
    再通过相似度与长度约束进行投票，降低误修风险。
    """
    raw = (name or '').strip()
    candidates: List[str] = []

    def add_candidate(text: str) -> None:
        t = _normalize_for_match(text)
        if t and t not in candidates:
            candidates.append(t)

    add_candidate(raw)
    add_candidate(_normalize_wiki_name(raw))
    add_candidate(raw.replace('干', '十'))
    add_candidate(raw.replace('厂', '广'))
    add_candidate(raw.replace('宫佐夫', '米哈伊尔'))
    add_candidate(raw.replace('宫佐关', '米哈伊尔'))

    # 常见前缀噪声（例如 “一`白友“）
    if raw.startswith('一') and len(raw) >= 3:
        add_candidate(raw[1:])

    # 去掉名称分隔符后的候选（例：娜娜·阿丝达 -> 娜娜阿丝达）
    merged = re.sub(r'[·\.\-]', '', raw)
    add_candidate(merged)

    # 改造舰名常见形态（例：神通.改 -> 神通）
    add_candidate(re.sub(r'[\.-]?改$', '', raw))

    # 若出现重复两遍，压缩成一遍
    compact = _normalize_for_match(raw)
    if compact and len(compact) % 2 == 0:
        half = len(compact) // 2
        if compact[:half] == compact[half:]:
            add_candidate(compact[:half])

    best_key = ''
    best_score = 0.0

    for cand in candidates:
        # 英文编号舰名大小写统一（例：z36 -> Z36）
        if re.fullmatch(r'[A-Za-z0-9\-\.]+', cand):
            cand = cand.upper()

        if cand in wiki_lib:
            return wiki_lib[cand], 'rescan_vote_exact', 1.0

        key, score = _pick_best_fuzzy(cand, wiki_keys)
        if not key:
            continue

        len_diff = abs(len(key) - len(cand))
        if level >= 100:
            # 高等级舰放宽，但仍限制长度漂移
            if score >= 0.72 and len_diff <= 4 and score > best_score:
                best_key = key
                best_score = score
        else:
            if score >= 0.86 and len_diff <= 2 and score > best_score:
                best_key = key
                best_score = score

    if best_key:
        return wiki_lib[best_key], 'rescan_vote', best_score
    return name, 'unresolved', 0.0


def _rescan_ocr_from_image(
    name_image: np.ndarray,
    level: int,
    wiki_lib: Dict[str, str],
    wiki_keys: List[str],
) -> Tuple[str, str, float]:
    """基于扫描阶段缓存的舰名截图进行二次 OCR。"""
    if name_image is None or not isinstance(name_image, np.ndarray):
        return '', 'unresolved', 0.0
    if name_image.size == 0:
        return '', 'unresolved', 0.0

    h, w = name_image.shape[:2]
    if h <= 0 or w <= 0:
        return '', 'unresolved', 0.0

    lang = 'jp' if server.server == 'jp' else 'cnocr'
    button = [(0, 0, w, h)]

    # 多组参数做“真补扫”，覆盖白字/粉字和略放宽阈值
    ocr_configs = [
        ((255, 255, 255), 144),
        ((236, 210, 205), 136),
        ((255, 255, 255), 132),
        ((236, 210, 205), 128),
    ]

    candidates: List[str] = []

    for letter, threshold in ocr_configs:
        try:
            ocr = Ocr(buttons=button, lang=lang, letter=letter, threshold=threshold)
            ocr.SHOW_LOG = False
            out = ocr.ocr(name_image)
            text = out[0] if isinstance(out, list) else out
            normalized = _normalize_for_match(str(text or ''))
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        except Exception:
            continue

    if not candidates:
        return '', 'unresolved', 0.0

    best_key = ''
    best_score = 0.0

    for cand in candidates:
        if cand in wiki_lib:
            return wiki_lib[cand], 'rescan_ocr_exact', 1.0

        key, score = _pick_best_fuzzy(cand, wiki_keys)
        if not key:
            continue
        len_diff = abs(len(key) - len(cand))

        if level >= 100:
            if score >= 0.72 and len_diff <= 4 and score > best_score:
                best_key = key
                best_score = score
        else:
            if score >= 0.86 and len_diff <= 2 and score > best_score:
                best_key = key
                best_score = score

    if best_key:
        return wiki_lib[best_key], 'rescan_ocr', best_score

    return '', 'unresolved', 0.0


def _load_wiki_library(base: Path) -> Dict[str, str]:
    lib: Dict[str, str] = {}

    # 先加载手工维护的小库（如果可用）
    try:
        from dev_tools.compare_wiki_names import WIKI_SHIP_NAMES  # type: ignore

        for k, v in WIKI_SHIP_NAMES.items():
            kk = _normalize_for_match(k)
            vv = (v or '').strip()
            if kk:
                lib[kk] = vv
            kv = _normalize_for_match(vv)
            if kv:
                lib[kv] = vv
    except Exception:
        pass

    # 加载本地提取的wiki完整名称库，优先最新文件
    patterns = [
        str(base / 'dev_tools' / 'wiki_ship_names_*.txt'),
        str(base / 'dev_tools' / 'wiki_ship_names_auto.txt'),
    ]
    files: List[str] = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files), reverse=True)

    if files:
        latest = Path(files[0])
        for line in latest.read_text(encoding='utf-8', errors='ignore').splitlines():
            raw = line.strip()
            if not raw:
                continue
            std = _normalize_wiki_name(raw)
            if std:
                lib[std] = std

    # 固定补充项
    manual = {
        '普莉茅斯': '普利茅斯',
        '前芷': '前卫',
        '奠斯科': '莫斯科',
        '海主星': '海天',
        '一信浓': '信浓',
        '朱丽里': '朱利奥凯撒',
        '俾斯麦Zwe': '俾斯麦Zwei',
    }
    for k, v in manual.items():
        lib[_normalize_for_match(k)] = v
        lib[_normalize_for_match(v)] = v

    return lib


def _write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['index', 'name', 'level', 'rarity'])
        writer.writeheader()
        writer.writerows(rows)


def _write_report_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['index', 'before', 'after', 'method', 'score', 'level', 'rarity'],
        )
        writer.writeheader()
        writer.writerows(rows)


def _export_unresolved(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['index', 'before', 'level', 'rarity'])
        writer.writeheader()
        writer.writerows(rows)


def process_dock_scan_result(ships: list, base_dir: str = '.') -> Dict[str, str]:
    """DockScan后处理：导出原始CSV、自动匹配、导出未解决清单。"""
    base = Path(base_dir).resolve()
    today = date.today().strftime('%Y%m%d')

    raw_csv = base / f'dock_scan_results_{today}.csv'
    cleaned_backup_csv = base / f'dock_scan_results_{today}_cleaned.before_auto.csv'
    cleaned_csv = base / f'dock_scan_results_{today}_cleaned.csv'
    matched_csv = base / f'dock_scan_results_{today}_matched.csv'
    unresolved_csv = base / f'dock_scan_symbol_unresolved_{today}.csv'
    report_csv = base / f'dock_scan_symbol_match_report_{today}.csv'

    # 1) 导出原始结果
    raw_rows: List[dict] = []
    ship_by_index: Dict[int, object] = {}
    for i, ship in enumerate(ships, 1):
        ship_by_index[i] = ship
        raw_rows.append(
            {
                'index': i,
                'name': (ship.name or 'Unknown').strip(),
                'level': int(ship.level or 0),
                'rarity': (ship.rarity or 'unknown').strip(),
            }
        )
    _write_csv(raw_csv, raw_rows)

    # 兼容：若已有cleaned文件，先备份
    if cleaned_csv.exists():
        cleaned_backup_csv.write_bytes(cleaned_csv.read_bytes())

    # 关键修复：后处理必须基于本次扫描的raw结果，不能使用历史cleaned文件
    source_rows = list(raw_rows)

    wiki_lib = _load_wiki_library(base)
    wiki_keys = list(wiki_lib.keys())

    symbol_rows = 0
    fixed_rows = 0
    rescan_fixed_rows = 0
    unresolved_rows: List[dict] = []
    matched_rows: List[dict] = []
    report_rows: List[dict] = []

    for row in source_rows:
        idx = int(row['index'])
        name = (row['name'] or '').strip()
        level = str(row['level']).strip()
        rarity = (row['rarity'] or '').strip()

        final_name = name
        polluted = _has_residual_symbol(name)
        method = 'clean'
        score = ''

        if polluted:
            symbol_rows += 1
            normalized = _normalize_for_match(name)

            if normalized in wiki_lib:
                final_name = wiki_lib[normalized]
                method = 'exact'
                score = '1.0'
            else:
                best_key, score = _pick_best_fuzzy(normalized, wiki_keys)
                
                # 分层模糊匹配策略
                # 第一层：高保证度（相似度 >= 0.86，长度相近）
                if best_key and score >= 0.86 and abs(len(best_key) - len(normalized)) <= 2:
                    final_name = wiki_lib[best_key]
                    method = 'fuzzy'
                # 第二层：对于誓约舰/高等级（level >= 100），放宽条件
                #        允许更低的相似度和更大的长度差异
                elif best_key and int(level or 0) >= 100 and score >= 0.70 and abs(len(best_key) - len(normalized)) <= 4:
                    final_name = wiki_lib[best_key]
                    method = 'fuzzy_high_level'
                # 第三层：仅去符号兜底
                elif normalized and normalized != name and ALLOWED_RE.match(normalized):
                    final_name = normalized
                    method = 'strip'
                else:
                    # 真补扫：优先使用扫描阶段缓存的舰名截图做二次 OCR
                    ship_obj = ship_by_index.get(idx)
                    name_image = getattr(ship_obj, 'name_image', None) if ship_obj else None

                    ocr_name, ocr_method, ocr_score = _rescan_ocr_from_image(
                        name_image=name_image,
                        level=int(level or 0),
                        wiki_lib=wiki_lib,
                        wiki_keys=wiki_keys,
                    )

                    if ocr_method in ('rescan_ocr', 'rescan_ocr_exact') and ocr_name:
                        final_name = ocr_name
                        method = ocr_method
                        score = f'{ocr_score:.4f}'
                        rescan_fixed_rows += 1
                    else:
                        # 无截图或OCR二次补扫未命中时，回退到文本投票融合
                        voted_name, voted_method, voted_score = _rescan_vote_match(
                            name=name,
                            level=int(level or 0),
                            wiki_lib=wiki_lib,
                            wiki_keys=wiki_keys,
                        )
                        final_name = voted_name
                        method = voted_method
                        score = f'{voted_score:.4f}' if voted_score else ''
                        if voted_method in ('rescan_vote', 'rescan_vote_exact'):
                            rescan_fixed_rows += 1

                    if method == 'unresolved':
                        unresolved_rows.append(
                            {
                                'index': idx,
                                'before': name,
                                'level': level,
                                'rarity': rarity,
                            }
                        )

        if final_name != name:
            fixed_rows += 1

        matched_rows.append(
            {
                'index': idx,
                'name': final_name,
                'level': level,
                'rarity': rarity,
            }
        )

        if polluted:
            report_rows.append(
                {
                    'index': idx,
                    'before': name,
                    'after': final_name,
                    'method': method,
                    'score': score if isinstance(score, str) else f'{score:.4f}',
                    'level': level,
                    'rarity': rarity,
                }
            )

    _write_csv(matched_csv, matched_rows)
    # 直接将匹配结果作为cleaned当前版本
    _write_csv(cleaned_csv, matched_rows)
    _export_unresolved(unresolved_csv, unresolved_rows)
    _write_report_csv(report_csv, report_rows)

    logger.info(
        f'DockScan后处理完成: symbol={symbol_rows}, fixed={fixed_rows}, '
        f'rescan_fixed={rescan_fixed_rows}, unresolved={len(unresolved_rows)}'
    )

    return {
        'raw_csv': str(raw_csv),
        'cleaned_csv': str(cleaned_csv),
        'matched_csv': str(matched_csv),
        'unresolved_csv': str(unresolved_csv),
        'report_csv': str(report_csv),
    }
