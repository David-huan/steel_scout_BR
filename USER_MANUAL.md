# YIEH 海外客户发现工作台 — 用户手册

版本：MVP v0.1  
适用场景：巴西不锈钢平板/型材客户开发  
最近更新：2026-10-22

---

## 1. 系统是什么

这是一个“客户发现工作台”，不是 CRM，也不是自动发信工具。

输入一个产品和目标国家后，系统会：

1. 生成葡语搜索查询；
2. 从 curated seed（内置种子）或 Serper 发现候选公司；
3. 抓取公司官网公开页面；
4. 抽取邮箱、电话、地址、CNPJ、产品、社交账号等证据；
5. 判断客户类型（进口商/分销商、加工中心、制造商等）；
6. 按六个维度评分并分为 A/B/C/D；
7. 自动合并同一公司的多个域名/别名；
8. 将不确定的重复项放入人工复核队列；
9. 支持人工标记和 CSV 导出。

当前版本只覆盖 **Brazil × 不锈钢平板/型材**，其他国家和品类尚未实现。

---

## 2. 快速开始（5 分钟）

### 2.1 环境要求

- Windows 10/11（当前开发环境）
- Python 3.13+
- Node.js 22 LTS 或 24 LTS（当前 Node 26 alpha 也能构建，但 npm 会提示不支持）
- 可访问公司官网的网络（实时抓取模式）

### 2.2 首次安装

在 PowerShell 中执行：

```powershell
Set-Location -LiteralPath "F:\programming\project\steel"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r backend\requirements.txt
```

如果 PowerShell 禁止执行脚本：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

只需要安装一次 Python 依赖。前端依赖由 `run.ps1 -Build` 自动安装。

### 2.3 构建并启动

```powershell
.\run.ps1 -Build
```

如果执行策略仍然拦截：

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Build
```

启动成功后打开：

```text
http://127.0.0.1:8000
```

后续启动不需要每次构建：

```powershell
.\run.ps1
```

端口被占用时：

```powershell
.\run.ps1 -Port 8010
```

然后访问 `http://127.0.0.1:8010`。

### 2.4 不安装前端依赖可以吗

可以运行 API，但页面会 404 或白屏。必须至少执行一次：

```powershell
cd frontend
npm.cmd install
npm.cmd run build
```

Windows 下请使用 `npm.cmd`，不要直接使用 `npm.ps1`。

---

## 3. 配置

复制配置模板：

```powershell
Copy-Item .env.example .env
```

