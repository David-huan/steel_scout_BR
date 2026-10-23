# YIEH 海外客户开发 Prototype — Brazil × Stainless Steel

> 输入「产品 + 国家」，自动发现潜在客户、采集公开信息、判定客户类型、评估与 YIEH 产品的匹配度，并持续去重沉淀为客户主数据。
>
> 当前状态：**可运行 MVP v0.1（FastAPI + SQLite + React/Vite）**
> 演示场景：`Stainless Steel Flat / Profiles` × `Brazil`
>
> 已实现：run 编排、葡语查询生成、seed/Serper 发现、公开页面抓取、证据抽取、类型判定、六维评分、A/B/C/D 分级、Jatinox 多域自动合并、人工复核、去重队列、CSV 导出、前端任务台/证据抽屉。冷启动无 API Key 也可完成 19 家巴西不锈钢公司的离线演示。
>
> 使用说明：[`USER_MANUAL.md`](USER_MANUAL.md)（安装、配置、页面操作、评分解释、故障排查）。

---

## 0. 技术文档（spec/）

模块化技术文档见 [`spec/README.md`](spec/README.md)：

| 分组 | 文档 |
|---|---|
| 架构 | [00-architecture](spec/00-architecture.md) |
| 数据链路 | [01-brief-taxonomy](spec/01-brief-taxonomy.md) · [02-query-generation](spec/02-query-generation.md) · [03-discovery](spec/03-discovery.md) · [04-crawler-extraction](spec/04-crawler-extraction.md) · [05-enrichment](spec/05-enrichment.md) |
| 判断与治理 | [06-classification-scoring](spec/06-classification-scoring.md) · [07-dedup-entity-resolution](spec/07-dedup-entity-resolution.md) · [08-data-model](spec/08-data-model.md) |
| 交付 | [09-backend-api](spec/09-backend-api.md) · [10-frontend](spec/10-frontend.md) · [11-export-integration](spec/11-export-integration.md) |
| 质量/合规/运维 | [12-testing-observability](spec/12-testing-observability.md) · [13-compliance-security](spec/13-compliance-security.md) · [14-deployment-ops](spec/14-deployment-ops.md) |

---

## 1. 目标与非目标

### 1.1 目标

| # | 目标 | 验收标准 |
|---|---|---|
| 1 | 可重复的客户发现流程 | 同一输入可重复执行；每次运行有 run_id、查询集、来源、耗时与成本 |
| 2 | 自动采集公开信息 | 至少拿到 Company Name / Website / Email；尽量补充地址、电话、CNPJ、CNAE、产品、规模、社交账号 |
| 3 | 判断客户类型 | 进口商/分销商、加工服务中心、制造商、终端用户、钢厂、贸易商等 |
| 4 | 评估匹配度 | 0–100 分 + 分级 A/B/C/D + 可解释理由（必须引用证据） |
| 5 | 自动去重 | 对历史库比对；识别别名、多域名、集团/子公司；灰区转人工 |
| 6 | 可展示 | 前端可发起任务、看进度、筛选结果、查看证据、人工复核、导出 CSV |
| 7 | 数据真实 | 不编造邮箱/联系人；未知字段为 `null`；每条数据有来源与抓取时间 |

### 1.2 非目标（本期不做）

- 不做完整 CRM、邮件序列、自动发信。
- 不绕过登录、验证码、付费墙，不抓取个人隐私数据。
- 不承诺 100% 自动化；本期定位是「AI + 规则 + 人工复核」的半自动工作台。
- 不做漂亮的 UI，优先保证流程、数据质量和可解释性。

---

## 2. 业务定义：谁才是 YIEH 的目标客户

YIEH 产品为 **不锈钢平板（卷/板/带）与型材（棒/角/异型）**。对应巴西 NCM：

| NCM | 含义 | 与产品关系 |
|---|---|---|
| 7219 | 宽度 ≥ 600mm 的不锈钢平轧材 | 核心 |
| 7220 | 宽度 < 600mm 的不锈钢平轧材 | 核心 |
| 7222 | 不锈钢棒、杆、角材、型材 | 核心 |

### 2.1 客户类型分类法

