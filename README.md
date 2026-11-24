# 金融分析与监控智能体（A 股）

面向中国 A 股市场的金融分析、事件监控、跨资产对比与基于证据的 AI 调查 / 追问智能体。

- 作业要求：`Financial-Analysis-and-Monitoring-Agent.pdf`（**基础 70% + 高级 30%**）
- 方案文档：`OOAD Project Proposal Report.docx`
- **架构说明：[`docs/architecture.md`](docs/architecture.md)**
- **前端使用说明：[`docs/frontend-guide.md`](docs/frontend-guide.md)**
- **交接文档：[`HANDOFF.md`](HANDOFF.md)** —— 需求核对、缺口清单、踩坑记录（新对话先读这个）

**核心特点**：所有 AI 结论（调查报告与追问）都带**证据编号引用**，编造的引用会被拦截并退回模板——
防幻觉靠的是结构与校验，不是提示词。

---

## 现在到哪一步了

**后端、前端、LLM 全部跑通，可以完整演示。**

| 模块 | 状态 | 在哪 |
|---|---|---|
| 数据源可行性验证（25+ 接口） | ✅ | `scripts/probes/` |
| 申万行业映射（31 行业 / 5229 只） | ✅ | `data/seed/` |
| **分层架构**（domain / application / infrastructure / api） | ✅ | `backend/app/` |
| 行情 Provider（三源降级，无 if/elif） | ✅ | `infrastructure/providers/` |
| **财务数据（A1）** | ✅ 新浪财务指标 86 列 → 8 字段快照，TTL 7 天 | `sina_financial_provider.py` + `financials.py` |
| **指标计算（A1 / A2 / A3）** | ✅ 已交叉验证 | `core/` + `application/` |
| 新闻采集 + 新闻↔股票关联 | ✅ 15,089 条 / 9,093 关联 | `infrastructure/` |
| 公告采集（东财列表 + 巨潮 PDF） | ✅ | `eastmoney_notice_provider` + `cninfo_provider` |
| **事件检测（B2 / D1）：行情类 + 公告类** | ✅ 涨跌幅 / 放量 / z-score / **财报·分红·回购·增减持·重大交易·澄清·监管** | `domain/events.py` + `domain/notices.py` |
| **行业监控（B1）** | ✅ 申万一级 31 个行业指数 + 行业事件（`scope=industry`） | `industry_service.py` + `sw_industry_index_provider.py` |
| **事件调查（B3 / D2）** | ✅ LLM 归纳 + 引用校验；**高等级事件刷新时自动调查** | `llm_conclusion.py` + `refresh_service.py` |
| **可配置监控/任务/预警（C1）** | ✅ 自选股 + 分析任务（保存重跑）+ 预警三级配置 | `alert_config_service.py` + `task_service.py` |
| **自然语言追问（C2）** | ✅ 意图路由 + 证据编号 + 条件修改 | `conversation_service.py` |
| **图表（C3）** | ✅ 手写 SVG：走势图 / 相对表现 / 相关性热力表 / 行业指数 | `frontend/src/components/` |
| **跨资产分析（D3）** | ✅ 净值 / 相关系数 / 基准 β / 跟踪误差 | `cross_asset_service.py` |
| 一键更新 + 保留策略 | ✅ 按钮刷新（新闻/公告/财务/行业/事件/自动调查）+ 90 天裁剪 | `refresh_service.py` |
| **FastAPI 接口** | ✅ 37 个路径 | `api/routes/` |
| **React 前端** | ✅ 指标/图表/事件/报告/追问/跨资产/预警/任务/行业 | `frontend/` |
| D4 情景分析 | ⬜ 数据齐，逻辑未写 | — |
| D2 真·动态多步调查 | 🟡 形式满足（固定流水线，非 ReAct） | `investigation_service.py` |
| 需求用户故事 / UML | ⬜ | — |

指标实测（贵州茅台，2023-11-20 ~ 2026-11-16，724 个交易日，前复权 / baostock）：

| 累计收益 | 年化波动率 | 最大回撤 | PE(TTM) | ROE（财务快照） |
|---|---|---|---|---|
| −8.18% | 23.34% | −27.92% | 22.12 | 23.77%（2026-09-30） |

（`python scripts/verify_indicators.py` 每次运行会按「最近 3 年」重新取数并打印上表，
同时输出与 pandas 实现的逐项对照。）

