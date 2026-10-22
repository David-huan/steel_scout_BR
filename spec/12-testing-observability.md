# M12 — 测试、评测与可观测性

> 状态：设计基线 · 依赖：全部模块 · 关联：M7、M9、M14 · 代码：`backend/tests/*`、`scripts/eval.py`

## 1. 目标

让「客户质量」可被度量，而不是靠感觉：

1. 每次改动不破坏核心流程（单测/集成/契约）。
2. 用金标准集量化召回、准确率、去重质量。
3. 线上可看到每个阶段耗时、成功率、成本、失败原因。
4. 回归可比较（同输入分数/公司数不应无故大幅波动）。

## 2. 测试金字塔

| 层级 | 范围 | 工具 | 是否联网 | 运行时机 |
|---|---|---|---|---|
| 单元 | 规范化、正则、评分、schema、状态机 | pytest | 否 | 每次提交 |
| 契约 | 外部 API fixture、OpenAPI | pytest + responses | 否 | 每次提交 |
| 集成 | 完整 pipeline（mock 外部） | pytest + 临时 SQLite | 否 | 每次提交 |
| 前端 | 页面/交互/筛选 | Vitest + Testing Library | 否 | 每次提交 |
| E2E | 发起 run → 看结果 → 导出 | Playwright | 否（mock API） | 合并前 |
| 冒烟 | 3 个真实站点抓取 | 脚本 | 是 | 每日/手动 |
| 评测 | 金标准集指标 | `scripts/eval.py` | 否（缓存） | 每周/发版前 |

## 3. 单元测试清单

| 模块 | 用例 |
|---|---|
| M1 Brief | 国家别名、产品别名、未知产品、冲突过滤、NCM 白名单 |
| M2 Query | 模板渲染、葡语介词、去重、优先级、预算截断、LLM 非法输出 |
| M3 Discovery | URL 规范化、非公司过滤、早期去重、来源 mock、预算 |
| M4 Crawl | 邮箱混淆、模板邮箱过滤、电话归一、CNPJ 校验、地址/CEP、robots、SSRF、HTML 解析 |
| M5 Enrich | CNPJ 映射、地址拼接、CNAE 先验、注销状态、冲突合并、缓存 |
| M6 Classify | 硬过滤、规则分类、LLM schema、证据校验、冲突、封顶 |
| M6 Score | 每个子项边界、权重和、四舍五入、版本、无数据降级 |
| M7 Dedup | 名称规范化、blocking、override、否决、合并字段、拆分、幂等 |
| M9 API | 校验、过滤、分页、错误码、状态机、幂等键、导出 |
| M11 Export | CSV 转义、BOM、多值、公式注入、DNC、字段映射 |

### 3.1 关键 fixture

```
tests/fixtures/
  html/static_company.html
  html/js_shell.html
  html/obfuscated_email.html
  html/multi_unit.html
  serper/query_*.json
  places/city_*.json
  cnpj/active.json, inactive.json, not_found.json
  llm/classify_*.json, extract_*.json, invalid.json
  company/jatinox.json, tech_inox.json, brasil_inox.json
  dedup/pairs.csv
```

## 4. 金标准集（Gold Set）

### 4.1 构成

| 数据集 | 规模 | 标注内容 | 来源 |
|---|---|---|---|
| 公司相关性 | 100 家 | 是否目标客户、类型、州、产品 | 人工从 demo 结果+补充 |
| 去重对 | 100 对 | 同实体/不同实体、集团/法人 | 人工构造（含难例） |
| 邮箱抽取 | 50 页 | 正确邮箱/角色/是否应过滤 | 人工标注真实页面 |
| 查询相关性 | 30 条 | 查询是否属于目标语义 | 人工 |
| 评分校准 | 50 家 | 业务主观 A/B/C（可选） | 业务同事 |

### 4.2 去重难例（必须包含）

- Jatinox 三域名；
- Tech-Inox 官网/邮箱域不同；
- Brasil Inox `.com.br`/`.ind.br`；
- Jacinox vs Jatinox（不同实体）；
- 同集团两个 CNPJ；
- 同名不同州；
- 品牌缩写 vs 全称；
- 收购后更名。

### 4.3 指标

| 指标 | 定义 | 目标 |
|---|---|---|
| Discovery recall | 金标准公司中被系统发现的占比 | ≥ 70% |
| Candidate precision | 进入抓取的候选中相关占比 | ≥ 60% |
| Email coverage | A/B 客户中有业务邮箱的占比 | ≥ 65% |
| Email accuracy | 抽取邮箱中正确占比 | ≥ 95% |
| Type accuracy | 类型判断正确占比 | ≥ 85% |
| Dedup precision | 自动合并对中正确占比 | ≥ 95% |
| Dedup recall | 应合并对中被发现占比 | ≥ 85% |
| Review rate | 进入人工复核的 pair 占比 | ≤ 10% |
| Cost per qualified | 成本 / A/B 客户数 | ≤ $0.50（demo） |
| Run success rate | 无 fatal 的 run 占比 | ≥ 95% |

### 4.4 评测脚本

```bash
python scripts/eval.py \
  --gold tests/gold/companies.csv \
  --dedup-gold tests/gold/dedup_pairs.csv \
  --predictions data/eval/latest.json \
  --out reports/eval_2026-10-22.json
```

输出：

