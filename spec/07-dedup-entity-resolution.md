# M7 — 去重与客户主数据（Entity Resolution）

> 状态：设计基线 · 依赖：M5、M8 · 关联：M9、M10、M12 · 代码：`pipeline/dedup.py`

## 1. 目标

把来自不同查询、来源、域名的记录，识别为**同一个真实公司**，并沉淀为可持续使用的客户主数据（Golden Record）。

必须解决：

- 同一公司多个官网/微站/产品站；
- 官网域名与邮箱域名不同；
- 品牌名 vs 法人名 vs 别名；
- 集团/母子公司/多 CNPJ；
- 名称极像但无关的公司；
- 历史客户库与新发现客户的比对。

原则：**宁可转人工，不可误合并**。合并是高风险操作，必须可解释、可回滚。

## 2. 实体模型

```
company_group (grp_)
   │ 1..n
   ▼
company (cmp_)  ← canonical / merged_into
   ├─ company_aliases      (名称变体)
   ├─ company_domains      (主站/微站/邮件域)
   ├─ company_emails       (多邮箱 + 角色)
   ├─ company_phones       (多电话)
   ├─ company_sources      (来源/证据)
   └─ company_products     (产品/材质)

dedup_pair (ddp_) — 任意两条记录的关系与决策
```

## 3. 规范化

### 3.1 名称

```python
LEGAL_SUFFIXES = {"ltda", "ltd", "sa", "s/a", "s.a", "me", "eireli", "mei", "slu"}
GENERIC = {"de", "da", "do", "das", "dos", "e", "comercio", "industria",
           "distribuidora", "distribuicao", "importadora", "importacao",
           "representacoes", "materiais", "metais", "acos", "aco", "inox"}

def normalize_name(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " e ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t not in LEGAL_SUFFIXES and t not in GENERIC]
    return " ".join(tokens)
```

示例：

```
"Jatinox Distribuidora de Aços Inoxidáveis Ltda."
→ "jatinox"
"BRASIL INOX COMÉRCIO DE METAIS LTDA"
→ "brasil inox"
```

> 注意：去掉 `inox` 等品类词有助于品牌对齐，但可能让 `Brasil Inox` 与 `Brasil Metais` 混淆；需结合州/域名/电话。

### 3.2 域名

- 使用 `tldextract`，正确处理 `.com.br`, `.ind.br`, `.org.br`, `.net.br`。
- 取 `registered_domain` 作为主键：`www.tech-inox.ind.br` → `tech-inox.ind.br`。
- 邮件域单独保存：`techmetais.com.br`。
- 去掉 `www.`、端口、路径。

### 3.3 电话

- 归一 E.164：`+5541995967661`。
- 巴西固定电话/手机均保留。
- 去除 `0800`（可能是客服总机，不用于实体匹配）。

### 3.4 地址

- 去重音、小写、去标点。
- 提取 `CEP`（8 位）、`state`、`city`、街道首词。
- 地址相似度用 token set ratio。

## 4. 匹配键与分桶（Blocking）

为避免 O(n²)，先按以下键分桶，再在桶内两两比较：

| 键 | 说明 | 召回 |
|---|---|---|
| `cnpj` | 全码 | 极高 |
| `cnpj_root` | 前 8 位（集团） | 高 |
| `registered_domain` | 注册域 | 高 |
| `email_domain` | 邮箱域 | 中 |
| `phone_e164` | 电话 | 中高 |
| `state + first_token` | 州 + 名称首 token | 中 |
| `state + normalized_name` | 州 + 全名 | 高 |

同一记录可进入多个桶；pair 去重。

## 5. 成对比较（Pair Features）

| 特征 | 计算 | 权重 |
|---|---|---|
| `cnpj_match` | 全码一致 | 强覆盖 |
| `cnpj_root_match` | 前 8 位一致 | 0.25（集团线索） |
| `domain_match` | 注册域一致 | 强覆盖 |
| `name_sim` | rapidfuzz `token_set_ratio` / 100 | 0.30 |
| `phone_match` | 电话一致 | 0.20 |
| `address_sim` | token set ratio / 100 | 0.15 |
| `state_match` | 州一致 | 0.10 |
| `email_domain_match` | 邮箱域一致 | 0.10 |
| `city_match` | 城市一致 | 0.05 |
| `brand_token_overlap` | 品牌 token Jaccard | 0.10 |

