# Spec 索引 — YIEH Brazil 客户开发 Prototype

本目录是 `README.md` 的技术落地版：按模块拆分，每个模块定义**职责、输入输出、数据契约、算法/规则、接口、错误处理与验收标准**，可直接作为编码与联调依据。

- 文档版本：v0.1
- 场景基线：`Stainless Steel Flat / Profiles` × `Brazil`
- 数据原则：公开 B2B 信息、证据可追溯、未知字段为 `null`、不编造联系人

---

## 1. 模块地图

| ID | 模块 | 核心职责 | 主要产出 | 依赖 | 代码位置（计划） |
|---|---|---|---|---|---|
| M0 | [架构](00-architecture.md) | 系统边界、流水线、运行模型 | 架构基线 | — | — |
| M1 | [Brief 与产品分类](01-brief-taxonomy.md) | 输入归一化、NCM/关键词词典 | `Brief` | M0 | `backend/app/pipeline/brief.py` |
| M2 | [查询生成](02-query-generation.md) | 查询矩阵、LLM 扩展、预算 | `Query[]` | M1 | `pipeline/queries.py` |
| M3 | [客户发现](03-discovery.md) | SERP/Places/目录/协会/贸易数据 | `Candidate[]` | M2 | `pipeline/discover.py` |
| M4 | [抓取与抽取](04-crawler-extraction.md) | 官网抓取、字段/证据抽取 | `CrawlResult` | M3 | `pipeline/crawl.py` |
| M5 | [数据增强](05-enrichment.md) | CNPJ/CNAE/Places/贸易信号 | `EnrichedCompany` | M4 | `pipeline/enrich.py` |
| M6 | [分类与评分](06-classification-scoring.md) | 客户类型、匹配分、等级 | `Classification`, `Score` | M5 | `pipeline/classify.py`, `score.py` |
| M7 | [去重与主数据](07-dedup-entity-resolution.md) | 实体解析、合并/拆分、集团 | `canonical company` | M5, M8 | `pipeline/dedup.py` |
| M8 | [数据模型](08-data-model.md) | 表结构、索引、生命周期 | Schema/DDL | M0 | `backend/app/models.py` |
| M9 | [后端与 API](09-backend-api.md) | 任务编排、REST、导出 | API | M1–M8 | `backend/app/api/*` |
| M10 | [前端](10-frontend.md) | 任务台、结果表、证据、复核 | Web UI | M9 | `frontend/src/*` |
| M11 | [导出与 CRM 集成](11-export-integration.md) | CSV/XLSX、Webhook | 文件/推送 | M9 | `api/export.py` |
| M12 | [测试与可观测性](12-testing-observability.md) | 金标准集、指标、日志 | 质量报告 | 全部 | `backend/tests/*` |
| M13 | [合规与安全](13-compliance-security.md) | LGPD、robots、密钥、DNC | 合规约束 | 全部 | 横切 |
| M14 | [部署与运维](14-deployment-ops.md) | 环境、容器、备份、Runbook | 可运行系统 | 全部 | `docker-compose.yml` |

---

## 2. 数据流与依赖

```
User Input
   │
   ▼
[M1 Brief] ──► [M2 Queries] ──► [M3 Discovery] ──► [M4 Crawl/Extract]
                                                        │
                                                        ▼
                                                  [M5 Enrichment]
                                                        │
                              ┌─────────────────────────┴──────────────┐
                              ▼                                        ▼
                     [M6 Classify/Score]                       [M7 Dedup/ER]
                              │                                        │
                              └──────────────► [M8 Data Model] ◄───────┘
                                                     │
                                                     ▼
                                            [M9 Backend API]
                                                     │
                              ┌──────────────────────┴──────────────────┐
                              ▼                                         ▼
                        [M10 Frontend]                          [M11 Export/CRM]

横切：M12 测试/观测 · M13 合规/安全 · M14 部署/运维
```

**原则**：M1–M7 不直接访问数据库，只接收/返回 Pydantic 对象；持久化统一由 M9 的 repository 层完成。这样 pipeline 可单测、可重放。

---

## 3. 全局约定

### 3.1 ID

| 对象 | 前缀 | 示例 |
|---|---|---|
| Run | `run_` | `run_20261022_001` |
| Candidate | `cand_` | `cand_a1b2c3` |
| Company | `cmp_` | `cmp_0007` |
| Group | `grp_` | `grp_0002` |
| Dedup pair | `ddp_` | `ddp_000031` |
| Query | `qry_` | `qry_0012` |

ID 生成使用 UUIDv7（或 `prefix + ULID`）；demo 可用自增 + 前缀。

### 3.2 时间与时区

- 存储统一 UTC ISO 8601：`2026-10-22T13:00:00Z`。
- 展示层转 `America/Sao_Paulo`（UTC-3）。
- 所有抓取记录必须带 `fetched_at`。

### 3.3 空值与真实性

- 未获取：`null`，不用 `""`、`"N/A"`、`"unknown"`。
- 数组无数据：`[]`。
- 不允许 LLM 生成邮箱、电话、CNPJ、地址；这些字段只能来自原文或官方 API。
- 每个非结构化字段附 `evidence`（原文引用 + URL + 时间 + 提取器）。

### 3.4 置信度

- `confidence ∈ [0,1]`，保留两位小数。
- 类型/字段/去重均记录 confidence 与 `method`（`rule` / `regex` / `api` / `llm` / `manual`）。
- 低于阈值的记录进入人工复核，不静默丢弃。

### 3.5 版本

- `pipeline_version`：代码版本（git sha）。
- `taxonomy_version`：产品/客户类型词典版本。
- `prompt_version`：LLM 提示词版本。
- `score_version`：评分公式版本。
- 每次 run 记录以上版本，保证结果可复现与可比较。

### 3.6 语言

- 对外展示：中文（面试/内部），客户字段保留葡语原文。
- 抓取查询：`pt-BR` 为主，`en` 为辅。
- LLM 输出：结构化 JSON（字段名英文），理由可中文。

---

## 4. 推荐阅读顺序

1. `00-architecture.md` — 先理解运行模型与状态机
2. `01` → `02` → `03` → `04` → `05` — 数据如何一步步变干净
3. `06` → `07` — 如何判断「值不值得跟」与「是不是同一家」
4. `08` → `09` — 如何落库与暴露 API
5. `10` → `11` — 如何展示与交付
6. `12` → `13` → `14` — 质量、合规、上线

---

## 5. 文档维护

- 修改数据契约必须同步 `08-data-model.md` 与相关模块。
- 新增数据源：在 `03-discovery.md` 增加适配器章节，并更新 M3 验收标准。
- 新增字段：先改 `08`，再改 pipeline 与前端。
- 每次重要决策在文末「决策记录」追加一行（日期 / 决策 / 原因 / 影响模块）。
