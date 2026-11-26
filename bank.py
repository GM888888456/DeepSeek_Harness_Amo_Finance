# -*- coding: utf-8 -*-
"""贵州发展银行：完整架构 + 对公/对私产品 + 企业信贷。

用户口径（2026-11-25）：金融不变，银行提供企业信贷服务，要有完整的架构。

本模块纯数据 + 纯函数，不落库、不发消息。金额单位：万元；利率是年化 %。

一笔企业贷的判定看三样：资产负债率、利息保障倍数、抵押物覆盖率。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

BANK = {
    "name": "中国邮政储蓄银行",
    "short": "邮储银行",
    "since": 1919,
    "type": "国有大型商业银行",
    "branches": 39800,
    "staff": 197000,
    "assets": 157000.0,          # 亿元
    "deposits": 132000.0,
    "loans": 86000.0,
    "npl": 0.83,               # 不良率 %
    "car": 13.6,               # 资本充足率 %
    "chair": "陆宗铭（董事长）",
    "president": "江馥宁（总行副行长，集团总裁的母亲）",
    "note": "网点最多的一家国有大行；中国计算智脑集团是它的重点客户，授信 3 亿。",
}

# 总行架构：部门 / 职责 / 负责人 / 编制
DEPARTMENTS = [
    {"name": "公司金融部", "head": "汤瑾", "headcount": 86,
     "duty": "对公存贷款、供应链、银承与保函", "kpi": "对公贷款新增 90 亿/年"},
    {"name": "零售金融部", "head": "舒桐", "headcount": 210,
     "duty": "房贷、车贷、消费贷、信用卡", "kpi": "零售 AUM 增长 15%"},
    {"name": "金融市场部", "head": "何书棠", "headcount": 64,
     "duty": "同业、债券、外汇、贵金属", "kpi": "交易账户收益 ≥ 6%"},
    {"name": "风险管理部", "head": "莫岚", "headcount": 58,
     "duty": "信用风险、市场风险、模型与压力测试", "kpi": "不良率 ≤ 1.5%"},
    {"name": "授信审批部", "head": "曾以宁", "headcount": 42,
     "duty": "授信审查、额度管理、审批会", "kpi": "审批时效 ≤ 5 个工作日"},
    {"name": "运营管理部", "head": "王小满", "headcount": 420,
     "duty": "柜面、清算、账户、网点运营", "kpi": "差错率 ≤ 0.02%"},
    {"name": "信息科技部", "head": "文竹", "headcount": 180,
     "duty": "核心系统、手机银行、数据平台、安全", "kpi": "可用性 ≥ 99.95%"},
    {"name": "合规与法务部", "head": "宋知微", "headcount": 36,
     "duty": "反洗钱、监管报送、合同与诉讼", "kpi": "监管处罚零发生"},
    {"name": "资产负债部", "head": "顾清源", "headcount": 28,
     "duty": "定价、流动性、资本管理", "kpi": "净息差 ≥ 1.9%"},
    {"name": "人力资源部", "head": "范允之", "headcount": 34,
     "duty": "编制、招聘、绩效、培训", "kpi": "关键岗到位 ≤ 45 天"},
]

# 利率表（年化 %）
RATES = {
    "LPR1Y": 3.10,
    "LPR5Y": 3.60,
    "存款活期": 0.20,
    "存款一年": 1.35,
    "存款三年": 1.90,
    "大额存单三年": 2.15,
    "企业流贷": 3.65,
    "企业固贷": 4.10,
    "科创信用贷": 3.20,
    "供应链融资": 3.45,
    "并购贷款": 4.60,
    "个人房贷": 3.40,
    "个人车贷": 3.90,
    "消费贷": 4.80,
    "信用卡分期": 12.60,
    "银承手续费": 0.05,
    "保函手续费": 0.30,
}

# 对公产品
CORPORATE = [
    {"name": "流动资金贷款", "limit": "≤ 5000 万", "term": "1~3 年", "rate": "3.65%",
     "need": "近两年盈利、负债率 ≤ 70%" , "note": "按季付息，到期还本"},
    {"name": "固定资产贷款", "limit": "≤ 2 亿", "term": "3~10 年", "rate": "4.10%",
     "need": "项目立项、环评、资本金 ≥ 30%", "note": "按项目进度提款"},
    {"name": "科创信用贷", "limit": "≤ 1000 万", "term": "1 年", "rate": "3.20%",
     "need": "高新技术企业、研发投入占比 ≥ 5%", "note": "免抵押，看专利与订单"},
    {"name": "供应链融资", "limit": "按应收 70%", "term": "≤ 1 年", "rate": "3.45%",
     "need": "核心企业确权", "note": "应收账款质押"},
    {"name": "银行承兑汇票", "limit": "≤ 3000 万", "term": "6 个月", "rate": "手续费 0.05%",
     "need": "保证金 30%~100%", "note": "可贴现"},
    {"name": "履约保函", "limit": "≤ 5000 万", "term": "按合同", "rate": "手续费 0.3%/年",
     "need": "授信额度内", "note": "政企投标常用"},
    {"name": "并购贷款", "limit": "≤ 交易价 60%", "term": "≤ 7 年", "rate": "4.60%",
     "need": "标的清晰、还款来源可测算", "note": "需报总行审批会"},
]

# 对私产品
RETAIL = [
    {"name": "个人住房贷款", "limit": "≤ 房价 80%", "term": "≤ 30 年", "rate": "3.40%",
     "note": "等额本息/等额本金可选"},
    {"name": "个人汽车贷款", "limit": "≤ 车价 80%", "term": "≤ 5 年", "rate": "3.90%",
     "note": "车抵，需保险"},
    {"name": "消费贷", "limit": "≤ 50 万", "term": "≤ 3 年", "rate": "4.80%",
     "note": "线上审批，T+1 到账"},
    {"name": "信用卡分期", "limit": "按额度", "term": "3~24 期", "rate": "12.60%",
     "note": "手续费折算年化，不便宜"},
    {"name": "大额存单", "limit": "20 万起", "term": "3 年", "rate": "2.15%",
     "note": "可转让、可质押"},
    {"name": "结构性存款", "limit": "1 万起", "term": "3~12 月", "rate": "1.5%~2.6%",
     "note": "保本浮动"},
]

# 股票池（她可以买卖的那几只）
STOCKS = [
    {"code": "600519", "name": "贵州茅台", "price": 1680.0, "sector": "白酒"},
    {"code": "300750", "name": "宁德时代", "price": 218.0, "sector": "新能源"},
    {"code": "688981", "name": "中芯国际", "price": 92.0, "sector": "半导体"},
    {"code": "002594", "name": "比亚迪", "price": 265.0, "sector": "汽车"},
    {"code": "600036", "name": "招商银行", "price": 38.0, "sector": "银行"},
    {"code": "002230", "name": "科大讯飞", "price": 46.0, "sector": "AI"},
]


def stock(code: str):
    code = str(code or "").strip()
    for s_ in STOCKS:
        if code in (s_["code"], s_["name"]) or code and code in s_["name"]:
            return dict(s_)
    return None


# 授信与风控口径
RISK = {
    "资产负债率": "≤ 70%（超过要抵押或担保）",
    "利息保障倍数": "≥ 3 倍",
    "抵押率": "厂房 60% / 土地 55% / 设备 40% / 应收 70%",
    "单户集中度": "≤ 资本净额 10%",
    "关联交易": "需董事会关联交易委员会前置",
    "审批链": "客户经理 → 授信审批部 → 风险总监 → 行长（超 5000 万上会）",
}

# 集团在这家行的授信（和 company.py 的口径对齐）
GROUP_CREDIT = {"line": 30000.0, "used": 6200.0, "rate": 3.65, "term": "3 年",
                "collateral": "应收账款质押 + 集团担保"}


def profile() -> Dict[str, Any]:
    row = dict(BANK)
    row["credit_group"] = dict(GROUP_CREDIT)
    return row


def departments() -> List[Dict[str, Any]]:
    return [dict(d) for d in DEPARTMENTS]


def products(kind: str = "") -> List[Dict[str, Any]]:
    kind = str(kind or "").lower()
    if kind in ("corporate", "对公", "企业"):
        return [dict(x) for x in CORPORATE]
    if kind in ("retail", "对私", "个人"):
        return [dict(x) for x in RETAIL]
    return [dict(x) for x in CORPORATE] + [dict(x) for x in RETAIL]


def rates() -> Dict[str, float]:
    return dict(RATES)


def annuity(principal: float, rate_pct: float, months: int) -> Dict[str, Any]:
    """等额本息：月供、总利息、还款表摘要。"""
    principal = max(0.0, float(principal or 0))
    months = max(1, int(months or 1))
    r = float(rate_pct or 0) / 100.0 / 12.0
    if r <= 0:
        pay = principal / months
        total = principal
    else:
        f = (1 + r) ** months
        pay = principal * r * f / (f - 1)
        total = pay * months
    return {
        "principal": round(principal, 2),
        "months": months,
        "rate": round(float(rate_pct or 0), 2),
        "monthly": round(pay, 2),
        "interest": round(total - principal, 2),
        "total": round(total, 2),
    }


def credit_apply(amount: float, months: int = 12, kind: str = "流动资金贷款",
                 debt_ratio: float = 52.0, collateral_cover: float = 1.2,
                 group: bool = True) -> Dict[str, Any]:
    """企业信贷审批小模型：给结论，不吹。

    参数都是她能看懂的：借多少、几年、负债率、抵押覆盖倍数。
    """
    amount = float(amount or 0)
    months = max(3, int(months or 12))
    table = {p["name"]: p for p in CORPORATE}
    product = table.get(kind) or CORPORATE[0]
    rate = float(str(product["rate"]).replace("%", "").split()[0].replace("手续费", "").strip() or RATES["企业流贷"])
    if kind == "银行承兑汇票":
        rate = RATES["企业流贷"]          # 银承按贴现代价估
    plan = annuity(amount, rate, months)

    reasons = []
    approved = True
    if debt_ratio > 70:
        approved = False
        reasons.append("资产负债率 %.0f%% 超过 70%% 红线" % float(debt_ratio))
    if collateral_cover < 0.8 and "信用" not in kind:
        approved = False
        reasons.append("抵押覆盖率 %.2f 不足 0.8" % float(collateral_cover))
    if group:
        left = float(GROUP_CREDIT["line"]) - float(GROUP_CREDIT["used"])
        if amount > left:
            approved = False
            reasons.append("集团授信只剩 %.0f 万，不够 %.0f 万" % (left, amount))
    if kind == "科创信用贷" and amount > 1000:
        approved = False
        reasons.append("科创信用贷单笔上限 1000 万")

    if approved:
        verdict = "可以批"
        reasons.append("负债率、覆盖倍数、授信额度都在口径内")
    else:
        verdict = "批不了（或要加条件）"

    return {
        "ok": approved,
        "verdict": verdict,
        "product": product["name"],
        "amount": round(amount, 2),
        "rate": rate,
        "plan": plan,
        "reasons": reasons,
        "conditions": [
            "按季付息，到期还本" if months <= 36 else "按项目进度提款",
            "抵押物需评估并办登记" if "信用" not in kind else "需高新技术企业证书",
        ],
    }


def outline() -> Dict[str, Any]:
    return {
        "bank": profile(),
        "departments": [{"name": d["name"], "head": d["head"], "headcount": d["headcount"],
                         "duty": d["duty"], "kpi": d["kpi"]} for d in DEPARTMENTS],
        "rates": dict(RATES),
        "corporate": len(CORPORATE),
        "retail": len(RETAIL),
        "risk": RISK,
    }


if __name__ == "__main__":   # python3 bank.py
    import json
    print(json.dumps(credit_apply(2000, 24, "流动资金贷款", 52, 1.2), ensure_ascii=False)[:420])
    print(json.dumps(outline()["bank"], ensure_ascii=False)[:260])