| 类型 | 葡语关键词 | 是否目标 | 说明 |
|---|---|---|---|
| 进口商 / 分销商 | importador, distribuidor, atacadista | ★★★ | 最优先，直接进口或具备进口能力 |
| 加工服务中心 | centro de serviço, beneficiamento, slitter, corte | ★★★ | 有库存+加工能力，复购稳定 |
| 制造商 / OEM | fabricante, indústria, caldeiraria | ★★☆ | 用量大但决策链长，常通过分销采购 |
| 终端用户 | food, petroquímica, papel e celulose, naval | ★★☆ | 项目型需求，适合大单跟进 |
| 贸易商 / 代理 | trading, representação, agente | ★★☆ | 可合作，也可能只是中间商 |
| 钢厂 / 生产者 | usina, siderúrgica, produtor | ✗ | 竞争对手，硬过滤 |
| 回收 / 废料 | reciclagem, sucata | ✗ | 非目标 |
| 无关 | 其他 | ✗ | 硬过滤 |

### 2.2 硬过滤规则（不进入评分）

- 钢厂/生产者：站点出现 `usina`、`siderúrgica`、`produção de aço`，且无分销业务。
- 纯回收/废料。
- 与不锈钢无关的金属加工（只做碳钢且无 inox 业务）。
- 域名明显为印度/中国出口商伪装的「Brazil supplier」落地页（如 `*-brazil.html` SEO 页），不是巴西本地客户。

---

## 3. 总体架构

```
┌────────────────────────── Frontend (React 19 + Vite + TS + custom CSS) ─────────────────────────┐
│  Run Console   │   Results Table   │   Company Drawer   │   Dedup Review   │   Export / History  │
└──────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                               │ REST / JSON
┌──────────────────────────────────────────────▼───────────────────────────────────────────────────┐
│                         Backend (Python 3.13 + FastAPI + SQLite/Postgres)                        │
│                                                                                                  │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────────────┐  │
│  │ 1. Brief     │──▶│ 2. Discovery │──▶│ 3. Crawl     │──▶│ 4. Enrich   │──▶│ 5. Classify/Score│  │
│  │   Parser     │   │  (multi-src) │   │  (httpx/Play)│   │  (CNPJ/Maps)│   │  (LLM + rules)   │  │
│  └─────────────┘   └──────────────┘   └──────────────┘   └─────────────┘   └────────┬─────────┘  │
│         │                  │                  │                  │                   │            │
│         ▼                  ▼                  ▼                  ▼                   ▼            │
│  ┌───────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │ 6. Dedup / Entity Resolution  →  Canonical Company Master  →  Review Queue  →  Export     │   │
│  └───────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                  │
│  PostgreSQL/SQLite  ·  Job/Run tables  ·  Evidence store  ·  LLM client  ·  Rate limiter        │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘

External: Serper.dev (Google SERP) · Google Places · ABINOX/industry directories · BrasilAPI CNPJ
          · company websites · optional Comex Stat / Volza / ImportGenius
```

### 3.1 技术选型与理由

| 层 | 选型 | 解决什么问题 | 为什么不是别的 |
|---|---|---|---|
| 前端 | React 19 + Vite + TypeScript + 自定义 CSS | 任务台、结果表、证据抽屉 | 比 Next.js 更轻；MVP 不引入重型表格/状态库，后续可替换 TanStack |
| 后端 | FastAPI + Pydantic | 类型化 API、自动 OpenAPI、后台任务 | Python 生态最适合爬虫/NLP |
| 数据库 | SQLite + `sqlite3`（demo）→ Postgres（生产） | 客户主数据、运行记录、证据链 | 零运维起步，SQLAlchemy 可平滑迁移 |
| 抓取 | httpx + BeautifulSoup；Playwright 兜底（后续） | 静态页快速抓，JS 站渲染 | 全量 Playwright 太慢太贵 |
| 搜索 | Serper.dev（Google）主，Tavily/Brave 备 | 发现候选公司与官网 | 直接爬 Google 不稳定且不合规 |
| 本地化目录 | ABINOX 会员、Quem Fornece、Guia Industrial 等 | 提高召回，找到不上 Google 广告的公司 | 单一 SERP 会漏掉本地中小企业 |
| 地图 | Google Places Text Search | 按城市发现分销商，带地址/电话/网站 | 适合本地商户，补 SERP 盲区 |
| 工商核验 | BrasilAPI / Minha Receita（CNPJ） | 官方名称、CNAE、地址、状态、母公司根号 | 免费、结构化、可验证 |
| 去重 | rapidfuzz + tldextract + 规则 + 向量（可选） | 名称/域名/集团识别 | 纯字符串匹配会误杀，纯向量不可解释 |
| 任务 | 进程内 asyncio worker + 可恢复 run 表 | 70 分钟内不引入 Redis/Celery | 生产再换 Celery/RQ |

