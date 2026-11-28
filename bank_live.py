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
    s.setdefault("credit_group_used", float(base.GROUP_CREDIT.get("used") or 0))
    if not isinstance(s.get("cash"), dict):
        s["cash"] = {"vault": 0.0, "clearing": 100000.0}
    else:
        s["cash"].setdefault("vault", 0.0)
        s["cash"].setdefault("clearing", 100000.0)
    # 兼容旧版空状态：只有完全没有业务历史时才注入银行初始流动性；
    # 有真实历史的 0 头寸必须保留，不能偷偷补钱。
    if (float(s["cash"].get("clearing") or 0) <= 0
            and not s["loans"] and not s["deposits"] and not s["events"]):
        s["cash"]["clearing"] = 100000.0
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
               collateral_cover: float = 1.2, collateral_type: str = "",
               collateral_amount: float = 0.0, eligible_amount: float = 0.0,
               collateral_ref: str = "") -> Dict[str, Any]:
    s = load(data_dir)
    is_group = "智脑" in str(borrower or "") or "计算" in str(borrower or "")
    if is_group:
        group_line = float(base.GROUP_CREDIT.get("line") or 0)
        group_used = float(s.get("credit_group_used") or 0)
        if amount > max(0.0, group_line - group_used):
            return {"ok": False, "stage": "approval",
                    "application": {"ok": False, "verdict": "批不了（集团授信不足）",
                                    "reasons": ["集团动态授信只剩 %.2f 万，不够 %.2f 万" % (max(0.0, group_line - group_used), amount)]}}
    check = base.credit_apply(amount, months, kind, debt_ratio, collateral_cover, group=is_group)
    if not check.get("ok"):
        return {"ok": False, "stage": "approval", "application": check}
    row = {"id": _id("LOAN"), "borrower": str(borrower or "客户"),
           "product": check["product"], "principal": check["amount"],
           "outstanding": check["amount"], "months": months, "rate": check["rate"],
           "status": "approved", "applied_at": _now(), "approved_at": _now(),
           "next_due": time.strftime("%Y-%m-%d", time.localtime(time.time()+30*86400)),
           "paid": 0.0, "interest_paid": 0.0, "principal_paid": 0.0,
           "collateral": {
               "type": str(collateral_type or ""),
               "amount": round(float(collateral_amount or 0), 2),
               "eligible_amount": round(float(eligible_amount or 0), 2),
               "ref": str(collateral_ref or ""),
               "status": "pending_pledge" if collateral_type else "none",
           }}
    s["loans"].append(row)
    if is_group:
        s["credit_group_used"] = round(float(s.get("credit_group_used") or 0) + float(row["principal"]), 2)
    _event(s, "loan_approved", loan=row["id"], borrower=row["borrower"], amount=row["principal"])
    save(data_dir, s)
    return {"ok": True, "loan": dict(row), "plan": check["plan"]}

def cancel_loan(data_dir: str, loan_id: str, reason: str = "cancelled") -> Dict[str, Any]:
    """取消尚未放款的贷款审批；释放动态授信占用。"""
    s = load(data_dir)
    for loan in s["loans"]:
        if loan.get("id") != loan_id:
            continue
        if loan.get("status") != "approved":
            return {"ok": False, "reason": "只有尚未放款的审批可以取消"}
        if "智脑" in str(loan.get("borrower") or "") or "计算" in str(loan.get("borrower") or ""):
            s["credit_group_used"] = round(max(0.0, float(s.get("credit_group_used") or 0) -
                                              float(loan.get("principal") or 0)), 2)
        loan["status"] = "cancelled"
        loan["cancel_reason"] = str(reason or "cancelled")
        _event(s, "loan_cancelled", loan=loan_id, reason=loan["cancel_reason"])
        save(data_dir, s)
        return {"ok": True, "loan": dict(loan)}
    return {"ok": False, "reason": "没有这笔贷款"}

def disburse(data_dir: str, loan_id: str) -> Dict[str, Any]:
    s = load(data_dir)
    for loan in s["loans"]:
        if loan.get("id") == loan_id:
            if loan.get("status") != "approved": return {"ok": False, "reason": "当前状态不能放款"}
            collateral = loan.get("collateral") or {}
            if collateral.get("type") and collateral.get("status") != "active":
                return {"ok": False, "reason": "应收质押尚未生效，不能放款"}
            amount = float(loan["principal"])
            if float(s["cash"].get("clearing") or 0) < amount:
                return {"ok": False, "reason": "清算头寸不足，暂不能放款"}
            loan["status"] = "active"; loan["disbursed_at"] = _now()
            s["cash"]["clearing"] = round(float(s["cash"].get("clearing") or 0) - amount, 2)
            _event(s, "loan_disbursed", loan=loan_id, amount=loan["principal"])
            save(data_dir, s); return {"ok": True, "loan": dict(loan)}
    return {"ok": False, "reason": "没有这笔贷款"}

