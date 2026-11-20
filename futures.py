# -*- coding: utf-8 -*-
"""期货：合约乘数、保证金、盈亏。只做计算，钱走账本。

内盘主力连续合约，行情来自新浪 `nf_` 公开接口（不需要 key）。期货天生带杠杆：
保证金比例 7%–15%，相当于 7–14 倍；亏损超过保证金就爆仓。
"""

from __future__ import annotations

from typing import Any

#: code: (名字, 合约乘数, 保证金比例)
INSTRUMENTS: dict[str, tuple[str, float, float]] = {
    "RB": ("螺纹钢", 10.0, 0.10),
    "HC": ("热卷", 10.0, 0.10),
    "I": ("铁矿石", 100.0, 0.12),
    "CU": ("沪铜", 5.0, 0.12),
    "AL": ("沪铝", 5.0, 0.12),
    "AU": ("沪金", 1000.0, 0.09),
    "AG": ("沪银", 15.0, 0.12),
    "SC": ("原油", 1000.0, 0.15),
    "M": ("豆粕", 10.0, 0.08),
    "Y": ("豆油", 10.0, 0.09),
    "SR": ("白糖", 10.0, 0.07),
    "CF": ("棉花", 5.0, 0.09),
    "IF": ("沪深300", 300.0, 0.12),
    "IC": ("中证500", 200.0, 0.14),
    "IH": ("上证50", 300.0, 0.12),
    "IM": ("中证1000", 200.0, 0.15),
}

DEFAULT_CONTRACTS = 1


def normalize(code: str) -> str:
    """rb0 / RB0 / nf_RB0 → RB。"""
    body = str(code or "").upper().strip()
    if body.startswith("NF_"):
        body = body[3:]
    for suffix in ("0", "1", "2", "3"):
        if body.endswith(suffix) and body[:-1] in INSTRUMENTS:
            return body[:-1]
    return body if body in INSTRUMENTS else ""


def spec(code: str) -> dict[str, Any]:
    key = normalize(code)
    if not key:
        return {}
    name, multiplier, margin_rate = INSTRUMENTS[key]
    return {"code": key, "name": name, "multiplier": multiplier,
            "margin_rate": margin_rate, "market_code": key + "0"}


def notional(price: float, contracts: int, code: str) -> float:
    item = spec(code)
    if not item:
        return 0.0
    return round(max(0.0, float(price)) * max(1, int(contracts)) * item["multiplier"], 2)


def margin_for(price: float, contracts: int, code: str) -> float:
    item = spec(code)
    if not item:
        return 0.0
    return round(notional(price, contracts, code) * item["margin_rate"], 2)


def pnl_for(pos: dict[str, Any], price: float) -> float:
    """浮动盈亏：多头 (现价-开仓)×乘数×手数；空头反过来。"""
    item = spec(pos.get("code") or "")
    if not item:
        return 0.0
    try:
        entry = float(pos.get("entry") or 0)
        current = float(price or 0)
        contracts = int(pos.get("contracts") or 0)
    except (TypeError, ValueError):
        return 0.0
    if entry <= 0 or current <= 0 or contracts <= 0:
        return 0.0
    direction = 1.0 if str(pos.get("side") or "long") == "long" else -1.0
    return round((current - entry) * direction * contracts * item["multiplier"], 2)


def contracts_from_budget(budget: float, price: float, code: str) -> int:
    item = spec(code)
    if not item:
        return 0
    one = margin_for(price, 1, code)
    if one <= 0:
        return 0
    return max(0, int(float(budget) // one))


def summarize(positions: dict[str, dict[str, Any]], quotes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """期货账户：保证金占用、浮动盈亏、权益。"""
    rows = []
    margin = 0.0
    pnl = 0.0
    for code, pos in (positions or {}).items():
        quote = quotes.get(code) or {}
        price = float(quote.get("price") or pos.get("last") or 0)
        row = dict(pos)
        row["last"] = price
        row["pnl"] = pnl_for(pos, price)
        try:
            row["pnl_pct"] = round(row["pnl"] / max(0.01, float(pos.get("margin") or 0)) * 100, 2)
        except Exception:
            row["pnl_pct"] = 0.0
        margin += float(pos.get("margin") or 0)
        pnl += row["pnl"]
        rows.append(row)
    return {"positions": rows, "count": len(rows),
            "margin": round(margin, 2), "pnl": round(pnl, 2),
            "equity": round(margin + pnl, 2)}