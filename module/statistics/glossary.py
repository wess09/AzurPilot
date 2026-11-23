"""统计页物品名与任务名的多语言对照。

统计接口沿用中文名作为标签：前端按中文名查图标、筛选与导出。固定文案由前端字典翻译，
物品名和任务名只有后端掌握（物品名称表、配置页 i18n），因此随报表附带一份只含本次出现名称的对照表。
"""
import json
import re
import typing as t

from module.logger import logger

LANGUAGES = ('en-US', 'ja-JP', 'zh-TW', 'zh-CN-neko')
# 掉落记录单元格形如「钛合金 x2、HBX炸药 x1」，委托记录等也可能用顿号拼接。
_SPLIT = re.compile(r'[、，,]\s*')
_AMOUNT = re.compile(r'^(.*?)\s*[x×]\s*\d+$')

_index: t.Optional[dict] = None


def _add(index: dict, zh, names: dict):
    if not isinstance(zh, str) or not zh:
        return
    entry = {lang: name for lang, name in names.items() if isinstance(name, str) and name and name != zh}
    if entry:
        index.setdefault(zh, {}).update({lang: name for lang, name in entry.items() if lang not in index[zh]})


def _load_index() -> dict:
    """建立「中文名 -> {语言: 名称}」索引（进程内缓存）。"""
    global _index
    if _index is not None:
        return _index
    index = {}
    try:
        from module.statistics import opsi_drop_stats, research_stats
        tables = [research_stats.BUILTIN_NAMES, research_stats.load_name_table(), opsi_drop_stats.load_name_table()]
        by_id = {}
        for table in tables:
            for name, info in table.items():
                if isinstance(info, dict):
                    by_id.setdefault(name, info)
                    _add(index, info.get('zh'), {'en-US': info.get('en')})
        # 仓库目录与物品名称表共用模板标识，中文名可能略有不同，按标识补齐。
        from module.statistics.resource_flow import ROOT
        catalog = json.loads((ROOT / 'assets/stats/storage_items/catalog.json').read_text(encoding='utf-8'))
        for item in catalog.get('items', []):
            info = by_id.get(item.get('id'))
            if info:
                _add(index, item.get('name'), {'en-US': info.get('en')})
    except Exception as error:
        logger.warning(f'[统计-对照] 读取物品名称表失败: {type(error).__name__}')
    try:
        from module.config.utils import filepath_i18n
        translations = {}
        for lang in ('zh-CN', *LANGUAGES):
            with open(filepath_i18n(lang), encoding='utf-8') as f:
                translations[lang] = json.load(f).get('Task') or {}
        for task, value in translations['zh-CN'].items():
            if isinstance(value, dict):
                _add(index, value.get('name'), {
                    lang: (translations[lang].get(task) or {}).get('name') for lang in LANGUAGES})
    except Exception as error:
        logger.warning(f'[统计-对照] 读取任务名称失败: {type(error).__name__}')
    _index = index
    return index


def _candidates(text: str) -> t.Iterator[str]:
    yield text
    for part in _SPLIT.split(text):
        part = part.strip()
        if part:
            yield part
            match = _AMOUNT.match(part)
            if match:
                yield match.group(1).strip()


def build_glossary(texts: t.Iterable) -> dict:
    """为给定文本中出现的物品名、任务名生成对照表。

    Args:
        texts: 待查的文本；非字符串会被忽略，拼接的掉落记录会拆开查找。

    Returns:
        dict: {中文名: {语言: 名称}}，只含查到的条目。
    """
    index = _load_index()
    glossary = {}
    for text in texts:
        if not isinstance(text, str) or not text:
            continue
        for candidate in _candidates(text):
            if candidate in index:
                glossary[candidate] = index[candidate]
    return glossary


def report_texts(result: dict) -> t.Iterator:
    """列出统计报表里可能含物品名、任务名的文本。"""
    for item in result.get('metrics') or []:
        yield item.get('label')
    for item in result.get('series') or []:
        yield item.get('label')
    for table in result.get('tables') or []:
        yield from table.get('columns') or []
        for row in table.get('rows') or []:
            yield from row
    for item in result.get('taskOptions') or []:
        yield item.get('label')
