# 金融分析与监控智能体（A 股）

面向中国 A 股市场的金融分析、事件监控与基于证据的 AI 调查智能体。

- 作业要求：`Financial-Analysis-and-Monitoring-Agent.pdf`（**基础 70% + 高级 30%**）
- 方案文档：`OOAD Project Proposal Report.docx`
- **架构说明：[`docs/architecture.md`](docs/architecture.md)**

**核心特点**：所有 AI 结论都带**证据编号引用**，编造的引用会被拦截并退回模板——
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
| **指标计算（A1 / A2 / A3）** | ✅ 已交叉验证 | `core/` + `application/` |
| 新闻采集 + 新闻↔股票关联 | ✅ 15,089 条 / 9,093 关联 | `infrastructure/` |
| 公告 Provider（巨潮列表 + PDF 正文） | ✅ | `cninfo_provider.py` |
| **事件检测（B2 / D1）** | ✅ 阈值 / 放量 / z-score | `domain/events.py` |
| **事件调查（B3 / D2）** | ✅ LLM 归纳 + 引用校验 | `llm_conclusion.py` |
| **一键更新 + 保留策略** | ✅ 按钮刷新 + 90 天自动裁剪 | `refresh_service.py` |
| **FastAPI 接口** | ✅ 17 个端点 | `api/routes/` |
| **React 前端** | ✅ 指标 / 事件 / 报告 / 一键更新 | `frontend/` |
| D3 跨资产 / D4 情景分析 | ⬜ 数据齐，逻辑未写 | — |
| 需求用户故事 / UML | ⬜ | — |

指标实测（贵州茅台，2023-10-30 ~ 2026-10-27，前复权）：

| 累计收益 | 年化波动率 | 最大回撤 | PE(TTM) | ROE |
|---|---|---|---|---|
| −10.21% | 23.24% | −28.21% | 20.81 | 17.95% |

**验证**：68 个测试（19 指标 + 18 架构 + 15 LLM + 4 并发 + 12 运维）+ pandas 独立实现交叉验证
（5 项对齐到 `1e-9`）+ 复权恒等式检验。

---

## 目录

```
├── backend/app/
│   ├── domain/                 # 领域层：不认识框架与数据库
│   │   ├── models.py           #   StockRef / PriceRecord / PriceSeries / IndicatorSet
│   │   ├── ports.py            #   抽象契约：PriceProvider / Repository ...
│   │   ├── events.py           #   MarketEvent + AlertRule 策略族
│   │   ├── investigation.py    #   Evidence / InvestigationReport
│   │   ├── watchlist.py        #   WatchItem / Watchlist（聚合根）
│   │   └── entity_linking.py   #   新闻 → 股票 实体链接
│   ├── core/indicators.py      # 纯函数指标计算（无 I/O，可单测）
│   ├── application/            # 应用层：只依赖抽象
│   │   ├── market_service.py   #   ProviderChain + MarketDataService
│   │   ├── analysis_service.py #   FinancialAnalyzer
│   │   ├── monitoring_service.py   # EventMonitor
│   │   ├── investigation_service.py # InvestigationAgent + 3 个工具
│   │   ├── llm_conclusion.py   #   结论策略：模板 / LLM（含引用校验）
│   │   ├── news_service.py     #   新闻采集（回溯 + 快照），脚本与 API 共用
│   │   ├── maintenance_service.py  # 保留策略与裁剪
│   │   └── refresh_service.py  #   一键刷新编排
│   ├── infrastructure/         # 基础设施层：实现 ports
│   │   ├── providers/          #   baostock / sina / eastmoney / cninfo / 新闻源
│   │   ├── repositories/       #   news / event / report / watchlist 仓储
│   │   ├── llm/client.py       #   OpenAI 兼容客户端（DeepSeek / OpenAI）
│   │   ├── catalog.py          #   申万映射（5229 只）
│   │   └── providers/cache.py  #   CSV 行情缓存
│   ├── api/                    # 接口层
│   │   ├── app.py  deps.py     #   FastAPI 装配 + Composition Root
│   │   └── routes/             #   stocks / events / maintenance
│   └── db.py                   # SQLite 建表（新闻 / 事件 / 报告 / 自选股）
├── frontend/src/
│   ├── models/index.ts         # 与后端 DTO 对应的视图对象
│   ├── services/               # HttpClient / Stock / Event / Report / Maintenance
│   └── components/             # StockSearch / IndicatorPanel / EventList
│                               # ReportView / RefreshBar / WatchlistEvents
├── docs/
│   ├── architecture.md         # ★ 分层、类职责、设计模式
│   ├── datasource-eval.md      # 数据源评估（所有实测数字）
│   ├── news-pipeline.md        # 新闻采集与关联
│   ├── indicators.md           # 指标公式与验证
│   ├── llm.md                  # LLM 接入与防幻觉
│   └── data-lifecycle.md       # ★ 保留策略与一键更新
├── scripts/
│   ├── run_api.py              # 启动后端 API
│   ├── build_industry_map.py   # 建申万映射表
│   ├── backfill_news.py        # 新闻回溯（--auto / --prune / --stats）
│   ├── run_collector.py        # 实时新闻采集
│   ├── verify_indicators.py    # 指标验收
│   ├── check_llm.py            # LLM 连通性与抗幻觉自检
│   └── probes/                 # 11 个数据源探针 + outputs/
├── tests/                      # 5 个测试文件，68 个用例
├── data/
│   ├── seed/                   # ✅ 提交：行业结构、股票映射 CSV
│   ├── cache/market/           # ⛔ 忽略：行情缓存
│   ├── news.db                 # ⛔ 忽略：应用库（新闻/事件/报告/自选股）
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

不配也能跑——结论退回模板拼接，报告里会明确标注来源。

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

打开后点「更新数据」→ 自动采集新闻、检测自选股事件、清理旧数据（约 8 秒），
然后就能看到事件列表，点「调查」生成带引用编号的报告。

也可直接 `http://127.0.0.1:5173/?code=600519` 指定标的。

