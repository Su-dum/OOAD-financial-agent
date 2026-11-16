# 金融分析与监控智能体（A 股）

面向中国 A 股市场的金融分析、事件监控与基于证据的调查智能体。

- 作业要求：`Financial-Analysis-and-Monitoring-Agent.pdf`（**基础 70% + 高级 30%**）
- 方案文档：`OOAD Project Proposal Report.docx`
- **架构说明：[`docs/architecture.md`](docs/architecture.md)**（分层、类职责、设计模式）

---

## 现在到哪一步了

**后端骨架已完整跑通**：分层架构 + 指标计算 + 事件检测 + 事件调查 + API。
LLM 已接入（带引用校验与降级），前端骨架已建但未装依赖。

| 模块 | 状态 | 在哪 |
|---|---|---|
| 数据源可行性验证（25+ 接口） | ✅ | `scripts/probes/` |
| 申万行业映射（31 行业 / 5229 只） | ✅ | `data/seed/` |
| 新闻采集 + 新闻↔股票关联（6823 条） | ✅ | `infrastructure/repositories/` |
| **分层架构（domain / application / infrastructure / api）** | ✅ | `backend/app/` |
| **行情 Provider（三源降级，无 if/elif）** | ✅ | `infrastructure/providers/` |
| **指标计算（A1 / A2 / A3）** | ✅ 已交叉验证 | `core/` + `application/` |
| **公告 Provider（巨潮列表 + PDF 正文）** | ✅ | `cninfo_provider.py` |
| **事件检测（B2 / D1）** | ✅ 阈值 / 放量 / z-score 三种规则 | `domain/events.py` |
| **事件调查（B3 / D2）** | ✅ **已接 LLM 并实测通过**（带引用校验） | `investigation_service.py` + `llm_conclusion.py` |
| **FastAPI 接口** | ✅ 12 个端点 | `api/routes/` |
| **React 前端** | ✅ 已跑起来（指标 / 事件 / 报告） | `frontend/` |
| **一键更新 + 保留策略** | ✅ 按钮式刷新 + 90 天自动裁剪 | `refresh_service.py` |
| D3 跨资产 / D4 情景分析 | ⬜ 数据齐，逻辑未写 | — |

指标已实测（贵州茅台，2023-10-30 ~ 2026-10-27，前复权）：

| 累计收益 | 年化波动率 | 最大回撤 | PE(TTM) | ROE |
|---|---|---|---|---|
| −10.21% | 23.24% | −28.21% | 20.81 | 17.95% |

