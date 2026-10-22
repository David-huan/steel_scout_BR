# M1 — Brief 解析与产品分类

> 状态：设计基线 · 依赖：M0 · 关联：M2、M6 · 代码：`pipeline/brief.py`

## 1. 目标

把自由输入（产品、国家，可选行业/客户类型）转换为**机器可用的检索上下文**：

- 标准产品类目与 HS/NCM
- 葡语/英语产品词表
- 目标客户类型与负样本词
- 国家/语言/地区/港口配置
- 检索约束与预算

这一层是业务知识的锚点：**不能完全交给 LLM 自由发挥**，否则查询会漂移、评分不可比。

## 2. 输入

```json
{
  "product": "Stainless Steel Flat / Profiles",
  "country": "Brazil",
  "target_count": 15,
  "optional": {
    "industries": ["food", "petrochemical"],
    "customer_types": ["distributor", "importer"],
    "exclude_keywords": ["sucata", "reciclagem"],
    "regions": ["SP", "PR", "SC", "MG"]
  }
}
```

校验：

- `product`、`country` 必填，长度 2–120。
- `target_count` 默认 15，范围 1–200。
- `country` 支持 ISO 代码（`BR`）、英文名、葡语名、中文名 → 统一为 `BR`。
- 未识别的产品：进入 `needs_review=true`，仍用 LLM 生成临时 taxonomy，但标记低置信度。

## 3. 输出契约 `Brief`

```json
{
  "brief_id": "brf_001",
  "product": {
    "category": "stainless_steel_flat_profiles",
    "display_name": "Stainless Steel Flat / Profiles",
    "ncm": ["7219", "7220", "7222"],
    "hs": ["7219", "7220", "7222"],
    "grades": ["201", "304", "304L", "316", "316L", "430", "439", "441"],
    "forms": [
      { "pt": "chapas", "en": "sheets/plates" },
      { "pt": "bobinas", "en": "coils" },
      { "pt": "tiras", "en": "strips" },
      { "pt": "blanks", "en": "blanks" },
      { "pt": "barras", "en": "bars" },
      { "pt": "perfis", "en": "profiles" },
      { "pt": "cantoneiras", "en": "angles" }
    ],
    "finishes": ["2B", "2D", "BA", "No.1", "polido", "escovado"],
    "applications_pt": ["alimentícia", "petroquímica", "papel e celulose", "naval", "construção civil"]
  },
  "country": {
    "code": "BR",
    "name_zh": "巴西",
    "languages": ["pt-BR", "en"],
    "currency": "BRL",
    "timezone": "America/Sao_Paulo",
    "regions": [
      { "code": "SP", "name": "São Paulo", "cities": ["São Paulo", "Campinas", "Indaiatuba", "Santos"] },
      { "code": "PR", "name": "Paraná", "cities": ["Curitiba", "Araucária", "Paranaguá"] },
      { "code": "SC", "name": "Santa Catarina", "cities": ["Joinville", "Itajaí", "Blumenau"] },
      { "code": "MG", "name": "Minas Gerais", "cities": ["Belo Horizonte", "Contagem"] },
      { "code": "RS", "name": "Rio Grande do Sul", "cities": ["Porto Alegre", "Caxias do Sul"] },
      { "code": "DF", "name": "Distrito Federal", "cities": ["Brasília"] }
    ],
    "ports": ["Santos", "Paranaguá", "Itajaí", "Rio Grande", "Suape"]
  },
  "customer_types_target": ["importer_distributor", "service_center", "fabricator", "end_user"],
  "negative_keywords_pt": [
    "sucata", "reciclagem", "ferro-velho", "usina siderúrgica", "produção de aço"
  ],
  "search_hints_pt": [
    "distribuidor de aço inoxidável",
    "importador de aço inox",
    "chapas de aço inox",
    "bobinas inox 304",
    "barras e perfis de inox",
    "centro de serviço inox",
    "estoque de inox"
  ],
  "taxonomy_version": "2026-10-22.1",
  "needs_review": false,
  "confidence": 0.96
}
```

## 4. 产品 Taxonomy（`data/product_taxonomy.yaml`）

```yaml
categories:
  stainless_steel_flat_profiles:
    display_name: "Stainless Steel Flat / Profiles"
    ncm: ["7219", "7220", "7222"]
    hs: ["7219", "7220", "7222"]
    grades:
      austenitic: ["201", "202", "301", "304", "304L", "316", "316L", "321"]
      ferritic: ["409", "430", "439", "441", "444"]
      duplex: ["2205", "2507"]
    forms:
      - { pt: "chapas", en: "sheets/plates", ncm: ["7219", "7220"] }
      - { pt: "bobinas", en: "coils", ncm: ["7219"] }
      - { pt: "tiras", en: "strips", ncm: ["7220"] }
      - { pt: "blanks", en: "blanks", ncm: ["7219", "7220"] }
      - { pt: "barras", en: "bars", ncm: ["7222"] }
      - { pt: "perfis", en: "profiles", ncm: ["7222"] }
      - { pt: "cantoneiras", en: "angles", ncm: ["7222"] }
    finishes: ["2B", "2D", "BA", "No.1", "polido", "escovado", "laminado a quente", "laminado a frio"]
    applications_pt:
      - "alimentícia"
      - "bebidas"
      - "petroquímica"
      - "papel e celulose"
      - "naval"
      - "construção civil"
      - "cozinha industrial"
      - "farmacêutica"
```

