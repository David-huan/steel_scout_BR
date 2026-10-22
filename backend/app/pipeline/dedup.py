import copy
import json
import re
import unicodedata
from collections import defaultdict

from rapidfuzz import fuzz

from ..db import add_event, dumps, new_id, utcnow
from .classify import classify
from .score import score_company

LEGAL = {"ltda", "ltd", "sa", "s/a", "s.a", "me", "eireli", "mei", "slu"}
GENERIC = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "comercio",
    "comércio",
    "industria",
    "indústria",
    "distribuidora",
    "distribuicao",
    "distribuição",
    "importadora",
    "importacao",
    "importação",
    "representacoes",
    "representações",
    "materiais",
    "metais",
}


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " e ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t not in LEGAL and t not in GENERIC]
    return " ".join(tokens)


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a, b) / 100.0


def _set(values) -> set:
    return {v for v in (values or []) if v}


def _pair_features(a: dict, b: dict) -> dict:
    name_sim = _sim(a.get("normalized_name", ""), b.get("normalized_name", ""))
    domains_a = _set(a.get("domains"))
    domains_b = _set(b.get("domains"))
    phones_a = {p["e164"] for p in a.get("phones", []) if p.get("e164")}
    phones_b = {p["e164"] for p in b.get("phones", []) if p.get("e164")}
    emails_a = {e["value"] for e in a.get("emails", []) if e.get("value")}
    emails_b = {e["value"] for e in b.get("emails", []) if e.get("value")}
    domain_match = bool(domains_a & domains_b)
    phone_match = bool(phones_a & phones_b)
    email_match = bool(emails_a & emails_b)
    state_match = bool(a.get("state") and a.get("state") == b.get("state"))
    city_match = bool(a.get("city") and a.get("city") == b.get("city"))
    address_sim = _sim(
        normalize_name(a.get("address") or ""), normalize_name(b.get("address") or "")
    )
    cnpj_match = bool(a.get("cnpj") and a.get("cnpj") == b.get("cnpj"))

    score = (
        0.45 * name_sim
        + 0.20 * (1.0 if domain_match else 0.0)
        + 0.15 * (1.0 if phone_match else 0.0)
        + 0.10 * address_sim
        + 0.10 * (1.0 if state_match else 0.0)
    )
    if email_match:
        score = max(score, 0.96)
    if cnpj_match:
        score = max(score, 1.0)

    return {
        "name_sim": round(name_sim, 3),
        "domain_match": domain_match,
        "phone_match": phone_match,
        "email_match": email_match,
        "state_match": state_match,
        "city_match": city_match,
        "address_sim": round(address_sim, 3),
        "cnpj_match": cnpj_match,
        "score": round(score, 3),
    }


def _decide(features: dict) -> tuple[str, list[str], float]:
    name_sim = features["name_sim"]
    reasons = []
    if features["cnpj_match"]:
        return "auto_merge", ["CNPJ 完全一致"], 1.0
    if features["domain_match"]:
        return "auto_merge", ["注册域一致"], max(features["score"], 0.98)
    if features["email_match"]:
        return "auto_merge", ["邮箱完全一致"], max(features["score"], 0.96)
    if features["phone_match"] and name_sim >= 0.6:
        return "auto_merge", ["电话一致且名称相似"], max(features["score"], 0.95)
    if name_sim >= 0.92 and features["state_match"] and (
        features["phone_match"] or features["address_sim"] >= 0.8
    ):
        return "auto_merge", ["名称高度相似且地址/电话一致"], max(features["score"], 0.95)
    if name_sim >= 0.92 and not features["state_match"]:
        return "review", ["名称高度相似但州不同"], features["score"]
    if 0.85 <= name_sim < 0.92 and features["state_match"]:
        return "review", ["名称较相似且同州"], features["score"]
    return "distinct", [], features["score"]


class _UF:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _completeness(company: dict) -> float:
    return (
        len(company.get("emails", [])) * 3
        + len(company.get("phones", [])) * 2
        + (2 if company.get("address") else 0)
        + len(company.get("products", []))
        + len(company.get("grades", [])) * 0.5
        + (2 if company.get("size_bucket") not in (None, "", "unknown") else 0)
        + (1 if company.get("cnpj") else 0)
        + (1 if company.get("type_hint") else 0)
    )


