# M6 — 客户分类与匹配评分

> 状态：设计基线 · 依赖：M5 · 关联：M7、M9、M10 · 代码：`pipeline/classify.py`、`pipeline/score.py`

## 1. 目标

回答两个业务问题：

1. **这是谁？**（进口商/分销商/加工中心/制造商/终端/钢厂/贸易商）
2. **值不值得跟？**（0–100 分 + A/B/C/D + 可解释理由）

原则：

- 分类可以先规则后 LLM，但**评分必须确定性**（同输入同输出）。
- LLM 只做「理解与解释」，不自由给分。
- 每个结论附证据；无法判断时降置信度，不硬猜。

## 2. 客户类型体系

```json
{
  "primary_type": "importer_distributor",
  "secondary_types": ["service_center"],
  "flags": {
    "is_importer": true,
    "is_distributor": true,
    "is_processor": true,
    "is_manufacturer": false,
    "is_end_user": false
  },
  "confidence": 0.88,
  "method": "llm",
  "evidence": [
    { "quote": "Como importadores e estoque próprio...", "source_url": "https://tech-inox.ind.br/" }
  ]
}
```

| 类型 | 定义 | 关键词（pt） | 商业含义 |
|---|---|---|---|
| `importer_distributor` | 进口并分销钢材 | importador, importação, distribuidor, atacadista, estoque | 最优先，直接采购 |
| `service_center` | 库存 + 切割/加工服务 | centro de serviço, beneficiamento, slitter, corte, polimento | 高复购，需稳定货源 |
| `fabricator` | 制造设备/结构件 | fabricante, indústria, caldeiraria, metalúrgica | 用量大，决策链长 |
| `end_user` | 终端行业用户 | alimentícia, petroquímica, papel e celulose, naval | 项目型，适合大单 |
| `trader` | 贸易/代理，无库存 | trading, representação, agente, intermediário | 可合作，利润薄 |
| `mill_producer` | 钢厂/生产者 | usina, siderúrgica, produtor, laminadora | 竞争对手，排除 |
| `recycler` | 回收/废料 | sucata, reciclagem, ferro-velho | 非目标，排除 |
| `other` | 无法归类 | — | 人工复核 |

## 3. 分类流程

```
EnrichedCompany
   │
   ├─ 1. 硬过滤（钢厂/回收/注销/无关）
   ├─ 2. 规则分类（关键词 + CNAE + 进口信号）
   │      命中强规则 → 直接输出，confidence 0.85–0.95
   ├─ 3. LLM 分类（规则不确定时）
   │      输入：名称、摘要、产品、信号、CNAE、证据片段
   │      输出：type + confidence + quotes
   ├─ 4. 冲突检测（规则 vs LLM vs CNAE）
   ├─ 5. 置信度 < 0.6 → needs_review=true
   └─ 输出 Classification
```

### 3.1 硬过滤规则

| 条件 | 结果 |
|---|---|
| `registry_status != ATIVA` | `inactive`，评分 D，默认不导出 |
| 出现 `usina`/`siderúrgica` + `produção de aço`，且无分销业务 | `mill_producer`，排除 |
| 只做 `sucata`/`reciclagem`/`ferro-velho` | `recycler`，排除 |
| 页面仅碳钢/铝/铜，且无 `inox`/`stainless` | `other`，排除 |
| 印度/中国出口商 SEO 落地页（非巴西实体） | `other`，排除 |
| 无网站、无电话、无地址、无 CNPJ | `other`，最多 C |

> 硬过滤必须记录原因与证据，允许人工恢复（误杀）。

### 3.2 规则分类

| 规则 | 类型 | 置信度 |
|---|---|---|
| `importador` + 不锈钢产品 | `importer_distributor` | 0.90 |
| `distribuidor` + 不锈钢产品 | `importer_distributor` | 0.85 |
| `centro de serviço`/`beneficiamento` + 库存 | `service_center` | 0.88 |
| `fabricante`/`caldeiraria` + 不锈钢 | `fabricator` | 0.82 |
| 行业词（alimentícia 等）+ 无分销词 | `end_user` | 0.65 |
| `trading`/`representação` 且无库存 | `trader` | 0.70 |
| `usina`/`siderúrgica` + 生产 | `mill_producer` | 0.85 |

CNAE 先验（M5）作为加分，不单独定类：

- `4671` → `importer_distributor` +0.10
- `24xx`/`25xx` → `fabricator` +0.08
- `28xx` → `end_user`/`fabricator` +0.05

### 3.3 LLM 分类提示词