常用配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_PATH` | `./data/steel.db` | SQLite 数据库路径 |
| `CRAWL_LIVE` | `true` | `true` 抓取真实官网；`false` 完全离线，仅使用 seed |
| `HTTP_TIMEOUT` | `8` | 单个页面请求超时秒数 |
| `CRAWL_MAX_PAGES` | `2` | 每个公司最多抓取的页面数 |
| `CRAWL_THREADS` | `6` | 并发抓取线程数 |
| `SERPER_API_KEY` | 空 | 可选。配置后增加 Google 搜索结果；不配置只使用 seed |
| `SERPER_MAX_QUERIES` | `6` | 每次 run 最多发送的 Serper 查询数 |
| `MAX_QUERIES` | `40` | 查询生成上限 |
| `MAX_SITES` | `120` | 单次 run 最多处理的候选站点数 |
| `GOOGLE_MAPS_API_KEY` | 空 | 预留，当前 MVP 未启用 |
| `OPENAI_API_KEY` | 空 | 预留，当前 MVP 的评分与分类以规则为主 |
| `PORT` | `8000` | 默认端口；`run.ps1 -Port` 会覆盖 |

### 三种运行模式

**A. 实时 + 内置种子（默认）**

```dotenv
CRAWL_LIVE=true
```

会尝试抓取真实官网，同时使用内置巴西公司种子。适合演示和实际调研。

**B. 完全离线**

```dotenv
CRAWL_LIVE=false
```

不访问外部网站，只用内置种子数据。适合无网络演示、测试和快速验收。

**C. Serper 增强**

```dotenv
CRAWL_LIVE=true
SERPER_API_KEY=your_key_here
```

在 seed 之外增加搜索结果。没有 key 也能跑，只是候选来源更少。

修改 `.env` 后需要重启服务。

---

## 4. 页面使用流程

### 4.1 发起一次客户发现

1. 打开首页；
2. 在“产品”中输入或选择 `Stainless steel flat products and profiles`；
3. 国家保持 `Brazil`；
4. 目标数量默认 `15`；
5. 点击“发起客户发现”。

目标数量用于进度展示和预算参考，不保证结果正好等于该数字。

### 4.2 查看运行进度

“运行概览”会显示当前阶段：

```text
Brief → Queries → Discovery → Crawl → Enrich → Classify/Score → Dedup
```

常见状态：

- `queued`：已创建，等待执行；
- `running`：正在抓取和处理；
- `completed`：完成，可以查看结果；
- `failed`：失败，查看错误信息和日志。

页面会自动轮询进度，不需要手动刷新。

### 4.3 看懂顶部统计

| 指标 | 含义 |
|---|---|
| 候选公司 | 去重前的候选数量 |
| 客户公司 | 去重后的 canonical 公司数量 |
| 合格 A/B | 评分达到 B 及以上的公司数 |
| A 级 | 高优先级公司数 |
| 有邮箱 | 至少抽到一个公开邮箱的公司数 |
| 实时抓取 | 成功抓到官网内容的公司数 |
| 自动合并 | 被自动合并的重复实体数 |
| 待复核 | 需要人工判断的重复项数量 |
| 候选总数 | 本次 run 的原始候选数 |

### 4.4 筛选客户

默认筛选是 **A+B**。如果结果为空，先切换到“全部等级”确认是否有 C/D 公司。

可用筛选：

- 搜索：公司名、域名、城市；
- 等级：全部 / A+B / A / B / C / D；
- 州：SP、PR、SC、MG、RS、DF 等；
- 类型：进口商/分销商、加工中心、制造商等；
- 最低分；
- 排序：总分、公司名、州。

筛选只影响页面展示。CSV 导出使用当前等级和州筛选，不包含搜索词、最低分和排序。

### 4.5 查看公司详情与证据

点击表格行打开右侧抽屉。抽屉包含：

- 联系方式：邮箱、电话、官网、地址；
- 工商信息：CNPJ、CNAE、成立时间、规模；
- 评分拆解：产品契合、采购意图、规模、可触达、地理物流、战略匹配；
- 产品与行业：产品形态、牌号、应用行业；
- 证据链：字段、值、原文引用、来源 URL、置信度、抓取时间；
- 去重关联：别名、合并来源；
- 人工复核：备注和状态按钮。

证据链是判断数据是否可信的核心。没有来源的字段会显示为空或“未知”，系统不会编造邮箱和联系人。

### 4.6 人工复核

抽屉底部有三个操作：

| 操作 | 结果 |
|---|---|
| 标记合格 | `approved`，保留在结果中 |
| 待补充 | `needs_info`，保留在结果中，提示后续补充 |
| 淘汰 | `rejected`，从默认列表和导出中排除 |

可以填写备注，例如“电话已确认，等待采购联系人”。

淘汰不会物理删除数据，只是从默认视图隐藏。需要恢复时，可通过 API 将状态改回 `new` 或 `approved`。

### 4.7 处理重复公司

打开“去重复核”标签页。

**自动合并**

系统对强信号直接合并，例如：

- CNPJ 相同；
- 根域名相同；
- 邮箱或电话相同；
- 电话相同且名称相似。

被合并的记录不会丢失，会在公司详情和“最近自动合并”中保留来源关系。

**人工复核队列**

以下情况会转人工：

- 名称相似但州/地址冲突；
- 可能是集团与子公司；
- 共享电话但品牌不同；
- 其他无法确定的灰区情况。

每个待复核项有两个操作：

- “保留这家并合并”：确认是同一公司；
- “不是同一家”：拒绝合并，保留为两家公司。

处理完成后，待复核数量会减少。

### 4.8 导出 CSV

点击“导出 CSV”。

导出范围：

- 最近一次完成的 run（或当前 run）；
- 当前等级筛选；
- 当前州筛选；
- 默认排除 `rejected` 公司。

CSV 使用 UTF-8 BOM，Excel 打开中文/葡语不应乱码。

主要列：

```text
公司名称, CNPJ, 官网, 州, 城市, 客户类型, 总分, 等级,
产品契合, 采购意图, 规模, 可触达, 地理物流, 战略匹配,
邮箱, 电话, 产品形态, 牌号, 应用行业, 评分理由, 证据来源
```

多个邮箱/电话/产品用 `;` 分隔，评分理由和证据来源用 ` | ` 分隔。

---

## 5. 评分与等级说明

### 5.1 六个维度

| 维度 | 权重 | 关注点 |
|---|---:|---|
| 产品契合 | 30% | 是否经营不锈钢平板/型材、牌号覆盖、库存、加工能力 |
| 采购意图 | 20% | 进口、分销、库存、询价、供应链信号 |
| 规模 | 15% | 公司规模、成立年限、覆盖区域 |
| 可触达 | 15% | 邮箱、电话、联系人、官网质量 |
| 地理物流 | 10% | 州、港口、工业区、物流便利度 |
| 战略匹配 | 10% | 客户类型、应用行业、与 YIEH 产品的协同 |

### 5.2 等级

| 等级 | 分数 | 建议 |
|---|---|---|
| A | ≥ 75 | 优先联系，通常有明确进口/分销/加工信号 |
| B | 55–74 | 值得跟进，需补充联系人或确认采购能力 |
| C | 35–54 | 低优先级，适合批量培育 |
| D | < 35 | 暂不跟进或信息不足 |

### 5.3 分数上限规则

为避免“信息很少但分数虚高”：

- 没有邮箱且没有电话：总分最高 50；
- 没有官网且没有 CNPJ：总分最高 45；
- 钢厂/回收商：总分最高 20；
- 类型为“其他”：总分最高 40。

因此，看到 50 分或 45 分时，要重点检查是否缺联系方式或官网。

### 5.4 客户类型

- `importer_distributor`：进口商/分销商，优先级最高；
- `service_center`：加工服务中心；
- `manufacturer`：制造商/OEM；
- `end_user`：终端用户；
- `trader`：贸易商/代理；
- `mill_producer`：钢厂/生产者，通常硬过滤；
- `recycler`：回收/废料，通常硬过滤；
- `other`：无法归类。

---

## 6. 演示预期结果

在默认配置、无 Serper key、实时抓取模式下，典型结果为：

```text
候选公司：21
客户公司：19
合格 A/B：15
A 级：4
B 级：11
有邮箱：12
实时抓取成功：15
自动合并：2
待复核：0
```

其中 Jatinox 的主站和两个产品微站会按共享电话 + 名称相似自动合并；Jacinox DF 是另一家公司，不会被误合并。

实际结果会随网络、官网改版和抓取超时变化。若实时抓取失败较多，可切换 `CRAWL_LIVE=false` 做稳定离线演示。

---

## 7. 常见问题

### 7.1 页面打不开

依次检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

- 无响应：服务未启动，检查终端报错；
- API 正常但页面空白：没有构建前端，执行 `.\run.ps1 -Build`；
- 端口冲突：使用 `.\run.ps1 -Port 8010`。

### 7.2 `npm.ps1 cannot be loaded`

PowerShell 执行策略限制。使用：

```powershell
npm.cmd install
npm.cmd run build
```

或：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### 7.3 npm 提示 Node 版本不支持

当前环境的 Node 26 alpha 会触发警告，但构建可用。生产环境建议 Node 22/24 LTS。

### 7.4 结果里没有 A 级公司

可能原因：

- 使用离线模式，种子数据中缺少高分公司；
- 联系方式不足，触发 50 分上限；
- 实时抓取失败，产品/进口信号缺失；
- 筛选条件过窄。

先切换到“全部等级”，再检查 A/B 公司的证据链。

### 7.5 实时抓取成功数偏低

- 部分巴西公司官网响应慢或屏蔽爬虫；
- 网站使用 JavaScript 渲染，当前 MVP 没有 Playwright 兜底；
- 网络/DNS/TLS 问题；
- 超时设置过短。

可调大 `HTTP_TIMEOUT`，或改用离线模式演示。

### 7.6 想重新开始

停止服务后删除数据库：

```powershell
Remove-Item .\data\steel.db, .\data\steel.db-shm, .\data\steel.db-wal -Force -ErrorAction SilentlyContinue
```

再次启动会重新建表。该操作会清空历史 run、客户和证据，不可恢复。

### 7.7 中文/葡语在终端乱码

这是 Windows 控制台编码问题，不影响数据库和 CSV。可设置：

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

### 7.8 端口被占用

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

找到进程后停止，或换端口启动。

### 7.9 如何查看 API

启动后访问：

```text
http://127.0.0.1:8000/docs
```

可查看和调试所有接口。健康检查：

```text
http://127.0.0.1:8000/api/health
```

---

## 8. 数据与合规边界

系统只处理公开可访问的信息：

- 公司官网公开页面；
- 公开目录/搜索结果；
- BrasilAPI 公开 CNPJ 数据；
- 页面中公开展示的邮箱和电话。

系统不会：

- 绕过登录、验证码或付费墙；
- 抓取个人隐私数据；
- 编造邮箱、联系人或 CNPJ；
- 自动发送邮件或执行外联。

使用时应遵守目标网站的服务条款和 robots 规则，并控制抓取频率。用于商业决策前，建议通过电话、邮件或官方渠道二次核验关键信息。

---

## 9. 维护与验证

### 运行测试

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m unittest discover -s backend\tests -v
```