def _merge_group(base: dict, others: list[dict]) -> dict:
    merged = copy.deepcopy(base)
    for other in others:
        merged["aliases"] = list(
            dict.fromkeys(
                (merged.get("aliases") or [])
                + (other.get("aliases") or [])
                + [other.get("display_name")]
            )
        )
        merged["domains"] = list(dict.fromkeys((merged.get("domains") or []) + (other.get("domains") or [])))
        merged["products"] = sorted(set(merged.get("products") or []) | set(other.get("products") or []))
        merged["grades"] = sorted(set(merged.get("grades") or []) | set(other.get("grades") or []))
        merged["applications"] = sorted(
            set(merged.get("applications") or []) | set(other.get("applications") or [])
        )
        merged["secondary_types"] = list(
            dict.fromkeys(
                (merged.get("secondary_types") or []) + (other.get("secondary_types") or [])
            )
        )
        for key in ("address", "postal_code", "city", "state"):
            if not merged.get(key) and other.get(key):
                merged[key] = other[key]
        if merged.get("size_bucket") in (None, "", "unknown") and other.get("size_bucket") not in (None, "", "unknown"):
            merged["size_bucket"] = other["size_bucket"]
        if not merged.get("cnpj") and other.get("cnpj"):
            merged["cnpj"] = other["cnpj"]
        if not merged.get("type_hint") and other.get("type_hint"):
            merged["type_hint"] = other["type_hint"]
        if other.get("import_signals"):
            merged["import_signals"] = " | ".join(
                [x for x in [merged.get("import_signals"), other["import_signals"]] if x]
            )
        if other.get("notes") and other["notes"] not in (merged.get("notes") or ""):
            merged["notes"] = " | ".join([x for x in [merged.get("notes"), other["notes"]] if x])
        merged["sources"] = (merged.get("sources") or []) + (other.get("sources") or [])
        merged["has_contact_form"] = bool(merged.get("has_contact_form")) or bool(other.get("has_contact_form"))
        merged["social_links"] = list(
            dict.fromkeys((merged.get("social_links") or []) + (other.get("social_links") or []))
        )

    merged["emails"] = list(
        {e["value"]: e for e in (merged.get("emails") or [])}.values()
    )
    merged["phones"] = list(
        {p["e164"]: p for p in (merged.get("phones") or [])}.values()
    )
    merged["aliases"] = [a for a in dict.fromkeys(merged.get("aliases") or []) if a]
    return merged


def _find_existing(conn, company: dict) -> str | None:
    for domain in company.get("domains") or []:
        row = conn.execute(
            "SELECT cd.company_id FROM company_domains cd JOIN companies c ON c.id=cd.company_id "
            "WHERE cd.domain=? AND c.status='active' LIMIT 1",
            (domain,),
        ).fetchone()
        if row:
            return row[0]
    for phone in company.get("phones", []):
        row = conn.execute(
            "SELECT cp.company_id FROM company_phones cp JOIN companies c ON c.id=cp.company_id "
            "WHERE cp.e164=? AND c.status='active' LIMIT 1",
            (phone.get("e164"),),
        ).fetchone()
        if row:
            return row[0]
    for email in company.get("emails", []):
        row = conn.execute(
            "SELECT ce.company_id FROM company_emails ce JOIN companies c ON c.id=ce.company_id "
            "WHERE ce.email=? AND c.status='active' LIMIT 1",
            (email.get("value"),),
        ).fetchone()
        if row:
            return row[0]
    if company.get("normalized_name") and company.get("state"):
        row = conn.execute(
            "SELECT ca.company_id FROM company_aliases ca JOIN companies c ON c.id=ca.company_id "
            "WHERE ca.alias_norm=? AND c.state=? AND c.status='active' LIMIT 1",
            (company["normalized_name"], company["state"]),
        ).fetchone()
        if row:
            return row[0]
    return None