```text
你是钢铁行业 B2B 客户分类器。根据给定事实，判断公司类型。

类型（只能选一个主类型）：
- importer_distributor: 进口并分销钢材
- service_center: 有库存并提供切割/加工服务
- fabricator: 制造设备/结构件/金属制品
- end_user: 终端行业用户（食品、石化、造纸、造船等）
- trader: 贸易/代理，无库存
- mill_producer: 钢厂/生产者（竞争对手）
- recycler: 回收/废料
- other: 无法判断

规则：
1. 只使用提供的事实，不引入外部知识。
2. 每个判断必须引用原文 quote（≤ 200 字符）。
3. 证据不足时 primary_type=other, confidence<0.5。
4. 不要输出评分。
5. 输出严格 JSON：
{
  "primary_type": "...",
  "secondary_types": ["..."],
  "flags": {"is_importer": false, "is_distributor": false, "is_processor": false, "is_manufacturer": false, "is_end_user": false},
  "confidence": 0.0,
  "evidence": [{"quote": "...", "source_url": "..."}],
  "reason_zh": "..."
}
```

### 3.4 冲突处理

| 冲突 | 处理 |
|---|---|
| 规则 importer，LLM fabrator | 若页面明确 `importador` 且有不锈钢 → 以 importer 为主，`secondary=[fabricator]` |
| CNAE 4671，网站只做碳钢 | 降为 `other`，记录冲突 |
| 同时 `distribuidor` + `fabricante` | primary 取进口/分销，secondary 加 fabricator |
| LLM 置信度 < 0.6 | `needs_review=true`，不自动导出 A |

## 4. 匹配评分

### 4.1 总分公式

```
Score = 0.30 × ProductFit
      + 0.20 × BuyerIntent
      + 0.15 × Scale
      + 0.15 × Reachability
      + 0.10 × GeoLogistics
      + 0.10 × StrategicFit
```

每项 0–100，加权后四舍五入为整数。分值拆解必须落库，前端可看。

### 4.2 ProductFit（0–100）

| 子项 | 分值 | 规则 |
|---|---|---|
| 形态匹配 | 40 | chapas/bobinas/tiras = 40；barras/perfis = 35；仅 tubos/其他 = 10；无 = 0 |
| 材质匹配 | 20 | 304/316/430 等 ≥2 种 = 20；1 种 = 12；仅泛称 inox = 6；无 = 0 |
| 库存/现货 | 15 | `estoque`/`pronta entrega` = 15；有产品页无库存词 = 8 |
| 加工能力 | 10 | slitter/切割/抛光/caldeiraria = 10；仅贸易 = 3 |
| 应用行业 | 15 | 命中 YIEH 优势行业 ≥2 = 15；1 = 8 |

### 4.3 BuyerIntent（0–100）

| 子项 | 分值 | 规则 |
|---|---|---|
| 明确进口词 | 40 | `importador`/`importação`/`importado` = 40 |
| 提单/贸易数据 | 30 | 12 个月有进口记录 = 30；无数据 = 0（不扣分） |
| 外国供应商/品牌 | 15 | 提到 Aperam/Outokumpu/进口原产地等 = 15 |
| 分销/批发角色 | 15 | `distribuidor`/`atacadista` = 15 |

> 没有贸易数据时，BuyerIntent 上限 70，避免「看起来像进口商」被高估。

### 4.4 Scale（0–100）

| 子项 | 分值 | 规则 |
|---|---|---|
| `porte` | 40 | DEMAIS=40, MEDIA=30, PEQUENA=18, MICRO=8, MEI=2, unknown=10 |
| 分支/单元 | 20 | ≥4=20, 2–3=14, 1=8, unknown=5 |
| 成立年限 | 15 | ≥30y=15, 15–29=12, 5–14=8, <5=3 |
| 注册资本 | 15 | ≥R$50M=15, 10–50M=11, 1–10M=7, <1M=3, unknown=5 |
| Places 评论数 | 10 | ≥200=10, 50–199=7, 10–49=4, <10=1 |

### 4.5 Reachability（0–100）

| 子项 | 分值 | 规则 |
|---|---|---|
| 业务邮箱 | 50 | 有 `comercial/vendas/contato` = 50；只有 `info` = 35；只有个人邮箱 = 20；无 = 0 |
| 电话 | 25 | 有 E.164 电话 = 25；只有 WhatsApp = 20 |
| 联系表单 | 10 | 有 = 10 |
| LinkedIn/社交 | 15 | 公司主页 = 15 |

### 4.6 GeoLogistics（0–100）

