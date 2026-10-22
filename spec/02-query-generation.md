# M2 — 查询生成（Query Generation）

> 状态：设计基线 · 依赖：M1 · 关联：M3、M12 · 代码：`pipeline/queries.py`

## 1. 目标

把 `Brief` 展开为**结构化查询矩阵**，在成本可控的前提下最大化召回，并保证每次运行可复现、可归因。

核心不是「让 LLM 想 100 条 query」，而是：

```
模板保证覆盖 × LLM 补充长尾 × 规则去重降噪 × 预算排序
```

## 2. 输入 / 输出

**输入**：`Brief`（M1）+ run 预算。

**输出**：`Query[]`

```json
{
  "query_id": "qry_0012",
  "run_id": "run_20261022_001",
  "text": "distribuidor de aço inoxidável São Paulo",
  "lang": "pt-BR",
  "source": "template",
  "dimensions": {
    "role": "distributor",
    "form": "generic",
    "region": "SP",
    "industry": null,
    "supply_signal": null
  },
  "expected_customer_types": ["importer_distributor", "service_center"],
  "priority": 92,
  "budget_weight": 1.0,
  "query_hash": "9f2c...",
  "status": "pending"
}
```

## 3. 查询矩阵

| 维度 | 取值（示例） | 目的 |
|---|---|---|
| `role` | distribuidor / importador / centro de serviço / atacadista / representante / comércio de metais | 锁定客户类型 |
| `form` | genérico / chapas / bobinas / tiras / blanks / barras / perfis / cantoneiras | 锁定产品 |
| `material` | aço inoxidável / aço inox / inox 304 / inox 316L / inox 430 | 锁定材质 |
| `region` | São Paulo / Curitiba / Belo Horizonte / Joinville / Porto Alegre / Recife | 地理覆盖 |
| `industry` | alimentícia / petroquímica / papel e celulose / naval / caldeiraria | 终端行业 |
| `supply_signal` | importação / importado / estoque / representante oficial / fornecedor | 进口/采购信号 |
| `directory` | site:abinox.org.br / site:quemfornece.com / site:guiaindustrial.com.br | 目录定向 |
| `language` | pt-BR / en | 补充英文站 |

### 3.1 组合策略（不做全笛卡尔积）

| 层级 | 组合 | 数量 | 目的 |
|---|---|---|---|
| L1 核心 | `role × region`（6 角色 × 6 地区） | 36 | 覆盖主要分销商 |
| L2 产品 | `form × region`（7 形态 × 4 重点州） | 28 | 找产品匹配 |
| L3 进口信号 | `"importador" × (inox + form)` | 10 | 找真实进口商 |
| L4 目录 | 协会/B2B 定向 | 8 | 补本地中小企业 |
| L5 长尾 | LLM 生成 + 去重 | ≤ 20 | 补语义变体 |
| L6 英文 | `stainless steel distributor Brazil` 等 | 6 | 国际站/双语站 |

预算：默认 `max_queries=40`。按 `priority` 降序取前 N，同优先级轮询各维度，避免全被某个州占满。

### 3.2 优先级公式

```
priority = 40 × role_weight
         + 25 × form_weight
         + 15 × region_weight
         + 10 × supply_weight
         + 10 × source_reliability
```

| 因子 | 权重示例 |
|---|---|
| role: importer/distributor | 1.0 |
| role: service_center | 0.95 |
| role: fabricator | 0.7 |
| form: 与 YIEH 完全匹配 | 1.0 |
| form: generic | 0.7 |
| region: SP/PR/SC/MG | 1.0；其他 0.6 |
| supply_signal: importação/importado | 1.0 |

## 4. 模板（`data/query_templates.yaml`）

```yaml
templates:
  - id: role_region
    pattern_pt: "{role} de {material} {region}"
    pattern_en: "{role_en} of {material_en} {region_en}"
    dimensions: [role, region]
    priority: 90
    expected_types: [importer_distributor, service_center]

  - id: form_region
    pattern_pt: "{form} de {material} {region}"
    pattern_en: "{form_en} {material_en} {region_en}"
    dimensions: [form, region]
    priority: 80
    expected_types: [importer_distributor, service_center, fabricator]

  - id: import_signal
    pattern_pt: "importador de {material} {form}"
    dimensions: [form]
    priority: 95
    expected_types: [importer_distributor, trader]

  - id: stock_signal
    pattern_pt: "estoque de {form} {material} {region}"
    dimensions: [form, region]
    priority: 75
    expected_types: [importer_distributor]

  - id: directory
    pattern_pt: "site:{domain} {material} {form}"
    dimensions: [directory]
    priority: 85
    expected_types: [importer_distributor]

  - id: industry
    pattern_pt: "{material} para indústria {industry} {region}"
    dimensions: [industry, region]
    priority: 60
    expected_types: [end_user, fabricator]
```

### 4.1 取值表

