# M10 — 前端（Web 工作台）

> 状态：设计基线 · 依赖：M9 · 关联：M7、M11 · 代码：`frontend/src/*`

## 1. 目标

给业务人员一个**能完成闭环**的工作台，不追求视觉，追求：

1. 30 秒内发起一次「产品 + 国家」任务；
2. 实时看到卡在哪一步；
3. 快速筛出 A/B 客户；
4. 一眼看到「为什么推荐」与原文证据；
5. 处理去重灰区；
6. 一键导出给业务跟进。

## 2. 技术栈

| 项 | 选型 | 理由 |
|---|---|---|
| 框架 | React 19 + TypeScript + Vite | 轻、启动快 |
| 路由 | 单页，无 Router | MVP 一个任务台即可完成主流程 |
| 数据 | `fetch` + 自定义 hooks + 轮询 | 不引入额外状态库；run 状态 1.2s 轮询 |
| 表格 | 原生 `<table>` + CSS | 19–200 行规模无需虚拟化 |
| 样式 | 自定义 CSS 变量与组件样式 | 可控的工业风设计，不依赖 Tailwind 构建链 |
| 图标 | 文字/符号，无图标库 | 减少依赖 |
| 表单 | React 受控组件 | 字段少，浏览器原生校验足够 |
| 图表 | CSS 评分条 | 六维拆解直接可读 |
| API 类型 | 手写 `src/types.ts` | 与 FastAPI 响应保持一致 |

> TanStack Query/Table、Tailwind、React Router 等可在客户量 >1,000 或需要多页面时再引入；当前 MVP 优先可运行与可解释。

## 3. 路由

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | Run Console | 新建任务 + 最近 run |
| `/runs` | Run History | 历史任务列表 |
| `/runs/:runId` | Results | 结果表 + 阶段进度 |
| `/runs/:runId/companies/:companyId` | Results + Drawer | 深链到公司详情 |
| `/dedup` | Dedup Review | 去重复核队列 |
| `/stats` | Stats | 覆盖率/成本/质量 |
| `/settings` | Settings | 权重/数据源开关（只读或 admin） |

## 4. 页面设计

### 4.1 Run Console

区块：

1. **任务表单**
   - 产品（默认 `Stainless Steel Flat / Profiles`，可搜索选择）
   - 国家（默认 Brazil，ISO/中文/英文）
   - 目标数量（默认 15）
   - 数据源开关：SERP / Places / ABINOX / 目录 / 贸易数据
   - 高级：地区、预算、最大站点数
   - 预估成本（基于上次 run/单价）
2. **提交**
   - 校验失败 inline 提示
   - 提交后跳转 `/runs/:id`，按钮禁用防重复
3. **最近任务**
   - 最近 5 条：时间、输入、状态、A/B 数、耗时

交互：

- 表单值存 localStorage（草稿）。
- 产品/国家选择支持键盘。
- 显示「数据只来自公开来源」提示。

### 4.2 Results

顶部：

- Run 摘要：输入、状态、耗时、成本、A/B/C 数量。
- Stage Timeline：7 个阶段，状态色 + 耗时 + 警告。
- 进度条：`stages_done / 7`；crawl 阶段显示 `done/total`。

筛选栏：

| 控件 | 说明 |
|---|---|
| 搜索框 | 名称/域名/邮箱 |
| Tier | A/B/C/D 多选 |
| 类型 | importer_distributor 等 |
| 州 | SP/PR/SC/MG... |
| 有邮箱 | toggle |
| 去重状态 | unique/review/merged |
| 复核状态 | new/qualified/rejected |
| 排序 | 分数/新增/名称 |
| 导出 | CSV/XLSX |

表格列：

| 列 | 内容 |
|---|---|
| 公司 | 名称 + 官网 favicon/域名 |
| 类型 | badge（进口分销/加工中心/制造商/终端/钢厂） |
| 地区 | 城市/州 |
| 产品 | 前 3 个 form + `+n` |
| 邮箱 | 主邮箱 + 复制按钮；无则「—」 |
| 评分 | 分数 + Tier badge |
| 去重 | unique / 待复核 / 已合并 |
| 复核 | 新 / 已合格 / 已排除 |
| 操作 | 查看、标记、重抓 |

行为：

- 行点击开右侧 Drawer（不改路由），支持 `?company=` 深链。
- 列宽可调；表头排序。
- 批量选择：标记合格/排除、导出选中。
- 空状态：解释「可能预算不足/来源失败」，给「重试/放宽筛选」。

### 4.3 Company Drawer

Tab：

1. **概览**
   - 名称/别名/法人名/CNPJ/状态/成立时间
   - 类型 + 置信度 + 证据
   - 地址/城市/州/CEP
   - 网站/域名/社交
   - 评分：总分 + 6 维条形 + 等级 + 理由
2. **联系方式**
   - 邮箱（角色、MX、来源、复制）
   - 电话/WhatsApp
   - 联系表单链接
   - 禁止联系开关
3. **产品**
   - form + grades + 原文 quote
4. **证据**
   - 按字段分组：value、quote、来源链接、抓取时间、提取器
   - 点击来源新窗口打开
5. **去重**
   - 域名/别名/集团
   - 可能的重复公司（跳转对比）
