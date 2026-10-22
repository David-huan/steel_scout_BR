# M5 — 数据增强（Enrichment）

> 状态：设计基线 · 依赖：M4 · 关联：M6、M7 · 代码：`pipeline/enrich.py`、`services/cnpj.py`

## 1. 目标

把「网站抓取结果」升级为**可核验、可评分、可去重**的公司实体：

- 用官方工商数据核验公司身份（CNPJ、法人名、状态、CNAE、地址、规模）。
- 用地图/贸易数据补齐联系方式与进口信号。
- 统一主值、保留冲突与来源。
- 为 M6 分类评分、M7 实体解析提供强特征。

## 2. 增强源

| 来源 | 数据 | 成本 | 可信度 | 缓存 |
|---|---|---|---|---|
| BrasilAPI CNPJ | 法人名、商号、状态、CNAE、地址、电话、邮箱、规模、成立日期 | 免费 | 高（官方） | 30 天 |
| Minha Receita | 同上（备用/自建） | 免费 | 高 | 30 天 |
| ViaCEP | CEP → 街道/城市/州 | 免费 | 高 | 180 天 |
| Google Places | 地址、电话、营业状态、评分/评论数 | 中 | 中高 | 30 天 |
| 贸易数据（Volza/ImportGenius） | 进口商、HS、重量、金额、港口、日期 | 高 | 高 | 按导入 |
| Comex Stat | NCM × 国家/州聚合 | 免费 | 高（聚合） | 90 天 |
| 官网二次抓取 | 社交、认证、下游行业 | 低 | 中 | 7 天 |

## 3. CNPJ 核验流程

```
页面/ Places 提取到 CNPJ（或多个）
   │
   ├─ 校验 14 位 + 校验码
   ├─ 查缓存（30 天）
   ├─ 调 BrasilAPI：GET /api/cnpj/v1/{cnpj}
   ├─ 失败 → Minha Receita 兜底
   ├─ 仍失败 → registry_status=unverified，保留抓取值
   ├─ 成功 → 归一字段、记录 situacao
   └─ 派生 cnpj_root = 前 8 位（集团/子公司线索）
```

### 3.1 响应字段映射

```json
{
  "cnpj": "12.345.678/0001-90",
  "razao_social": "EMPRESA EXEMPLO LTDA",
  "nome_fantasia": "EXEMPLO INOX",
  "descricao_situacao_cadastral": "ATIVA",
  "data_inicio_atividade": "1994-03-01",
  "cnae_fiscal": 4671201,
  "cnae_fiscal_descricao": "Comércio atacadista de metais e minérios",
  "logradouro": "...",
  "numero": "...",
  "bairro": "...",
  "municipio": "...",
  "uf": "SP",
  "cep": "04221060",
  "ddd_telefone_1": "1121720405",
  "email": null,
  "porte": "DEMAIS",
  "capital_social": 1000000.0,
  "natureza_juridica": "206-2 - Sociedade Empresária Limitada"
}
```

内部映射：

| 内部字段 | 来源 | 规则 |
|---|---|---|
| `legal_name` | `razao_social` | 原文大写，保留 |
| `display_name` | `nome_fantasia` 或网站品牌 | 优先网站品牌；空则 fantasia |
| `cnpj` | `cnpj` | 归一 14 位 |
| `cnpj_root` | 前 8 位 | 派生 |
| `registry_status` | `descricao_situacao_cadastral` | `ATIVA`/`BAIXADA`/其他 |
| `founded_at` | `data_inicio_atividade` | ISO date |
| `cnae` | `cnae_fiscal` | 7 位字符串 |
| `cnae_desc` | `cnae_fiscal_descricao` | 原文 |
| `address` | 拼接 | 见 3.2 |
| `state` | `uf` | 2 字母 |
| `city` | `municipio` | 原文 |
| `postal_code` | `cep` | 8 位 |
| `size_bucket` | `porte` | 映射见 3.3 |
| `capital_social` | `capital_social` | 保留数值 + 币种 BRL |

> **不采集/不存储** `qsa`（合伙人）等个人数据；demo 只处理公司级信息。

### 3.2 地址拼接

```
{logradouro}, {numero}{complemento?} - {bairro}, {municipio}/{uf} - CEP {cep}
```