跨资产实测（2026-11-17，242 个共同交易日，基准沪深300）：

| 标的 | 区间收益 | 年化波动 | β | 与基准相关 |
|---|---|---|---|---|
| 600519 贵州茅台 | +2.90% | 23.43% | −0.037 | −0.028 |
| 000001 平安银行 | +11.26% | 16.74% | 0.010 | 0.010 |
| 300750 宁德时代 | −37.27% | 37.89% | 1.023 | 0.482 |

**验证**：231 个测试（40 公告 + 23 追问 + 21 预警 + 19 指标 + 18 架构 + 17 跨资产
+ 16 任务 + 14 财务 + 14 LLM + 13 行业 + 13 运维 + 8 自动调查 + 6 采集 + 5 兼容 + 4 并发）
+ pandas 独立实现交叉验证
（5 项指标对齐 `1e-9`，相关系数/β 与 pandas 完全一致）+ 复权恒等式检验。

---

## 目录

```
├── backend/app/
│   ├── domain/                 # 领域层：不认识框架与数据库
│   │   ├── models.py           #   PriceSeries / IndicatorSet（含财务字段）
│   │   ├── ports.py            #   抽象契约：Price/Financial Provider / Repository ...
│   │   ├── events.py           #   MarketEvent + AlertRule 族 + NoticeRule 族（scope）
│   │   ├── notices.py          #   公告 → 事件分类（87 种类型 -> 11 类）
│   │   ├── financials.py       #   财务快照（8 字段 + 报告期 + 来源）
│   │   ├── industry.py         #   申万行业标识
│   │   ├── analysis_task.py    #   分析任务（C1）
│   │   ├── investigation.py    #   Evidence / InvestigationReport
│   │   ├── watchlist.py        #   WatchItem / Watchlist（聚合根）
│   │   └── entity_linking.py   #   新闻 → 股票 实体链接
│   ├── core/indicators.py      # 纯函数：收益/风险/估值 + 相关系数/beta/跟踪误差
│   ├── application/            # 应用层：只依赖抽象
│   │   ├── market_service.py   #   ProviderChain + MarketDataService
│   │   ├── analysis_service.py #   FinancialAnalyzer（财务快照优先）
│   │   ├── cross_asset_service.py  # CrossAssetAnalyzer（D3）
│   │   ├── monitoring_service.py   # EventMonitor（两条规则链 + evaluate_series）
│   │   ├── alert_config_service.py # AlertConfigService（C1 三级配置）
│   │   ├── financial_service.py    # 财务快照 TTL/刷新（A1）
│   │   ├── industry_service.py     # 行业监控（B1）
│   │   ├── task_service.py         # 分析任务校验/重跑（C1）
│   │   ├── investigation_service.py# InvestigationAgent + 3 个工具
│   │   ├── conversation_service.py # ConversationAgent（C2 追问）
│   │   ├── llm_conclusion.py   #   结论策略：模板 / LLM（含引用校验）
│   │   ├── notice_service.py   #   公告采集（东财 → 巨潮 降级）
│   │   ├── news_service.py     #   新闻采集（回溯 + 快照）
│   │   ├── maintenance_service.py  # 保留策略与裁剪
│   │   └── refresh_service.py  #   一键刷新 + 自动调查（B3）
│   ├── infrastructure/         # 基础设施层：实现 ports
│   │   ├── providers/          #   行情 / 指数 / 行业指数 / 财务 / 公告 / 新闻源
│   │   │                       #   + akshare_compat（改名兼容）+ pdf_utils
│   │   ├── repositories/       #   news / event / report / watchlist / notice /
│   │   │                       #   alert_rule / financial / industry_watch / analysis_task
│   │   ├── llm/client.py       #   OpenAI 兼容客户端（DeepSeek / OpenAI）
│   │   ├── catalog.py          #   申万映射（5229 只）+ 31 个行业
│   │   └── providers/cache.py  #   CSV 行情缓存
│   ├── api/                    # 接口层
│   │   ├── app.py  deps.py     #   FastAPI 装配 + Composition Root
│   │   └── routes/             #   stocks / events / notices / alerts / chat / maintenance
│   └── db.py                   # SQLite 建表 + 轻量迁移（notice / alert_rule / event.source_url）
├── frontend/src/
│   ├── models/index.ts         # 与后端 DTO 对应的视图对象（含图表/跨资产/追问/预警）
│   ├── services/               # HttpClient / Stock / Event / Report / Maintenance / Chat / Alert
│   └── components/             # StockSearch / IndicatorPanel / PriceChart / EventList
│                               # ReportView / RefreshBar / WatchlistEvents
│                               # CrossPanel / NetValueChart / CorrelationMatrix
│                               # ChatPanel / AlertConfig / IndustryPanel / TaskPanel
├── docs/
│   ├── architecture.md         # ★ 分层、类职责、设计模式
│   ├── frontend-guide.md       # ★ 前端使用说明（界面、流程、FAQ）
│   ├── datasource-eval.md      # 数据源评估（所有实测数字）
│   ├── news-pipeline.md        # 新闻采集与关联
│   ├── notices.md              # ★ 公告事件（B2）：87 种类型 -> 11 类的映射与坑
│   ├── industry.md             # ★ 行业监控（B1）：行业指数 + scope
│   ├── cross-asset.md          # ★ 跨资产分析（D3）：对齐、相关、β
│   ├── conversation.md         # ★ 追问 / 预警配置 / 分析任务（C2 / C1）
│   ├── indicators.md           # 指标公式、验证、财务快照（A1）
│   ├── llm.md                  # LLM 接入与防幻觉
│   └── data-lifecycle.md       # ★ 保留策略与一键更新
├── scripts/
│   ├── run_api.py              # 启动后端 API
│   ├── build_industry_map.py   # 建申万映射表（需 akshare<1.20.44，见下文）
│   ├── backfill_news.py        # 新闻回溯（--auto / --prune / --stats）
│   ├── run_collector.py        # 实时新闻采集
│   ├── verify_indicators.py    # 指标验收
│   ├── check_llm.py            # LLM 连通性与抗幻觉自检
│   └── probes/                 # 11 个数据源探针 + outputs/
├── tests/                      # 15 个测试文件，231 个用例
├── data/
│   ├── seed/                   # ✅ 提交：行业结构、股票映射 CSV
│   ├── cache/market/           # ⛔ 忽略：行情缓存
│   ├── news.db                 # ⛔ 忽略：应用库（新闻/公告/事件/报告/自选股/预警配置）
│   └── sw_industry.db          # ⛔ 忽略：行业库
├── requirements.txt
├── .env.example                # 配置模板（key 填到 .env，不入库）
├── Financial-Analysis-and-Monitoring-Agent.pdf
└── OOAD Project Proposal Report.docx
```