### 5.1 基础分

```
base = 0.30*name_sim
     + 0.20*phone_match
     + 0.15*address_sim
     + 0.10*state_match
     + 0.10*email_domain_match
     + 0.05*city_match
     + 0.10*brand_token_overlap
```

（各项为 0/1 或 0–1；权重和 1.0。）

### 5.2 覆盖规则（Override）

| 条件 | 决策 | 说明 |
|---|---|---|
| `cnpj` 完全一致 | 自动合并 | 最强 |
| `registered_domain` 一致 + `state` 一致 | 自动合并 | 同站 |
| `cnpj_root` 一致 + `name_sim ≥ 0.7` | 同集团，建 `group_id`，不自动合并法人 | 母子公司 |
| `phone` 一致 + `name_sim ≥ 0.6` | 自动合并 | 同联系方式 |
| `name_sim ≥ 0.92` + `state` 一致 + 地址/电话任一一致 | 自动合并 | 强名称 |
| `name_sim ≥ 0.92` 但 `state` 不同 | 人工复核 | 可能是同名连锁/不同公司 |
| `name_sim 0.85–0.92` | 人工复核 | 灰区 |
| `base ≥ 0.85` 且无强冲突 | 人工复核 | 灰区 |
| `base < 0.85` | 保持独立 | — |

### 5.3 否决条件（即使名称相似也不合并）

| 条件 | 原因 |
|---|---|
| 州不同 + 地址/电话/CNPJ 全不同 | 很可能是不同公司（如 Jacinox/DF vs Jatinox/SP） |
| 两个不同 CNPJ 且无集团关系 | 不同法人 |
| 一个是钢厂、一个是分销商 | 业务不同 |
| 网站语言/国家不同 | 跨国同名 |

## 6. 决策阈值

| 分数 | 决策 | 是否写主数据 |
|---|---|---|
| ≥ 0.95 或强覆盖 | `auto_merge` | 是 |
| 0.85–0.949 | `review` | 否，进队列 |
| 0.70–0.849 | `suggest` | 否，仅提示 |
| < 0.70 | `distinct` | 是（独立） |

> 阈值可配置；M12 用金标准集校准。默认偏保守（减少误合并）。

## 7. 集团识别

满足任一：

1. `cnpj_root` 相同（同一母公司根号）。
2. 地址 + 电话相同，名称不同。
3. 页面出现 `Grupo {X}` 且列出多个 CNPJ/单位。
4. 官网 `unidades`/`filiais` 列出多地址，且品牌一致。

处理：

- 建 `company_groups` 记录，`group_id` 挂到各公司。
- 保留各法人独立记录（用于合同/开票/联系）。
- 评分取集团内最高分，但开发时按法人跟进。
- 前端展示「集团关系」，避免重复触达。

## 8. 合并算法

```
1. 选取 canonical：
   a. registry_status=ATIVA 优先
   b. 数据完整度得分高（邮箱/电话/地址/CNPJ/产品）
   c. 创建时间早
   d. company_id 字典序（确定性）
2. 字段合并（按 M5 主值优先级）：
   - legal_name/cnpj/address：registry 优先
   - display_name/emails/phones/products：并集
   - aliases：并集（含被合并方 display/legal）
   - domains：并集
   - sources/evidence：全部保留
3. 被合并记录：merged_into = canonical_id，status=merged
4. 重算 canonical 分数（score_version 不变）
5. 写 events（操作人/原因/前后快照）
```

**禁止硬删除**。导出/查询默认过滤 `status=merged`，但保留可追溯。

## 9. 拆分算法

误合并时：

1. 人工选择要迁出的域名/邮箱/别名/电话。
2. 新建 canonical 公司（或挂到已有记录）。
3. 迁移关联数据，保留来源。
4. 原记录恢复 `status=active`。
5. 写 `events` + `dedup_pairs.decision=split`。

## 10. 历史库比对

- 每次 run 的新候选先与 `companies` 主库比对（同一套 blocking + 规则）。
- 命中：
  - `auto_merge` → 追加来源/新邮箱/新证据，更新 `last_seen_at`，不重复开发。
  - `review` → 标记 `possible_duplicate`，进入复核队列。