```json
{
  "run_id": "eval_20261022",
  "version": { "pipeline": "abc123", "taxonomy": "...", "score": "..." },
  "discovery_recall": 0.74,
  "candidate_precision": 0.63,
  "email_coverage": 0.68,
  "email_accuracy": 0.96,
  "type_accuracy": 0.86,
  "dedup_precision": 0.96,
  "dedup_recall": 0.87,
  "review_rate": 0.08,
  "cost_per_qualified": 0.42,
  "failures": [
    { "company": "X", "reason": "no_email", "expected": "A", "predicted": "B" }
  ]
}
```

- CI 门槛：dedup precision < 0.95、email accuracy < 0.90、type accuracy < 0.80 → 阻止合并。
- 每次发版保存报告，趋势对比。

## 5. 集成测试

用 mock adapters 跑完整流程：

```
brief → queries → discovery(mock 30 candidates) → crawl(mock 20 sites)
→ enrich(mock CNPJ) → classify/score → dedup → persist
```

断言：

- 产出 ≥ 15 家；
- A/B ≥ 5；
- 无重复域名；
- 所有公司有 source_url；
- 分数/等级可解释；
- 重复执行幂等（公司数不变）。

## 6. 前端测试

- 组件：Table 排序/筛选、Drawer tab、TierBadge。
- 交互：发起 run（mock 202）、轮询状态、标记合格、合并确认。
- 可访问性：jest-axe 关键页面。
- E2E：Playwright 走「首页 → 结果 → Drawer → 导出」。

## 7. 日志规范

结构化 JSON：

```json
{
  "ts": "2026-10-22T13:05:00.123Z",
  "level": "info",
  "service": "worker",
  "request_id": "req_...",
  "run_id": "run_...",
  "stage": "crawl",
  "event": "page_fetched",
  "domain": "tech-inox.ind.br",
  "url": "https://tech-inox.ind.br/",
  "status": 200,
  "duration_ms": 412,
  "bytes": 48210,
  "method": "httpx",
  "retry": 0
}
```

必须：

- 每个外部调用记录 `adapter, duration_ms, status, retry, cost_usd`。
- 错误记录 `error_code, message, retryable`。
- 不记录：完整 HTML、邮箱列表、密钥、Authorization、Cookie。

## 8. 指标（Metrics）

### 8.1 业务/质量

| 指标 | 类型 | 说明 |
|---|---|---|
| `run_total` | counter | 按状态 |
| `run_duration_seconds` | histogram | 端到端 |
| `stage_duration_seconds` | histogram | 按 stage |
| `candidates_total` | counter | 按 source |
| `companies_total` | counter | 按 tier/type/state |
| `email_coverage_ratio` | gauge | A/B 邮箱覆盖 |
| `dedup_auto_merge_total` | counter | 自动合并数 |
| `dedup_review_queue_size` | gauge | 待复核 |
| `cost_usd_total` | counter | 按 source/stage |
| `llm_tokens_total` | counter | 输入/输出 |

### 8.2 系统

| 指标 | 说明 |
|---|---|
| `http_request_duration_seconds` | API P50/P95/P99 |
| `http_errors_total` | 按 code |
| `adapter_errors_total` | 按 source/error_code |
| `crawl_success_ratio` | 成功页/总页 |
| `db_query_duration_seconds` | 慢查询 |
| `queue_depth` | 生产任务积压 |

## 9. 告警

| 条件 | 级别 | 动作 |
|---|---|---|
| run 失败率 > 20%（15 min） | P1 | 通知 + 检查外部依赖 |
| Serper/Places 错误率 > 50% | P1 | 切换备用/暂停 |
| 单 run 成本 > 预算 1.5x | P2 | 熔断 + 排查查询 |
| crawl 成功率 < 50% | P2 | 检查反爬/代理 |
| dedup 复核队列 > 100 | P3 | 增加人工/调阈值 |
| API P95 > 1s | P2 | 查慢查询/索引 |
| 邮箱覆盖率骤降 > 20% | P2 | 检查抽取规则/站点变化 |

## 10. 数据质量监控

每日/每 run 检查：

- 邮箱语法/MX 通过率；
- 邮箱域与官网域不一致比例（应为少数，且可解释）；
- 公司无来源/无证据比例（应 0）；
- 重复公司率（抽样）；
- `tier=A` 但无邮箱比例；
- CNPJ 校验失败率；
- 抓取 403/超时比例；
- LLM schema 失败率。

异常写入 `data_quality_events` 或在 run 报告中标记。

## 11. 回归与版本对比

- 每次发版跑同一 `seed run`（固定候选/查询），比较：
  - 公司数、A/B 数、邮箱覆盖、去重结果；
  - 分数分布（均值/方差）；
  - 成本/耗时。
- 允许阈值内波动；超出需解释（如评分权重调整）。
- 保存 `reports/regression_{date}.json`。

## 12. 验收标准

1. CI 在无网络环境下跑通单测/集成/前端测试。
2. 金标准评测可一键运行并输出 JSON + 可读报告。
3. 去重 precision/recall 达标，且难例全部覆盖。
4. 每个 run 的关键指标可在 `/api/stats` 与日志中查到。
5. 告警规则可触发（用 mock 指标测试）。
6. 日志无邮箱/密钥泄漏（自动扫描测试）。
7. 发版回归报告可对比上一版。

## 13. 待定

- 是否接入 OpenTelemetry + Grafana/Tempo。
- 金标准集由谁维护、多久更新一次。
- 是否用 LLM-as-judge 做大规模相关性评估（需人工抽检校准）。
- 是否把「回复率/成交」接入，做真正的闭环评估。
