# M9 — 后端与 API

> 状态：设计基线 · 依赖：M8 · 关联：M1–M7、M10、M11 · 代码：`backend/app/main.py`
>
> 实现状态（2026-10-22）：MVP 已实现 `POST /api/runs`、`GET /api/runs`、`GET /api/runs/{id}`、`GET /api/runs/{id}/companies`、`GET /api/runs/{id}/events`、`GET /api/companies/{id}`、`POST /api/companies/{id}/review`、`GET /api/dedup/queue`、`POST /api/dedup/{pair_id}/merge`、`POST /api/dedup/{pair_id}/dismiss`、`GET /api/export`、`GET /api/health`。cancel/retry/rescore/stages/queries/PATCH/suppress/split/stats 为后续迭代。MVP 的 run 终态为 `completed` / `failed`。

## 1. 目标

提供稳定、可测试的 REST API，让前端能：

1. 发起/取消/重试客户发现任务；
2. 查看阶段进度与统计；
3. 筛选/查看/复核客户；
4. 处理去重队列；
5. 导出结果。

后端同时负责**任务编排**与**持久化**，但业务逻辑放在 `pipeline/`，API 层保持薄。

## 2. 技术栈

| 项 | 选型 |
|---|---|
| 框架 | FastAPI + Pydantic v2 |
| 数据访问 | `sqlite3`（stdlib，MVP）→ SQLAlchemy 2.x（生产） |
| DB | SQLite（demo）/ PostgreSQL（生产） |
| 迁移 | `db.py` 内联 schema（MVP）→ Alembic |
| 任务 | FastAPI `BackgroundTasks`（MVP）；生产 RQ/Celery/Postgres 队列 |
| 日志 | `events` 表 + uvicorn 日志 |
| 测试 | `unittest` + FastAPI `TestClient`（MVP）→ pytest + Testcontainers |

## 3. 目录结构

```
backend/app/
  main.py                # FastAPI app, CORS, lifespan, routes, static dist
  config.py              # env + paths
  db.py                  # sqlite3 schema/connection/events
  schemas.py             # Pydantic DTO
  pipeline/              # 纯业务，不 import fastapi
    orchestrator.py
    brief.py queries.py discovery.py crawl.py enrich.py classify.py score.py dedup.py
  data/seed_candidates.csv
backend/tests/
  test_pipeline.py
```

> 生产化时再拆 `api/`、`repositories/`、`services/`、`workers/`；MVP 将路由集中在 `main.py`，以 19–200 家规模优先可运行性。

## 4. 任务编排

### 4.1 创建任务

```
POST /api/runs
```

```json
{
  "product": "Stainless Steel Flat / Profiles",
  "country": "Brazil",
  "target_count": 15,
  "sources": ["serper", "places", "abinox", "directory"],
  "options": {
    "max_queries": 40,
    "max_candidates": 300,
    "max_sites": 120,
    "max_cost_usd": 8,
    "regions": ["SP", "PR", "SC", "MG"]
  },
  "locale": "pt-BR"
}
```

响应 `202 Accepted`：

```json
{
  "run_id": "run_20261022_001",
  "status": "queued",
  "created_at": "2026-10-22T13:00:00Z"
}
```

**幂等**：支持 `Idempotency-Key` 头；相同 key 24h 内返回同一 run。

### 4.2 执行循环（worker）

```python
async def run_pipeline(run_id):
    ctx = load_context(run_id)
    for stage in [brief, queries, discovery, crawl, enrich, classify_score, dedup_persist]:
        if not acquire_stage_lock(run_id, stage.name):
            continue
        mark_stage(run_id, stage.name, "running")
        try:
            result = await stage.run(ctx)
            mark_stage(run_id, stage.name, result.status, result.stats, result.warnings)
        except StageFatal as e:
            mark_stage(run_id, stage.name, "failed", error=str(e))
            mark_run(run_id, "failed")
            return
        except Exception as e:
            mark_stage(run_id, stage.name, "partial", error=str(e))
            # 可继续后续阶段
    finalize_run(run_id)
```

- demo：`asyncio.create_task(run_pipeline(run_id))`，同一 run 只允许一个 worker（DB 锁/状态检查）。
- 生产：队列 + 心跳 + 超时回收；stage 级 checkpoint。
- 取消：设置 `runs.status=cancelled`，worker 在 stage 边界检查。
- 重试：`POST /api/runs/{id}/retry` 从失败 stage 继续（`resume_from`）。
- 重跑：`POST /api/runs` 新 run，可引用旧 `run_id` 复制 brief/queries。

### 4.3 进度事件

- 前端轮询 `GET /api/runs/{id}`（2s）。
- 可选 SSE：`GET /api/runs/{id}/events`，事件：
  - `stage.started/succeeded/failed`
  - `candidate.found`（可选，量大时关闭）
  - `company.qualified`
  - `run.finished`

