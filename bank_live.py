# -*- coding: utf-8 -*-
"""银行实时业务层：账户、存款、授信、放款、还款、风险事件。
bank.py 只保存银行底稿；本文件负责可变状态与业务生命周期。
"""
from __future__ import annotations
import json, os, time
from typing import Any, Dict, List

try:
    from . import bank as base
except Exception:
    import bank as base  # type: ignore

STATE_NAME = "bank_state.json"

def _path(data_dir: str) -> str:
    return os.path.join(str(data_dir or "."), STATE_NAME)

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def load(data_dir: str) -> Dict[str, Any]:
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            s = json.load(f)
        if not isinstance(s, dict):
            raise ValueError("bad state")
    except Exception:
        s = {}
    s.setdefault("accounts", [])
    s.setdefault("loans", [])
    s.setdefault("deposits", [])
    s.setdefault("events", [])
    s.setdefault("cash", {"vault": 0.0, "clearing": 0.0})
    return s

def save(data_dir: str, state: Dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(_path(data_dir)), exist_ok=True)
        tmp = _path(data_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path(data_dir))
        return True
    except Exception:
        return False

def _event(s, kind, **detail):
    s["events"].append({"at": _now(), "kind": kind, **detail})
    s["events"] = s["events"][-300:]

def _id(prefix):
    return "%s-%d" % (prefix, int(time.time() * 1000))

def open_account(data_dir: str, owner: str, kind: str = "个人结算账户") -> Dict[str, Any]:
    s = load(data_dir)
    owner = str(owner or "").strip()
    if not owner:
        return {"ok": False, "reason": "缺少开户人"}
    row = {"id": _id("ACC"), "owner": owner, "kind": kind or "个人结算账户",
           "balance": 0.0, "status": "active", "opened_at": _now()}
    s["accounts"].append(row); _event(s, "open_account", account=row["id"], owner=owner)
    save(data_dir, s)
    return {"ok": True, "account": dict(row)}

def deposit(data_dir: str, owner: str, amount: float, term: str = "活期") -> Dict[str, Any]:
    s = load(data_dir)
    amount = round(float(amount or 0), 2)
    if amount <= 0: return {"ok": False, "reason": "存款金额必须大于 0"}
    rate = {"活期": base.RATES["存款活期"], "一年": base.RATES["存款一年"],
            "三年": base.RATES["存款三年"], "大额存单三年": base.RATES["大额存单三年"]}.get(term, base.RATES["存款活期"])
    row = {"id": _id("DEP"), "owner": str(owner or "客户"), "principal": amount,
           "term": term, "rate": rate, "status": "active", "opened_at": _now()}
    s["deposits"].append(row)
    s["cash"]["clearing"] = round(float(s["cash"].get("clearing") or 0) + amount, 2)
    _event(s, "deposit", id=row["id"], owner=row["owner"], amount=amount, term=term)
    save(data_dir, s)
    return {"ok": True, "deposit": dict(row)}

def apply_loan(data_dir: str, borrower: str, amount: float, months: int = 12,
               kind: str = "流动资金贷款", debt_ratio: float = 52.0,
               collateral_cover: float = 1.2) -> Dict[str, Any]:
    s = load(data_dir)
    is_group = "智脑" in str(borrower or "") or "计算" in str(borrower or "")
    check = base.credit_apply(amount, months, kind, debt_ratio, collateral_cover, group=is_group)
    if not check.get("ok"):
        return {"ok": False, "stage": "approval", "application": check}
    row = {"id": _id("LOAN"), "borrower": str(borrower or "客户"),
           "product": check["product"], "principal": check["amount"],
           "outstanding": check["amount"], "months": months, "rate": check["rate"],
           "status": "approved", "applied_at": _now(), "approved_at": _now(),
           "next_due": time.strftime("%Y-%m-%d", time.localtime(time.time()+30*86400)),
           "paid": 0.0}
    s["loans"].append(row); _event(s, "loan_approved", loan=row["id"], borrower=row["borrower"], amount=row["principal"])
    save(data_dir, s)
    return {"ok": True, "loan": dict(row), "plan": check["plan"]}

def disburse(data_dir: str, loan_id: str) -> Dict[str, Any]:
    s = load(data_dir)
    for loan in s["loans"]:
        if loan.get("id") == loan_id:
            if loan.get("status") != "approved": return {"ok": False, "reason": "当前状态不能放款"}
            loan["status"] = "active"; loan["disbursed_at"] = _now()
            amount = float(loan["principal"])
            if float(s["cash"].get("clearing") or 0) < amount:
                return {"ok": False, "reason": "清算头寸不足，暂不能放款"}
            s["cash"]["clearing"] = round(float(s["cash"].get("clearing") or 0) - amount, 2)
            _event(s, "loan_disbursed", loan=loan_id, amount=loan["principal"])
            save(data_dir, s); return {"ok": True, "loan": dict(loan)}
    return {"ok": False, "reason": "没有这笔贷款"}

def repay(data_dir: str, loan_id: str, amount: float) -> Dict[str, Any]:
    s = load(data_dir); amount = round(float(amount or 0), 2)
    if amount <= 0: return {"ok": False, "reason": "还款金额必须大于 0"}
    for loan in s["loans"]:
        if loan.get("id") == loan_id:
            if loan.get("status") not in ("active", "approved"): return {"ok": False, "reason": "贷款不可还款"}
            paid = min(amount, float(loan.get("outstanding") or 0))
            loan["outstanding"] = round(float(loan["outstanding"]) - paid, 2)
            loan["paid"] = round(float(loan.get("paid") or 0) + paid, 2)
            s["cash"]["clearing"] = round(float(s["cash"].get("clearing") or 0) + paid, 2)
            if loan["outstanding"] <= 0.01: loan["outstanding"] = 0.0; loan["status"] = "closed"
            _event(s, "loan_repaid", loan=loan_id, amount=paid, outstanding=loan["outstanding"])
            save(data_dir, s); return {"ok": True, "loan": dict(loan), "paid": paid}
    return {"ok": False, "reason": "没有这笔贷款"}

def snapshot(data_dir: str) -> Dict[str, Any]:
    s = load(data_dir)
    active = [x for x in s["loans"] if x.get("status") in ("approved", "active")]
    overdue = [x for x in active if x.get("next_due") and x["next_due"] < time.strftime("%Y-%m-%d")]
    deposits = sum(float(x.get("principal") or 0) for x in s["deposits"] if x.get("status") == "active")
    loans = sum(float(x.get("outstanding") or 0) for x in active)
    return {"bank": base.profile(), "accounts": len(s["accounts"]), "deposits_live": round(deposits,2),
            "loans_live": round(loans,2), "active_loans": len(active), "overdue_loans": len(overdue),
            "events": list(s["events"][-20:]), "state": s}

def reset(data_dir: str) -> Dict[str, Any]:
    s = {"accounts": [], "loans": [], "deposits": [], "events": [], "cash": {"vault": 0.0, "clearing": 0.0}}
    save(data_dir, s); return snapshot(data_dir)