| 子项 | 分值 | 规则 |
|---|---|---|
| 州权重 | 60 | SP=60, PR=55, SC=50, MG=45, RS=40, 其他=25 |
| 港口便利 | 25 | 距 Santos/Paranaguá/Itajaí/Rio Grande ≤200km = 25；≤500km=15；其他=5 |
| 全国覆盖 | 15 | 明确 `atende todo Brasil`/多州 = 15；本地 = 5 |

### 4.7 StrategicFit（0–100）

| 子项 | 分值 | 规则 |
|---|---|---|
| 下游行业匹配 | 50 | 食品/石化/造纸/造船/建筑 ≥2 = 50；1 = 30 |
| 认证/资质 | 25 | ISO 9001/Petrobras/ASME/ASTM = 25；有其一 = 15 |
| 增长信号 | 25 | 扩产/新分支/招聘采购 = 25；新闻活跃 = 10 |

### 4.8 等级与封顶

| 等级 | 分数 | 默认动作 |
|---|---|---|
| A | ≥ 75 | 优先人工跟进 |
| B | 55–74 | 进入开发序列 |
| C | 35–54 | 观察/培育 |
| D | < 35 | 不导出 |

封顶规则：

- `mill_producer` / `recycler` / `inactive` → D，不导出。
- 无邮箱且无电话 → 总分 ≤ 50。
- 无网站且无 CNPJ → 总分 ≤ 45。
- 仅 `other` 类型 → 总分 ≤ 40。

### 4.9 示例（Tech-Inox）

| 维度 | 分 | 依据 |
|---|---|---|
| ProductFit | 92 | chapas/bobinas/tubos/barras + 304/316 + 库存 + 加工 |
| BuyerIntent | 85 | 「importadores e estoque próprio」 |
| Scale | 62 | 中型、单站点、10+ 年 |
| Reachability | 95 | 业务邮箱 + WhatsApp + 表单 |
| GeoLogistics | 80 | PR + 近 Paranaguá |
| StrategicFit | 70 | 食品/船舶/建筑 |
| **总分** | **82** | `0.3*92 + 0.2*85 + 0.15*62 + 0.15*95 + 0.1*80 + 0.1*70 = 82.05` → A |

## 5. 评分配置与版本

`data/scoring.yaml`：

```yaml
version: "2026-10-22.1"
weights:
  product_fit: 0.30
  buyer_intent: 0.20
  scale: 0.15
  reachability: 0.15
  geo_logistics: 0.10
  strategic_fit: 0.10
tiers:
  A: 75
  B: 55
  C: 35
caps:
  no_contact: 50
  no_website: 45
  other_type: 40
  buyer_intent_without_trade_data: 70
state_scores:
  SP: 60
  PR: 55
  SC: 50
  MG: 45
  RS: 40
  default: 25
```

- 配置变更 → `score_version` 递增。
- 每次评分保存 `score_version` + 配置 hash。
- 重算：`POST /api/runs/{id}/rescore` 生成新分数，不覆盖历史（版本化）。

## 6. 可解释性与人工复核

- 每条分数存 `breakdown` 与 `reasons[]`（中文，引用证据）。
- 前端展示雷达图/条形图 + 原文 quote + 来源链接。
- 人工可改类型、标记 qualified/rejected；修改写 `events`，不直接改算法分。
- 若人工判断与模型长期不一致，进入 M12 的评测集，定期调权。

## 7. 错误处理

| 情况 | 行为 |
|---|---|
| LLM 不可用 | 规则分类 + 规则评分 |
| LLM 返回非法 JSON | 重试 1 次 → 规则回退 |
| 证据 quote 不在原文 | 丢弃该证据；类型置信度 -0.2 |
| 缺 CNAE/规模 | 对应子项给 unknown 分，不臆测 |
| 所有维度缺失 | `other` + D + needs_review |
| 评分配置缺失 | 启动 fail fast |

## 8. 验收标准

1. 19 家 demo 公司中，≥ 8 家为 A/B，且人工抽查类型准确率 ≥ 80%。
2. `mill_producer`/`recycler`/`inactive` 不进入 A/B 导出。
3. 同输入重复评分结果完全一致（浮点四舍五入后）。
4. 每条评分包含 6 维 breakdown、总分、等级、版本。
5. 每个 LLM 类型判断至少 1 条可定位 quote。
6. 关闭 LLM 时仍可产出分数（规则回退）。
7. 单测：每个子项边界、封顶、权重和=1、版本化。

## 9. 待定

- 是否引入 learning-to-rank（用成交/回复数据调权）。
- 是否把「采购负责人可触达」纳入 Reachability（需合规联系人数据）。
- 行业/产品权重是否按 YIEH 产能战略动态调整。
- A 级阈值是否按国家/产品线分别配置。