当前应有 5 个测试通过。

### 重新构建前端

```powershell
cd frontend
npm.cmd run build
```

### 检查后端语法

```powershell
python -m compileall -q backend\app
```

### 数据位置

```text
data/steel.db      SQLite 主库
data/             运行时数据目录
frontend/dist/    构建后的前端静态文件
```

数据库和日志文件不建议提交到版本库。

---

## 10. 目录速查

```text
backend/app/main.py                 API、运行管理、导出、静态页面托管
backend/app/db.py                   SQLite 表结构与连接
backend/app/config.py               环境变量与路径
backend/app/pipeline/orchestrator.py 运行编排
backend/app/pipeline/crawl.py       官网抓取与证据抽取
backend/app/pipeline/score.py       六维评分与等级
backend/app/pipeline/dedup.py       去重、合并、复核队列
backend/app/data/seed_candidates.csv 巴西种子数据
backend/tests/test_pipeline.py      端到端测试
frontend/src/                       React 前端源码
run.ps1                             构建并启动脚本
.env.example                        配置模板
```

---

## 11. 技术支持信息

提交问题前，建议准备：

1. 浏览器访问的 URL 和操作步骤；
2. 页面显示的 run 状态和错误；
3. 后端终端最后 30 行日志；
4. `.env` 中是否配置了 Serper key（不要发送 key 本身）；
5. 是否使用实时抓取，目标公司官网是否可访问。