验证：68 个测试（19 指标 + 18 架构 + 15 LLM + 4 并发 + 12 运维）+ pandas 独立实现交叉验证（5 项对齐到 `1e-9`）+ 复权恒等式检验。

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
│   │   ├── monitoring_service.py    # EventMonitor
│   │   ├── investigation_service.py # InvestigationAgent + 3 个工具
│   │   ├── llm_conclusion.py   #   结论策略：模板 / LLM（含引用校验）
│   │   ├── news_service.py     #   新闻采集（回溯 + 快照），脚本与 API 共用
│   │   ├── maintenance_service.py  # 保留策略与裁剪
│   │   └── refresh_service.py  #   一键刷新编排
│   ├── infrastructure/         # 基础设施层：实现 ports
│   │   ├── providers/          #   baostock / sina / eastmoney / cninfo / 新闻源
│   │   ├── repositories/       #   news / event / report 仓储
│   │   ├── llm/client.py       #   OpenAI 兼容客户端（DeepSeek / OpenAI）
│   │   ├── catalog.py          #   申万映射（5229 只）
│   │   └── providers/cache.py  #   CSV 行情缓存
│   ├── api/                    # 接口层
│   │   ├── app.py  deps.py     #   FastAPI 装配 + Composition Root
│   │   └── routes/             #   stocks / events
│   └── db.py                   # SQLite 建表（新闻 / 事件 / 报告）
├── frontend/src/
│   ├── models/index.ts         # 与后端 DTO 对应的视图对象
│   ├── services/               # HttpClient / Stock / Event / Report
│   └── components/             # StockSearch / IndicatorPanel / EventList / ReportView
├── docs/
│   ├── architecture.md         # ★ 架构说明（分层、类职责、设计模式）
│   ├── datasource-eval.md      # 数据源评估（所有实测数字）
│   ├── news-pipeline.md        # 新闻采集与关联
│   ├── indicators.md           # 指标公式与验证
│   └── llm.md                  # ★ LLM 接入与防幻觉
├── scripts/
│   ├── run_api.py              # 启动后端 API
│   ├── build_industry_map.py   # 建申万映射表
│   ├── backfill_news.py        # 新闻回溯（--auto 自动算断档）
│   ├── run_collector.py        # 实时新闻采集
│   ├── verify_indicators.py    # 指标验收
│   ├── check_llm.py            # LLM 连通性与抗幻觉自检
│   └── probes/                 # 11 个数据源探针 + outputs/
├── tests/
│   ├── test_indicators.py      # 19 个离线单测
│   └── test_architecture.py    # 18 个架构测试（全程不联网，用假 Provider）
├── data/
│   ├── seed/                   # ✅ 提交：行业结构、股票映射 CSV
│   ├── cache/market/           # ⛔ 忽略：行情缓存
│   ├── news.db                 # ⛔ 忽略：应用库（新闻/事件/报告）
│   └── sw_industry.db          # ⛔ 忽略：行业库
├── requirements.txt
├── Financial-Analysis-and-Monitoring-Agent.pdf
└── OOAD Project Proposal Report.docx
```

---

## 怎么跑

```bash
pip install -r requirements.txt
```

### LLM 配置

```bash
copy .env.example .env        # 填 LLM_API_KEY（+ 自建网关的 BASE_URL / MODEL）
python scripts/check_llm.py   # 自检：连通性 / JSON 模式 / 抗幻觉
```

本站实际用的是学校内网网关（`custom` + `deepseek-flash`，失败自动降级到 `deepseek-v4-pro`），**仅校园网可达**。
不配也能跑——结论会退回模板拼接，报告里会明确标注来源。
详见 [`docs/llm.md`](docs/llm.md)。

> ⚠️ 推理模型（`deepseek-v4-pro` / `r1`）的思考过程也算 token，
> `LLM_MAX_TOKENS` 给少了会返回空内容（默认已设 2500）。
> 实测单次调查耗时：`flash` 约 8~11 秒，`v4-pro` 约 34~94 秒。

### 后端

```bash
python scripts/run_api.py            # http://127.0.0.1:8000
# 文档：http://127.0.0.1:8000/docs
```

主要端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（数据源、股票数、新闻数） |
| GET | `/api/stocks/{code}/indicators` | 区间指标（A1/A2） |
| GET | `/api/stocks/compare?codes=600519,000001` | 跨标的比较（A3） |
| GET | `/api/stocks/{code}/events` | 事件检测（B2/D1） |
| POST | `/api/stocks/investigate` | 发起事件调查（B3/D2） |
| GET | `/api/events` | 已入库事件 |
| **POST** | **`/api/refresh`** | **一键更新：新闻+快照+自选股事件+清理** |
| GET | `/api/watchlist` | 自选股列表 |
| GET | `/api/events/watchlist` | 自选股已落库事件 |
| GET | `/api/maintenance/stats` | 数据量与保留策略 |

### 前端

```bash
cd frontend
pnpm install     # 或 npm install
pnpm dev         # http://127.0.0.1:5173 （已配好 /api 代理到 8000）
```

打开后输入 6 位代码点「分析」，或直接用 `?code=600519` 自动加载：

```
http://127.0.0.1:5173/?code=600519
```

> 依赖装的坑：pnpm 10+ 默认跳过依赖的构建脚本，vite 依赖的 `esbuild`
> 会报 `IGNORED_BUILDS`。本项目已加 `frontend/pnpm-workspace.yaml`
> 声明 `onlyBuiltDependencies: [esbuild]`；用 npm 装则无此问题。

### 数据与验证

```bash
python scripts/build_industry_map.py      # 重建申万映射（被限流时加 --delay 30 --backoff 45）
python scripts/backfill_news.py --auto    # 新闻回溯补齐

python -m pytest tests -q                 # 37 个测试
python scripts/verify_indicators.py       # 指标验收（命中缓存，秒级）
```

---

## 几条必须知道的结论

详细版在 `docs/`，这里只留会影响决策的：

1. **指标必须基于 baostock 的前复权序列。**
   东财的 `adjust="qfq"` 在非除权日不满足「复权收益 == 不复权收益」（675 天里 470 天不符），
   拿它算会让年化波动率虚高 **1.23pp**。架构上已用 `returns_trustworthy=False` 强制约束。

2. **行情有三源降级：baostock → 新浪 → 东财。**
   新浪的 qfq 口径已验证正确（偏差 6.95e-06，只是舍入噪声）。

3. **新闻不可回查，但能事后补。**
   东财可翻 200 天、财联社可翻 180 天，所以不必 7×24 采集，定期 `backfill_news.py --auto` 即可。

4. **行业统一用申万一级 31 个。** 三套体系互不兼容，混用会让跨行业分析错乱。

5. **缓存是必需品不是优化。** baostock 单次查询实测从 3 秒恶化到 57 秒甚至挂起。

6. **新闻必须设保留期。** 实测约 300 条/天、2,845 字节/条，一年就是 300 MB+；
   而调查只用得到最近几十天。默认新闻留 90 天、事件留 180 天、报告永久。

---

## 接下来要做

1. **填 API key 跑真实调查** —— 代码已就绪，`.env` 填 key 后 `check_llm.py` 自检即可
2. **前端装依赖跑起来** —— `frontend/` 的组件已齐全，`npm install` 即可联调
3. **D3 跨资产分析** —— 指数与行业数据源已验证，接进 `FinancialAnalyzer` 即可
4. **D4 情景分析**
5. **需求用户故事 + UML** —— 现在代码结构已稳定，可以照着 `docs/architecture.md` 画

### 暂缓的优化（不急，别忘）

因为取数都收敛在 `MarketDataService` 一个入口，这些是**内部替换、不返工**：

| 优化 | 什么时候做 |
|---|---|
| 增量拉取（只补最新 K 线，省 90% 请求） | 接口稳定后 |
| 全市场快照采集器（1 次拿 5576 只，11.2s） | 做盘中预警时 |
| baostock 子进程隔离（它没有超时保护） | 演示前若仍不稳 |
| 停牌 / ST / 涨跌停标记 | 事件检测精度不够时 |

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