---

## 4. 客户搜索流程（核心）

### Stage 0 — Brief 解析

输入：`product = "Stainless Steel Flat / Profiles"`, `country = "Brazil"`。

系统将其标准化为：

```json
{
  "product": {
    "category": "stainless_steel_flat_profiles",
    "ncm": ["7219", "7220", "7222"],
    "grades": ["201", "304", "304L", "316", "316L", "430", "439", "441"],
    "forms_pt": ["chapas", "bobinas", "tiras", "blanks", "barras", "perfis", "cantoneiras"],
    "forms_en": ["sheets", "coils", "strips", "plates", "bars", "profiles", "angles"]
  },
  "country": { "code": "BR", "lang": "pt-BR", "currency": "BRL" }
}
```

> 实现方式：产品字典（人工维护）+ 归一化。NCM 与葡语词表是业务知识，不能完全交给模型。

### Stage 1 — 查询生成（Query Expansion）

不是搜一次「stainless steel Brazil」，而是生成 **查询矩阵**：

| 维度 | 示例（pt-BR） |
|---|---|
| 角色 | `distribuidor de aço inoxidável` / `importador de aço inox` / `centro de serviço inox` |
| 产品 | `chapas de aço inox` / `bobinas inox 304` / `barras e perfis de inox` / `tubos inox` |
| 地区 | `São Paulo` / `Curitiba` / `Belo Horizonte` / `Porto Alegre` / `Joinville` / `Recife` |
| 行业 | `inox para indústria alimentícia` / `inox petroquímica` / `inox caldeiraria` |
| 供应链信号 | `importação de aço inoxidável` / `representante Aperam` / `estoque inox` |
| 英文补充 | `stainless steel distributor Brazil` / `stainless flat products Brazil importer` |
| 目录/展会 | `site:abinox.org.br associado inox` / `expositor feira metalurgia inox` |


### Stage 2 — 多源发现（Discovery Fan-out）

并行执行，统一产出 `Candidate`：

```
Candidate {
  raw_name, url, snippet, source_type, source_url, query, discovered_at
}
```

| 来源 | 具体做法 | 解决的问题 | 自动化 |
|---|---|---|---|
| Google SERP API | Serper.dev，按查询矩阵翻页 1–2 页 | 官网、目录页、新闻 | 全自动 |
| Google Places | `distribuidor aço inox` + 城市，取 name/website/phone/address | 本地分销商，补 SERP 盲区 | 全自动 |
| ABINOX 会员名录 | 抓取协会会员列表（公开） | 高相关度种子 | 半自动（结构可能变） |
| B2B/行业目录 | Quem Fornece、Guia Industrial、Kompass、Europages | 中小进口商 | 半自动 |
| 展会 exhibitor list | 金属/管材/工业展展商名单 | 有采购/出口意向的企业 | 半自动 |
| 海关/贸易数据 | Comex Stat（NCM 聚合）；Volza/ImportGenius（进口商提单，付费） | 真实进口信号 | 付费源需 API/人工 |
| 已知客户反查 | 用已成交客户特征生成 lookalike 查询 | 提高转化率 | 半自动 |
| 负样本过滤 | 钢厂、回收、印度 SEO 站 | 降噪 | 全自动规则 |

**为什么多源**：单一 SERP 的召回偏向投广告/做 SEO 的公司；协会名录和 Places 能补上本地中型分销商；贸易数据能验证「是否真的进口」。

### Stage 3 — 抓取与抽取（Crawl & Extract）

每个候选域名执行 **优先级 BFS**，最多 8–12 页：

