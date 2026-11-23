# -*- coding: utf-8 -*-
"""已废弃的副本（2026-11-23 合并）。

这里的商品表原本是世态插件 `DeepSeek_Harness_Amo_Market/catalog.py` 的一份拷贝，
两份数据各自漂移、品类也对不上。金融的 `market_core()` 早就 `return None`
（市场拆回独立插件后不再实例化），所以这个模块只是被 import 着、没人真的用。

现在它只做转发：商品数据唯一真源 = 世态的 catalog.py。
接口（CATALOGS / counts / pick / OUTFIT_SETS / _set_price）保持不变，
老引用照样能 import，但数据不会再分叉。
"""
from __future__ import annotations

import importlib.util
import pathlib

_MARKET_CATALOG = (pathlib.Path(__file__).resolve().parents[2]
                   / "DeepSeek_Harness_Amo_Market" / "catalog.py")

_mod = None
_error = ""
try:
    if _MARKET_CATALOG.is_file():
        _spec = importlib.util.spec_from_file_location(
            "amo_market_catalog_shared", str(_MARKET_CATALOG))
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
    else:
        _error = "找不到世态商品表: %s" % _MARKET_CATALOG
except Exception as exc:  # 世态没装也不该把金融拖死
    _mod = None
    _error = str(exc)

CATALOGS = dict(getattr(_mod, "CATALOGS", {}) or {})
OUTFIT_SETS = getattr(_mod, "OUTFIT_SETS", ()) or ()
_set_price = getattr(_mod, "_set_price", None)
DRUGS = getattr(_mod, "DRUGS", []) or []
GROCERIES = getattr(_mod, "GROCERIES", []) or []
TAKEOUT = getattr(_mod, "TAKEOUT", []) or []
OUTFITS = getattr(_mod, "OUTFITS", []) or []
JEWELRY_ITEMS = getattr(_mod, "JEWELRY_ITEMS", []) or []
COSMETICS = getattr(_mod, "COSMETICS", []) or []
DINING = getattr(_mod, "DINING", []) or []


def counts() -> dict:
    return {key: len(value) for key, value in CATALOGS.items()}


def pick(kind: str, rng=None) -> dict:
    rows = CATALOGS.get(str(kind or "")) or []
    if not rows:
        return {}
    import random as _random
    return dict((rng or _random.Random()).choice(rows))