- 新增字段（如新邮箱）需保留 `first_seen_at` / `last_seen_at`。
- 支持「客户已存在于 CRM」的外部 ID 映射（`crm_id`）。

## 11. 人工复核队列

`dedup_pairs`：

```json
{
  "pair_id": "ddp_000031",
  "left_company_id": "cmp_0007",
  "right_company_id": "cmp_0012",
  "score": 0.89,
  "decision": "review",
  "features": {
    "name_sim": 0.93,
    "cnpj_match": false,
    "domain_match": false,
    "phone_match": false,
    "address_sim": 0.71,
    "state_match": true
  },
  "reasons": ["名称高度相似", "同州", "地址部分匹配"],
  "status": "pending",
  "created_at": "..."
}
```

前端展示：

- 左右公司卡片：名称、别名、域名、邮箱、电话、地址、CNPJ、来源、证据。
- 差异高亮；一键「合并 / 保持独立 / 稍后」。
- 合并时选择 canonical；可填写原因。
- 操作写审计日志。

## 12. 真实案例

| 案例 | 信号 | 决策 |
|---|---|---|
| Jatinox：`jatinox.com.br` + `chapadeinox.com.br` + `barrasdeinox.com.br` | 同一电话/地址/品牌，微站内容互链 | 自动合并（电话 + 名称 + 地址） |
| Tech-Inox：`tech-inox.ind.br` vs 邮箱 `techmetais.com.br` | 页面品牌/电话一致，邮箱域不同 | 合并域名列表，不因域名不同拆分 |
| Brasil Inox：`.com.br` vs `.ind.br` | 品牌 token + 电话 + 地址 | 自动合并（电话/地址） |
| Jacinox（DF）vs Jatinox（SP） | 名称相似 0.9+，但州/地址/电话/CNPJ 全不同 | 保持独立（否决条件） |
| 集团：同一 `cnpj_root` 的母子公司 | 根号一致，名称不同 | 同 group，法人独立 |
| 同名不同州连锁 | 名称一致，州不同，无共享联系方式 | 人工复核 |

## 13. 持续优化

1. **金标准集**：100 对人工标注（50 同实体 / 50 不同），覆盖多域名、集团、别名、同名不同州。
2. **指标**：precision（合并对中正确的比例）、recall（应合并中被发现的比例）、人工复核率。
3. **调参**：按月用金标准集网格搜索阈值/权重；变更记录 `dedup_version`。
4. **反馈**：人工 merge/split 作为标注，修正规则；对高频误判类型加专门规则。
5. **监控**：自动合并率、复核队列长度、误合并投诉（拆分次数）。

目标：precision ≥ 0.95，recall ≥ 0.85，复核率 ≤ 10%。

## 14. 错误处理

| 情况 | 行为 |
|---|---|
| 无域名/无名称 | 不参与自动合并，进人工 |
| CNPJ 冲突（不同全码但同根） | 建集团，法人独立 |
| 合并后分数下降 | 允许；记录原因（数据更全但规模未知） |
| 合并事务失败 | 回滚，pair 保持 pending |
| 并发合并同一对 | 唯一约束 + 乐观锁 |
| 拆分后历史来源丢失 | 禁止：迁移而非删除 |

## 15. 验收标准

1. 19 家 demo 公司中，Jatinox 多域名、Tech-Inox 邮箱域、Brasil Inox 双后缀均正确归并。
2. Jacinox 与 Jatinox 不被误合并。
3. 重复 run 不新增重复公司（幂等）。
4. 每次合并/拆分有 events 记录，可回滚。
5. 灰区（0.85–0.949）进入复核队列，不自动写主数据。
6. 金标准集 precision ≥ 0.95。
7. 单测：名称规范化、blocking、override、否决、合并字段、幂等。

## 16. 待定

- 是否引入 embedding（公司描述向量）补充名称/域名之外的语义相似。
- 是否用图算法做集团传播（共享地址/电话/股东）。
- 跨语言别名（中文名/英文名）维护方式。
- 与 CRM 双向同步时的实体映射与冲突策略。