- `numero` 为 `S/N` 或空时保留 `S/N`。
- 与网站地址不一致时：registry 为主值，网站原文放 `alternate_addresses[]`。
- 记录 `address_source=registry|website|places`。

### 3.3 规模映射

| `porte` | `size_bucket` | 评分用法 |
|---|---|---|
| `MEI` | `micro` | 低分/排除（不代表没需求，但采购量小） |
| `MICRO` | `micro` | 低分 |
| `PEQUENA` | `small` | 中 |
| `MEDIA` | `medium` | 中高 |
| `DEMAIS` | `large` | 高 |
| 空 | `unknown` | 不加分 |

辅助：`capital_social`、成立年限、Places 评论数、网站分支数。

### 3.4 状态处理

| 状态 | 行为 |
|---|---|
| `ATIVA` | 正常 |
| `BAIXADA` / `INAPTA` / `SUSPENSA` | 标记 `inactive`，评分降为 D，不导出 |
| `NULA` | 排除 |
| API 无记录 | `unverified`，保留候选，人工复核 |

## 4. CNAE → 客户类型先验

| CNAE 前缀 | 描述（示例） | 类型先验 |
|---|---|---|
| `4671` | 金属及金属矿批发 | `importer_distributor` / `service_center` |
| `4672` | 建材批发 | `distributor`（可能相关） |
| `24xx` | 冶金/金属制品制造 | `fabricator` / `mill`（需看是否生产不锈钢） |
| `25xx` | 金属制品制造 | `fabricator` |
| `28xx` | 机械设备制造 | `fabricator` / `end_user` |
| `46xx` 其他 | 综合批发 | `trader` / `distributor`（弱先验） |

规则：

- CNAE 只作为**先验**，与网站证据冲突时以网站 + LLM 为准（记录冲突）。
- `24xx` 且网站出现 `usina`/`siderúrgica`/`produção de aço` → `mill`（排除）。
- 一个 CNPJ 可有多个 CNAE；取主 CNAE + 所有次要 CNAE。

## 5. Places 增强

- 输入：公司名 + 城市，或 `place_id`（若 M3 已获取）。
- 取：`formattedAddress`、`nationalPhoneNumber`、`businessStatus`、`rating`、`userRatingCount`。
- 用途：
  - 补地址/电话；
  - `CLOSED_PERMANENTLY` → 标记 inactive；
  - `userRatingCount` → 规模/活跃度弱信号。
- 不做：抓评论内容、用户个人信息。

## 6. 贸易数据增强（可选）

### 6.1 Comex Stat（免费聚合）

- 按 NCM + 国家 + 州查询进口额/量/单价趋势。
- 用途：判断巴西市场对该 NCM 的进口规模、主要来源国、价格带。
- 不提供进口商名称 → 不用于公司级增强。

### 6.2 提单数据（付费）

字段：`importer_name`, `importer_cnpj?`, `supplier_name`, `hs_code`, `description`, `weight_kg`, `value_usd`, `port`, `date`。

匹配：

1. CNPJ 精确匹配（最强）。
2. 规范化名称 + 州 精确/模糊（≥ 90）。
3. 域名/品牌词匹配。
4. 无法匹配 → `trade_matches` 人工队列。

输出：

```json
{
  "import_volume_12m_kg": 1250000,
  "import_value_12m_usd": 3200000,
  "import_shipments_12m": 14,
  "top_suppliers": ["..."],
  "top_hs": ["7219", "7220"],
  "last_import_at": "2026-08-11",
  "source": "volza",
  "matched_by": "cnpj"
}
```

> license 限制：只存储聚合/派生字段，不转售原始提单记录；按合同约定保留。

## 7. 冲突解决与主值

| 字段 | 主值优先级 | 冲突处理 |
|---|---|---|
| `legal_name` | registry > 网站页脚 | 保留网站名作 alias |
| `display_name` | 网站品牌 > registry fantasia > legal_name | 记录来源 |
| `cnpj` | registry > 页面 | 多个 CNPJ → 全部保留，主 CNPJ 取与地址/品牌最匹配者 |
| `address` | registry（ATIVA）> Places > 网站 | 其他存 `alternate_addresses` |
| `emails` | 联系页 > mailto > 全站文本 | 全部保留，按角色排序 |
| `phones` | 网站 > registry > Places | 去重，保留类型 |
| `state` | registry > CEP > 地址 | 用于去重/筛选 |
| `size` | registry porte > 网站信号 | 记录 `size_confidence` |
| `products` | 网站 + LLM | 保留 quote |