> NCM 校验：7219（≥600mm 不锈钢平轧）、7220（<600mm 不锈钢平轧）、7222（不锈钢棒/型材）。新增产品必须人工确认 NCM。

## 5. 国家配置（`data/countries.yaml`）

```yaml
BR:
  name_zh: "巴西"
  languages: ["pt-BR", "en"]
  currency: "BRL"
  timezone: "America/Sao_Paulo"
  regions: [...]
  ports: ["Santos", "Paranaguá", "Itajaí", "Rio Grande", "Suape"]
  registry:
    provider: "brasilapi"
    endpoint: "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
  directories:
    - name: "ABINOX"
      url: "https://www.abinox.org.br/"
      type: "association"
    - name: "Quem Fornece"
      url: "https://quemfornece.com/"
      type: "b2b"
  search:
    google_hl: "pt-BR"
    google_gl: "br"
```

## 6. 归一化流程

```text
输入
 │
 ├─ 1. trim / 去控制字符 / 长度校验
 ├─ 2. 国家解析：ISO / 英文 / 葡语 / 中文 → code
 ├─ 3. 产品解析：
 │     a. 精确匹配 taxonomy display_name / alias
 │     b. 关键词匹配（stainless + flat/coil/sheet/bar/profile）
 │     c. LLM 兜底：返回候选 category + 置信度
 ├─ 4. 合并用户可选过滤（行业/地区/客户类型）
 ├─ 5. 生成 negatives / search_hints
 ├─ 6. 版本号 + needs_review
 └─ 输出 Brief
```

### 6.1 产品匹配规则

| 输入 | 判定 |
|---|---|
| `stainless steel`, `inox`, `aço inoxidável` | 材质命中 |
| `flat`, `sheet`, `plate`, `coil`, `strip` | 平材 |
| `profile`, `bar`, `angle`, `rod` | 型材 |
| 同时含材质 + 形态 | category = `stainless_steel_flat_profiles` |
| 仅 `steel` | 不自动匹配，`needs_review=true` |

### 6.2 LLM 兜底提示词（仅未知产品）

```text
你是钢铁外贸产品分类助手。将用户产品映射到以下类目之一：
- stainless_steel_flat_profiles
- stainless_steel_tubes
- carbon_steel_flat
- other

只输出 JSON：
{
  "category": "...",
  "ncm_candidates": ["..."],
  "pt_keywords": ["..."],
  "confidence": 0.0,
  "reason": "..."
}

禁止编造 NCM；不确定时给空数组并降低 confidence。
```

## 7. 负样本与硬过滤词

| 类型 | 词（pt-BR） |
|---|---|
| 钢厂/生产者 | `usina`, `siderúrgica`, `produtor de aço`, `laminadora`（需结合上下文） |
| 回收 | `sucata`, `reciclagem`, `ferro-velho`, `aparas` |
| 无关金属 | `alumínio`, `cobre`, `latão`（若页面同时有不锈钢则保留） |
| SEO 伪装 | `brazil.html`, `supplier-in-brazil`, 印度/中国出口商模板站 |
| 个人隐私 | 不以 `@gmail.com` 等个人邮箱作为主联系方式（可作补充） |

> 负样本只用于**发现阶段降权**与**分类阶段硬过滤**，不能误杀同时经营不锈钢的综合金属商。

## 8. 配置与版本

- taxonomy 文件变更 → 更新 `taxonomy_version`（日期 + 递增号）。
- 每次 run 在 `runs.brief_json` 中保存完整 Brief 与版本，保证结果可复现。
- 新增国家只需加 `countries.yaml` 与查询模板，不改代码。

## 9. 错误处理

| 情况 | 行为 |
|---|---|
| 国家无法识别 | 400 `UNSUPPORTED_COUNTRY` |
| 产品无法识别 | 200 + `needs_review=true` + LLM 临时 taxonomy |
| taxonomy 文件缺失/损坏 | 启动时 fail fast |
| 用户传入冲突过滤（如只选 end_user 又排除所有行业） | 400 `CONFLICTING_FILTERS` |
| NCM 不在白名单 | 记录 warning，不阻断 |

## 10. 验收标准

1. 输入 `Stainless Steel Flat / Profiles` + `Brazil`，输出包含 7219/7220/7222、7 类形态、6 个重点州。
2. 输入 `stainless steel tubes` 不会误判为 flat/profiles（可返回 tubes 或 needs_review）。
3. 输入 `aço inox` + `Brasil` 能正确归一为 `BR` + 不锈钢类目。
4. 未知产品不崩溃，返回 `needs_review=true` 且 confidence < 0.6。
5. 单测覆盖：国家/产品别名、负样本、版本号、冲突过滤。

## 11. 待定

- 是否支持多产品组合（如 flat + tubes）→ 建议 v1 只允许单主类目，附加 `secondary_forms`。
- 是否引入 HS 6 位国际编码映射表 → 生产期接入 WCO/UN Comtrade 对照。
- 西语国家（墨西哥/秘鲁）词表复用与本地化。
