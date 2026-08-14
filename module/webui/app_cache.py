"""WebUI 页面切换性能缓存：配置、菜单、搜索索引跨切换复用。"""
from __future__ import annotations

import time as _time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# AzurLaneConfig 实例缓存
# ---------------------------------------------------------------------------
_config_cache: Dict[str, tuple] = {}  # name -> (AzurLaneConfig, last_used_ts)
_CONFIG_CACHE_MAX = 4  # 最多缓存 4 个实例的配置


def get_cached_config(config_name: str, load_config_fn) -> Any:
    """返回缓存的 AzurLaneConfig 实例；未命中时调用 load_config_fn 加载。"""
    now = _time.time()
    try:
        entry = _config_cache.get(config_name)
        if entry is not None and entry[1] > now - 1800:  # 30 分钟有效期
            _config_cache[config_name] = (entry[0], now)
            return entry[0]
    except Exception:
        pass
    config = load_config_fn(config_name)
    if len(_config_cache) >= _CONFIG_CACHE_MAX:
        oldest = min(_config_cache, key=lambda k: _config_cache[k][1])
        del _config_cache[oldest]
    _config_cache[config_name] = (config, now)
    return config


def invalidate_config(config_name: Optional[str] = None) -> None:
    """清除配置缓存。无参数时清空全部。"""
    if config_name is None:
        _config_cache.clear()
    else:
        _config_cache.pop(config_name, None)


# ---------------------------------------------------------------------------
# ALAS_MENU / ALAS_ARGS 跨实例缓存（这些文件不随实例变化）
# ---------------------------------------------------------------------------
_alas_menu_cache: Optional[Dict[str, Any]] = None
_alas_args_cache: Optional[Dict[str, Any]] = None
_alas_args_mod: str = ""


def get_cached_menu_args(alas_mod: str, read_file_fn, filepath_args_fn):
    """
    返回 (ALAS_MENU, ALAS_ARGS)。
    当 alas_mod 未变化时直接返回缓存，避免每次切换都读盘。
    """
    global _alas_menu_cache, _alas_args_cache, _alas_args_mod

    if _alas_args_mod == alas_mod and _alas_menu_cache is not None:
        return _alas_menu_cache, _alas_args_cache

    menu = read_file_fn(filepath_args_fn("menu", alas_mod))
    args = read_file_fn(filepath_args_fn("args", alas_mod))
    _alas_menu_cache = menu
    _alas_args_cache = args
    _alas_args_mod = alas_mod
    return menu, args