def confirm_collateral(data_dir: str, loan_id: str) -> Dict[str, Any]:
    s = load(data_dir)
    for loan in s["loans"]:
        if loan.get("id") != loan_id:
            continue
        collateral = loan.get("collateral") or {}
        if not collateral.get("type"):
            return {"ok": True, "loan": dict(loan)}
        collateral["status"] = "active"
        loan["collateral"] = collateral
        _event(s, "collateral_pledged", loan=loan_id, type=collateral.get("type"),
               amount=collateral.get("amount"), ref=collateral.get("ref"))
        save(data_dir, s)
        return {"ok": True, "loan": dict(loan)}
    return {"ok": False, "reason": "没有这笔贷款"}

def repay(data_dir: str, loan_id: str, amount: float) -> Dict[str, Any]:
    s = load(data_dir); amount = round(float(amount or 0), 2)
    if amount <= 0: return {"ok": False, "reason": "还款金额必须大于 0"}
    for loan in s["loans"]:
        if loan.get("id") == loan_id:
            if loan.get("status") not in ("active", "approved"): return {"ok": False, "reason": "贷款不可还款"}
            outstanding = float(loan.get("outstanding") or 0)
            paid = min(amount, outstanding + max(0.0, outstanding * float(loan.get("rate") or 0) / 100.0 / 12.0))
            # 每次还款先付当期利息，再冲本金；本金才减少负债和集团授信占用。
            interest_due = round(outstanding * float(loan.get("rate") or 0) / 100.0 / 12.0, 2)
            interest_paid = min(paid, interest_due)
            principal_paid = min(outstanding, max(0.0, paid - interest_paid))
            loan["outstanding"] = round(outstanding - principal_paid, 2)
            loan["paid"] = round(float(loan.get("paid") or 0) + paid, 2)
            loan["interest_paid"] = round(float(loan.get("interest_paid") or 0) + interest_paid, 2)
            loan["principal_paid"] = round(float(loan.get("principal_paid") or 0) + principal_paid, 2)
            if "智脑" in str(loan.get("borrower") or "") or "计算" in str(loan.get("borrower") or ""):
                s["credit_group_used"] = round(max(0.0, float(s.get("credit_group_used") or 0) - principal_paid), 2)
            s["cash"]["clearing"] = round(float(s["cash"].get("clearing") or 0) + paid, 2)
            if loan["outstanding"] <= 0.01: loan["outstanding"] = 0.0; loan["status"] = "closed"
            _event(s, "loan_repaid", loan=loan_id, amount=paid, principal=principal_paid, interest=interest_paid,
                   outstanding=loan["outstanding"])
            save(data_dir, s); return {"ok": True, "loan": dict(loan), "paid": paid,
                                       "principal_paid": principal_paid, "interest_paid": interest_paid}
    return {"ok": False, "reason": "没有这笔贷款"}

def snapshot(data_dir: str) -> Dict[str, Any]:
    s = load(data_dir)
    active = [x for x in s["loans"] if x.get("status") in ("approved", "active")]
    overdue = [x for x in active if x.get("next_due") and x["next_due"] < time.strftime("%Y-%m-%d")]
    deposits = sum(float(x.get("principal") or 0) for x in s["deposits"] if x.get("status") == "active")
    loans = sum(float(x.get("outstanding") or 0) for x in active)
    clearing = round(float(s["cash"].get("clearing") or 0), 2)
    liquidity = "healthy" if clearing >= max(1000.0, loans * 0.10) else "tight"
    return {"bank": base.profile(), "accounts": len(s["accounts"]), "deposits_live": round(deposits,2),
            "loans_live": round(loans,2), "active_loans": len(active), "overdue_loans": len(overdue),
            "cash_clearing": clearing, "liquidity": liquidity,
            "credit_group_used": round(float(s.get("credit_group_used") or 0), 2),
            "credit_group_left": round(max(0.0, float(base.GROUP_CREDIT.get("line") or 0) - float(s.get("credit_group_used") or 0)), 2),
            "events": list(s["events"][-20:]), "state": s}

def reset(data_dir: str) -> Dict[str, Any]:
    s = {"accounts": [], "loans": [], "deposits": [], "events": [],
         "credit_group_used": float(base.GROUP_CREDIT.get("used") or 0),
         "cash": {"vault": 0.0, "clearing": 100000.0}}
    save(data_dir, s); return snapshot(data_dir)
