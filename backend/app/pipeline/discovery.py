import csv
import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx

from ..config import SEED_PATH, SERPER_API_KEY, SERPER_MAX_QUERIES
from ..db import dumps, utcnow
from .brief import Brief

SKIP_HOSTS = (
    "google.",
    "bing.",
    "duckduckgo.",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "linkedin.com",
    "wikipedia.org",
    "mercadolivre.com.br",
    "amazon.com.br",
    "alibaba.com",
    "aliexpress.com",
    "made-in-china.com",
    "indiamart.com",
    "tradeindia.com",
    "exportersindia.com",
    "gov.br",
)

TWO_LEVEL_SUFFIXES = {
    "com.br",
    "ind.br",
    "org.br",
    "net.br",
    "gov.br",
    "edu.br",
    "com.ar",
    "com.mx",
}


def canonical_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def canonical_url(url: str) -> str:
    try:
        p = urlparse(url)
    except ValueError:
        return url
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme or "https", host, path, "", "", ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()


def _split(value: str) -> list[str]:
    return [x.strip() for x in (value or "").split(";") if x.strip()]


def load_seed(brief: Brief) -> list[dict]:
    path = Path(SEED_PATH)
    if not path.exists() or brief.country != "BR":
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            url = (row.get("website") or "").strip()
            domain = canonical_domain(url)
            if not domain:
                continue
            rows.append(
                {
                    "source": "seed",
                    "source_type": "curated_seed",
                    "source_url": (row.get("source_url") or url).strip(),
                    "raw_name": (row.get("name") or "").strip(),
                    "url": url,
                    "canonical_domain": domain,
                    "url_hash": url_hash(url),
                    "snippet": (row.get("notes") or "").strip(),
                    "phones": _split(row.get("phone") or ""),
                    "address": (row.get("address") or "").strip(),
                    "email_hint": (row.get("email") or "").strip(),
                    "type_hint": (row.get("type_hint") or "").strip(),
                    "secondary_types": _split(row.get("secondary_types") or ""),
                    "products": _split(row.get("products") or ""),
                    "grades": _split(row.get("grades") or ""),
                    "import_signals": (row.get("import_signals") or "").strip(),
                    "applications": _split(row.get("applications") or ""),
                    "size_bucket": (row.get("size_bucket") or "").strip(),
                    "state": (row.get("state") or "").strip(),
                    "city": (row.get("city") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                }
            )
    return rows


def _is_company_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in {"http", "https"}:
        return False
    host = (p.hostname or "").lower()
    if not host or any(host == h or host.endswith("." + h) or h in host for h in SKIP_HOSTS):
        return False
    if p.path.lower().endswith((".pdf", ".jpg", ".png", ".zip", ".docx")):
        return False
    return True


def serper_search(query: str, max_results: int = 20) -> list[dict]:
    if not SERPER_API_KEY:
        return []
    try:
        resp = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "gl": "br", "hl": "pt-BR", "num": max_results, "page": 1},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    results = []
    for item in data.get("organic", []) or []:
        url = item.get("link") or ""
        if not _is_company_url(url):
            continue
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        results.append(
            {
                "raw_name": title,
                "url": url,
                "canonical_domain": canonical_domain(url),
                "url_hash": url_hash(url),
                "snippet": snippet,
                "source": "serper",
                "source_type": "serp",
                "source_url": url,
                "phones": [],
                "address": "",
                "email_hint": "",
                "type_hint": "",
                "secondary_types": [],
                "products": [],
                "grades": [],
                "import_signals": "",
                "applications": [],
                "size_bucket": "",
                "state": "",
                "city": "",
                "notes": snippet,
            }
        )
    return results


def discover(run_id: str, brief: Brief, queries: list[dict], conn) -> dict:
    candidates = load_seed(brief)
    seen_domains = {c["canonical_domain"] for c in candidates if c["canonical_domain"]}
    serper_used = 0

    for q in queries:
        if serper_used >= SERPER_MAX_QUERIES:
            break
        if not SERPER_API_KEY:
            break
        results = serper_search(q["text"])
        serper_used += 1
        new_for_query = 0
        for item in results:
            domain = item["canonical_domain"]
            if not domain or domain in seen_domains:
                continue
            seen_domains.add(domain)
            item["query_id"] = q["id"]
            candidates.append(item)
            new_for_query += 1
        conn.execute(
            "UPDATE queries SET hits = ?, new_candidates = ?, status = 'done' WHERE id = ?",
            (len(results), new_for_query, q["id"]),
        )

    inserted = 0
    for c in candidates[:300]:
        try:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO candidates (
                  id, run_id, query_id, source, source_type, source_url, raw_name,
                  normalized_name, url, canonical_domain, url_hash, snippet, phones_json,
                  address, email_hint, type_hint, secondary_types_json, products_json,
                  grades_json, import_signals, applications_json, size_bucket, state, city,
                  notes, discovered_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    c.get("id") or f"cand_{hashlib.md5((run_id + c['canonical_domain']).encode()).hexdigest()[:12]}",
                    run_id,
                    c.get("query_id"),
                    c["source"],
                    c["source_type"],
                    c["source_url"],
                    c["raw_name"],
                    c["raw_name"],
                    c["url"],
                    c["canonical_domain"],
                    c["url_hash"],
                    c.get("snippet"),
                    dumps(c.get("phones", [])),
                    c.get("address"),
                    c.get("email_hint"),
                    c.get("type_hint"),
                    dumps(c.get("secondary_types", [])),
                    dumps(c.get("products", [])),
                    dumps(c.get("grades", [])),
                    c.get("import_signals"),
                    dumps(c.get("applications", [])),
                    c.get("size_bucket"),
                    c.get("state"),
                    c.get("city"),
                    c.get("notes"),
                    c.get("discovered_at") or utcnow(),
                ),
            )
            inserted += max(cur.rowcount, 0)
        except Exception:
            continue
    conn.commit()
    return {
        "candidates": conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE run_id = ?", (run_id,)
        ).fetchone()[0],
        "seed": len(load_seed(brief)),
        "serper_queries": serper_used,
        "inserted": inserted,
    }