## 5. API 一览

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（DB、外部依赖配置） |
| POST | `/api/runs` | 创建任务 |
| GET | `/api/runs` | 任务列表（分页） |
| GET | `/api/runs/{id}` | 任务详情 + 阶段 + 统计 |
| POST | `/api/runs/{id}/cancel` | 取消 |
| POST | `/api/runs/{id}/retry` | 从失败阶段重试 |
| POST | `/api/runs/{id}/rescore` | 用当前评分配置重算 |
| GET | `/api/runs/{id}/stages` | 阶段状态 |
| GET | `/api/runs/{id}/queries` | 查询及命中 |
| GET | `/api/runs/{id}/companies` | 结果列表（筛选/排序/分页） |
| GET | `/api/companies/{id}` | 客户详情 + 证据 |
| PATCH | `/api/companies/{id}` | 人工修正字段/类型 |
| POST | `/api/companies/{id}/review` | 标记 qualified/rejected/DNC |
| POST | `/api/companies/{id}/suppress` | 加入禁止联系 |
| GET | `/api/dedup/queue` | 待复核实体对 |
| POST | `/api/dedup/{pair_id}/merge` | 合并 |
| POST | `/api/dedup/{pair_id}/reject` | 保持独立 |
| POST | `/api/companies/{id}/split` | 拆分 |
| GET | `/api/export` | CSV/XLSX 导出 |
| GET | `/api/stats` | 全局统计（覆盖率/成本/质量） |

## 6. 请求/响应契约

### 6.1 `GET /api/runs/{id}`

```json
{
  "run_id": "run_20261022_001",
  "status": "running",
  "current_stage": "crawl",
  "product": "Stainless Steel Flat / Profiles",
  "country": "BR",
  "target_count": 15,
  "progress": { "stages_done": 3, "stages_total": 7, "percent": 43 },
  "stats": {
    "queries": 38,
    "candidates": 126,
    "companies": 84,
    "tier_a": 7,
    "tier_b": 18,
    "with_email": 41,
    "cost_usd": 2.14
  },
  "stages": [
    { "stage": "brief", "status": "succeeded", "started_at": "...", "finished_at": "..." },
    { "stage": "queries", "status": "succeeded", "stats": { "count": 38 } },
    { "stage": "discovery", "status": "succeeded", "stats": { "candidates": 126 } },
    { "stage": "crawl", "status": "running", "stats": { "done": 32, "total": 84 } }
  ],
  "budget": { "max_cost_usd": 8, "used_usd": 2.14 },
  "warnings": ["serper_rate_limited: retried 2x"],
  "created_at": "...",
  "started_at": "...",
  "finished_at": null
}
```

### 6.2 `GET /api/runs/{id}/companies`

Query：

| 参数 | 类型 | 说明 |
|---|---|---|
| `tier` | `A,B` | 等级 |
| `type` | `importer_distributor` | 客户类型 |
| `state` | `SP,PR` | 州 |
| `has_email` | bool | 是否有邮箱 |
| `dedup_status` | `unique,review` | 去重状态 |
| `q` | string | 名称/域名/邮箱搜索 |
| `sort` | `total_desc,created_desc,name_asc` | 排序 |
| `page` | int | 默认 1 |
| `page_size` | int | 默认 20，最大 100 |
| `include_merged` | bool | 默认 false |

响应：

```json
{
  "items": [
    {
      "company_id": "cmp_0007",
      "display_name": "Tech-Inox",
      "legal_name": "TECH INOX DISTRIBUIDORA DE ACO INOX LTDA",
      "website": "https://tech-inox.ind.br",
      "state": "PR",
      "city": "Curitiba",
      "primary_type": "importer_distributor",
      "score": 82,
      "tier": "A",
      "email": "atendimento@techmetais.com.br",
      "phone": "+5541995967661",
      "products": ["chapas", "bobinas", "barras"],
      "dedup_status": "unique",
      "review_status": "new"
    }
  ],
  "total": 84,
  "page": 1,
  "page_size": 20,
  "filters_applied": { "tier": ["A"] }
}
```

### 6.3 `GET /api/companies/{id}`

返回 M5 `EnrichedCompany` + M6 评分 + 证据 + 来源 + 去重关系 + 审计摘要。

```json
{
  "company": { "...": "..." },
  "score": { "total": 82, "tier": "A", "breakdown": { "...": 0 }, "reasons": ["..."] },
  "sources": [{ "field": "emails", "value": "...", "quote": "...", "source_url": "...", "fetched_at": "..." }],
  "domains": ["tech-inox.ind.br", "techmetais.com.br"],
  "aliases": ["Tech-Inox", "Tech Metais"],
  "group": null,
  "dedup": { "status": "unique", "possible_duplicates": [] },
  "review": { "status": "new", "reviewed_by": null, "note": null }
}
```

### 6.4 `POST /api/companies/{id}/review`

```json
{ "action": "qualified", "note": "有进口+加工能力，A 级跟进" }
```

`action ∈ qualified | rejected | do_not_contact | reset`。

响应：更新后的 review 状态 + 审计事件 ID。

### 6.5 `GET /api/dedup/queue`

