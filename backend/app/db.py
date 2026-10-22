import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  product TEXT NOT NULL,
  country TEXT NOT NULL,
  target_count INTEGER NOT NULL DEFAULT 15,
  options_json TEXT NOT NULL DEFAULT '{}',
  brief_json TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  current_stage TEXT,
  stats_json TEXT NOT NULL DEFAULT '{}',
  cost_usd REAL NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

CREATE TABLE IF NOT EXISTS run_stages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  stats_json TEXT NOT NULL DEFAULT '{}',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  started_at TEXT,
  finished_at TEXT,
  UNIQUE(run_id, stage)
);

CREATE TABLE IF NOT EXISTS queries (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'pt-BR',
  source TEXT NOT NULL,
  dimensions_json TEXT NOT NULL DEFAULT '{}',
  expected_types_json TEXT NOT NULL DEFAULT '[]',
  priority INTEGER NOT NULL DEFAULT 50,
  query_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  hits INTEGER NOT NULL DEFAULT 0,
  new_candidates INTEGER NOT NULL DEFAULT 0,
  qualified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, query_hash)
);
CREATE INDEX IF NOT EXISTS idx_queries_run ON queries(run_id, priority DESC);

CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  query_id TEXT REFERENCES queries(id) ON DELETE SET NULL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_url TEXT,
  raw_name TEXT,
  normalized_name TEXT,
  url TEXT,
  canonical_domain TEXT,
  url_hash TEXT,
  snippet TEXT,
  phones_json TEXT NOT NULL DEFAULT '[]',
  address TEXT,
  email_hint TEXT,
  type_hint TEXT,
  secondary_types_json TEXT NOT NULL DEFAULT '[]',
  products_json TEXT NOT NULL DEFAULT '[]',
  grades_json TEXT NOT NULL DEFAULT '[]',
  import_signals TEXT,
  applications_json TEXT NOT NULL DEFAULT '[]',
  size_bucket TEXT,
  state TEXT,
  city TEXT,
  notes TEXT,
  crawl_status TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  discovered_at TEXT NOT NULL,
  UNIQUE(run_id, canonical_domain)
);
CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(run_id, status);

CREATE TABLE IF NOT EXISTS crawl_pages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  candidate_id TEXT REFERENCES candidates(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  url TEXT NOT NULL,
  http_status INTEGER,
  title TEXT,
  content_hash TEXT,
  bytes INTEGER,
  fetch_method TEXT,
  error_code TEXT,
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crawl_run ON crawl_pages(run_id, domain);

CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  legal_name TEXT,
  website TEXT,
  cnpj TEXT,
  registry_status TEXT,
  address TEXT,
  city TEXT,
  state TEXT,
  postal_code TEXT,
  country TEXT NOT NULL DEFAULT 'BR',
  size_bucket TEXT,
  primary_type TEXT,
  secondary_types_json TEXT NOT NULL DEFAULT '[]',
  type_confidence REAL,
  status TEXT NOT NULL DEFAULT 'active',
  merged_into TEXT,
  dedup_status TEXT NOT NULL DEFAULT 'unique',
  review_status TEXT NOT NULL DEFAULT 'new',
  review_note TEXT,
  notes TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(website);
CREATE INDEX IF NOT EXISTS idx_companies_cnpj ON companies(cnpj);
CREATE INDEX IF NOT EXISTS idx_companies_state ON companies(state);
CREATE INDEX IF NOT EXISTS idx_companies_type ON companies(primary_type);

CREATE TABLE IF NOT EXISTS company_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  source TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(company_id, alias_norm)
);

CREATE TABLE IF NOT EXISTS company_domains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'website',
  is_primary INTEGER NOT NULL DEFAULT 0,
  source TEXT,
  first_seen_at TEXT NOT NULL,
  UNIQUE(company_id, domain)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_kind ON company_domains(domain, kind);

CREATE TABLE IF NOT EXISTS company_emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  role TEXT,
  mx_ok INTEGER,
  source TEXT,
  source_url TEXT,
  first_seen_at TEXT NOT NULL,
  UNIQUE(company_id, email)
);
CREATE INDEX IF NOT EXISTS idx_email_value ON company_emails(email);

CREATE TABLE IF NOT EXISTS company_phones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  e164 TEXT NOT NULL,
  type TEXT,
  source TEXT,
  UNIQUE(company_id, e164)
);

CREATE TABLE IF NOT EXISTS company_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  field TEXT,
  value TEXT,
  quote TEXT,
  source_url TEXT,
  extractor TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  fetched_at TEXT NOT NULL,
  UNIQUE(company_id, field, value, source_url)
);
CREATE INDEX IF NOT EXISTS idx_sources_company ON company_sources(company_id, field);

CREATE TABLE IF NOT EXISTS company_products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  form TEXT,
  grades_json TEXT NOT NULL DEFAULT '[]',
  quote TEXT,
  source_url TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  UNIQUE(company_id, form, source_url)
);

CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
  total INTEGER NOT NULL,
  tier TEXT NOT NULL,
  product_fit REAL NOT NULL DEFAULT 0,
  buyer_intent REAL NOT NULL DEFAULT 0,
  scale REAL NOT NULL DEFAULT 0,
  reachability REAL NOT NULL DEFAULT 0,
  geo_logistics REAL NOT NULL DEFAULT 0,
  strategic_fit REAL NOT NULL DEFAULT 0,
  breakdown_json TEXT NOT NULL DEFAULT '{}',
  reasons_json TEXT NOT NULL DEFAULT '[]',
  score_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_company ON scores(company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scores_run ON scores(run_id, total DESC);

CREATE TABLE IF NOT EXISTS run_companies (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  score_id INTEGER,
  candidate_id TEXT,
  dedup_status TEXT NOT NULL DEFAULT 'unique',
  PRIMARY KEY (run_id, company_id)
);

CREATE TABLE IF NOT EXISTS dedup_pairs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  left_company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  right_company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  decision TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  features_json TEXT NOT NULL DEFAULT '{}',
  reasons_json TEXT NOT NULL DEFAULT '[]',
  reviewed_at TEXT,
  review_note TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(left_company_id, right_company_id)
);
CREATE INDEX IF NOT EXISTS idx_pairs_status ON dedup_pairs(status, score DESC);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  company_id TEXT,
  pair_id TEXT,
  event_type TEXT NOT NULL,
  actor TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_company ON events(company_id, created_at DESC);

CREATE TABLE IF NOT EXISTS suppression_list (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT,
  email TEXT,
  domain TEXT,
  reason TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def get_conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value, default=None):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def row_to_dict(row) -> dict | None:
    return dict(row) if row is not None else None


def add_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    run_id: str | None = None,
    company_id: str | None = None,
    pair_id: str | None = None,
    actor: str = "system",
    payload: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO events (run_id, company_id, pair_id, event_type, actor, payload_json, created_at) VALUES (?,?,?,?,?,?,?)",
        (run_id, company_id, pair_id, event_type, actor, dumps(payload or {}), utcnow()),
    )
