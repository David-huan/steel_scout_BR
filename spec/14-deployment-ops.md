# M14 — 部署与运维

> 状态：设计基线 · 依赖：全部模块 · 关联：M9、M12、M13 · 代码：`docker-compose.yml`、`.env.example`

## 1. 目标

让系统在三种环境可运行：

| 环境 | 用途 | 数据 | 外部依赖 |
|---|---|---|---|
| Local | 开发/面试 demo | SQLite | 真实 API（可选 mock） |
| Staging | 联调/评测 | Postgres | 真实 API + 限额 |
| Prod | 日常获客 | Postgres + 对象存储 | 正式 API + 监控 |

要求：一条命令启动、配置全环境变量、失败可诊断、数据可备份/恢复。

## 2. 本地运行

```bash
# 1. 配置
copy .env.example .env
# 填入 SERPER_API_KEY / GOOGLE_MAPS_API_KEY / OPENAI_API_KEY

# 2. 后端
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
playwright install chromium
uvicorn app.main:app --reload --port 8000

# 3. 前端
cd frontend
npm install
npm run dev
```

访问：

- Web: http://localhost:5173
- API: http://localhost:8000
- Docs: http://localhost:8000/docs

### 2.1 无密钥降级

- 无 Serper：仅 Places/目录（需 Maps key）或导入 `data/seed_candidates.csv`。
- 无 Maps：仅 SERP。
- 无 LLM：规则分类 + 正则抽取 + 关键词评分。
- 全无：`DEMO_MODE=true` 使用本地 seed 数据跑通 UI。

## 3. Docker Compose

```yaml
services:
  api:
    build: ./backend
    env_file: .env
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  web:
    build: ./frontend
    ports: ["5173:80"]
    depends_on: [api]

  worker:
    build: ./backend
    env_file: .env
    volumes:
      - ./data:/app/data
    command: python -m app.workers.runner
    depends_on: [api]
    profiles: ["prod"]

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: steel
      POSTGRES_USER: steel
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    profiles: ["prod"]

volumes:
  pgdata:
```

- demo 默认不启 `db/worker`：API 进程内跑 worker + SQLite。
- 生产：`docker compose --profile prod up -d`，API 与 worker 分离，DB 独立。

## 4. 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `APP_ENV` | 否 | `dev` | dev/staging/prod |
| `DATABASE_URL` | 是 | `sqlite:///./steel.db` | 生产用 Postgres |
| `SERPER_API_KEY` | 建议 | — | Google SERP |
| `GOOGLE_MAPS_API_KEY` | 建议 | — | Places |
| `OPENAI_API_KEY` | 建议 | — | LLM |
| `OPENAI_BASE_URL` | 否 | OpenAI | 兼容接口 |
| `LLM_MODEL` | 否 | `gpt-4o-mini` | 模型名 |
| `MAX_QUERIES` | 否 | `40` | 预算 |
| `MAX_CANDIDATES` | 否 | `300` | 预算 |
| `MAX_SITES` | 否 | `120` | 预算 |
| `MAX_COST_USD` | 否 | `8` | 熔断 |
| `CRAWL_RATE_LIMIT` | 否 | `1` | req/s/domain |
| `CRAWL_MAX_PAGES` | 否 | `10` | 每站 |
| `HTTP_TIMEOUT` | 否 | `20` | 秒 |
| `CORS_ORIGINS` | 否 | `http://localhost:5173` | 逗号分隔 |
| `LOG_LEVEL` | 否 | `INFO` | |
| `EXPORT_DIR` | 否 | `./data/exports` | |
| `RAW_HTML_DIR` | 否 | `./data/raw` | |
| `DEMO_MODE` | 否 | `false` | 使用 seed |
| `API_KEY` | 否 | — | demo 简单鉴权 |
| `POSTGRES_PASSWORD` | 生产 | — | |

校验：

- 启动时打印「已配置/缺失」的依赖（不打印值）。
- `GET /api/health` 返回各依赖状态；缺失为 `degraded`，不阻止启动。

## 5. 生产拓扑

```
            ┌────────────┐
Internet ──►│ CDN/Nginx  │──► Web (static)
            └─────┬──────┘
                  │ /api
            ┌─────▼──────┐      ┌──────────────┐
            │ API (x N)  │─────►│ PostgreSQL   │
            └─────┬──────┘      └──────────────┘
                  │ enqueue
            ┌─────▼──────┐      ┌──────────────┐
            │ Worker (x N)│─────►│ Object Store │ (HTML 快照)
            └─────┬──────┘      └──────────────┘
                  │
        ┌─────────▼─────────┐
        │ External APIs      │
        └───────────────────┘
```

- API 无状态，可水平扩展。
- Worker 独立扩展；任务按 run 分片，单 run 内串行 stage。
- DB 主从/托管；对象存储放 HTML 快照与导出。
- 出口 IP 固定（便于 API 白名单）或代理池。

## 6. 健康检查

