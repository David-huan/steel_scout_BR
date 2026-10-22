# M8 — 数据模型与存储

> 状态：设计基线 · 依赖：M0 · 关联：M1–M7、M9 · 代码：`backend/app/models.py`、`db.py`

## 1. 目标

定义客户发现系统的持久化契约：**运行记录、候选、抓取证据、公司主数据、评分、去重关系、审计**。

原则：

- demo 用 SQLite（WAL），生产迁 PostgreSQL，DDL 保持兼容。
- 所有「事实」带来源与时间；合并/修改不丢历史。
- JSON 字段只用于灵活统计/证据，不用于核心查询条件。
- 主数据（company）与运行态（candidate）分离。

## 2. ER 关系

```
runs 1─n run_stages
runs 1─n queries
runs 1─n candidates
candidates 1─0..1 crawl_pages (通过 domain/run)
companies 1─n company_aliases
companies 1─n company_domains
companies 1─n company_emails
companies 1─n company_phones
companies 1─n company_sources
companies 1─n company_products
companies 1─n scores
companies n─1 company_groups
companies n─n companies (dedup_pairs)
runs 1─n events (可选)
```

## 3. DDL（SQLite）

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 运行
CREATE TABLE runs (
  id                TEXT PRIMARY KEY,              -- run_...
  product           TEXT NOT NULL,
  country           TEXT NOT NULL,
  target_count      INTEGER NOT NULL DEFAULT 15,
  options_json      TEXT NOT NULL DEFAULT '{}',
  brief_json        TEXT,
  status            TEXT NOT NULL DEFAULT 'queued', -- queued|running|partial|succeeded|failed|cancelled
  current_stage     TEXT,
  pipeline_version  TEXT,
  taxonomy_version  TEXT,
  score_version     TEXT,
  prompt_version    TEXT,
  budget_json       TEXT NOT NULL DEFAULT '{}',
  stats_json        TEXT NOT NULL DEFAULT '{}',
  cost_usd          REAL NOT NULL DEFAULT 0,
  error             TEXT,
  created_at        TEXT NOT NULL,
  started_at        TEXT,
  finished_at       TEXT
);
CREATE INDEX idx_runs_status_created ON runs(status, created_at DESC);

-- 阶段
CREATE TABLE run_stages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  stage        TEXT NOT NULL,                      -- brief|queries|discovery|crawl|enrich|classify_score|dedup_persist
  status       TEXT NOT NULL DEFAULT 'pending',    -- pending|running|succeeded|partial|failed|skipped
  stats_json   TEXT NOT NULL DEFAULT '{}',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  error        TEXT,
  cost_usd     REAL NOT NULL DEFAULT 0,
  started_at   TEXT,
  finished_at  TEXT,
  UNIQUE(run_id, stage)
);

-- 查询
CREATE TABLE queries (
  id               TEXT PRIMARY KEY,               -- qry_...
  run_id           TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  text             TEXT NOT NULL,
  lang             TEXT NOT NULL DEFAULT 'pt-BR',
  source           TEXT NOT NULL,                  -- template|llm|manual
  dimensions_json  TEXT NOT NULL DEFAULT '{}',
  expected_types_json TEXT NOT NULL DEFAULT '[]',
  priority         INTEGER NOT NULL DEFAULT 50,
  query_hash       TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'pending',
  hits             INTEGER NOT NULL DEFAULT 0,
  new_candidates   INTEGER NOT NULL DEFAULT 0,
  qualified        INTEGER NOT NULL DEFAULT 0,
  cost_usd         REAL NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL,
  UNIQUE(run_id, query_hash)
);
CREATE INDEX idx_queries_run ON queries(run_id, priority DESC);

-- 候选
CREATE TABLE candidates (
  id                 TEXT PRIMARY KEY,             -- cand_...
  run_id             TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  query_id           TEXT REFERENCES queries(id) ON DELETE SET NULL,
  source             TEXT NOT NULL,                -- serper|places|abinox|directory|trade|signal
  source_type        TEXT NOT NULL,
  source_url         TEXT,
  raw_name           TEXT,
  normalized_name    TEXT,
  url                TEXT,
  canonical_domain   TEXT,
  url_hash           TEXT,
  snippet            TEXT,
  phones_json        TEXT NOT NULL DEFAULT '[]',
  address            TEXT,
  place_id           TEXT,
  cnpj_hint          TEXT,
  source_reliability REAL NOT NULL DEFAULT 0.5,
  signals_json       TEXT NOT NULL DEFAULT '[]',
  negative_json      TEXT NOT NULL DEFAULT '[]',
  status             TEXT NOT NULL DEFAULT 'new',  -- new|accepted|rejected|duplicate|crawled|failed
  rejection_reason   TEXT,
  discovered_at      TEXT NOT NULL,
  UNIQUE(run_id, source, url_hash)
);
CREATE INDEX idx_candidates_run_status ON candidates(run_id, status);
CREATE INDEX idx_candidates_domain ON candidates(canonical_domain);

