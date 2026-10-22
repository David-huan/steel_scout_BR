VALID_TYPES = {
    "importer_distributor",
    "service_center",
    "fabricator",
    "end_user",
    "trader",
    "mill_producer",
    "recycler",
    "other",
}

TYPE_ZH = {
    "importer_distributor": "进口商/分销商",
    "service_center": "加工服务中心",
    "fabricator": "制造商",
    "end_user": "终端用户",
    "trader": "贸易商",
    "mill_producer": "钢厂/生产者",
    "recycler": "回收/废料",
    "other": "其他",
}


def _text(company: dict) -> str:
    return " ".join(
        str(x)
        for x in [
            company.get("display_name"),
            company.get("notes"),
            company.get("import_signals"),
            " ".join(company.get("products", [])),
        ]
        if x
    ).lower()


def classify(company: dict) -> dict:
    hint = (company.get("type_hint") or "").strip()
    secondary = [t for t in company.get("secondary_types", []) if t in VALID_TYPES and t != hint]
    text = _text(company)
    method = "rule"
    confidence = 0.7

    if hint in VALID_TYPES:
        primary = hint
        confidence = 0.9
        method = "curated_hint"
    elif any(w in text for w in ("sucata", "reciclagem", "ferro-velho")):
        primary = "recycler"
        confidence = 0.9
    elif any(w in text for w in ("usina", "siderúrgica", "siderurgica", "produtor de aço")):
        primary = "mill_producer"
        confidence = 0.85
    elif any(w in text for w in ("importador", "importadora", "importação", "importacao")):
        primary = "importer_distributor"
        confidence = 0.85
    elif any(w in text for w in ("centro de serviço", "beneficiamento", "slitter", "caldeiraria")):
        primary = "service_center"
        confidence = 0.8
    elif any(w in text for w in ("distribuidor", "distribuidora", "atacadista", "estoque")):
        primary = "importer_distributor"
        confidence = 0.75
    elif any(w in text for w in ("fabricante", "fabricação", "fabricacao", "indústria", "industria")):
        primary = "fabricator"
        confidence = 0.75
    elif any(w in text for w in ("trading", "representação", "representacao", "agente")):
        primary = "trader"
        confidence = 0.7
    else:
        primary = "other"
        confidence = 0.35

    if primary == "mill_producer" or primary == "recycler":
        status = "excluded"
    elif company.get("registry_status") in {"BAIXADA", "INAPTA", "SUSPENSA", "NULA"}:
        status = "inactive"
    else:
        status = "active"

    quote = company.get("import_signals") or company.get("notes") or ""
    return {
        "primary_type": primary,
        "secondary_types": secondary,
        "type_confidence": round(confidence, 2),
        "method": method,
        "status": status,
        "reasons": [f"类型依据：{TYPE_ZH.get(primary, primary)}"]
        + ([f"原文信号：{quote[:160]}"] if quote else []),
        "evidence": (
            [
                {
                    "field": "customer_type",
                    "value": primary,
                    "quote": quote[:300],
                    "source_url": company.get("website"),
                    "extractor": method,
                    "confidence": confidence,
                }
            ]
            if quote
            else []
        ),
    }
