# M11 — 导出与 CRM 集成

> 状态：设计基线 · 依赖：M9 · 关联：M7、M10、M13 · 代码：`api/export.py`、`services/crm.py`

## 1. 目标

把客户主数据安全、可审计地交付给业务侧：

- CSV/XLSX 可直接用 Excel 打开（巴西/中国环境兼容）。
- 字段足够业务跟进，且不泄露内部证据/密钥。
- 支持按 run、tier、类型、州、是否有邮箱筛选。
- 可选推送到 CRM（HubSpot/Pipedrive/飞书表格/Webhook）。
- 推送前检查禁止联系名单（DNC）。

## 2. 导出范围

| 参数 | 默认 | 说明 |
|---|---|---|
| `run_id` | 必填（或 `all`） | 某次运行/全库 |
| `tier` | `A,B` | 等级 |
| `type` | 全部 | 客户类型 |
| `state` | 全部 | 州 |
| `has_email` | `false` | 仅导出有邮箱 |
| `include_evidence` | `false` | 是否带证据页 |
| `include_merged` | `false` | 是否含已合并 |
| `format` | `csv` | `csv` / `xlsx` |
| `delimiter` | `,` | CSV 可选 `;`（巴西 Excel） |
| `fields` | 标准集 | 自定义列 |

安全：

- 导出含邮箱 → 需 `analyst` 权限，记 `events.exported`。
- `do_not_contact` / `inactive` / `merged` 默认排除。
- 文件名：`yieh_brazil_stainless_20261022_A-B.csv`。

## 3. 字段定义（标准集）

| 列名 | 来源 | 示例 | 说明 |
|---|---|---|---|
| `company_id` | companies.id | cmp_0007 | 内部 ID |
| `company_name` | display_name | Tech-Inox | 展示名 |
| `legal_name` | legal_name | TECH INOX ... LTDA | 法人名 |
| `cnpj` | cnpj | 12.345.678/0001-90 | 格式化 |
| `website` | website | https://tech-inox.ind.br | 官网 |
| `country` | country | BR | |
| `state` | state | PR | |
| `city` | city | Curitiba | |
| `address` | address | Rua ... | |
| `postal_code` | postal_code | 81260-000 | |
| `customer_type` | primary_type | importer_distributor | 机器值 |
| `customer_type_zh` | 映射 | 进口商/分销商 | 业务可读 |
| `secondary_types` | secondary_types | service_center | 分号分隔 |
| `products` | company_products | chapas; bobinas; barras | |
| `grades` | company_products | 304; 316L | |
| `primary_email` | 角色排序第一 | atendimento@... | |
| `all_emails` | company_emails | a@;b@ | 分号分隔 |
| `primary_phone` | company_phones | +5541995967661 | E.164 |
| `whatsapp` | phones type | +55... | 可空 |
| `contact_form` | crawl | https://.../contato | |
| `score` | scores.total | 82 | |
| `tier` | scores.tier | A | |
| `score_product_fit` | scores | 92 | 6 维 |
| `score_buyer_intent` | scores | 85 | |
| `score_scale` | scores | 62 | |
| `score_reachability` | scores | 95 | |
| `score_geo` | scores | 80 | |
| `score_strategic` | scores | 70 | |
| `score_reasons` | reasons_json | 有进口词; 有库存; ... | 分号分隔 |
| `import_signals` | signals | importadores e estoque próprio | 截断 300 字 |
| `applications` | applications | alimentícia; naval | |
| `size_bucket` | size_bucket | medium | |
| `founded_at` | founded_at | 2010-05-12 | |
| `dedup_status` | dedup_status | unique | |
| `group_id` | group_id | grp_0002 | |
| `review_status` | review | new | |
| `first_seen_at` | first_seen_at | 2026-10-22 | |
| `last_seen_at` | last_seen_at | 2026-10-22 | |
| `source_count` | count(sources) | 4 | |
| `top_source_url` | 证据 | https://... | |
| `notes` | review_note | 人工备注 | 可选 |