-- 抓取页面
CREATE TABLE crawl_pages (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id        TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  candidate_id  TEXT REFERENCES candidates(id) ON DELETE CASCADE,
  domain        TEXT NOT NULL,
  url           TEXT NOT NULL,
  url_hash      TEXT NOT NULL,
  http_status   INTEGER,
  content_type  TEXT,
  title         TEXT,
  content_hash  TEXT,
  bytes         INTEGER,
  fetch_method  TEXT,                              -- httpx|playwright
  error_code    TEXT,
  fetched_at    TEXT NOT NULL,
  snapshot_path TEXT,
  UNIQUE(run_id, url_hash)
);
CREATE INDEX idx_crawl_domain ON crawl_pages(run_id, domain);

-- 集团
CREATE TABLE company_groups (
  id          TEXT PRIMARY KEY,                    -- grp_...
  name        TEXT,
  cnpj_root   TEXT,
  notes       TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_groups_root ON company_groups(cnpj_root);

-- 公司主数据
CREATE TABLE companies (
  id                 TEXT PRIMARY KEY,             -- cmp_...
  group_id           TEXT REFERENCES company_groups(id) ON DELETE SET NULL,
  display_name       TEXT NOT NULL,
  legal_name         TEXT,
  website            TEXT,
  cnpj               TEXT,
  cnpj_root          TEXT,
  registry_status    TEXT,                          -- ATIVA|BAIXADA|INAPTA|SUSPENSA|NULA|unverified
  founded_at         TEXT,
  cnae_json          TEXT NOT NULL DEFAULT '[]',
  cnae_desc_json     TEXT NOT NULL DEFAULT '[]',
  address            TEXT,
  alternate_addresses_json TEXT NOT NULL DEFAULT '[]',
  city               TEXT,
  state              TEXT,
  postal_code        TEXT,
  country            TEXT NOT NULL DEFAULT 'BR',
  size_bucket        TEXT,                          -- micro|small|medium|large|unknown
  capital_social     REAL,
  primary_type       TEXT,                          -- importer_distributor|service_center|fabricator|end_user|trader|mill_producer|recycler|other
  secondary_types_json TEXT NOT NULL DEFAULT '[]',
  flags_json         TEXT NOT NULL DEFAULT '{}',
  type_confidence    REAL,
  status             TEXT NOT NULL DEFAULT 'active', -- active|inactive|merged|do_not_contact
  merged_into        TEXT REFERENCES companies(id) ON DELETE SET NULL,
  dedup_status       TEXT NOT NULL DEFAULT 'unique',  -- unique|review|merged
  first_seen_at      TEXT NOT NULL,
  last_seen_at       TEXT NOT NULL,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  crm_id             TEXT
);
CREATE INDEX idx_companies_state ON companies(state);
CREATE INDEX idx_companies_cnpj ON companies(cnpj);
CREATE INDEX idx_companies_root ON companies(cnpj_root);
CREATE INDEX idx_companies_type ON companies(primary_type);
CREATE INDEX idx_companies_status ON companies(status);

-- 别名
CREATE TABLE company_aliases (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  alias       TEXT NOT NULL,
  alias_norm  TEXT NOT NULL,
  source      TEXT,
  confidence  REAL NOT NULL DEFAULT 0.5,
  created_at  TEXT NOT NULL,
  UNIQUE(company_id, alias_norm)
);
CREATE INDEX idx_alias_norm ON company_aliases(alias_norm);

-- 域名
CREATE TABLE company_domains (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id    TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  domain        TEXT NOT NULL,                     -- registrable domain
  kind          TEXT NOT NULL DEFAULT 'website',   -- website|microsite|email
  is_primary    INTEGER NOT NULL DEFAULT 0,
  source        TEXT,
  first_seen_at TEXT NOT NULL,
  UNIQUE(company_id, domain)
);
CREATE UNIQUE INDEX idx_domain_unique ON company_domains(domain, kind);

-- 邮箱
CREATE TABLE company_emails (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id   TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  email        TEXT NOT NULL,
  role         TEXT,                               -- sales|contact|info|support|other
  mx_ok        INTEGER,
  verified     INTEGER NOT NULL DEFAULT 0,
  source       TEXT,
  source_url   TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT,
  UNIQUE(company_id, email)
);
CREATE INDEX idx_email_value ON company_emails(email);

-- 电话
CREATE TABLE company_phones (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  e164        TEXT NOT NULL,
  type        TEXT,                                -- phone|whatsapp|fax|0800
  source      TEXT,
  UNIQUE(company_id, e164)
);

-- 来源/证据
CREATE TABLE company_sources (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  field       TEXT,
  value       TEXT,
  quote       TEXT,
  source_url  TEXT,
  extractor   TEXT,                                -- regex|mailto|api|llm|manual
  confidence  REAL NOT NULL DEFAULT 0.5,
  fetched_at  TEXT NOT NULL,
  UNIQUE(company_id, field, value, source_url)
);
CREATE INDEX idx_sources_company ON company_sources(company_id, field);

-- 产品
CREATE TABLE company_products (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  form        TEXT,                                -- chapas|bobinas|tiras|blanks|barras|perfis|cantoneiras
  grades_json TEXT NOT NULL DEFAULT '[]',
  quote       TEXT,
  source_url  TEXT,
  confidence  REAL NOT NULL DEFAULT 0.5,
  UNIQUE(company_id, form, source_url)
);

-- 评分
CREATE TABLE scores (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id      TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  run_id          TEXT REFERENCES runs(id) ON DELETE SET NULL,
  total           INTEGER NOT NULL,
  tier            TEXT NOT NULL,                   -- A|B|C|D
  product_fit     REAL NOT NULL DEFAULT 0,
  buyer_intent    REAL NOT NULL DEFAULT 0,
  scale           REAL NOT NULL DEFAULT 0,
  reachability    REAL NOT NULL DEFAULT 0,
  geo_logistics   REAL NOT NULL DEFAULT 0,
  strategic_fit   REAL NOT NULL DEFAULT 0,
  breakdown_json  TEXT NOT NULL DEFAULT '{}',
  reasons_json    TEXT NOT NULL DEFAULT '[]',
  score_version   TEXT NOT NULL,
  created_at      TEXT NOT NULL
);
CREATE INDEX idx_scores_company ON scores(company_id, created_at DESC);
CREATE INDEX idx_scores_run ON scores(run_id, total DESC);

-- 去重对
CREATE TABLE dedup_pairs (
  id                TEXT PRIMARY KEY,              -- ddp_...
  left_company_id   TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  right_company_id  TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  score             REAL NOT NULL,
  decision          TEXT NOT NULL,                 -- auto_merge|review|suggest|distinct|merged|split|rejected
  status            TEXT NOT NULL DEFAULT 'pending', -- pending|resolved
  features_json     TEXT NOT NULL DEFAULT '{}',
  reasons_json      TEXT NOT NULL DEFAULT '[]',
  reviewed_by       TEXT,
  reviewed_at       TEXT,
  review_note       TEXT,
  created_at        TEXT NOT NULL,
  UNIQUE(left_company_id, right_company_id)
);
CREATE INDEX idx_pairs_status ON dedup_pairs(status, score DESC);

-- 增强缓存
CREATE TABLE enrichment_cache (
  cache_key   TEXT NOT NULL,
  source      TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  PRIMARY KEY (cache_key, source)
);
CREATE INDEX idx_cache_expiry ON enrichment_cache(expires_at);

-- 审计
CREATE TABLE events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT,
  company_id  TEXT,
  pair_id     TEXT,
  event_type  TEXT NOT NULL,                       -- created|merged|split|reviewed|exported|rescored|suppressed
  actor       TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_events_company ON events(company_id, created_at DESC);

-- 禁止联系
CREATE TABLE suppression_list (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  TEXT REFERENCES companies(id) ON DELETE SET NULL,
  email       TEXT,
  domain      TEXT,
  reason      TEXT NOT NULL,
  created_by  TEXT,
  created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_suppression_email ON suppression_list(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX idx_suppression_domain ON suppression_list(domain) WHERE domain IS NOT NULL;
```

## 4. 关键约束与不变量

1. `companies.merged_into` 非空 ⇒ `status='merged'`；不允许链式合并（合并到最终 canonical）。
2. 一个 `domain` 在 `company_domains` 中只能属于一个公司（`UNIQUE(domain, kind)`）；如冲突，先解决去重。
3. 一个邮箱可属于多个公司（集团共用），但 `(company_id,email)` 唯一。
4. `scores` 只追加不覆盖；最新一条为当前分。
5. `dedup_pairs` 的左右 ID 按字典序存储，避免重复方向。
6. 删除公司：默认软删除（`status=inactive`）或匿名化，满足 LGPD 删除请求时清空邮箱/电话。
7. 所有时间 UTC ISO 8601；展示层转换。

## 5. 常用查询

### 5.1 某次运行的 A/B 客户

```sql
SELECT c.id, c.display_name, c.state, c.primary_type, s.total, s.tier
FROM companies c
JOIN scores s ON s.company_id = c.id
WHERE s.run_id = :run_id
  AND s.tier IN ('A','B')
  AND c.status = 'active'
ORDER BY s.total DESC;
```

### 5.2 去重复核队列

```sql
SELECT p.*, l.display_name AS left_name, r.display_name AS right_name
FROM dedup_pairs p
JOIN companies l ON l.id = p.left_company_id
JOIN companies r ON r.id = p.right_company_id
WHERE p.status = 'pending' AND p.decision = 'review'
ORDER BY p.score DESC;
```

### 5.3 历史客户命中

```sql
SELECT c.id, c.display_name, c.last_seen_at
FROM companies c
JOIN company_aliases a ON a.company_id = c.id
WHERE a.alias_norm = :normalized_name
  AND c.status = 'active';
```

### 5.4 邮箱覆盖率

```sql
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN EXISTS (
    SELECT 1 FROM company_emails e WHERE e.company_id = c.id
  ) THEN 1 ELSE 0 END) AS with_email
FROM companies c
WHERE c.status = 'active';
```

## 6. 迁移与索引策略

- 迁移工具：Alembic（SQLite 用 batch mode）。
- 初始迁移一次性建表；后续按模块增量。
- 高频筛选字段建索引：`state`, `primary_type`, `status`, `scores(run_id,total)`, `dedup_pairs(status,score)`。
- JSON 字段不建索引；确需查询时抽列（如 `tier` 已在 scores）。
- 生产 Postgres：`JSONB`、部分索引、`pg_trgm`（名称模糊）可选。

## 7. 数据生命周期

| 数据 | 保留 | 说明 |
|---|---|---|
| 原始 HTML 快照 | 30 天 | 对象存储/本地，过期清理 |
| `crawl_pages` 元数据 | 180 天 | 证据审计 |
| `candidates` | 180 天 | 运行态 |
| `runs` / `run_stages` | 1 年 | 统计与复现 |
| `companies` 主数据 | 长期 | 直到删除请求/业务下线 |
| `company_sources` | 与公司同生命周期 | 证据 |
| `scores` | 长期（版本化） | 可对比历史 |
| `events` | 2 年 | 审计 |
| `suppression_list` | 长期 | 合规要求 |
| `enrichment_cache` | TTL 自动 | 30/90/180 天 |

## 8. 备份与恢复

- SQLite：每日 `.backup` 到 `data/backups/`，保留 14 天。
- Postgres：每日 `pg_dump` + WAL 归档（生产）。
- 恢复演练：每季度一次；验证 `companies` + `company_sources` 一致。
- 导出快照：`GET /api/export?format=csv&include_evidence=true` 可作为业务侧备份。

## 9. 验收标准

1. 迁移脚本可在空库一次建成，外键/索引生效。
2. 重复 run 不违反唯一约束（幂等）。
3. 合并后查询默认不返回 `merged` 记录，但可通过 `include_merged=true` 查看。
4. 删除/匿名化公司后，邮箱/电话不再可查，`events` 保留操作记录。
5. 5.1–5.4 查询在 10 万公司规模下 P95 < 300ms（Postgres）。
6. 备份恢复后数据行数与校验和一致。

## 10. 待定

- 是否引入 `company_people`（联系人）表：当前不存个人数据，v2 视合规与业务需要。
- 是否用 `pgvector` 存公司描述向量（去重/相似客户）。
- 多租户 `tenant_id` 是否加入所有表（生产 SaaS 化时）。
- 原始 HTML 是否迁对象存储（S3/MinIO）。