```yaml
roles_pt: ["distribuidor", "importador", "centro de serviço", "atacadista", "representante", "comércio de metais"]
roles_en: ["distributor", "importer", "service center", "wholesaler", "stockholder"]
materials_pt: ["aço inoxidável", "aço inox", "inox"]
materials_en: ["stainless steel", "stainless"]
forms_pt: ["chapas", "bobinas", "tiras", "blanks", "barras", "perfis", "cantoneiras"]
forms_en: ["sheets", "coils", "strips", "blanks", "bars", "profiles", "angles"]
regions_pt: ["São Paulo", "Curitiba", "Belo Horizonte", "Joinville", "Porto Alegre", "Recife"]
```

> 葡语介词处理：`de` / `do` / `da` 按地区性别变化（`de São Paulo`, `do Paraná`, `da Bahia`）。模板层做简单规则，LLM 只补长尾，避免低级语法错误影响召回。

## 5. LLM 扩展（长尾）

### 5.1 触发条件

- 模板查询 < 预算 70%，或
- 用户显式要求 `expand=true`，或
- 首次运行某国家/产品，模板覆盖不足。

### 5.2 提示词

```text
你是巴西不锈钢行业 B2B 采购研究员。基于以下上下文，生成最多 15 条 Google 搜索查询，用于发现潜在客户（不是供应商）。

产品：不锈钢平板/型材（chapas, bobinas, tiras, barras, perfis）
目标客户：进口商、分销商、加工服务中心、制造商
国家：巴西（使用巴西葡语）
已知模板查询（不要重复）：
{existing_queries}

要求：
1. 每条查询 3–10 个词，符合巴西本地表达。
2. 覆盖：进口信号、行业应用、区域、公司类型、海关/协会/展会。
3. 不要包含人名、邮箱、电话。
4. 不要使用 site: 以外的搜索操作符；不要生成违规/黑帽查询。
5. 输出 JSON 数组：
[
  {"text": "...", "lang": "pt-BR", "expected_types": ["..."], "reason": "..."}
]
```

### 5.3 后处理

1. 小写、去重音、压缩空格 → `query_hash` 去重。
2. 删除与模板重复（token Jaccard ≥ 0.85）。
3. 删除含个人姓名/邮箱/电话的查询。
4. 删除纯供应商词（`fabricante chinês`, `fornecedor da china`）→ 避免找到同行。
5. 限制单查询长度 ≤ 120 字符。
6. LLM 失败：跳过，不影响模板查询。

## 6. 去重与可复现

```python
def query_hash(text: str, lang: str) -> str:
    norm = normalize(text)  # lower, strip accents, collapse spaces
    return sha1(f"{lang}|{norm}").hexdigest()
```

- 同一 run 内 `query_hash` 唯一。
- 跨 run 记录命中率，用于下次调权；不因历史失败而永久删除（市场会变）。
- 保存 `prompt_version` 与模型名，保证可解释。

## 7. 预算与动态停止

| 规则 | 行为 |
|---|---|
| 达到 `max_queries` | 停止生成 |
| 连续 8 条查询新增候选 < 2 | 提前停止（边际收益低） |
| 某来源错误率 > 50% | 暂停该来源，剩余预算给其他来源 |
| 已发现候选 ≥ `max_candidates × 0.8` | 降低查询优先级，只保留 import/directory |

## 8. 查询效果归因

每条 query 记录：

```json
{
  "hits": 18,
  "new_candidates": 11,
  "qualified_companies": 3,
  "cost_usd": 0.02,
  "precision_proxy": 0.27
}
```

`precision_proxy = qualified / new_candidates`。每周汇总「高产出查询模板」，用于：

- 提高同类查询权重；
- 淘汰长期 0 产出查询；
- 发现新的地区/行业词。

> 注意：不能用点击率代替业务结果；最终以人工标记的 qualified 为准。

## 9. 错误处理

| 情况 | 行为 |
|---|---|
| 模板变量缺失 | 跳过该组合，记录 warning |
| LLM 超时 | 使用模板查询继续 |
| LLM 返回非 JSON | 提取 JSON 块；失败则跳过 |
| 查询重复 | 静默去重 |
| 查询数为 0 | `StageFatal`（配置错误） |

## 10. 验收标准

1. `Stainless Steel Flat / Profiles` + `Brazil` 生成 ≥ 30 条查询，覆盖 ≥ 5 个州、≥ 4 种角色、≥ 5 种形态。
2. 无重复 `query_hash`；无邮箱/电话/人名。
3. 关闭 LLM 时仍能生成 ≥ 30 条模板查询。
4. 预算 40 时按优先级截断，且各地区至少 1 条（保证覆盖）。
5. 单测：模板渲染、葡语介词、去重、优先级、预算截断。

## 11. 待定

- 是否接入 Google Autocomplete / People Also Ask 做真实语言挖掘（需遵守 API 条款）。
- 是否按 NCM 反查进口商（需付费贸易数据）。
- 查询效果是否进入 bandit 自动分配预算（v2）。