---

## 怎么跑

```bash
pip install -r requirements.txt
```

### 1. LLM 配置（建议配，不配也能跑）

```bash
copy .env.example .env        # 填入 LLM_API_KEY（+ 自建网关的 BASE_URL / MODEL）
python scripts/check_llm.py   # 自检：连通性 / JSON 模式 / 抗幻觉
```

当前实际配置（学校内网网关，**仅校园网可达**）：

```ini
LLM_PROVIDER=custom
LLM_BASE_URL=https://sustech-ooad.dns.navy:19443/v1
LLM_MODEL=deepseek-flash
LLM_FALLBACK_MODEL=deepseek-v4-pro
```

不配也能跑——结论与追问都退回模板拼接，界面会明确标注「模板答案 / LLM 降级」。

### 2. 后端

```bash
python scripts/run_api.py     # http://127.0.0.1:8000
# 文档：http://127.0.0.1:8000/docs
```

### 3. 前端

```bash
cd frontend
pnpm install                  # 或 npm install
pnpm dev                      # http://127.0.0.1:5173
```

打开后点「更新数据」→ 采集新闻 + **公告**、检测自选股事件（行情类 + 公告类）、清理旧数据，
然后就能看到事件列表，点「调查」生成带引用编号的报告，或在「追问」里自由提问。

也可直接 `http://127.0.0.1:5173/?code=600519` 指定标的。

> 依赖装的坑：pnpm 10+ 默认跳过依赖构建脚本，vite 依赖的 `esbuild` 会报 `IGNORED_BUILDS`。
> 已加 `frontend/pnpm-workspace.yaml` 声明；用 npm 装无此问题。

### 4. 数据与验证

```bash
python scripts/build_industry_map.py      # 重建申万映射（限流时加 --delay 30 --backoff 45）
python scripts/backfill_news.py --auto    # 新闻回溯补齐
python scripts/backfill_news.py --stats   # 看库现状与保留策略
python scripts/backfill_news.py --prune   # 按保留策略清理

python -m pytest tests -q                 # 173 个测试
python scripts/verify_indicators.py       # 指标验收（命中缓存，秒级）
```