冲突不覆盖、不静默丢弃；写入 `company_sources` 并在详情页展示。

## 8. 输出 `EnrichedCompany`

```json
{
  "candidate_id": "cand_a1b2c3",
  "display_name": "Tech-Inox",
  "legal_name": "TECH INOX DISTRIBUIDORA DE ACO INOX LTDA",
  "aliases": ["Tech-Inox Distribuidora de Aço Inox", "Tech Metais"],
  "cnpj": "12345678000190",
  "cnpj_root": "12345678",
  "registry_status": "ATIVA",
  "founded_at": "2010-05-12",
  "cnae": ["4671201"],
  "cnae_desc": ["Comércio atacadista de metais e minérios"],
  "address": "Rua ..., 206 - CIC, Curitiba/PR - CEP 81260-000",
  "alternate_addresses": [],
  "city": "Curitiba",
  "state": "PR",
  "postal_code": "81260000",
  "emails": [
    { "value": "atendimento@techmetais.com.br", "role": "sales", "mx_ok": true, "source": "website" }
  ],
  "phones": [
    { "e164": "+5541995967661", "type": "whatsapp", "source": "website" }
  ],
  "website": "https://tech-inox.ind.br",
  "domains": ["tech-inox.ind.br", "techmetais.com.br"],
  "size_bucket": "medium",
  "capital_social": null,
  "products": [{ "form": "chapas", "grades": ["304", "316"] }],
  "import_signals": [{ "quote": "importadores e estoque próprio", "strength": "strong" }],
  "applications": ["alimentícia", "naval"],
  "trade_signals": null,
  "social": { "linkedin": null, "instagram": "..." },
  "enrichment_status": "partial",
  "warnings": ["cnpj_not_found"],
  "evidence": []
}
```

## 9. 缓存与限速

| 源 | 缓存键 | TTL | 限速 |
|---|---|---|---|
| BrasilAPI | CNPJ | 30 天 | 5 req/s，并发 4 |
| Minha Receita | CNPJ | 30 天 | 5 req/s |
| ViaCEP | CEP | 180 天 | 5 req/s |
| Places | place_id / 名称+城市 | 30 天 | 按配额 |
| Comex Stat | NCM+国家+年 | 90 天 | 1 req/s |

- 缓存表：`enrichment_cache(key, source, payload_json, fetched_at, expires_at)`。
- 缓存命中不重复计费；失败不缓存（或短 TTL 5 min 防打爆）。

## 10. 错误处理

| 情况 | 行为 |
|---|---|
| CNPJ 校验失败 | 丢弃该 CNPJ，保留其他字段 |
| BrasilAPI 429/5xx | 重试 3 次；失败转 Minha Receita |
| 两源都失败 | `registry_status=unverified`，不阻断 |
| 公司已注销 | 标记 `inactive`，评分 D，不导出 |
| 地址拼接失败 | 保留原始地址 |
| Places 无结果 | 跳过，标记 `places_missing` |
| 贸易数据未授权 | 跳过，`trade_signals=null` |
| 多个 CNPJ | 全部保留，主 CNPJ 置信度最高者；M7 判断是否集团 |

## 11. 验收标准

1. 给定真实 CNPJ，能正确映射法人名、状态、CNAE、地址、州。
2. 校验码错误的 CNPJ 不被查询/入库。
3. 注销公司被标记 `inactive`，不出现在默认导出。
4. 网站与 registry 地址冲突时，两者都保留且主值可解释。
5. 邮箱域与官网域不同（如 `techmetais.com.br` vs `tech-inox.ind.br`）不被误删，进入域名列表。
6. 缓存命中率 ≥ 60%（重复 run）。
7. 单测：字段映射、地址拼接、CNAE 先验、状态处理、冲突合并。

## 12. 待定

- 是否接入 Serpro/Receita 官方付费 API（更稳定、字段更全）。
- 是否存储合伙人信息（当前不存，避免个人数据合规风险）。
- 贸易数据供应商选型与字段授权。
- 是否用 LLM 从官网提取认证/产能（需更强证据约束）。
