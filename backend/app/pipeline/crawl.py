import hashlib
import ipaddress
import json
import re
import socket
import threading
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import CRAWL_LIVE, CRAWL_MAX_PAGES, CRAWL_THREADS, HTTP_TIMEOUT, USER_AGENT
from ..db import dumps, utcnow
from .discovery import canonical_domain, canonical_url

EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24})(?![\w.-])"
)
PHONE_RE = re.compile(
    r"(?:\+?55[\s\-.]?)?\(?0?\d{2}\)?[\s\-.]?(?:9?\d{4})[\s\-.]?\d{4}"
)
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
CEP_RE = re.compile(r"\b\d{5}-?\d{3}\b")
STATE_RE = re.compile(r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b")

FORM_WORDS = {
    "chapas": ["chapa", "chapas", "sheet", "plate", "plates"],
    "bobinas": ["bobina", "bobinas", "coil", "coils"],
    "tiras": ["tira", "tiras", "fita", "fitas", "strip"],
    "blanks": ["blank", "blanks"],
    "barras": ["barra", "barras", "bar", "bars", "rod"],
    "perfis": ["perfil", "perfis", "profile", "profiles", "cantoneira", "angle"],
}
APPLICATION_WORDS = {
    "alimentícia": ["alimentícia", "alimenticia", "food"],
    "petroquímica": ["petroquímica", "petroquimica", "petrochemical"],
    "papel e celulose": ["papel e celulose", "pulp"],
    "naval": ["naval", "shipyard", "estaleiro"],
    "construção civil": ["construção civil", "construcao civil", "construction"],
    "farmacêutica": ["farmacêutica", "farmaceutica", "pharma"],
    "arquitetura": ["arquitetura", "architecture"],
}
IMPORT_WORDS = [
    "importador",
    "importadora",
    "importação",
    "importacao",
    "importado",
    "importados",
    "importing",
]
STOCK_WORDS = ["estoque", "pronta entrega", "pronta-entrega", "stock"]
PROCESS_WORDS = [
    "beneficiamento",
    "corte",
    "slitter",
    "polimento",
    "escovamento",
    "caldeiraria",
    "plasma",
    "laser",
]

ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}
ROBOTS_LOCK = threading.Lock()


def _is_public_host(host: str) -> bool:
    if not host or host in {"localhost", "localhost.localdomain"}:
        return False
    if host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _robots_allowed(url: str) -> bool:
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    with ROBOTS_LOCK:
        rp = ROBOTS_CACHE.get(root)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(root + "/robots.txt")
        try:
            resp = httpx.get(
                root + "/robots.txt",
                headers={"User-Agent": USER_AGENT},
                timeout=4,
                follow_redirects=True,
            )
            if resp.status_code < 400:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])
        except Exception:
            return True
        with ROBOTS_LOCK:
            ROBOTS_CACHE[root] = rp
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _clean_email(value: str) -> str:
    return value.strip().strip(".,;:()[]<>\"'").lower()


def _valid_email(value: str) -> bool:
    if not value or "@" not in value or len(value) > 254:
        return False
    local, domain = value.rsplit("@", 1)
    if not local or "." not in domain:
        return False
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")):
        return False
    bad_domains = {
        "example.com",
        "domain.com",
        "email.com",
        "test.com",
        "sentry.io",
        "wixpress.com",
    }
    if domain in bad_domains or any(domain.endswith("." + b) for b in bad_domains):
        return False
    if local in {"noreply", "no-reply", "donotreply", "do-not-reply"}:
        return False
    return True


def email_role(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    if any(k in local for k in ("comercial", "vendas", "sales", "orcamento", "cotacoes", "servicos")):
        return "sales"
    if any(k in local for k in ("contato", "atendimento", "contact")):
        return "contact"
    if any(k in local for k in ("info", "sac", "suporte")):
        return "info"
    return "other"


def _deobfuscate(text: str) -> str:
    text = text.replace("(at)", "@").replace("[at]", "@").replace(" at ", "@")
    text = re.sub(r"\s*@\s*", "@", text)
    return text


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 13 and digits.startswith("55"):
        return "+" + digits
    if len(digits) == 12 and digits.startswith("55"):
        return "+" + digits
    if len(digits) == 11:
        return "+55" + digits
    if len(digits) == 10:
        return "+55" + digits
    return None


def validate_cnpj(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 14 or len(set(digits)) == 1:
        return None
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6] + weights1
    total = sum(int(d) * w for d, w in zip(digits[:12], weights1))
    d1 = 11 - (total % 11)
    d1 = 0 if d1 >= 10 else d1
    total = sum(int(d) * w for d, w in zip(digits[:13], weights2))
    d2 = 11 - (total % 11)
    d2 = 0 if d2 >= 10 else d2
    if digits[-2:] != f"{d1}{d2}":
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _text_window(text: str, start: int, end: int, radius: int = 160) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)].strip()