6. **审计**
   - 创建/合并/复核/重抓记录

操作：

- 标记合格/排除/禁止联系
- 修正类型/主邮箱/州
- 重抓本页
- 加入导出

### 4.4 Dedup Review

布局：左右对比卡片 + 中间分数/信号。

- 左/右：名称、别名、域名、邮箱、电话、地址、CNPJ、州、来源数、证据摘要。
- 差异高亮；相同项折叠。
- 中间：`score`、features（名称相似度/域名/电话/地址/州）、reasons。
- 操作：合并（选择 canonical）、保持独立、稍后。
- 键盘：`M` 合并、`K` 独立、`J/N` 下一条。
- 合并需二次确认（输入/勾选），防误操作。

### 4.5 Run History / Stats

History：

- 列表：run_id、输入、状态、耗时、成本、候选数、A/B 数、操作人。
- 对比：选择两次 run，显示新增公司/邮箱覆盖率变化。

Stats：

- 每个 run 的漏斗：queries → candidates → crawled → enriched → qualified。
- 来源贡献：SERP/Places/目录/贸易。
- 州分布、类型分布。
- 成本：每条候选/每家合格客户。
- 质量：邮箱覆盖率、去重率、人工复核率。

## 5. 状态管理（MVP 实现）

- **Server state**：`App.tsx` 内 `fetch` + `useEffect`。
  - run 为 `queued`/`running` 时每 1.2s 轮询 `GET /api/runs/{id}`。
  - 状态变为 `completed` 后加载公司列表与去重队列。
  - 筛选变化 220ms 防抖后重新请求公司列表。
- **UI state**：`useState`（drawer、选中公司、tab、筛选）。
- **URL state**：MVP 未持久化；刷新后自动打开最近一次 run。
- 不用 Redux；后续多页面时再引入 TanStack Query 与 Router。

### 5.1 Query Key 约定（后续 TanStack 迁移）
['run', runId, 'companies', filters]
['company', companyId]
['dedup', { status: 'pending' }]
['stats', runId]
```

### 5.2 错误/加载

- 骨架屏：表格 10 行、Drawer 各区块。
- 错误：顶部 banner + 重试按钮；404 显示「任务不存在」。
- 轮询失败：指数退避，最多 3 次后提示手动刷新。
- 乐观更新：复核/合并后先更新 UI，失败回滚并提示。

## 6. 组件清单

| 组件 | 职责 |
|---|---|
| `AppShell` | 侧边导航 + 顶栏 |
| `RunForm` | 新建任务 |
| `StageTimeline` | 7 阶段进度 |
| `RunSummary` | 输入/统计/成本 |
| `CompanyTable` | 结果表 |
| `FilterBar` | 筛选/搜索/排序 |
| `CompanyDrawer` | 详情 |
| `ScoreBreakdown` | 6 维评分 |
| `EvidenceList` | 证据与来源 |
| `TypeBadge` / `TierBadge` | 类型/等级 |
| `DedupCompare` | 左右对比 |
| `ExportDialog` | 字段/格式/范围 |
| `EmptyState` / `ErrorState` | 空/错 |
| `ConfirmDialog` | 合并/删除确认 |

## 7. API 集成

- `api/client.ts`：fetch 封装，注入 `X-API-Key`（如启用），统一错误。
- 类型由 OpenAPI 生成：`npm run gen:api`。
- 不在前端做业务计算（分数/类型以服务端为准）。
- 导出：`window.location = /api/export?...` 或 fetch blob。

## 8. UX 细节

- 默认只显示 A/B，提供「显示 C/D」。
- 分数旁显示 `?` tooltip，解释 6 维权重。
- 邮箱一键复制；电话 `tel:`/WhatsApp 链接。
- 「为什么推荐」固定展示 2–3 条理由 + 原文。
- 无邮箱客户不隐藏，标「仅表单/电话」。
- 合并/排除必须二次确认。
- 所有时间显示本地时区，hover 显示 UTC。
- 移动端：表格横向滚动，Drawer 全屏。

## 9. 可访问性与国际化

- 语义化标签、`aria-label`、focus trap（Drawer）。
- 键盘可完成主要操作。
- 色盲友好：状态不只靠颜色，配文字/图标。
- 界面中文；客户字段保留葡语原文；日期本地化。
- 文案避免绝对化（「可能」「根据公开信息」）。

## 10. 验收标准

1. 从首页发起任务，5s 内进入结果页并看到阶段进度。
2. running 时每 2s 更新；完成后停止轮询。
3. 筛选/排序/分页写入 URL，刷新后保持。
4. 点击公司打开 Drawer，能看到评分明细 + 至少 1 条证据链接。
5. 标记合格后列表状态即时更新，刷新后仍正确。
6. 去重队列可完成合并/保持独立，并写审计。
7. 导出 A/B 客户 CSV，字段与 M11 一致。
8. 空/错/加载状态完整，无白屏。
9. 键盘可完成「打开公司 → 标记合格 → 关闭」。
10. Lighthouse 可访问性 ≥ 90（demo 目标）。

## 11. 待定

- 是否做表格虚拟化（>1000 行）。
- 是否支持暗色主题。
- 是否内嵌地图（州分布）。
- 是否加「一键生成开发信草稿」（v2，人工发送）。