```json
{
  "items": [
    {
      "pair_id": "ddp_000031",
      "score": 0.89,
      "left": { "company_id": "cmp_0007", "name": "Tech-Inox", "domains": ["tech-inox.ind.br"], "cnpj": null },
      "right": { "company_id": "cmp_0012", "name": "Tech Metais", "domains": ["techmetais.com.br"], "cnpj": null },
      "features": { "name_sim": 0.93, "state_match": true, "phone_match": false },
      "reasons": ["名称高度相似", "同州"]
    }
  ],
  "total": 3
}
```

### 6.6 `POST /api/dedup/{pair_id}/merge`

```json
{ "canonical_id": "cmp_0007", "note": "同一公司，邮箱域不同" }
```

响应：`{ "canonical_id": "...", "merged_ids": ["..."], "event_id": 123 }`。

### 6.7 `GET /api/export`

Query：`run_id`, `format=csv|xlsx`, `tier=A,B`, `include_evidence=true`, `include_merged=false`。

响应：文件流，`Content-Disposition` 带时间戳。字段见 M11。

## 7. 错误格式

```json
{
  "error": {
    "code": "UNSUPPORTED_COUNTRY",
    "message": "Country 'Atlantis' is not supported",
    "details": { "supported": ["BR"] },
    "request_id": "req_..."
  }
}
```

| HTTP | code | 场景 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 参数缺失/类型错 |
| 400 | `UNSUPPORTED_COUNTRY` | 国家不支持 |
| 400 | `CONFLICTING_FILTERS` | 过滤条件冲突 |
| 401 | `UNAUTHORIZED` | 缺少/错误 token |
| 403 | `FORBIDDEN` | 无权限 |
| 404 | `RUN_NOT_FOUND` / `COMPANY_NOT_FOUND` | 资源不存在 |
| 409 | `RUN_ALREADY_RUNNING` | 重复执行 |
| 409 | `MERGE_CONFLICT` | 并发合并 |
| 422 | `INVALID_TRANSITION` | 状态不允许 |
| 429 | `RATE_LIMITED` | 客户端限流 |
| 500 | `INTERNAL_ERROR` | 未捕获异常 |
| 503 | `DEPENDENCY_UNAVAILABLE` | DB/外部依赖不可用 |

- 所有错误带 `request_id`，日志可关联。
- 不把堆栈/密钥/SQL 暴露给客户端。

## 8. 鉴权与权限（生产）

| 角色 | 权限 |
|---|---|
| viewer | 查看 run/公司/导出只读 |
| analyst | 创建 run、复核、合并/拆分 |
| admin | 配置、用户管理、删除/匿名化 |

- demo：可选 `X-API-Key`；本地默认关闭。
- 生产：OIDC/JWT，后端校验 `tenant_id` + role。
- 导出含邮箱，需 `analyst` 以上；下载记审计。

## 9. 配置

```env
APP_ENV=dev
DATABASE_URL=sqlite:///./steel.db
SERPER_API_KEY=
GOOGLE_MAPS_API_KEY=
OPENAI_API_KEY=
OPENAI_BASE_URL=
LLM_MODEL=gpt-4o-mini
MAX_QUERIES=40
MAX_CANDIDATES=300
MAX_SITES=120
MAX_COST_USD=8
CRAWL_RATE_LIMIT=1
CRAWL_MAX_PAGES=10
HTTP_TIMEOUT=20
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:5173
```

- 启动时校验必填项；缺失时 `/api/health` 返回 `degraded`，不直接崩溃（便于 demo）。
- 密钥只从环境变量读取，不写日志。

## 10. 日志与观测

- 结构化 JSON：`ts, level, request_id, run_id, stage, event, duration_ms, cost_usd, error_code`。
- 每个外部调用的耗时/状态/重试次数。
- 不记录完整 HTML、邮箱列表、API key。
- 指标见 M12。

## 11. 测试

- 单测：schema 校验、过滤器、分页、错误映射、状态机。
- 集成：TestClient + 临时 SQLite + mock adapters，跑完整 run。
- 契约：OpenAPI snapshot；前端类型由 `openapi-typescript` 生成。
- 幂等：同 `Idempotency-Key` 返回同一 run；重复 stage 不重复写。

## 12. 验收标准

1. `POST /api/runs` 后 2s 内可查到 run，状态从 `queued → running → succeeded`。
2. 列表筛选（tier/type/state/has_email）与排序正确，分页稳定。
3. 取消后 worker 在 5s 内停止，状态 `cancelled`。
4. 失败 stage 可通过 retry 继续，不重复已完成阶段。
5. 合并/拆分/复核均写 `events`，可追溯。
6. 导出文件字段与 M11 一致，含证据开关。
7. OpenAPI 文档可访问 `/docs`，前端类型可生成。
8. 无密钥泄漏；错误响应不含堆栈。

## 13. 待定

- 是否用 SSE 还是 WebSocket 做实时进度（demo 轮询足够）。
- 多租户与配额管理。
- 任务队列选型（Postgres SKIP LOCKED vs Redis）。
- 导出大文件是否异步生成 + 下载链接。
