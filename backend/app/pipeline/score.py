import re
from datetime import datetime, timezone

SCORE_VERSION = "2026-10-22.1"

WEIGHTS = {
    "product_fit": 0.30,
    "buyer_intent": 0.20,
    "scale": 0.15,
    "reachability": 0.15,
    "geo_logistics": 0.10,
    "strategic_fit": 0.10,
}

STATE_SCORES = {"SP": 60, "PR": 55, "SC": 50, "MG": 45, "RS": 40, "DF": 35}
SIZE_SCORES = {"large": 40, "medium": 30, "small": 18, "micro": 8, "unknown": 10}
SALES_ROLES = {"sales", "contact"}


def _contains(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def _years(company: dict) -> int:
    notes = (company.get("notes") or "").lower()
    m = re.search(r"(\d{1,3})\s*\+?\s*anos", notes)
    if m:
        return int(m.group(1))
    m = re.search(r"desde\s+(19\d{2}|20\d{2})", notes)
    if m:
        return max(0, datetime.now(timezone.utc).year - int(m.group(1)))
    founded = company.get("founded_at") or ""
    if re.match(r"^\d{4}", founded):
        return max(0, datetime.now(timezone.utc).year - int(founded[:4]))
    return 0


def _product_fit(company: dict) -> tuple[float, list[str]]:
    products = set(company.get("products", []))
    grades = set(company.get("grades", []))
    text = " ".join([company.get("notes") or "", company.get("import_signals") or ""]).lower()

    flat_forms = {"chapas", "bobinas", "tiras", "blanks"}
    long_forms = {"barras", "perfis", "cantoneiras"}
    if products & flat_forms:
        form_score = 40
    elif products & long_forms:
        form_score = 35
    elif products:
        form_score = 20
    else:
        form_score = 0

    grade_score = 20 if len(grades) >= 2 else 12 if grades else (6 if "inox" in text else 0)
    stock_score = 15 if _contains(text, ["estoque", "pronta entrega", "pronta-entrega"]) else (8 if products else 0)
    process_score = 10 if _contains(
        text, ["beneficiamento", "corte", "slitter", "polimento", "escovamento", "caldeiraria", "plasma", "laser"]
    ) else 3
    apps = company.get("applications", [])
    app_score = 15 if len(apps) >= 2 else 8 if len(apps) == 1 else 0

    score = form_score + grade_score + stock_score + process_score + app_score
    reasons = []
    if products & flat_forms:
        reasons.append("产品含平板类（chapas/bobinas/tiras）")
    elif products & long_forms:
        reasons.append("产品含型材类（barras/perfis）")
    if len(grades) >= 3:
        reasons.append(f"覆盖 {len(grades)} 个不锈钢牌号")
    if stock_score == 15:
        reasons.append("有库存/现货信号")
    if process_score == 10:
        reasons.append("具备加工/beneficiamento 能力")
    return min(100, score), reasons


def _buyer_intent(company: dict) -> tuple[float, list[str]]:
    text = " ".join(
        [
            company.get("notes") or "",
            company.get("import_signals") or "",
            company.get("display_name") or "",
        ]
    ).lower()
    primary = company.get("primary_type")
    import_word = _contains(text, ["importador", "importadora", "importação", "importacao", "importado", "importing"])
    distributor = _contains(text, ["distribuidor", "distribuidora", "atacadista"]) or primary in {
        "importer_distributor",
        "service_center",
    }
    trade_data = bool(company.get("trade_signals"))
    foreign = _contains(text, ["aperam", "outokumpu", "acerinox", "importado da", "importado de"])

    score = 0
    reasons = []
    if import_word:
        score += 40
        reasons.append("明确进口信号")
    elif primary == "trader":
        score += 30
        reasons.append("贸易商角色")
    elif primary in {"importer_distributor", "service_center"}:
        score += 25
        reasons.append("分销/服务中心角色")
    if trade_data:
        score += 30
        reasons.append("有贸易/提单数据")
    if foreign:
        score += 15
        reasons.append("提到外国钢厂/进口来源")
    if distributor:
        score += 15
        reasons.append("分销/批发定位")

    if not trade_data:
        score = min(score, 70)
    return min(100, score), reasons


def _scale(company: dict) -> tuple[float, list[str]]:
    size = company.get("size_bucket") or "unknown"
    score = SIZE_SCORES.get(size, 10)
    reasons = []
    if size in {"large", "medium"}:
        reasons.append(f"规模：{size}")

    notes = (company.get("notes") or "").lower()
    if _contains(notes, ["unidades", "unidade", "filiais", "frota"]):
        score += 20
        reasons.append("多分支/自有物流")
    elif _contains(notes, ["atuação nacional", "atende todo brasil", "todo o brasil"]):
        score += 14
        reasons.append("全国覆盖")
    elif "grupo" in notes:
        score += 14
        reasons.append("集团多主体")
    else:
        score += 5

    years = _years(company)
    if years >= 30:
        score += 15
        reasons.append(f"经营 {years} 年")
    elif years >= 15:
        score += 12
    elif years >= 5:
        score += 8
    elif years > 0:
        score += 3

    score += 5  # capital unknown: neutral
    score += 1  # places unknown: neutral
    return min(100, score), reasons


def _reachability(company: dict) -> tuple[float, list[str]]:
    emails = company.get("emails", [])
    phones = company.get("phones", [])
    score = 0
    reasons = []
    if emails:
        roles = {e.get("role") for e in emails}
        if roles & SALES_ROLES:
            score += 50
            reasons.append("有销售/联系业务邮箱")
        elif "info" in roles:
            score += 35
            reasons.append("有 info 邮箱")
        else:
            score += 20
            reasons.append("有邮箱")
    if phones:
        score += 25
        reasons.append("有电话/WhatsApp")
    if company.get("has_contact_form"):
        score += 10
        reasons.append("有联系表单")
    if company.get("social_links"):
        score += 15
        reasons.append("有 LinkedIn/社交主页")
    if company.get("website"):
        score += 5
    return min(100, score), reasons


def _geo(company: dict) -> tuple[float, list[str]]:
    state = (company.get("state") or "").upper()
    score = STATE_SCORES.get(state, 25)
    score += {"SP": 25, "PR": 25, "SC": 25, "RS": 25, "MG": 15, "DF": 5}.get(state, 5)
    notes = (company.get("notes") or "").lower()
    reasons = [f"州：{state or '未知'}"] if state else []
    if _contains(notes, ["nacional", "todo o brasil", "frota"]):
        score += 15
        reasons.append("全国/物流覆盖")
    else:
        score += 5
    return min(100, score), reasons


def _strategic(company: dict) -> tuple[float, list[str]]:
    apps = company.get("applications", [])
    text = " ".join([company.get("notes") or "", company.get("import_signals") or ""]).lower()
    score = 50 if len(apps) >= 2 else 30 if len(apps) == 1 else 0
    reasons = []
    if len(apps) >= 2:
        reasons.append(f"下游行业匹配：{', '.join(apps[:4])}")
    if _contains(text, ["iso 9001", "petrobras", "asme", "astm", "crc"]):
        score += 25
        reasons.append("有认证/资质")
    if _contains(text, ["expansão", "expansao", "nova fábrica", "nova fabrica", "investimento", "contratando"]):
        score += 25
        reasons.append("有增长信号")
    if _contains(text, ["líder", "lider", "maior estoque", "um dos maiores"]):
        score += 10
        reasons.append("区域/品类领先")
    return min(100, score), reasons


def score_company(company: dict) -> dict:
    product, r1 = _product_fit(company)
    buyer, r2 = _buyer_intent(company)
    scale, r3 = _scale(company)
    reach, r4 = _reachability(company)
    geo, r5 = _geo(company)
    strategic, r6 = _strategic(company)

    total = (
        product * WEIGHTS["product_fit"]
        + buyer * WEIGHTS["buyer_intent"]
        + scale * WEIGHTS["scale"]
        + reach * WEIGHTS["reachability"]
        + geo * WEIGHTS["geo_logistics"]
        + strategic * WEIGHTS["strategic_fit"]
    )
    total = int(round(total))

    if company.get("primary_type") in {"mill_producer", "recycler"}:
        total = min(total, 20)
    if not company.get("emails") and not company.get("phones"):
        total = min(total, 50)
    if not company.get("website") and not company.get("cnpj"):
        total = min(total, 45)
    if company.get("primary_type") == "other":
        total = min(total, 40)

    if total >= 75:
        tier = "A"
    elif total >= 55:
        tier = "B"
    elif total >= 35:
        tier = "C"
    else:
        tier = "D"

    reasons = (
        [f"类型：{company.get('primary_type')}"]
        + r1[:2]
        + r2[:2]
        + r3[:1]
        + r4[:1]
        + r5[:1]
        + r6[:1]
    )
    return {
        "total": total,
        "tier": tier,
        "product_fit": round(product, 1),
        "buyer_intent": round(buyer, 1),
        "scale": round(scale, 1),
        "reachability": round(reach, 1),
        "geo_logistics": round(geo, 1),
        "strategic_fit": round(strategic, 1),
        "breakdown": {
            "product_fit": round(product, 1),
            "buyer_intent": round(buyer, 1),
            "scale": round(scale, 1),
            "reachability": round(reach, 1),
            "geo_logistics": round(geo, 1),
            "strategic_fit": round(strategic, 1),
        },
        "reasons": reasons,
        "score_version": SCORE_VERSION,
    }