```
/                    → 公司简介、导航
/quem-somos, /empresa, /sobre → 类型、历史、规模
/contato, /fale-conosco       → 邮箱、电话、地址、CNPJ
/produtos, /produtos/*        → 产品线、材质、规格
/importacao, /representadas   → 进口信号
```

抽取字段：

| 字段 | 方法 | 备注 |
|---|---|---|
| company_name | `<title>`、`og:site_name`、页脚、CNPJ 名称 | 多信号投票 |
| emails | `mailto:`、正则、`at`/`[at]` 混淆还原 | 过滤图片、示例邮箱 |
| phones | 巴西格式 `+55 (11) 9xxxx-xxxx` | 归一 E.164 |
| address / CEP | 正则 + 页脚 | 用于地图与州筛选 |
| CNPJ | `\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}` | 强标识，用于核验与去重 |
| products | 关键词 | 必须保留原文证据 |
| social | LinkedIn / Instagram / Facebook | 只取公司主页 |
| import signals | `importado`, `importação`, `representante`, 外国钢厂名 | 评分依据 |
| tech signals | 建站语言、版权年份、是否有电商 | 辅助判断活跃度 |

**邮箱策略**：

1. 只采集**公开的公司业务邮箱**，不抓个人隐私。
2. 过滤 `example@`、`noreply@`、图片文件名、第三方模板邮箱。
3. 域名 MX 记录校验（可选 SMTP 探测，但不在 demo 中做，避免骚扰与封禁）。
4. 同一公司多个邮箱按角色排序：`comercial@` > `vendas@` > `contato@` > `atendimento@` > `info@`。
5. 只有联系表单时，记录 `contact_form_url`，email 留空，不猜测。

**抓取约束**：

- 遵守 `robots.txt`；默认 1 req/s/domain，随机 UA，超时 15s。
- 静态优先；连续失败或检测到 SPA 才启用 Playwright。
- 不登录、不破验证码、不抓付费墙。
- 每页保存 `raw_html_hash`、`fetched_at`、`http_status`，支持增量与审计。

### Stage 4 — 增强（Enrichment）

1. **CNPJ 核验**：从页面提取 CNPJ → 调用 BrasilAPI/Minha Receita → 官方公司名、 trade name、CNAE、成立日期、状态、地址、州、母公司根号。
2. **CNAE 映射客户类型**：如 `46.71-2`（金属及金属矿批发）、`24.41`（冶金）等，作为分类强特征。
3. **Google Places**：补电话、地址、营业状态、评分/评论数（规模代理指标）。
4. **贸易信号（可选）**：Comex Stat 提供 NCM × 国家/州的聚合，不提供进口商名称；若预算允许接入 Volza/ImportGenius 获取提单进口商。

### Stage 5 — 分类与评分（Classify & Score）

**分类**：规则优先（关键词/CNPJ/CNAE）。硬过滤类型直接淘汰。

**匹配评分**（0–100，可解释）：

```
Score = 0.30 × ProductFit     产品线/材质/形态是否匹配
      + 0.20 × BuyerIntent    是否进口/分销/有库存/有外国供应商
      + 0.15 × Scale          规模（员工、分支、评论数、成立年限）
      + 0.15 × Reachability   是否有可用邮箱/电话/联系人
      + 0.10 × GeoLogistics   州/港口/物流便利度
      + 0.10 × StrategicFit   下游行业与 YIEH 优势匹配
```

| 维度 | 高分信号（示例） | 低分/负信号 |
|---|---|---|
| ProductFit | chapas/bobinas/barras/perfis + 304/316/430；有规格表 | 只做碳钢/铝/铜 |
| BuyerIntent | `importador`、`importação`、外国钢厂品牌、提单记录 | 只做本地钢厂代理且明确不进口 |
| Scale | 多分支、25,000m²、40+ 年、员工数、评论数 | 单人贸易公司、无固定地址 |
| Reachability | 业务邮箱 + 电话 + LinkedIn | 仅表单、无联系方式 |
| GeoLogistics | SP/PR/SC/MG，靠近 Santos/Itajaí/Paranaguá | 偏远且无物流说明 |
| StrategicFit | 食品/石化/造纸/造船/建筑 | 与不锈钢无关的行业 |

分级：`A ≥ 75`，`B 55–74`，`C 35–54`，`D < 35`（默认只导出 A/B，C 留观察）。

---