> ⚠️ `build_industry_map.py` 依赖的 `sw_index_first_info` 在 akshare ≥1.20.44 已被移除/改名，
> 重建映射需要装旧版 akshare 或改脚本；`data/seed/` 里的映射表已提交，**日常运行不需要重建**。

---

## 主要接口（37 个路径）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（数据源 / 新闻 / 公告 / 财务 / 行业 / 任务 / LLM） |
| GET | `/api/stocks/{code}/indicators` | 区间指标（A1/A2，含财务快照字段） |
| GET | `/api/stocks/{code}/financials` | **财务快照**（最近一期定期报告，不联网） |
| POST | `/api/stocks/{code}/financials/refresh` | **刷新财务快照**（打新浪接口） |
| GET | `/api/stocks/{code}/series` | **图表数据**：收盘价 + 成交量 + 估值（已抽样） |
| GET | `/api/stocks/compare?codes=600519,000001` | 跨标的比较（A3） |
| GET | `/api/stocks/{code}/periods` | **跨期比较**：近 1/3/6/12/24 个月（A3） |
| GET | `/api/stocks/cross?codes=...` | **跨资产分析**：净值 / 相关性 / 基准 β（D3） |
| GET | `/api/stocks/{code}/events` | 事件检测（B2/D1，行情类 + 公告类） |
| POST | `/api/stocks/investigate` | 发起事件调查（B3/D2） |
| GET | `/api/industries` | **31 个申万一级行业**（含监控状态） |
| GET | `/api/industries/watched` | 已监控行业（附最近事件） |
| POST · DELETE | `/api/industries/{code}/watch` | 行业加/移出监控（B1） |
| GET | `/api/industries/{code}/series` | 行业指数走势 |
| GET | `/api/industries/{code}/events` | **行业指数事件**（同一套行情规则） |
| POST | `/api/industries/refresh` | 批量检测已监控行业并落库 |
| GET · POST | `/api/tasks` | **分析任务**列表 / 新建（C1） |
| DELETE | `/api/tasks/{id}` | 删除分析任务 |
| POST | `/api/tasks/{id}/run` | **运行分析任务**：指标 + 事件 + 跨期 + 跨资产 |
| **POST** | **`/api/refresh`** | **一键更新：新闻 + 公告 + 财务 + 行业 + 事件 + 自动调查 + 清理** |
| GET · POST · DELETE | `/api/watchlist` · `/api/watchlist/{code}` | 自选股增删查 |
| GET | `/api/events/watchlist` | 自选股已落库事件 |
| GET | `/api/events` | 全部已入库事件（可按 scope 过滤） |
| GET | `/api/notices` | **本地公告列表**（不联网） |
| POST | `/api/notices/{code}/refresh` | **刷新公告并重算事件** |
| GET | `/api/notices/categories` | 公告类别映射表 |
| GET · PUT | `/api/alerts` | **预警条件读 / 改**（默认→全局→个股三级） |
| DELETE | `/api/alerts/{rule_type}` | 删除覆盖值，退回默认 |
| POST | `/api/chat` | **自然语言追问 / 交互式改条件**（C2/C1） |
| GET | `/api/chat/suggestions` | 追问示例 |
| GET | `/api/reports` · `/api/reports/{id}` | 调查报告列表 / 详情 |
| GET | `/api/maintenance/stats` | 数据量与保留策略 |
| POST | `/api/maintenance/prune` | 手动裁剪（支持 `dry_run`） |

---

## 几条必须知道的结论

详细版在 `docs/`，这里只留会影响决策的：

1. **指标必须基于 baostock 的前复权序列。**
   东财的 `adjust="qfq"` 在非除权日不满足「复权收益 == 不复权收益」（675 天里 470 天不符），
   拿它算会让年化波动率虚高 **1.23pp**。架构上已用 `returns_trustworthy=False` 强制约束。

2. **行情有三源降级：baostock → 新浪 → 东财。**
   新浪的 qfq 口径已验证正确（偏差 6.95e-06，只是舍入噪声）。

3. **公告是「事件」也是「证据」，但只落一次库。**
   东财给类型（分类依据），巨潮给 PDF 正文（引用依据）；两个源按顺序降级，
   同一批公告同时喂给 B2（事件）与 B3（证据），用户交互永远只读本地库。

