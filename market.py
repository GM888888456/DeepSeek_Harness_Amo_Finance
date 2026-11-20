# -*- coding: utf-8 -*-
"""行情：只取「现在多少钱」，不做任何预测。

数据源是腾讯的公开行情接口（不需要 key）：A 股、港股、美股都能查。
**拿不到就返回空**，绝不编一个价格——价格是账本的一部分，编出来的盈亏会让她
的情绪和实际资产对不上。
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime
from typing import Any

QUOTE_URL = "https://qt.gtimg.cn/q="
#: 同花顺公开行情（A 股）。港股/美股它不给，退回腾讯。
THS_URL = "http://d.10jqka.com.cn/v2/realhead/hs_%s/last.js"
FUTURES_URL = "https://hq.sinajs.cn/list="
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; amo-finance/1.0)",
    "Referer": "https://finance.qq.com/",
}

#: 没配汇率时的粗略折算（只用于把港币/美元资产折成人民币记账）
DEFAULT_FX = {"CNY": 1.0, "HKD": 0.92, "USD": 7.15}


def normalize(symbol: str) -> str:
    """把「600519 / 00700 / AAPL」统一成腾讯的写法：sh600519 / hk00700 / usAAPL。"""
    raw = str(symbol or "").strip().upper().replace(" ", "")
    if not raw:
        return ""
    for prefix in ("SH", "SZ", "HK", "US"):
        if raw.startswith(prefix) and len(raw) > len(prefix):
            rest = raw[len(prefix):]
            if prefix == "US":
                return "us" + rest
            if rest.isdigit():
                return prefix.lower() + rest.zfill(5 if prefix == "HK" else 6)
            return ""
    if raw.isdigit():
        if len(raw) == 5:
            return "hk" + raw
        if len(raw) == 6:
            return ("sh" if raw[0] == "6" else "sz") + raw
        return ""
    if raw.isalpha():
        return "us" + raw
    return ""


def market_of(symbol: str) -> str:
    """cn / hk / us。"""
    code = normalize(symbol)
    if code.startswith("hk"):
        return "hk"
    if code.startswith("us"):
        return "us"
    return "cn"


def currency_of(symbol: str) -> str:
    return {"cn": "CNY", "hk": "HKD", "us": "USD"}[market_of(symbol)]


def _parse_line(line: str) -> tuple[str, dict[str, Any]] | None:
    line = line.strip()
    if not line.startswith("v_") or "=" not in line:
        return None
    key, body = line.split("=", 1)
    fields = body.strip().rstrip(";").strip('"').split("~")
    if len(fields) < 33:
        return None
    code = key[2:]
    try:
        price = float(fields[3] or 0)
        prev = float(fields[4] or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None            # 停牌/无成交：不当成有效价格
    try:
        pct = float(fields[32] or 0)
    except (TypeError, ValueError):
        pct = (price - prev) / prev * 100 if prev else 0.0
    return code, {
        "symbol": code,
        "name": fields[1].strip(),
        "price": round(price, 3),
        "prev_close": round(prev, 3),
        "change": round(price - prev, 3) if prev else 0.0,
        "pct": round(pct, 2),
        "currency": currency_of(code),
    }


def _minutes(now: datetime) -> int:
    return now.hour * 60 + now.minute


def trading_open(market: str, now: datetime | None = None) -> bool:
    """北京时间下，这个市场现在是否在交易。

    A/H：周一至周五，上午/下午两段；美股：夏令时 21:30、冬令时 22:30 开盘。
    非交易时间一律不调接口，只读本地收盘缓存。
    """
    now = now or datetime.now()
    wd = now.weekday()
    hm = _minutes(now)
    market = str(market or "").lower()
    if market == "cn":
        return wd < 5 and (555 <= hm < 690 or 780 <= hm < 900)
    if market == "hk":
        return wd < 5 and (570 <= hm < 720 or 780 <= hm < 960)
    if market == "us":
        # 夏令时近似 3–10 月；11–2 月晚一小时
        summer = 3 <= now.month <= 10
        open_min = 21 * 60 + 30 if summer else 22 * 60 + 30
        close_min = 4 * 60 if summer else 5 * 60
        if hm >= open_min and wd < 5:
            return True
        if hm < close_min and 1 <= wd <= 5:   # 周二~周六凌晨，接前一晚美股
            return True
        return False
    return False


def _ths_code(code: str) -> str:
    """sh600519 -> 600519；只有 A 股能走同花顺。"""
    body = str(code or "")
    if body.startswith(("sh", "sz")) and body[2:].isdigit():
        return body[2:]
    return ""


def _parse_ths(text: str) -> dict[str, Any] | None:
    """同花顺 last.js：quotebridge_...( {...} )，字段 10=最新价、6=昨收。"""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
    except Exception:
        return None
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, dict):
        return None
    try:
        price = float(items.get("10") or 0)
        prev = float(items.get("6") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    pct = round((price - prev) / prev * 100, 2) if prev else 0.0
    return {
        "name": str((items or {}).get("name") or ""),
        "price": round(price, 3),
        "prev_close": round(prev, 3),
        "change": round(price - prev, 3) if prev else 0.0,
        "pct": pct,
        "time": str(items.get("time") or ""),
        "source": "ths",
    }


def futures_quote(code: str, timeout: float = 6.0, opener=None) -> dict[str, Any]:
    """内盘期货一条行情（新浪 nf_ 接口，不需要 key）。"""
    body = str(code or "").upper().strip()
    if not body:
        return {}
    if body.startswith("NF_"):
        body = body[3:]
    # 新浪的合约代码区分大小写：nf_RB0，不能小写
    url = FUTURES_URL + "nf_" + body
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as resp:
            text = resp.read().decode("gbk", errors="replace")
    except Exception:
        return {}
    start = text.find('"')
    end = text.rfind('"')
    if start < 0 or end <= start:
        return {}
    fields = text[start + 1:end].split(",")
    if len(fields) < 10:
        return {}
    name = ""
    try:
        float(fields[0])
        offset = 0
    except (TypeError, ValueError):
        name = fields[0]
        offset = 1
    # RB0：name,time,open,high,low,?,buy,sell,last,?,prev_settle...
    # IF0：open,high,low,last,volume,amount,... 没有 name/time
    try:
        if offset:
            price = float(fields[8]) or float(fields[2])
            prev = float(fields[10]) if len(fields) > 10 else 0.0
        else:
            price = float(fields[3])
            prev = float(fields[13]) if len(fields) > 13 else 0.0
    except (TypeError, ValueError):
        return {}
    if price <= 0:
        return {}
    return {
        "symbol": body, "name": name or body,
        "price": round(price, 3), "prev_close": round(prev, 3),
        "change": round(price - prev, 3) if prev else 0.0,
        "pct": round((price - prev) / prev * 100, 2) if prev else 0.0,
        "source": "sina_futures",
    }


class QuoteBoard:
    """行情缓存：同一个 symbol 60 秒内只打一次接口。"""

    def __init__(self, timeout: float = 6.0, ttl: float = 60.0, opener=None,
                 cache_path: str = "", prefer: str = "tencent", allow_closed: bool = False):
        self.timeout = timeout
        self.ttl = ttl
        self.prefer = str(prefer or "ths").lower()
        self.allow_closed = bool(allow_closed)
        self.cache_path = str(cache_path or "")
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._opener = opener or urllib.request.urlopen
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        for code, row in raw.items():
            if not isinstance(row, dict):
                continue
            data = row.get("data")
            if isinstance(data, dict):
                self._cache[str(code)] = (float(row.get("ts") or 0), data)

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            payload = {code: {"ts": ts, "data": data}
                       for code, (ts, data) in self._cache.items()}
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    def _fetch_ths(self, code: str) -> dict[str, Any]:
        ths = _ths_code(code)
        if not ths or self.prefer != "ths":
            return {}
        request = urllib.request.Request(THS_URL % ths, headers=HEADERS)
        try:
            with self._opener(request, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return {}
        data = _parse_ths(text)
        if not data:
            return {}
        data.update({"symbol": code, "currency": "CNY"})
        return data

    def _fetch(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        out = {}
        rest = []
        for code in codes:
            data = self._fetch_ths(code)
            if data:
                out[code] = data
            else:
                rest.append(code)
        if not rest:
            return out
        url = QUOTE_URL + ",".join(rest)
        request = urllib.request.Request(url, headers=HEADERS)
        with self._opener(request, timeout=self.timeout) as resp:
            raw = resp.read()
        text = raw.decode("gbk", errors="replace")
        for line in text.splitlines():
            parsed = _parse_line(line)
            if parsed:
                code, data = parsed
                out[code] = data
        return out

    def quotes(self, symbols: list[str], force: bool = False) -> dict[str, dict[str, Any]]:
        """交易时段内才请求；非交易时间只读本地收盘缓存，绝不调接口。"""
        now = time.time()
        codes, result = [], {}
        for item in symbols:
            code = normalize(item)
            if code:
                codes.append(code)
        fresh_codes = []
        for code in sorted(set(codes)):
            hit = self._cache.get(code)
            is_open = trading_open(market_of(code))
            if hit and (not force or not is_open) and now - hit[0] <= self.ttl:
                result[code] = dict(hit[1])
                continue
            if hit and not is_open and not self.allow_closed:
                result[code] = dict(hit[1])       # 收盘价，不请求
                continue
            if is_open or self.allow_closed:
                fresh_codes.append(code)
            elif hit:
                result[code] = dict(hit[1])
        if fresh_codes:
            try:
                fresh = self._fetch(fresh_codes)
            except Exception:
                fresh = {}
            for code, data in fresh.items():
                self._cache[code] = (now, data)
                result[code] = dict(data)
            if fresh:
                self._save_cache()
        return result

    def last_price(self, symbol: str) -> float:
        data = self.quotes([symbol]).get(normalize(symbol))
        try:
            return float(data["price"]) if data else 0.0
        except Exception:
            return 0.0