## 5. 数据模型

### 5.1 核心表

| 表 | 作用 |
|---|---|
| `runs` | 每次任务：输入、状态、阶段、统计、成本、错误 |
| `queries` | 查询矩阵、来源、命中数、转化率 |
| `candidates` | 原始候选（未去重），保留来源与快照 |
| `companies` | 规范化客户主数据（canonical） |
| `company_aliases` | 别名、旧名、葡语全称、品牌名 |
| `company_domains` | 多域名（主站、微站、邮件域） |
| `company_emails` | 邮箱、角色、来源、验证状态 |
| `company_phones` | 电话、来源 |
| `company_sources` | 每条数据的 provenance（source_url, snippet, fetched_at, extractor） |
| `company_products` | 产品/材质/形态，带证据 |
| `scores` | 各维度分、总分、等级、理由、模型版本 |
| `dedup_pairs` | 待合并/已合并/已拒绝的实体对，人工复核记录 |
| `events` | 审计日志：创建、合并、拆分、复核、导出 |

### 5.2 客户记录示例（真实字段，未知为 null）

```json
{
  "company_id": "cmp_0007",
  "name": "Tech-Inox Distribuidora de Aço Inox",
  "legal_name": null,
  "aliases": ["Tech-Inox", "Tech Metais"],
  "website": "https://tech-inox.ind.br",
  "domains": ["tech-inox.ind.br", "techmetais.com.br"],
  "emails": [
    { "value": "atendimento@techmetais.com.br", "role": "sales", "source": "SERP snippet", "verified": false }
  ],
  "phones": ["+55 41 99596-7661"],
  "address": "Rua Maurício Miguel Nasser Abrão, 206 – CIC, Curitiba/PR",
  "cnpj": null,
  "cnae": null,
  "customer_type": "importer_distributor",
  "type_confidence": 0.88,
  "products": ["chapas", "bobinas", "tubos", "barras", "cantoneiras", "inox 304/316"],
  "import_signals": ["importadores e estoque próprio"],
  "score": 82,
  "tier": "A",
  "score_breakdown": {
    "product_fit": 30,
    "buyer_intent": 18,
    "scale": 11,
    "reachability": 12,
    "geo_logistics": 6,
    "strategic_fit": 5
  },
  "status": "new",
  "dedup_status": "unique",
  "evidence": [
    {
      "field": "import_signals",
      "quote": "Como importadores e estoque próprio, oferecemos produtos de qualidade.",
      "source_url": "https://tech-inox.ind.br/",
      "fetched_at": "2026-10-22T10:00:00-03:00",
      "extractor": "llm"
    }
  ]
}
```

---

## 6. 去重与客户主数据（Entity Resolution）

### 6.1 为什么难

同一个客户可能表现为：

- 官网 `jatinox.com.br`，另有 `chapadeinox.com.br`、`barrasdeinox.com.br` 两个产品微站；
- 网站域名 `tech-inox.ind.br`，邮箱域名 `techmetais.com.br`；
- 官网 `brasilinox.com.br`，邮箱 `@brasilinox.ind.br`；
- 官方名 `Jatinox Distribuidora de Aços Inoxidáveis Ltda`，品牌只写 `Jatinox`；
- 集团下多个 CNPJ/子公司，地址与电话相同；
- 名称极像但完全无关：`Jacinox`（巴西利亚）vs `Jatinox`（圣保罗）。

### 6.2 匹配键（强 → 弱）

| 键 | 规则 | 强度 | 处理 |
|---|---|---|---|
| CNPJ 根号（前 8 位） | 完全一致 | 强 | 同一集团，自动归并到集团 |
| CNPJ 全码 | 完全一致 | 强 | 自动合并 |
| 注册域（eTLD+1） | `tldextract` 后一致 | 强 | 自动合并 |
| 邮箱域 | 与任一域名一致 | 中强 | 关联，不单独自动合并 |
| 电话 E.164 | 归一后一致 | 中强 | 候选合并 |
| 规范化名称 + 州 | 去法律后缀/重音/标点 | 中 | 模糊匹配 |
| 地址/CEP | 归一后一致 | 中 | 辅助 |
| 品牌词 | 名称 token 交集 | 弱 | 仅生成候选 |

