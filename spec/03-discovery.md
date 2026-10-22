# M3 — 客户发现（Discovery）

> 状态：设计基线 · 依赖：M1、M2 · 关联：M4、M7 · 代码：`pipeline/discover.py`、`services/serper.py`、`services/places.py`

## 1. 目标

用多个公开来源，把查询变成**候选公司**（不是最终客户），并尽可能早地降噪、去重、保留证据。

关键指标：

- 召回：目标国家/产品下的相关公司数量。
- 精度：进入抓取阶段的候选中，真正相关的比例。
- 单位成本：每条合格候选的 API 成本。
- 覆盖率：州/客户类型/产品形态的分布是否均衡。

## 2. 适配器接口

```python
class DiscoveryAdapter(Protocol):
    name: str
    source_type: str
    def search(self, query: Query, brief: Brief, limit: int) -> list[Candidate]: ...
```

统一异常：`AdapterError(code, retryable, detail)`。

每个适配器必须：

- 只返回公开 B2B 信息；
- 带 `source_url`、`snippet`、`query_id`；
- 遵守 API 条款与限速；
- 可被 mock（测试不联网）。

## 3. 来源与优先级

| 来源 | `source_type` | 可靠性权重 | 覆盖 | 成本 | 自动化 |
|---|---|---|---|---|---|
| Google SERP（Serper.dev） | `serp` | 0.75 | 官网/目录/新闻 | 低 | 全自动 |
| Google Places（New） | `places` | 0.85 | 本地分销商，带地址/电话 | 中 | 全自动 |
| ABINOX 会员名录 | `association` | 0.90 | 高相关不锈钢企业 | 低 | 半自动（结构变化需修） |
| B2B 目录（Quem Fornece 等） | `directory` | 0.65 | 中小进口商 | 低 | 半自动 |
| 展会 exhibitor list | `exhibition` | 0.80 | 有外贸意向 | 低 | 半自动 |
| 贸易数据（Volza/ImportGenius） | `trade` | 0.95 | 真实进口商/提单 | 高 | 付费/人工 |
| Comex Stat | `trade_aggregate` | 0.60 | NCM 国家/州聚合，无公司名 | 免费 | 仅用于市场判断 |
| 已有客户 lookalike | `lookalike` | 0.70 | 相似官网/描述 | 低 | 半自动 |
| 新闻/招聘 | `signal` | 0.55 | 扩产/进口信号 | 低 | 半自动 |

> 合并时以 `source_reliability` 作为候选置信度先验，不直接决定最终评分。

## 4. 各来源实现

### 4.1 Google SERP（Serper.dev）

```http
POST https://google.serper.dev/search
X-API-KEY: $SERPER_API_KEY
Content-Type: application/json

{
  "q": "distribuidor de aço inoxidável São Paulo",
  "gl": "br",
  "hl": "pt-BR",
  "num": 20,
  "page": 1
}
```

处理：

- 取 `organic[]` 的 `title`、`link`、`snippet`、`position`。
- 第 1 页为主；高优先级查询可取第 2 页。
- 过滤 `google.com.br/search`、`youtube.com`、`facebook.com`、`linkedin.com/company`（后者单独处理）。
- `snippet` 作为证据候选，不当作事实。
- 429/5xx 指数退避；配额耗尽切换备用 provider 或跳过。

### 4.2 Google Places（New）

```http
POST https://places.googleapis.com/v1/places:searchText
X-Goog-Api-Key: $GOOGLE_MAPS_API_KEY
X-Goog-FieldMask: places.id,places.displayName,places.websiteUri,places.formattedAddress,places.nationalPhoneNumber,places.rating,places.userRatingCount,places.businessStatus
Content-Type: application/json

{
  "textQuery": "distribuidor de aço inoxidável em São Paulo",
  "languageCode": "pt-BR",
  "regionCode": "BR",
  "pageSize": 20
}
```

处理：

- `websiteUri` 缺失 → 仍保留候选（name + address + phone），标记 `has_website=false`。
- `businessStatus != OPERATIONAL` → 降权/排除。
- `userRatingCount` 作为规模代理特征（不是评分依据）。
- 按城市轮询，避免只覆盖圣保罗。

### 4.3 ABINOX 与协会目录

- 公开会员列表：名称、网站、城市、类别。
- 解析 HTML 表格/卡片；结构变化时告警，不静默返回空。
- 会员即高置信候选；仍需抓取确认产品与进口能力。
- 其他：ABIMAQ、ABINEE 中与不锈钢下游相关的会员可作为 `end_user` 来源。

### 4.4 B2B 目录

- Quem Fornece、Guia Industrial、Kompass、Europages。
- 只取**公司页**，不抓个人联系人。
- 目录页可能聚合多家公司：先抽取公司卡片，再逐家入候选。
- 目录标注的 `Importador` / `Distribuidor` 作为 `buyer_intent` 证据。

### 4.5 贸易数据

- **Comex Stat**：按 NCM（7219/7220/7222）+ 国家/州查进口额与量，用于市场优先级，不含进口商名。
- **付费提单数据**（Volza/ImportGenius/Panjiva）：字段通常含 importer name、supplier、HS code、weight、value、port、date。
- 接入方式：CSV 导入优先，API 次之；必须有 license 与使用范围说明。
- 匹配：进口商名称 → 规范化 → 与官网/CNPJ 对齐；无法对齐的进入人工队列。

### 4.6 展会/新闻/招聘（信号源）

- 展会 exhibitor list：公司名 + 展位 + 官网。
- 新闻：`expansão`, `nova fábrica`, `investimento` → 扩产信号。
- 招聘：`comprador`, `importação`, `compras internacionais` → 采购团队信号。
- 仅作为 `signals[]` 与加分项，不单独构成候选（除非有官网）。

