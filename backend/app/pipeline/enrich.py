import httpx

from ..config import HTTP_TIMEOUT
from .discovery import canonical_domain

PORTE_MAP = {
    "MEI": "micro",
    "MICRO": "micro",
    "PEQUENA": "small",
    "MEDIA": "medium",
    "DEMAIS": "large",
}


def lookup_cnpj(cnpj: str) -> dict | None:
    if not cnpj:
        return None
    digits = "".join(ch for ch in cnpj if ch.isdigit())
    if len(digits) != 14:
        return None
    try:
        resp = httpx.get(
            f"https://brasilapi.com.br/api/cnpj/v1/{digits}",
            timeout=min(HTTP_TIMEOUT, 6),
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None
    return {
        "legal_name": data.get("razao_social"),
        "trade_name": data.get("nome_fantasia"),
        "registry_status": data.get("descricao_situacao_cadastral"),
        "founded_at": data.get("data_inicio_atividade"),
        "cnae": [str(data.get("cnae_fiscal"))] if data.get("cnae_fiscal") else [],
        "cnae_desc": [data.get("cnae_fiscal_descricao")] if data.get("cnae_fiscal_descricao") else [],
        "address": " ".join(
            x
            for x in [
                data.get("logradouro"),
                data.get("numero"),
                data.get("bairro"),
            ]
            if x
        ),
        "city": data.get("municipio"),
        "state": data.get("uf"),
        "postal_code": data.get("cep"),
        "size_bucket": PORTE_MAP.get(str(data.get("porte") or "").upper()),
        "capital_social": data.get("capital_social"),
    }


def enrich_run(run_id: str, companies: list[dict], conn) -> dict:
    enriched = []
    for company in companies:
        cnpj = company.get("cnpj")
        registry = lookup_cnpj(cnpj) if cnpj else None
        if registry:
            company["legal_name"] = registry.get("legal_name") or company.get("legal_name")
            company["registry_status"] = registry.get("registry_status") or "unverified"
            if registry.get("state"):
                company["state"] = registry["state"]
            if registry.get("city"):
                company["city"] = registry["city"]
            if registry.get("address"):
                company["address"] = registry["address"]
            if registry.get("postal_code"):
                company["postal_code"] = registry["postal_code"]
            if registry.get("size_bucket"):
                company["size_bucket"] = registry["size_bucket"]
            if registry.get("founded_at"):
                company["founded_at"] = registry["founded_at"]
            company["cnae"] = registry.get("cnae", [])
            company["cnae_desc"] = registry.get("cnae_desc", [])
        else:
            company["registry_status"] = "unverified"

        domains = list(company.get("domains") or [])
        site_domain = canonical_domain(company.get("website") or "")
        for email in company.get("emails", []):
            email_domain = canonical_domain("https://" + email["value"].split("@", 1)[-1])
            if email_domain and email_domain != site_domain and email_domain not in domains:
                domains.append(email_domain)
                company.setdefault("email_domains", []).append(email_domain)
        company["domains"] = [d for d in dict.fromkeys(domains) if d]

        aliases = list(company.get("aliases") or [])
        if company.get("legal_name") and company["legal_name"] not in aliases:
            aliases.append(company["legal_name"])
        if company.get("display_name") and company["display_name"] not in aliases:
            aliases.append(company["display_name"])
        company["aliases"] = list(dict.fromkeys(aliases))
        enriched.append(company)
    return {"enriched": len(enriched), "companies": enriched}