> 不导出：内部置信度明细、原始 HTML、API 成本、其他客户敏感信息。

## 4. CSV 规范

- 编码：UTF-8 with BOM（Excel 中文/葡语兼容）。
- 分隔符：默认 `,`；`delimiter=;` 时兼容巴西 Excel。
- 引号：字段含分隔符/换行/引号时用 `"` 包裹并转义。
- 换行：`\r\n`。
- 日期：`YYYY-MM-DD`；时间：ISO 8601（本地时区另加一列可选）。
- 空值：空字符串（不是 `null`）。
- 多值：`;` 分隔（避免与 CSV 逗号冲突）。
- 表头：英文 snake_case（便于系统导入）；可选 `header_lang=zh` 输出中文列名。

示例：

```csv
company_id,company_name,legal_name,cnpj,website,country,state,city,address,postal_code,customer_type,customer_type_zh,products,grades,primary_email,all_emails,primary_phone,score,tier,score_reasons,import_signals,dedup_status,review_status,first_seen_at,last_seen_at,source_count,top_source_url
cmp_0007,Tech-Inox,TECH INOX DISTRIBUIDORA DE ACO INOX LTDA,12.345.678/0001-90,https://tech-inox.ind.br,BR,PR,Curitiba,"Rua ..., 206 - CIC",81260-000,importer_distributor,进口商/分销商,chapas;bobinas;barras,304;316L,atendimento@techmetais.com.br,atendimento@techmetais.com.br,+5541995967661,82,A,有进口词;有库存;有加工,importadores e estoque próprio,unique,new,2026-10-22,2026-10-22,4,https://tech-inox.ind.br/
```

## 5. XLSX 规范

工作簿：

| Sheet | 内容 |
|---|---|
| `Companies` | 标准字段（同 CSV） |
| `Evidence` | company_id、field、value、quote、source_url、fetched_at、extractor |
| `Dedup` | 已合并/待复核对、分数、原因 |
| `Groups` | 集团与子公司关系 |
| `Run Summary` | 输入、时间、来源、查询数、成本、A/B 数、版本 |
| `Read Me` | 数据来源说明、字段解释、合规提示、生成时间 |

格式：

- 首行冻结、自动筛选、列宽自适应。
- Tier 条件色（A 绿/B 蓝/C 灰）。
- 邮箱列不自动生成超链接（防误点群发）。
- 不在单元格写公式（防注入）；以 `=`, `+`, `-`, `@` 开头的文本前置 `'`（CSV 注入防护）。

## 6. 导出流程

```
请求
 ├─ 权限校验（analyst+）
 ├─ 查询主数据（排除 merged/inactive/DNC）
 ├─ 应用筛选/字段选择
 ├─ 生成临时文件（data/exports/{uuid}.csv|xlsx）
 ├─ 写 events.exported（run_id, filters, row_count, actor）
 └─ StreamingResponse / 下载链接（大文件异步）
```

- 小文件（≤ 5k 行）同步返回。
- 大文件：后台生成，返回 `202 + export_id`；`GET /api/exports/{id}` 查状态/下载。
- 临时文件 24h 后清理。
- 不把导出文件放在公开静态目录。

## 7. CRM 推送

### 7.1 通用 Webhook

```http
POST https://crm.example.com/hooks/yieh
Content-Type: application/json
X-YIEH-Signature: sha256=...
X-Idempotency-Key: run_20261022_001:cmp_0007:v1

{
  "source": "yieh-customer-research",
  "run_id": "run_20261022_001",
  "companies": [
    {
      "external_id": "cmp_0007",
      "name": "Tech-Inox",
      "legal_name": "TECH INOX ... LTDA",
      "cnpj": "12345678000190",
      "website": "https://tech-inox.ind.br",
      "country": "BR",
      "state": "PR",
      "city": "Curitiba",
      "type": "importer_distributor",
      "score": 82,
      "tier": "A",
      "emails": [{"value": "atendimento@techmetais.com.br", "role": "sales"}],
      "phones": ["+5541995967661"],
      "products": ["chapas", "bobinas", "barras"],
      "reasons": ["有进口词", "有库存"],
      "source_url": "https://tech-inox.ind.br/",
      "research_at": "2026-10-22T13:00:00Z"
    }
  ]
}
```