## 5. 候选数据契约

```json
{
  "candidate_id": "cand_a1b2c3",
  "run_id": "run_20261022_001",
  "source": "serper",
  "source_type": "serp",
  "query_id": "qry_0012",
  "raw_name": "Jatinox - Chapas de Aço Inox",
  "url": "https://www.chapadeinox.com.br/",
  "canonical_domain": "chapadeinox.com.br",
  "snippet": "A Jatinox é uma empresa ... distribuidora exclusiva de matérias-primas em aço inoxidável.",
  "phones": ["+551121720405"],
  "address": "R. Roberto Koch, 363 - Ipiranga, São Paulo/SP",
  "place_id": null,
  "cnpj_hint": null,
  "source_reliability": 0.75,
  "signals": ["distribuidor", "chapas", "bobinas", "barras", "perfis"],
  "negative_signals": [],
  "status": "new",
  "discovered_at": "2026-10-22T13:05:00Z"
}
```

## 6. 早期规范化与降噪

### 6.1 URL 规范化

1. 解析并小写 host，去 `www.`。
2. 去跟踪参数：`utm_*`, `gclid`, `fbclid`, `ref`, `source`.
3. 去 fragment；保留 path（用于产品页）。
4. 跳过文件：`.pdf`, `.jpg`, `.png`, `.zip`, `.docx`（招聘 PDF 可单独处理）。
5. 解析短链/跳转（HEAD，最多 3 跳）。
6. 注册域用 `tldextract` 提取（注意 `.com.br`, `.ind.br`, `.org.br` 多级后缀）。

### 6.2 非公司 URL 过滤

| 类型 | 规则 |
|---|---|
| 搜索引擎 | `google.*`, `bing.*`, `duckduckgo.*` |
| 社交/视频 | `facebook.com`, `instagram.com`, `youtube.com`, `tiktok.com`（公司主页可另行采集） |
| 招聘 | `vagas.com`, `infojobs.com.br`, `linkedin.com/jobs` |
| 新闻门户 | `g1.globo.com`, `folha.uol.com.br`（可作信号，不作候选） |
| 电商平台 | `mercadolivre.com.br`, `amazon.com.br`, `alibaba.com`（非本地客户） |
| 出口商 SEO 站 | 路径含 `brazil`, `supplier-in-brazil` 且注册地在印度/中国 → 排除 |
| 政府/协会 | `.gov.br`, 协会站点（作为来源，不直接当客户） |

### 6.3 名称清洗

- 去后缀：`- Chapas de Aço Inox`, `| Distribuidora`, `- Home`。
- 去 emoji/HTML 实体/多余空白。
- 保留品牌原写法；另存 `normalized_name`。
- 若 title 与域名品牌冲突（如 `Tech-Inox` vs 邮箱 `techmetais`），不丢弃，交给 M7。

### 6.4 早期去重

在入 `candidates` 前做轻量去重，避免浪费抓取预算：

| 键 | 行为 |
|---|---|
| `canonical_domain` | 同 run 内只保留信息最全的一条 |
| `place_id` | 完全一致 → 合并 |
| 规范化名称 + 城市 | 完全一致 → 合并（保留多来源） |
| 电话 E.164 | 一致 → 合并候选（可能是集团/分支） |

> 深度实体解析（别名、集团、多域名）在 M7 做；M3 只做「明显重复」。

## 7. 覆盖率控制

Discovery 结束后检查分布，不足则补查：

| 维度 | 目标 |
|---|---|
| 州 | 至少覆盖 SP、PR、SC、MG；其他州尽量 |
| 客户类型 | importer/distributor ≥ 40%，service_center ≥ 20% |
| 产品形态 | chapas/bobinas/barras/perfis 均出现 |
| 来源 | 至少 2 类来源有贡献 |

若某维度不足，追加对应查询/城市，最多追加 10 条查询。

## 8. 限速、重试与预算

| 来源 | 并发 | 重试 | 熔断 |
|---|---|---|---|
| Serper | 4 | 429/5xx 3 次，退避 1/2/4s | 连续 5 次失败暂停 10 min |
| Places | 2 | 3 次 | 配额错误直接跳过 |
| 目录抓取 | 4 | 2 次 | 结构解析失败 3 次告警 |
| 贸易数据 | 1 | 文件级重试 | license/格式错误停止 |

预算：`max_candidates=300`；达到后只保留高可靠性来源的新候选。

## 9. 错误处理

| 错误 | 行为 |
|---|---|
| 某查询 0 结果 | 正常，记录 `zero_result` |
| 来源整体失败 | 标记 `source_status=degraded`，继续其他来源 |
| 全部来源失败 | Stage `failed`，保留查询供重跑 |
| URL 无法解析 | 丢弃并计数 |
| 重复候选 | 合并来源，不新增记录 |
| 候选超出预算 | 截断，记录 `truncated=true` |

## 10. 验收标准

1. 单次 run 产生 ≥ 40 个候选（去重后），覆盖 ≥ 3 个州、≥ 2 类来源。
2. 明显非公司 URL（社交/电商/搜索）不进入候选。
3. 同一域名在候选表中只出现一次（多查询命中需合并来源）。
4. 关闭 Serper 时，Places + 目录仍可产生 ≥ 20 个候选。
5. 每个候选都能追溯到 `query_id` + `source_url` + `snippet`。
6. 单测：URL 规范化、过滤规则、早期去重、预算截断、适配器 mock。

## 11. 待定

- LinkedIn 公司页是否纳入（需评估条款与反爬风险，建议仅用 SERP 摘要，不直接抓）。
- 是否接入巴西本地黄页/电话簿 API。
- 付费贸易数据的供应商选型与 license 范围。
- 多国家扩展时目录适配器的插件化。