def extract(html: str, url: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og = soup.find("meta", attrs={"property": "og:site_name"})
    site_name = (og.get("content") or "").strip() if og else ""
    has_contact_form = bool(soup.find("form"))
    social_links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(h in href for h in ("linkedin.com/company", "instagram.com", "facebook.com")):
            if href not in social_links:
                social_links.append(href)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    emails: dict[str, dict] = {}

    def add_email(raw: str, quote: str = "", extractor: str = "regex") -> None:
        email = _clean_email(raw)
        if not _valid_email(email):
            return
        if email not in emails:
            emails[email] = {
                "value": email,
                "role": email_role(email),
                "source": extractor,
                "source_url": url,
                "quote": quote or email,
            }

    for a in soup.select("a[href^='mailto:']"):
        value = (a.get("href") or "").split("mailto:", 1)[-1].split("?", 1)[0]
        for part in value.split(","):
            add_email(part, quote=a.get_text(" ", strip=True), extractor="mailto")

    haystack = _deobfuscate(text)
    for m in EMAIL_RE.finditer(haystack):
        add_email(m.group(1), quote=_text_window(haystack, m.start(), m.end()))

    phones: dict[str, dict] = {}
    for m in PHONE_RE.finditer(text):
        e164 = normalize_phone(m.group(0))
        if not e164:
            continue
        ctx = _text_window(text, m.start(), m.end(), 60).lower()
        ptype = "whatsapp" if "whatsapp" in ctx or "wa.me" in ctx else "phone"
        phones.setdefault(e164, {"e164": e164, "type": ptype, "source_url": url, "quote": m.group(0)})

    cnpj = None
    for m in CNPJ_RE.finditer(text):
        cnpj = validate_cnpj(m.group(0))
        if cnpj:
            break

    postal_code = None
    address = ""
    cep_match = CEP_RE.search(text)
    if cep_match:
        postal_code = cep_match.group(0).replace("-", "")
        address = _text_window(text, cep_match.start(), cep_match.end(), 180)

    state = None
    state_match = STATE_RE.search(address or text)
    if state_match:
        state = state_match.group(1)

    lower = text.lower()
    has_stainless = "inox" in lower or "stainless" in lower
    forms: list[str] = []
    if has_stainless:
        for form, words in FORM_WORDS.items():
            if any(w in lower for w in words):
                forms.append(form)
    grades = sorted(
        {
            g
            for g in ["201", "304", "304L", "316", "316L", "430", "439", "441", "2205"]
            if re.search(rf"\b{g}\b", text, re.IGNORECASE)
        }
    )
    applications = [
        label for label, words in APPLICATION_WORDS.items() if any(w in lower for w in words)
    ]
    import_signals = [w for w in IMPORT_WORDS if w in lower]
    stock_signals = [w for w in STOCK_WORDS if w in lower]
    process_signals = [w for w in PROCESS_WORDS if w in lower]

    name = site_name or title
    if not name and title:
        name = re.split(r"\s[|\-–]\s", title)[0].strip()

    return {
        "title": title,
        "name": name,
        "emails": list(emails.values()),
        "phones": list(phones.values()),
        "cnpj": cnpj,
        "address": address.strip(),
        "postal_code": postal_code,
        "state": state,
        "forms": forms,
        "grades": grades,
        "applications": applications,
        "import_signals": import_signals + stock_signals + process_signals,
        "has_contact_form": has_contact_form,
        "social_links": social_links[:5],
        "text_len": len(text),
    }


def _fetch(client: httpx.Client, url: str) -> tuple[int | None, str, str | None, str]:
    current = url
    try:
        for _ in range(4):
            host = urlparse(current).hostname or ""
            if not _is_public_host(host):
                return None, "", "ssrf_blocked", "httpx"
            if not _robots_allowed(current):
                return None, "", "robots_disallow", "httpx"
            resp = client.get(current, follow_redirects=False)
            if resp.status_code in {301, 302, 303, 307, 308}:
                location = resp.headers.get("location")
                if not location:
                    return resp.status_code, "", "redirect_without_location", "httpx"
                current = urljoin(current, location)
                continue
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and content_type:
                return resp.status_code, "", "unsupported_type", "httpx"
            return resp.status_code, resp.text[:2_000_000], None, "httpx"
        return None, "", "too_many_redirects", "httpx"
    except httpx.TimeoutException:
        return None, "", "timeout", "httpx"
    except httpx.HTTPError as exc:
        return None, "", f"http_error:{type(exc).__name__}", "httpx"


def _contact_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    wanted = ("contato", "contact", "quem-somos", "empresa", "sobre", "produto", "product")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(w in href.lower() for w in wanted):
            full = urljoin(base_url, href)
            if canonical_domain(full) == canonical_domain(base_url) and full not in links:
                links.append(full)
    return links[: max(0, CRAWL_MAX_PAGES - 1)]


def _crawl_candidate(candidate: dict) -> dict:
    seed = dict(candidate)
    domain = seed.get("canonical_domain") or ""
    base_url = seed.get("url") or f"https://{domain}"
    live: dict = {}
    pages: list[dict] = []
    status = "seed_fallback"

    if CRAWL_LIVE and domain and _is_public_host(domain):
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
        with httpx.Client(
            headers=headers,
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
            verify=True,
        ) as client:
            code, html, error, method = _fetch(client, base_url)
            pages.append(
                {
                    "url": base_url,
                    "http_status": code,
                    "error_code": error,
                    "bytes": len(html.encode("utf-8", errors="ignore")),
                    "title": "",
                    "content_hash": hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()
                    if html
                    else None,
                    "fetch_method": method,
                }
            )
            if code and 200 <= code < 300 and html:
                live = extract(html, base_url)
                status = "live_ok"
                for link in _contact_links(html, base_url):
                    if len(pages) >= CRAWL_MAX_PAGES:
                        break
                    code2, html2, error2, method2 = _fetch(client, link)
                    pages.append(
                        {
                            "url": link,
                            "http_status": code2,
                            "error_code": error2,
                            "bytes": len(html2.encode("utf-8", errors="ignore")),
                            "title": "",
                            "content_hash": hashlib.sha256(html2.encode("utf-8", errors="ignore")).hexdigest()
                            if html2
                            else None,
                            "fetch_method": method2,
                        }
                    )
                    if code2 and 200 <= code2 < 300 and html2:
                        more = extract(html2, link)
                        for k in ("emails", "phones", "forms", "grades", "applications", "import_signals"):
                            live[k] = (live.get(k) or []) + (more.get(k) or [])
                        if not live.get("cnpj") and more.get("cnpj"):
                            live["cnpj"] = more["cnpj"]
                        if not live.get("address") and more.get("address"):
                            live["address"] = more["address"]
                        if not live.get("name") and more.get("name"):
                            live["name"] = more["name"]
                        live["has_contact_form"] = bool(live.get("has_contact_form")) or bool(more.get("has_contact_form"))
                        live["social_links"] = list(dict.fromkeys((live.get("social_links") or []) + (more.get("social_links") or [])))

    def uniq(items, key):
        seen = set()
        out = []
        for item in items:
            k = item.get(key) if isinstance(item, dict) else item
            if k and k not in seen:
                seen.add(k)
                out.append(item)
        return out

    emails = uniq((live.get("emails") or []) + (
        [{"value": seed["email_hint"], "role": email_role(seed["email_hint"]), "source": "curated_seed", "source_url": seed.get("source_url"), "quote": seed["email_hint"]}]
        if seed.get("email_hint") else []
    ), "value")
    phones = uniq((live.get("phones") or []) + (
        [{"e164": p, "type": "phone", "source_url": seed.get("source_url"), "quote": p} for p in seed.get("phones", [])]
    ), "e164")
    forms = sorted(set(seed.get("products", [])) | set(live.get("forms", [])))
    grades = sorted(set(seed.get("grades", [])) | set(live.get("grades", [])))
    applications = sorted(set(seed.get("applications", [])) | set(live.get("applications", [])))
    signals = []
    if seed.get("import_signals"):
        signals.append(seed["import_signals"])
    if live.get("import_signals"):
        signals.append("; ".join(live["import_signals"]))

    if seed.get("source_type") == "curated_seed" and seed.get("raw_name"):
        name = seed["raw_name"]
    else:
        name = live.get("name") or seed.get("raw_name")
    sources = []
    for email in emails:
        sources.append(
            {
                "field": "email",
                "value": email["value"],
                "quote": email.get("quote") or email["value"],
                "source_url": email.get("source_url") or seed.get("source_url"),
                "extractor": email.get("source", "regex"),
                "confidence": 0.95,
            }
        )
    for phone in phones:
        sources.append(
            {
                "field": "phone",
                "value": phone["e164"],
                "quote": phone.get("quote") or phone["e164"],
                "source_url": phone.get("source_url") or seed.get("source_url"),
                "extractor": "regex" if status == "live_ok" else "curated_seed",
                "confidence": 0.9,
            }
        )
    if forms:
        sources.append(
            {
                "field": "products",
                "value": "; ".join(forms),
                "quote": seed.get("import_signals") or ", ".join(forms),
                "source_url": seed.get("source_url"),
                "extractor": "curated_seed" if seed.get("products") else "regex",
                "confidence": 0.9,
            }
        )
    if signals:
        sources.append(
            {
                "field": "import_signals",
                "value": " | ".join(signals),
                "quote": signals[0][:300],
                "source_url": seed.get("source_url"),
                "extractor": "curated_seed",
                "confidence": 0.85,
            }
        )

    return {
        "candidate_id": seed.get("id"),
        "display_name": name,
        "legal_name": None,
        "website": seed.get("url"),
        "domains": [domain] if domain else [],
        "cnpj": live.get("cnpj"),
        "state": seed.get("state") or live.get("state"),
        "city": seed.get("city"),
        "address": seed.get("address") or live.get("address"),
        "postal_code": live.get("postal_code"),
        "size_bucket": seed.get("size_bucket") or "unknown",
        "type_hint": seed.get("type_hint"),
        "secondary_types": seed.get("secondary_types", []),
        "products": forms,
        "grades": grades,
        "import_signals": " | ".join([s for s in signals if s]),
        "applications": applications,
        "emails": emails,
        "phones": phones,
        "notes": seed.get("notes") or seed.get("snippet"),
        "aliases": [seed.get("raw_name")] if seed.get("raw_name") and seed.get("raw_name") != name else [],
        "sources": sources,
        "crawl_status": status,
        "has_contact_form": bool(live.get("has_contact_form")),
        "social_links": live.get("social_links", []),
        "pages": pages,
        "discovered_at": seed.get("discovered_at"),
    }


def crawl_run(run_id: str, conn) -> dict:
    rows = conn.execute(
        "SELECT * FROM candidates WHERE run_id = ? AND status != 'rejected'", (run_id,)
    ).fetchall()
    candidates = []
    for row in rows:
        d = dict(row)
        d["phones"] = json.loads(d.get("phones_json") or "[]")
        d["secondary_types"] = json.loads(d.get("secondary_types_json") or "[]")
        d["products"] = json.loads(d.get("products_json") or "[]")
        d["grades"] = json.loads(d.get("grades_json") or "[]")
        d["applications"] = json.loads(d.get("applications_json") or "[]")
        candidates.append(d)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, CRAWL_THREADS)) as pool:
        futures = {pool.submit(_crawl_candidate, c): c for c in candidates}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                candidate = futures[future]
                result = {
                    "candidate_id": candidate.get("id"),
                    "display_name": candidate.get("raw_name"),
                    "website": candidate.get("url"),
                    "domains": [candidate.get("canonical_domain")],
                    "state": candidate.get("state"),
                    "city": candidate.get("city"),
                    "address": candidate.get("address"),
                    "size_bucket": candidate.get("size_bucket") or "unknown",
                    "type_hint": candidate.get("type_hint"),
                    "secondary_types": candidate.get("secondary_types", []),
                    "products": candidate.get("products", []),
                    "grades": candidate.get("grades", []),
                    "import_signals": candidate.get("import_signals") or "",
                    "applications": candidate.get("applications", []),
                    "emails": [],
                    "phones": [],
                    "notes": candidate.get("notes"),
                    "aliases": [],
                    "sources": [],
                    "crawl_status": f"error:{type(exc).__name__}",
                    "has_contact_form": False,
                    "social_links": [],
                    "pages": [],
                }
            results.append(result)

    now = utcnow()
    for result in results:
        candidate_id = result.get("candidate_id")
        for page in result.get("pages", []):
            conn.execute(
                """
                INSERT INTO crawl_pages (run_id, candidate_id, domain, url, http_status, title,
                  content_hash, bytes, fetch_method, error_code, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    candidate_id,
                    canonical_domain(page["url"]),
                    page["url"],
                    page.get("http_status"),
                    page.get("title"),
                    page.get("content_hash"),
                    page.get("bytes"),
                    page.get("fetch_method"),
                    page.get("error_code"),
                    now,
                ),
            )
        conn.execute(
            """
            UPDATE candidates SET status = 'crawled', crawl_status = ?, raw_name = COALESCE(?, raw_name),
              address = COALESCE(?, address), state = COALESCE(?, state),
              products_json = ?, grades_json = ?, applications_json = ?
            WHERE id = ?
            """,
            (
                result.get("crawl_status"),
                result.get("display_name"),
                result.get("address"),
                result.get("state"),
                dumps(result.get("products", [])),
                dumps(result.get("grades", [])),
                dumps(result.get("applications", [])),
                candidate_id,
            ),
        )
    conn.commit()
    live_ok = sum(1 for r in results if r.get("crawl_status") == "live_ok")
    return {
        "crawled": len(results),
        "live_ok": live_ok,
        "seed_fallback": len(results) - live_ok,
        "companies": results,
    }