def _upsert_company(conn, company: dict, run_id: str, score: dict) -> tuple[str, int]:
    now = utcnow()
    existing = _find_existing(conn, company)
    if existing:
        company_id = existing
        conn.execute(
            """
            UPDATE companies SET last_seen_at=?, updated_at=?,
              address=COALESCE(NULLIF(address,''), ?),
              city=COALESCE(NULLIF(city,''), ?),
              state=COALESCE(NULLIF(state,''), ?),
              postal_code=COALESCE(NULLIF(postal_code,''), ?),
              size_bucket=CASE WHEN size_bucket IN ('','unknown') OR size_bucket IS NULL THEN ? ELSE size_bucket END,
              primary_type=COALESCE(primary_type, ?),
              type_confidence=COALESCE(type_confidence, ?)
            WHERE id=?
            """,
            (
                now,
                now,
                company.get("address"),
                company.get("city"),
                company.get("state"),
                company.get("postal_code"),
                company.get("size_bucket"),
                company.get("primary_type"),
                company.get("type_confidence"),
                company_id,
            ),
        )
        add_event(
            conn,
            "history_match",
            run_id=run_id,
            company_id=company_id,
            payload={"name": company.get("display_name"), "domains": company.get("domains")},
        )
    else:
        company_id = new_id("cmp")
        conn.execute(
            """
            INSERT INTO companies (id, display_name, legal_name, website, cnpj, registry_status,
              address, city, state, postal_code, country, size_bucket, primary_type,
              secondary_types_json, type_confidence, status, dedup_status, review_status,
              notes, first_seen_at, last_seen_at, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                company_id,
                company.get("display_name") or "Unknown",
                company.get("legal_name"),
                company.get("website"),
                company.get("cnpj"),
                company.get("registry_status") or "unverified",
                company.get("address"),
                company.get("city"),
                company.get("state"),
                company.get("postal_code"),
                "BR",
                company.get("size_bucket") or "unknown",
                company.get("primary_type"),
                dumps(company.get("secondary_types", [])),
                company.get("type_confidence"),
                company.get("status") or "active",
                company.get("dedup_status") or "unique",
                "new",
                company.get("notes"),
                now,
                now,
                now,
                now,
            ),
        )

    for alias in company.get("aliases", []):
        if not alias:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO company_aliases (company_id, alias, alias_norm, source, created_at) VALUES (?,?,?,?,?)",
            (company_id, alias, normalize_name(alias), "pipeline", now),
        )
    for i, domain in enumerate(company.get("domains", [])):
        conn.execute(
            "INSERT OR IGNORE INTO company_domains (company_id, domain, kind, is_primary, source, first_seen_at) VALUES (?,?,?,?,?,?)",
            (company_id, domain, "website", 1 if i == 0 else 0, "pipeline", now),
        )
    for email in company.get("emails", []):
        conn.execute(
            "INSERT OR IGNORE INTO company_emails (company_id, email, role, source, source_url, first_seen_at) VALUES (?,?,?,?,?,?)",
            (
                company_id,
                email["value"],
                email.get("role"),
                email.get("source"),
                email.get("source_url"),
                now,
            ),
        )
    for phone in company.get("phones", []):
        conn.execute(
            "INSERT OR IGNORE INTO company_phones (company_id, e164, type, source) VALUES (?,?,?,?)",
            (company_id, phone["e164"], phone.get("type"), phone.get("source_url")),
        )
    for form in company.get("products", []):
        conn.execute(
            "INSERT OR IGNORE INTO company_products (company_id, form, grades_json, quote, source_url, confidence) VALUES (?,?,?,?,?,?)",
            (
                company_id,
                form,
                dumps(company.get("grades", [])),
                company.get("import_signals"),
                company.get("website") or "",
                0.8,
            ),
        )
    if company.get("has_contact_form"):
        conn.execute(
            "INSERT OR IGNORE INTO company_sources (company_id, field, value, quote, source_url, extractor, confidence, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                company_id,
                "contact_form",
                "yes",
                "contact form present on page",
                company.get("website") or "",
                "html_rule",
                0.8,
                now,
            ),
        )
    if company.get("social_links"):
        conn.execute(
            "INSERT OR IGNORE INTO company_sources (company_id, field, value, quote, source_url, extractor, confidence, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                company_id,
                "social",
                "; ".join(company["social_links"]),
                company["social_links"][0],
                company["social_links"][0],
                "html_rule",
                0.9,
                now,
            ),
        )
    if company.get("applications"):
        conn.execute(
            "INSERT OR IGNORE INTO company_sources (company_id, field, value, quote, source_url, extractor, confidence, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                company_id,
                "applications",
                "; ".join(company["applications"]),
                company.get("import_signals") or "; ".join(company["applications"]),
                company.get("website") or "",
                "rule",
                0.75,
                now,
            ),
        )
    for source in company.get("sources", []):
        conn.execute(
            "INSERT OR IGNORE INTO company_sources (company_id, field, value, quote, source_url, extractor, confidence, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                company_id,
                source.get("field"),
                source.get("value"),
                source.get("quote"),
                source.get("source_url") or "",
                source.get("extractor"),
                source.get("confidence", 0.5),
                now,
            ),
        )

    cur = conn.execute(
        """
        INSERT INTO scores (company_id, run_id, total, tier, product_fit, buyer_intent, scale,
          reachability, geo_logistics, strategic_fit, breakdown_json, reasons_json,
          score_version, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            company_id,
            run_id,
            score["total"],
            score["tier"],
            score["product_fit"],
            score["buyer_intent"],
            score["scale"],
            score["reachability"],
            score["geo_logistics"],
            score["strategic_fit"],
            dumps(score["breakdown"]),
            dumps(score["reasons"]),
            score["score_version"],
            now,
        ),
    )
    score_id = cur.lastrowid
    conn.execute(
        "INSERT OR REPLACE INTO run_companies (run_id, company_id, score_id, candidate_id, dedup_status) VALUES (?,?,?,?,?)",
        (run_id, company_id, score_id, company.get("candidate_id"), company.get("dedup_status") or "unique"),
    )
    return company_id, score_id