### 6.3 名称规范化

```
"Jatinox Distribuidora de Aços Inoxidáveis Ltda."
→ 去重音/小写/去标点
→ 去法律后缀（ltda, sa, s/a, me, eireli, comercio, industria, distribuidora）
→ 去通用词（de, da, do, e）
→ "jatinox acos inoxidaveis"
```

### 6.4 决策规则

1. **Blocking**：先按 `州 + 名称首 token`、`CNPJ 根号`、`注册域` 分桶，避免 O(n²)。
2. **Fuzzy**：`rapidfuzz.fuzz.token_set_ratio`。
3. **阈值**：
   - ≥ 92 且同州 → 自动合并；
   - 85–92 → 进入人工复核队列（展示双方证据、域名、电话、地址）；
   - < 85 → 保持独立。
4. **强键优先**：CNPJ/注册域一致时绕过名称阈值；但若名称完全不同且地址不同，仍转人工（防收购/壳公司）。
5. **集团识别**：CNPJ 根号相同、或地址+电话相同、或页面出现 `Grupo` + 多 CNPJ → 建 `group_id`，保留子公司独立记录。
6. **合并策略**：保留最早创建的 canonical 记录，其余标记 `merged_into`；所有别名/域名/邮箱/来源追加，不删除历史；记录操作人、时间、原因。
7. **拆分**：前端提供 split，处理误合并；所有变更写 `events`。
8. **持续优化**：每次人工「合并/不合并」作为标注，按月调整阈值与权重；维护 100 对金标准评测集，监控 precision/recall。

### 6.5 示例

| 场景 | 判定 | 依据 |
|---|---|---|
| Jatinox 三个域名 | 同一公司 | 相同电话/地址/品牌，注册域不同 |
| Tech-Inox 与 techmetais.com.br | 同一公司 | 页面明确品牌/邮箱/电话一致 |
| Brasil Inox `.com.br` vs `.ind.br` | 同一公司 | 品牌 token + 电话 + 地址 |
| Jacinox vs Jatinox | 不同公司 | 州不同（DF vs SP）、地址/电话/CNPJ 不同；名称相似但 token 不同 |
| 集团母公司 vs 子公司 | 同集团、不同法人 | CNPJ 根号相同；保留两条，挂 `group_id` |

---

## 7. 后端 API 设计

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/api/runs` | 创建任务：product, country, target_count, sources, locale |
| `GET` | `/api/runs` | 历史任务列表 |
| `GET` | `/api/runs/{id}` | 状态、阶段进度、统计、成本、错误 |
| `GET` | `/api/runs/{id}/queries` | 本次查询矩阵与命中数 |
| `GET` | `/api/runs/{id}/companies` | 分页/筛选：tier、type、state、has_email、dedup_status |
| `GET` | `/api/companies/{id}` | 详情 + 证据链 + 评分明细 |
| `PATCH` | `/api/companies/{id}` | 人工修正类型/字段/状态 |
| `POST` | `/api/companies/{id}/review` | 标记 qualified / rejected / do_not_contact |
| `GET` | `/api/dedup/queue` | 待复核实体对 |
| `POST` | `/api/dedup/merge` | 合并（记录原因与操作人） |
| `POST` | `/api/dedup/split` | 拆分 |
| `GET` | `/api/export` | CSV/XLSX，按 run + 筛选条件 |
| `POST` | `/api/companies/{id}/re crawl` | 单公司重抓 |
| `GET` | `/api/health` | 健康检查 |

任务执行：`POST /api/runs` 立即返回 `run_id`，后台 asyncio worker 推进；前端轮询或 SSE。每个 stage 写入 checkpoint，失败可从中断处重试。

---

## 8. 前端页面

| 页面 | 内容 | 关键交互 |
|---|---|---|
| Run Console | 产品、国家、目标数量、数据源开关、预估成本 | 一键运行，阶段时间线，实时日志 |
| Results | 公司表：名称、类型、州、产品、邮箱、评分、等级、去重状态 | 筛选/排序/搜索、批量导出、批量标记 |
| Company Drawer | 基本信息、评分雷达/明细、证据引用、来源链接、抓取页面 | 修正字段、标记合格/淘汰、重抓 |
| Dedup Review | 左右对比：名称/域名/电话/地址/CNPJ/证据 | 合并、保持独立、加入黑名单 |
| History | 历次 run、查询命中率、A/B 客户数、邮箱覆盖率、成本 | 对比两次运行的新增客户 |
| Export | CSV/XLSX 字段选择 | 导出含 evidence 与 score 的审计版 |

---

## 9. 合规、安全与数据真实性

- **LGPD/GDPR**：只处理公开的 B2B 公司信息与业务邮箱；不采集个人手机号/私人邮箱；提供 do-not-contact 标记与删除机制；保留来源与抓取时间；设置数据保留期。
- **robots.txt 与限速**：遵守站点规则；默认 1 req/s/domain；不绕过验证码/登录/付费墙。
- **API 条款**：Google Places/Serper 按其条款使用；不直接大规模抓 Google 搜索结果页。
- **数据真实性**：
  - 未知字段一律 `null`，不猜测、不补全。
  - 邮箱/电话/CNPJ 只来自页面原文或官方 API。
  - 每条记录可追溯到「哪个查询 → 哪个来源 → 哪个页面 → 何时抓取」。
- **密钥管理**：`.env` 不入库；日志脱敏；导出不含密钥。

---

## 10. 本地运行（已实现）

一键启动（Windows PowerShell）：

```powershell
# 首次运行：安装前端依赖并构建静态文件
.\run.ps1 -Build