> 依赖装的坑：pnpm 10+ 默认跳过依赖构建脚本，vite 依赖的 `esbuild` 会报 `IGNORED_BUILDS`。
> 已加 `frontend/pnpm-workspace.yaml` 声明；用 npm 装无此问题。

### 4. 数据与验证

```bash
python scripts/build_industry_map.py      # 重建申万映射（限流时加 --delay 30 --backoff 45）
python scripts/backfill_news.py --auto    # 新闻回溯补齐
python scripts/backfill_news.py --stats   # 看库现状与保留策略
python scripts/backfill_news.py --prune   # 按保留策略清理

python -m pytest tests -q                 # 68 个测试
python scripts/verify_indicators.py       # 指标验收（命中缓存，秒级）
```

---

## 主要接口（17 个）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（数据源 / 股票数 / 新闻数 / LLM / 保留策略） |
| GET | `/api/stocks/{code}/indicators` | 区间指标（A1/A2） |
| GET | `/api/stocks/compare?codes=600519,000001` | 跨标的比较（A3） |
| GET | `/api/stocks/{code}/events` | 事件检测（B2/D1） |
| POST | `/api/stocks/investigate` | 发起事件调查（B3/D2） |
| **POST** | **`/api/refresh`** | **一键更新：新闻+快照+自选股事件+清理** |
| GET · POST · DELETE | `/api/watchlist` · `/api/watchlist/{code}` | 自选股增删查 |
| GET | `/api/events/watchlist` | 自选股已落库事件 |
| GET | `/api/events` | 全部已入库事件 |
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

3. **新闻不可回查，但能事后补。** 东财可翻 200 天、财联社 180 天，
   所以不必 7×24 采集，定期 `backfill_news.py --auto` 即可。

4. **行业统一用申万一级 31 个。** 三套体系互不兼容，混用会让跨行业分析错乱。

5. **缓存是必需品不是优化。** baostock 单次查询实测从 3 秒恶化到 57 秒甚至挂起。

6. **新闻必须设保留期。** 约 300 条/天、2,845 字节/条，一年就是 300 MB+；
   而调查只用得到最近几十天。默认新闻 90 天、事件 180 天、报告永久。

7. **推理模型的 `max_tokens` 必须给足。** `deepseek-v4-pro` 的思考过程也算 token，
   给少了会 `finish_reason=length` 且 `content` 为空（默认已设 2500）。

---

## 接下来要做

1. **D3 跨资产分析** —— 指数与行业数据源已验证（指数 4 源 / 行业 3 源），接进 `FinancialAnalyzer` 即可
2. **D4 情景分析**
3. **需求用户故事 + UML** —— 代码结构已稳定，可直接照 `docs/architecture.md` 画
4. **前端补监控列表页** —— 目前自选股只在内嵌面板，缺独立页面

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
- 财务是季频、行情是日频、新闻是流式，**三种时间粒度不一样**，别混
- 任何指标都要能说清「哪个源、什么复权口径、什么时间段」，报告里必须标注
- A 股老坑：复权、停牌、ST、涨跌停、退市，都要单独处理
- 东财 / legulegu 都有未文档化限频，所有 Provider 必须带退避重试
- `.env` 已被 gitignore；**不要**把 key 写进 `.env.example`（那个会提交）