def dedup_run(run_id: str, companies: list[dict], conn) -> dict:
    for company in companies:
        company["normalized_name"] = normalize_name(company.get("display_name") or "")
        company.setdefault("aliases", [])
        if company.get("display_name") and company["display_name"] not in company["aliases"]:
            company["aliases"].append(company["display_name"])

    n = len(companies)
    uf = _UF(n)
    review_pairs: list[tuple[int, int, dict, list[str], float]] = []
    auto_reasons: list[str] = []

    for i in range(n):
        for j in range(i + 1, n):
            features = _pair_features(companies[i], companies[j])
            decision, reasons, score = _decide(features)
            if decision == "auto_merge":
                uf.union(i, j)
                auto_reasons.append(f"{companies[i]['display_name']} ↔ {companies[j]['display_name']}: {'; '.join(reasons)}")
            elif decision == "review":
                review_pairs.append((i, j, features, reasons, score))

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(n):
        groups[uf.find(idx)].append(idx)

    persisted: dict[int, str] = {}
    canonical_infos = []
    auto_merged_count = 0

    for root, indices in groups.items():
        members = [companies[i] for i in indices]
        base = max(members, key=_completeness)
        others = [m for m in members if m is not base]
        merged = _merge_group(base, others) if others else copy.deepcopy(base)
        auto_merged_count += len(others)
        merged["display_name"] = merged.get("display_name") or base.get("display_name")
        merged["normalized_name"] = normalize_name(merged["display_name"])
        merged["dedup_status"] = "merged" if others else "unique"

        cls = classify(merged)
        merged.update(
            {
                "primary_type": cls["primary_type"],
                "secondary_types": cls["secondary_types"],
                "type_confidence": cls["type_confidence"],
                "status": cls["status"],
            }
        )
        sc = score_company(merged)
        merged["score"] = sc
        company_id, score_id = _upsert_company(conn, merged, run_id, sc)
        for idx in indices:
            persisted[idx] = company_id
        canonical_infos.append(
            {
                "company_id": company_id,
                "display_name": merged["display_name"],
                "merged_names": [m["display_name"] for m in others],
                "score": sc,
            }
        )
        if others:
            add_event(
                conn,
                "auto_merge",
                run_id=run_id,
                company_id=company_id,
                payload={
                    "merged_names": [m.get("display_name") for m in others],
                    "reasons": auto_reasons[:10],
                },
            )

    for i, j, features, reasons, score in review_pairs:
        left, right = persisted.get(i), persisted.get(j)
        if not left or not right or left == right:
            continue
        pair_id = new_id("ddp")
        conn.execute(
            """
            INSERT OR IGNORE INTO dedup_pairs (id, run_id, left_company_id, right_company_id, score,
              decision, status, features_json, reasons_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pair_id,
                run_id,
                left,
                right,
                score,
                "review",
                "pending",
                dumps(features),
                dumps(reasons),
                utcnow(),
            ),
        )
        conn.execute(
            "UPDATE companies SET dedup_status='review' WHERE id IN (?,?)", (left, right)
        )
        conn.execute(
            "UPDATE run_companies SET dedup_status='review' WHERE run_id=? AND company_id IN (?,?)",
            (run_id, left, right),
        )

    conn.commit()

    stats = {
        "companies": len(canonical_infos),
        "candidates": n,
        "auto_merged": auto_merged_count,
        "review_pairs": len(review_pairs),
        "emails": conn.execute(
            "SELECT COUNT(DISTINCT ce.company_id) FROM company_emails ce JOIN run_companies rc ON rc.company_id=ce.company_id WHERE rc.run_id=?",
            (run_id,),
        ).fetchone()[0],
        "tier_a": conn.execute(
            "SELECT COUNT(*) FROM scores WHERE run_id=? AND tier='A'", (run_id,)
        ).fetchone()[0],
        "tier_b": conn.execute(
            "SELECT COUNT(*) FROM scores WHERE run_id=? AND tier='B'", (run_id,)
        ).fetchone()[0],
        "canonical": canonical_infos,
    }
    return stats