`GET /api/health`：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "checks": {
    "db": { "status": "ok", "latency_ms": 3 },
    "serper": { "status": "configured" },
    "places": { "status": "configured" },
    "llm": { "status": "configured" }
  },
  "time": "2026-10-22T13:00:00Z"
}
```

- `ok`：全部正常。
- `degraded`：部分外部源缺失，可运行。
- `down`：DB 不可用。

生产用 `/api/health` 做 liveness，`/api/health?deep=true` 做 readiness（含外部探测，限频）。

## 7. 备份与恢复

### 7.1 SQLite（demo）

```powershell
# 备份
sqlite3 steel.db ".backup 'data/backups/steel_20261022.db'"
# 恢复
copy data\backups\steel_20261022.db steel.db
```

- 每日备份，保留 14 天。
- 备份前 `PRAGMA wal_checkpoint(TRUNCATE)`。

### 7.2 Postgres（生产）

```bash
pg_dump -Fc "$DATABASE_URL" > backup_$(date +%F).dump
pg_restore -d "$DATABASE_URL" backup_2026-10-22.dump
```

- 每日全量 + WAL 归档（PITR）。
- 保留 30 天；每季度恢复演练。
- 备份加密，异地存储。

### 7.3 对象存储

- HTML 快照 30 天生命周期；导出文件 24h 生命周期。
- 版本化开启，防误删。

## 8. 发布流程

1. CI：lint + 单测 + 集成 + 前端测试 + 依赖扫描。
2. 构建镜像（tag = git sha）。
3. Staging 部署，跑 `seed run` + 金标准评测。
4. 对比上一版：公司数、A/B 数、邮箱覆盖、去重指标、成本。
5. 生产灰度（10% 流量/单租户）→ 全量。
6. 失败回滚上一镜像；数据库迁移需可逆（Alembic downgrade 或备份恢复）。

## 9. 运行手册（Runbook）

### 9.1 任务一直 `queued`

- 检查 worker 是否运行（`/api/health`、进程列表）。
- 检查 DB 锁/连接数。
- 查看日志 `event=run_claimed`。
- 处理：重启 worker；确认无重复 worker 抢同一 run。

### 9.2 发现结果很少

- 检查 `source_status`：Serper 配额/Places 配额。
- 检查查询数是否被预算截断。
- 检查国家/产品是否误判（`brief.needs_review`）。
- 处理：放宽预算/补来源/重跑。

### 9.3 抓取成功率低

- 看 `error_code` 分布：403/超时/JS/robots。
- 403 多：降速、换 UA、Playwright；仍失败跳过。
- 超时多：网络/代理；提高超时。
- JS 多：确认 Playwright 安装/浏览器依赖。

### 9.4 邮箱覆盖率骤降

- 站点改版/邮箱混淆方式变化。
- 检查抽取规则与样本；更新正则/fixture。
- 不要为覆盖率猜测邮箱。

### 9.5 去重复核积压

- 查看队列分数分布；若集中在 0.85–0.88，考虑调阈值/加规则。
- 增加人工或暂停自动导入。
- 禁止批量「全部合并」。

### 9.6 成本超预算

- 查看 `cost_usd` 按 stage/source。
- 降低 `max_queries`/`max_sites`；关闭低产出源。
- 缓存命中的 CNPJ/Places 不应重复计费。

### 9.7 DB 锁（SQLite）

- 确认 WAL 开启；写事务短小。
- 单 worker；避免并发写。
- 生产切 Postgres。

### 9.8 密钥失效

- 轮换 key；更新 Secret；
- 重启 API/worker；
- 检查 401/403 日志，重跑失败任务。

## 10. 容量与成本

| 规模 | 配置 | 估算 |
|---|---|---|
| demo | 1 API（1 vCPU/1GB） | 单 run < 25 min，< $8 |
| 小团队 | API 2 + worker 2（2 vCPU/4GB） | 10 run/天，< $100/月 API |
| 生产 | API 2–4 + worker 4–8 + PG 4 vCPU | 50 run/天，按 API 用量计 |

成本控制：

- 查询/站点/LLM 调用硬上限。
- 缓存 CNPJ/Places/页面。
- 小模型做分类，大模型只做难例。
- 低产出源自动降权。
- 每日成本报表与告警。

## 11. 安全加固

- 容器非 root、只读根文件系统、最小镜像。
- 网络策略：worker 只能出公网；DB 只内网。
- 密钥用 Secret Manager；不进镜像/仓库。
- TLS 终止在网关；内部也尽量 TLS。
- 定期打补丁；依赖扫描。
- 日志脱敏；访问审计。
- 备份加密；恢复权限最小化。

## 12. 监控与告警

- 指标：M12 列表（run/阶段/来源/成本/质量）。
- 仪表盘：
  - Run 漏斗与成功率；
  - 来源错误率/配额；
  - 抓取成功率；
  - A/B 产出与邮箱覆盖；
  - 成本趋势；
  - 去重队列。
- 告警：M12 第 9 节；通知到 Slack/飞书/邮件。

## 13. 验收标准

1. 新机器按 README 命令 10 分钟内启动并跑通 demo。
2. `docker compose up` 可启动 api/web；`--profile prod` 加 db/worker。
3. 健康检查正确反映 DB/外部依赖状态。
4. 备份可在空库恢复，数据行数一致。
5. 发布可回滚；迁移有 downgrade 或备份方案。
6. Runbook 覆盖 8 类常见故障。
7. 成本/质量仪表盘可用，告警可触发。
8. 容器以非 root 运行，密钥不在镜像中。

## 14. 待定

- 云厂商选择（AWS/GCP/阿里云）与区域（巴西圣保罗？）。
- 是否用托管队列（SQS/Cloud Tasks）替代自建 worker。
- 多租户部署模型（单库多租户 vs 独立实例）。
- 是否需要在巴西本地部署以满足数据驻留。
- 静态前端托管（CDN/S3）与 API 同域策略。