- 签名：`HMAC-SHA256(secret, raw_body)`，接收方校验。
- 幂等：`X-Idempotency-Key`，同一公司同一版本只推一次。
- 重试：5xx/超时 3 次（1/5/15 min）；4xx 记录失败不重试。
- 批量 ≤ 50 家/请求。
- 只推 `active` 且非 DNC；`inactive/merged` 不推。

### 7.2 HubSpot 映射（示例）

| 本地字段 | HubSpot property |
|---|---|
| company_name | `name` |
| website | `domain` / `website` |
| cnpj | `cnpj__c`（自定义） |
| state | `state` |
| customer_type | `customer_type__c` |
| score | `yieh_fit_score__c` |
| tier | `yieh_tier__c` |
| primary_email | `email`（公司对象无 email 时写备注/联系人） |
| products | `yieh_products__c` |
| source_url | `yieh_source_url__c` |

- 去重：优先 CNPJ，其次域名，再次规范化名称。
- 已存在 → 更新空字段，不覆盖人工维护字段（除显式配置）。
- 关联任务/备注：写入研究摘要与证据链接。

### 7.3 飞书/Google Sheets

- 通过 webhook/Apps Script 接收 JSON。
- 以 `external_id` 为幂等键；upsert。
- 适合 demo：把 A/B 客户推到共享表格，业务直接跟进。

## 8. 禁止联系（DNC）

推送/导出前检查：

- `suppression_list` 中匹配 `email` 或 `domain`。
- `companies.status = do_not_contact`。
- 命中则跳过，记录 `suppressed=true`，不报错。
- 支持按公司/邮箱/域名加入；保留原因与操作人。

## 9. 审计与权限

- 每次导出/推送写 `events`：
  - `event_type=exported|pushed`
  - `actor`、`run_id`、`row_count`、`filters`、`destination`
- 不记录导出文件内容到日志。
- 仅 `analyst/admin` 可导出含邮箱数据。
- 下载链接带短期签名（生产），过期失效。

## 10. 错误处理

| 情况 | 行为 |
|---|---|
| 无数据 | 返回空文件 + 表头，提示「无符合条件客户」 |
| 字段为空 | 空字符串，不写 `null` |
| CRM 超时 | 重试 3 次，失败标记 `push_failed` |
| 签名失败 | 接收方拒绝；本地记录 4xx，不重试 |
| 重复推送 | 幂等键去重 |
| 导出过大 | 异步生成 + 通知 |
| DNC 命中 | 跳过并计数 |
| 公式注入 | 前置 `'` 转义 |

## 11. 验收标准

1. 导出 A/B 客户 CSV，Excel 打开中文/葡语不乱码。
2. 多值字段用 `;` 分隔，不破坏 CSV 结构。
3. `include_evidence=true` 时 XLSX 含 Evidence sheet，每条可点回来源。
4. DNC/inactive/merged 默认不出现在导出。
5. Webhook 带签名与幂等键，重复调用不重复创建。
6. 导出/推送写审计，能查到操作人/时间/行数。
7. 以 `=cmd` 开头的字段被转义，CSV 注入测试通过。
8. 5k 行导出 < 10s；更大走异步。

## 12. 待定

- 是否支持直接生成 Google Sheets（OAuth）。
- CRM 字段映射是否配置化（YAML）。
- 是否加「开发信草稿」列（v2，人工发送）。
- 导出水印/追踪（防外泄）是否需要。