4. **87 种公告类型映射到 11 个类别，30% 是噪音。**
   东财实测 229 条类型是 `股票`、110 条是 `其他`，真信号只在标题里；
   制度类公告（含「关联交易」字样）必须靠**硬噪音表**先拦掉，否则会误报重大交易。

5. **新闻与公告都不能回溯很久，但能事后补。** 东财新闻可翻 200 天、财联社 180 天，
   所以不必 7×24 采集，定期 `backfill_news.py --auto` 即可。

6. **行业统一用申万一级 31 个。** 三套体系互不兼容，混用会让跨行业分析错乱。

7. **缓存是必需品不是优化。** baostock 单次查询实测从 3 秒恶化到 57 秒甚至挂起。

8. **akshare 在 1.20.44 起批量改名**（`stock_zh_a_hist` → `stock_zh_a_hist_em` 等），
   而 requirements 只锁下限。项目加了 `akshare_compat` 兼容层，
   新旧版本都能跑——不加这层，重装依赖后取数会全挂，且离线单测看不出来。

9. **零方差夏普是静默错误。** `sharpe([0.01]*50)` 在 Python 3.11 下曾算出 `4.5e16`
   （浮点均值误差让标准差 ≈4e-19 而非 0）。已用 `1e-12` 容差判定，并有单测锁住。

10. **LLM 网关会抖（503），但演示不会中断。** 瞬时错误退避重试 → 备用模型 →
    模板兜底，三层都在，且降级原因会写进响应。

11. **财务与行情的单位不一样。** 收益/波动/回撤是**小数**（0.12 = 12%），
    财务指标是**百分数本身**（23.77 = 23.77%）。两套口径各自内部一致，不跨口径运算。

12. **财务快照必须优先于静态映射表。** 同一只票 ROE 在静态快照里是 17.95%
    （2026-10-28），接上新浪财务接口后是 23.77%（2026-09-30）——静态数据会随时间失真。

13. **行业监控用行业指数，不用成分股聚合。** 31 个申万一级指数 1999 年起、
    口径公认；自己加权造指数既不可比也不可解释。行业事件与个股事件共用一套规则，
    靠 `event.scope` 区分。

14. **自动调查必须限流。** 刷新时只对 `severity=high`、且没生成过报告的事件自动调查，
    每次最多 2 条，默认用模板结论——否则一次刷新会从 20 秒变成几分钟。

---

## 接下来要做

1. **D4 情景分析** —— 「波动率/回撤假设冲击」推演，复用现有指标与跨资产计算（高级项最后一块）
2. **D2 真·动态多步调查** —— 现在是一次跑完 3 个工具；要改成 ReAct 循环（模型决定下一步）
3. **行业事件的调查** —— 行业事件目前只能检测、不能「调查」；需要把行业名作为关键词
   接进 `NewsSearchTool`（`docs/industry.md` 限制 3）
4. **需求用户故事 + UML** —— 代码结构已稳定，可直接照 `docs/architecture.md` 画

### 暂缓的优化（不急，别忘）

因为取数都收敛在 `MarketDataService` 一个入口，这些是**内部替换、不返工**：

| 优化 | 什么时候做 |
|---|---|
| 增量拉取（本地有历史就只补最新 K 线，省 90% 请求） | 接口稳定后 |
| 全市场快照采集（1 次拿 5576 只，11.2s） | 要做全市场扫描时 |
| baostock 子进程隔离（它没有超时保护） | 演示前若仍不稳 |
| 刷新改为后台任务队列 | 自选股扩到 50 只以上时 |

**两个有时间成本、别拖到最后：**

- **演示前 1~2 天预热缓存** —— 把常用标的拉进 `data/cache/market/`，演示当天零外部依赖
- **tushare token（如果要）** —— 申请有等待时间，决定要就提前提交

---

## 提醒

- 全部用免费源（`akshare` + `baostock` + 新浪 + 巨潮），不用花钱
- 财务是季频、行情是日频、公告是事件驱动、新闻是流式，**四种时间粒度不一样**，别混
- 任何指标都要能说清「哪个源、什么复权口径、什么时间段」，报告里必须标注
- A 股老坑：复权、停牌、ST、涨跌停、退市，都要单独处理
- 东财 / legulegu 都有未文档化限频，所有 Provider 必须带退避重试
- `.env` 已被 gitignore；**不要**把 key 写进 `.env.example`（那个会提交）