# 后续启动：FastAPI 同时托管 API 与 frontend/dist
.\run.ps1
```

打开 `http://127.0.0.1:8000`，API 文档在 `http://127.0.0.1:8000/docs`。

分步启动：

```powershell
# backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m uvicorn app.main:app --reload --port 8000 --app-dir backend

# frontend（开发模式，Vite 代理 /api 到 8000）
cd frontend
npm.cmd install
npm.cmd run dev
```

> Windows 下若 `npm.ps1` 被执行策略阻止，请使用 `npm.cmd`；若 `run.ps1` 也被阻止，可执行：
>
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\run.ps1 -Build
> ```

测试：

```powershell
python -m unittest discover -s backend\tests -v
```

`.env.example` 已随仓库提供，复制为 `.env` 后按需填写。无 `SERPER_API_KEY` 时仍会读取 `backend/app/data/seed_candidates.csv`，并实时抓取 19 家 seed 公司的公开官网；设置 `CRAWL_LIVE=false` 可完全离线演示。

```env
SERPER_API_KEY=
GOOGLE_MAPS_API_KEY=
OPENAI_API_KEY=
DATABASE_PATH=./data/steel.db
CRAWL_LIVE=true
CRAWL_MAX_PAGES=2
HTTP_TIMEOUT=8
```

---

## 11. Demo：Brazil × Stainless Steel 真实发现结果

以下为 2026-10-22 通过公开搜索实际找到的巴西不锈钢流通企业（**19 家，超过 15 家目标**）。邮箱仅填搜索摘要中公开出现的业务邮箱，未出现则留空；所有记录仍需 crawler + CNPJ 二次核验。

**实现后实跑结果（`CRAWL_LIVE=true`）**：19 家实体，15 家官网实时抓取成功，15 家进入 A/B（4 家 A、11 家 B），12 家拿到公开业务邮箱；Jatinox 主站与 2 个产品微站按共享电话自动合并为 1 家；Jacinox（DF）保持独立。离线模式（`CRAWL_LIVE=false`）仍产出 19 家、9 家 A/B，可完全断网演示。

| # | Company | Website | 推断类型 | 地区 | 公开邮箱（待核验） | 关键证据 |
|---|---|---|---|---|---|---|
| 1 | Jatinox | jatinox.com.br | 分销 + 加工 | SP / PR | — | 明确「distribuidora exclusiva」，chapas/bobinas/barras/perfis，4 个分支 |
| 2 | Brasil Inox | brasilinox.com.br | 分销 + 制造 | SP | atendimento@brasilinox.ind.br | chapas/tubos/válvulas，邮箱域与官网域不同 |
| 3 | Casa Inox São Paulo | casainoxsp.com.br | 分销 | SP | servicos@casainoxsp.com.br | bobinas/chapas/blanks/tubos，304/316/409/430 |
| 4 | Inoxplasma | inoxplasma.com.br | 分销 + 加工 | SP | — | 等离子/激光切割、caldeiraria、chapas/tubos/barras/perfis |
| 5 | Elinox | elinox.com.br | 分销 + 加工 | SP | — | 40+ 年，CBE 加工中心，chapas/bobinas/tubos/barras |
| 6 | MLSteel Inox | mlsteelinox.com.br | 分销 + 加工 | SP | — | 304/316L/430/201，切割/抛光/保护膜 |
| 7 | Tech-Inox | tech-inox.ind.br | 进口 + 分销 | PR | atendimento@techmetais.com.br | 原文「importadores e estoque próprio」，邮箱域 techmetais |
| 8 | Mundinox | mundinox.com.br | 分销 | SP | cotacoes@mundinox.com.br | 45 年，chapas/tubos/telas/retalhos |
| 9 | IMG Aço Inoxidável | imginox.com.br | 分销 + 加工 | SP | — | 1993 年起，chapas/bobinas/barras/perfis，ISO 9001 |
| 10 | Aço Inox Forte | acoinoxforte.com.br | 代理 + 分销 | SP | — | 30+ 年，perfis、slitter、焊接材料 |
| 11 | Grupo Feital | feital.com.br | 分销 | SP | — | 1946 年起，chapas/bobinas/barras |
| 12 | Suprir Indústria | suprir.com.br | 分销 | 全国 | — | 不锈钢 + 橡胶，chapas/tubos/barras/perfis trefilados |
| 13 | Aczinox | aczinox.com.br | 制造 + 分销 | BR | — | 不锈钢丝、棒、板、卷 |
| 14 | Jacinox DF | jacinox.com.br | 分销 | DF | — | 1994 年起，tubos/chapas/perfis/barras |
| 15 | Minas Inox | minasinox.com.br | 分销 | MG | — | 自称 MG 最全库存，barras/perfis/tubos |
| 16 | Aços Favorit | favorit.com.br | 分销 | BR | — | 特殊钢、不锈钢棒、结构型材 |
| 17 | Açosporte | acosporte.com.br | 制造 + 分销 + 进口 | SP | — | 目录标注 Importador，304/316 全系 |
| 18 | Steel Import | steelimport.com.br | 进口贸易商 | BR | — | 连接全球钢厂与巴西工业，含 stainless |
| 19 | Aço Certo | acocerto.com.br | 分销 / 代表 | SC | — | Joinville，服务南部，chapas/barras |

**负样本（应被过滤）**：

- Aperam / Usiminas / Gerdau / Villares Metals：钢厂/生产者，竞争对手。
- 印度出口商的 `stainless-steel-...-brazil.html` SEO 落地页：不是巴西本地客户。
- 纯回收/废料商。

**这组数据刻意保留的难点**（用于证明去重逻辑）：

- Jatinox 有多个产品微站（`chapadeinox.com.br`、`barrasdeinox.com.br`），需要按电话/地址/品牌归并。
- Tech-Inox 官网与邮箱域不同（`tech-inox.ind.br` vs `techmetais.com.br`）。
- Brasil Inox 的 `.com.br` 官网与 `.ind.br` 邮箱域。
- Jacinox vs Jatinox 高相似名称，必须靠州/CNPJ/地址避免误合并。

---

## 12. 自动化程度与人机边界

| 步骤 | 自动化 | 人工介入点 |
|---|---|---|
| 产品/国家标准化 | 90% | 新产品线需业务确认 NCM/关键词 |
| 查询生成 | 95% | 审核高成本/低产出查询 |
| SERP/Places/目录发现 | 95% | 目录结构变化时修适配器 |
| 页面抓取 | 85% | 反爬/JS 站失败时人工兜底 |
| 邮箱/电话/CNPJ 抽取 | 90% | 灰区邮箱与角色判断 |
| CNPJ 核验 | 100% | 无 |
| 客户类型分类 | 80% | 集团/多业务公司需人工确认 |
| 匹配评分 | 90% | A 级客户与战略客户人工复核 |
| 去重 | 85% | 85–92 分灰区人工合并/拆分 |
| 导出/CRM 推送 | 100% | 发送前人工审核 |
| 首封开发信 | 0%（本期不做） | 全部人工 |

