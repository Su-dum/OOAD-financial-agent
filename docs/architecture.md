# 系统架构（面向对象设计）

> 本文说明项目的分层、类职责、设计模式与依赖方向。
> 对应 OOAD 课程要求的「设计与实现一致」——本文每一条都能在代码里找到对应文件。

## 一、总览：依赖方向

```
┌──────────────────────────────────────────────────────────────┐
│  接口层  api/                                                 │
│    app.py  deps.py  routes/{stocks,events,notices,alerts,     │
│                             chat,maintenance}.py              │
└───────────────────────┬──────────────────────────────────────┘
                        │ 只依赖应用服务
┌───────────────────────▼──────────────────────────────────────┐
│  应用层  application/                                         │
│    MarketDataService   FinancialAnalyzer   CrossAssetAnalyzer │
│    EventMonitor        InvestigationAgent  ConversationAgent  │
│    AlertConfigService  NoticeIngestService NewsIngestService  │
│    MaintenanceService  RefreshService                         │
└───────────────────────┬──────────────────────────────────────┘
                        │ 只依赖抽象（ports）
┌───────────────────────▼──────────────────────────────────────┐
│  领域层  domain/            core/                            │
│    models / ports / events / notices / investigation /        │
│    watchlist / entity_linking                                │
│    core/indicators（纯函数计算，含跨资产统计量）              │
└───────────────────────▲──────────────────────────────────────┘
                        │ 实现 ports
┌───────────────────────┴──────────────────────────────────────┐
│  基础设施层  infrastructure/                                  │
│    providers/{baostock,sina,eastmoney,cninfo,sina_index,      │
│               eastmoney_notice,news_sources,akshare_compat,   │
│               pdf_utils,cache}                                │
│    repositories/{news,event,report,watchlist,notice,alert_rule}│
│    catalog   llm/{client}                                     │
└──────────────────────────────────────────────────────────────┘
```

**关键：箭头方向。** `domain` 不认识 `infrastructure`；依赖倒置由 `deps.py` 这个
Composition Root 在启动时装配。所以换数据源只改 `infrastructure/` 与 `deps.py`，
领域逻辑一行不动。

## 二、目录 → 层

| 目录 | 层 | 内容 |
|---|---|---|
| `domain/` | 领域 | `models.py` 值对象与实体；`ports.py` 抽象契约；`events.py` 事件与两类规则；`notices.py` 公告→事件分类；`investigation.py` 证据与报告；`entity_linking.py` 实体链接；`watchlist.py` 监控列表 |
| `core/` | 领域（计算） | `indicators.py` 纯函数：收益/风险/估值 + 相关系数/beta/跟踪误差 |
| `application/` | 应用 | `market_service` `analysis_service` `cross_asset_service` `monitoring_service` `investigation_service` `conversation_service` `alert_config_service` `notice_service` `news_service` `maintenance_service` `refresh_service` |
| `infrastructure/` | 基础设施 | `providers/` 数据源适配器；`repositories/` 持久化；`catalog.py` 静态参考数据；`llm/client.py` 大模型客户端 |
| `api/` | 接口 | FastAPI 路由与依赖装配 |
| `frontend/` | 表现层 | React + TS：`models/`（DTO 与视图对象）`services/`（API 客户端）`components/`（展示与图表） |

## 三、类清单与职责

### 领域层

| 类 / 协议 | 类型 | 职责 |
|---|---|---|
| `StockRef` | 值对象 | 股票标识，含 `bs_code` / `sina_code` 格式转换 |
| `PriceRecord` | 值对象 | 一根日线，**显式记录 `adjust` 与 `source`** |
| `PriceSeries` | 实体 | 一段价格序列，提供 `closes` / `start` / `end` |
| `IndicatorSet` | 值对象 | 一次分析的全部指标结果 |
| `PriceProvider` | **协议** | 行情源契约（`name` / `priority` / `returns_trustworthy` / `fetch`） |
| `PriceCache` / `NewsRepository` / `EventRepository` / `ReportRepository` / `NoticeRepository` | 协议 | 缓存与持久化契约 |
| `MarketEvent` | 值对象（frozen） | 一个被检测到的事件，带 `label` 与 `source_url` |
| `AlertRule` | **抽象基类** | 行情类预警规则策略父类 |
| `ThresholdRule` / `VolumeSpikeRule` / `ZScoreRule` | 策略 | 三种行情检测算法 |
| `NoticeRule` | **抽象基类** | 公告类预警规则策略父类（输入是公告流，不是价格序列） |
| `NoticeEventRule` | 策略 | 把重大公告按（类别, 公告日）聚合成事件 |
| `NoticeCategory` | 值对象（frozen） | 一个公告类别：关键词、事件类型、级别、是否构成事件 |
| `Evidence` | 值对象（frozen） | 一条可追溯的证据 |
| `InvestigationTask` | 值对象 | 调查子任务（多步骤调查单元） |
| `InvestigationReport` | 实体 | 调查报告，含 `facts` / `hypotheses` 分栏与 `to_markdown()` |
| `StockIndex` | 领域服务 | 实体链接索引（新闻 → 股票） |

### 应用层

| 类 | 职责 |
|---|---|
| `ProviderChain` | 按 `priority` 编排多个 Provider，实现降级；**无 if/elif** |
| `MarketDataService` | 对外的唯一取数入口；`default()` 工厂负责装配默认链 |
| `FinancialAnalyzer` | 取数 → 调纯函数 → 组装 `IndicatorSet`；`compare` / `compare_periods` 支持 A3 |
| `CrossAssetAnalyzer` | 多标对齐、净值、相关性矩阵、基准 beta（D3） |
| `EventMonitor` | 把价格序列喂给 `AlertRule`、把公告流喂给 `NoticeRule`，汇总事件（B2 / D1） |
| `AlertConfigService` | 三级合并「默认 → 全局 → 个股」预警配置，构造规则对象（C1） |
| `InvestigationTool` | 调查工具协议 |
| `NewsSearchTool` / `NoticeSearchTool` / `IndicatorTool` | 三个具体工具，各自产出 `Evidence` |
| `InvestigationAgent` | 拆任务 → 调工具 → 组装报告（B3 / D2） |
| `ConversationAgent` | 意图路由、证据快照、模板/LLM 作答、条件修改动作解析（C2 / C1） |
| `ConclusionWriter` | **协议**：结论生成策略 |
| `TemplateConclusionWriter` | 模板拼接（永远可用的兜底） |
| `LLMConclusionWriter` | 大模型归纳 + **引用校验** + 失败自动降级 |
| `NoticeIngestService` | 东财 → 巨潮 降级的公告采集与落库 |
| `NewsIngestService` / `MaintenanceService` / `RefreshService` | 新闻采集、保留策略、一键刷新编排 |

### 基础设施层

| 类 | 实现什么 |
|---|---|
| `BasePriceProvider` | **模板方法**：`fetch()` 固定「缓存 → 重试 → 解析 → 回写」，子类只填 `_request` / `_parse` |
| `BaostockProvider` | 口径完美（复权恒等式偏差 0），带 PE/PB |
| `SinaProvider` | 口径正确（偏差 6.95e-06），无 PE/PB |
| `EastmoneyProvider` | 字段最全，但 `returns_trustworthy = False` |
| `SinaIndexProvider` | 指数行情（D3 基准），代码带交易所前缀 |
| `EastmoneyNoticeProvider` | 公告列表 + **公告类型**（B2 分类依据） |
| `CninfoNoticeProvider` | 巨潮公告列表 + PDF 正文抽取（B3 证据） |
| `akshare_compat` | akshare 改名兼容层（旧名 → 新名解析） |
| `pdf_utils` | 详情链接 → PDF 直链 → 抽正文（两个公告 Provider 共用） |
| `CsvPriceCache` | `PriceCache` 实现，CSV 落盘 + TTL |
| `SqliteNewsRepository` / `SqliteEventRepository` / `SqliteReportRepository` / `SqliteWatchlistRepository` / `SqliteNoticeRepository` / `SqliteAlertRuleRepository` | 仓储实现 |
| `CsvStockCatalog` | 申万行业映射（5229 只） |
| `OpenAIChatClient` / `LLMConfig` | OpenAI 兼容客户端与配置装配 |

## 四、用到的设计模式

| 模式 | 落在哪 | 解决什么问题 |
|---|---|---|
| **适配器** | `providers/*` 实现 `Ports` | baostock / 新浪 / 东财 / 巨潮 / 指数 接口各不相同，统一成少数协议 |
| **模板方法** | `BasePriceProvider.fetch()` | 各数据源的缓存/重试/解析不再复制粘贴 |
| **策略**（行情） | `AlertRule` + 三个子类 | 检测算法可互换，新增规则不改 `EventMonitor` |
| **策略**（公告） | `NoticeRule` + `NoticeEventRule` | 公告是「流」，输入与行情规则不同，平行抽象而非硬塞 |
| **策略**（结论） | `ConclusionWriter` → 模板 / LLM | 有 key 用模型归纳，无 key 或校验失败自动退回模板 |
| **链式职责** | `ProviderChain` / `NoticeIngestService` | 数据源降级，顺序可配、可插拔 |
| **仓储** | `repositories/*` | 领域层不认识 SQLite 表结构 |
| **门面** | `MarketDataService` / `FinancialAnalyzer` / `CrossAssetAnalyzer` | 给接口层一个简单入口，隐藏内部编排 |
| **依赖倒置** | `ports.py` + `deps.py` | 上层依赖抽象，具体实现由 Composition Root 注入 |
| **值对象** | `PriceRecord` / `MarketEvent` / `Evidence` / `NoticeCategory`（frozen） | 不可变，避免共享状态被意外修改 |
| **防腐层** | `akshare_compat` | 第三方库改名/换签名不外溢到业务代码 |
| **校验即守卫** | `llm_conclusion` / `conversation_service` | 引用编号必须存在，编造即整段作废 |

## 五、五个刻意的设计取舍

### 1. 指标计算保持纯函数，不封装成类

`core/indicators.py` 是 14 个无副作用的函数。**这是资产不是债**：

- 可精确单测（含与 O(n²) 暴力实现比对最大回撤、与 pandas 比对相关系数）
- 编排放在应用层，符合「计算归计算、编排归编排」
- 如果把公式塞进类里，只会增加耦合，不增加任何能力

### 2. Provider 用 `Protocol` 而不是强制继承

`PriceProvider` 是结构化类型（typing.Protocol）。好处：

- 假替身（测试用）不需要继承真实基类
- 天然支持鸭子类型，第三方实现零侵入
- `BasePriceProvider` 只是**可选的**复用骨架，不是强制父类

### 3. 事实与推测在类型层面就分开

`InvestigationReport` 有 `facts` 和 `hypotheses` 两个字段，`Evidence` 只描述
「我看到了什么」。这是对提案「AI 生成的解释不可靠」的设计级应对——
**不可能把推测写成事实**，因为它们在结构上不是一回事。

### 4. 两类规则平行，而不是合并成一个「更通用」的接口

`AlertRule.evaluate(series)` 与 `NoticeRule.evaluate(notices)` 签名不同，
如果强行统一成 `evaluate(context)`，每个规则都要 `context.price` / `context.notices`
做类型判断——等于把里氏替换问题推给每个实现类。平行抽象 + `EventMonitor` 汇总，
是更小、更可测的代价。

### 5. 配置与规则分离：规则怎么算归领域，参数是多少归配置

`ThresholdRule(drop, surge)` 不认识数据库；`AlertConfigService` 从 `alert_rule` 表
读出参数再构造规则。所以「用户可配置阈值」不需要改任何规则类，
`EventMonitor` 也只是把「规则列表」换成了「规则来源」。

## 六、可测试性（架构是否有效的直接证据）

```
$ pytest tests -q
180 passed in 0.83s
```

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_indicators.py` | 19 | 纯函数计算（含暴力/随机对照） |
| `test_architecture.py` | 18 | **完全不联网**，假 Provider / 假工具注入 |
| `test_llm.py` | 14 | 假 LLM：幻觉拦截、置信度封顶、降级 |
| `test_maintenance.py` | 13 | 保留策略、自选股、刷新编排 |
| `test_threading.py` | 4 | SQLite 跨线程 |
| `test_notices.py` | 39 | 公告分类、硬噪音、聚合、落库、迁移、标题清洗 |
| `test_alerts.py` | 21 | 三级配置合并、参数校验、配置真的改变检测行为 |
| `test_chat.py` | 23 | 意图路由、动作解析、证据编号、引用校验 |
| `test_cross_asset.py` | 17 | pearson/beta、交集对齐、矩阵性质、基准 |
| `test_compat.py` | 5 | akshare 新旧名解析 |
| `test_news_service.py` | 6 | 采集边界：页数上限 / 已知 / 时间边界 / 源报错 |

架构测试覆盖：

| 验证点 | 说明 |
|---|---|
| `isinstance(FakeProvider(), PriceProvider)` | 结构化类型成立 |
| 按 `priority` 排序 / 首个失败自动降级 | 优先级与链式职责生效 |
| `require_returns=True` 时跳过东财类源 | 口径约束被架构强制 |
| 缓存命中不重复请求 | 模板方法生效 |
| 三种行情规则 + 公告规则都能跑同一序列 | 策略多态成立 |
| 行情源失败时公告事件照常产出 | 两条规则链解耦 |
| Agent 在工具抛异常时仍出报告 | 容错边界清晰 |
| 事实 / 推测分离 | 领域约束可断言 |
| 配置改阈值后事件数量变化 | 配置真的驱动行为（不是存了不用） |

**能做到「不联网跑通全链路」，就是解耦成功的证据**——如果代码里到处是
`if src == "baostock"` 或 `if notice_type == "年度报告"`，这些替身根本插不进去。

## 七、演进方式：改需求时动哪个文件

| 变化 | 需要改 | 不需要改 |
|---|---|---|
| 新增一个行情数据源 | 写一个 `BasePriceProvider` 子类 + 在 `deps.py` 加一行 | 应用层、领域层、接口层 |
| 新增一种行情异常检测算法 | 写一个 `AlertRule` 子类 + 在 `AlertConfigService` 注册 | `EventMonitor`、报告流程 |
| 新增一种公告事件类别 | 在 `domain/notices.py` 加一个 `NoticeCategory`（关键词表） | 规则、监控器、接口、前端 |
| 新增一个可配预警参数 | `DEFAULT_RULES` + `BOUNDS` + 规则构造 | 数据库、接口、前端表单（自动出现） |
| 换数据库 | 换 `repositories/` 的实现 | 领域层、应用层 |
| 接入另一家大模型 | 写一个满足 `LLMClient` 协议的类，注入 Agent | 报告结构、证据收集、追问 |
| 换前端框架 | 重写 `frontend/` | 后端全部 |

## 八、与评分项对应

| 评分项 | 架构落点 |
|---|---|
| A1 获取行情与财务 | `MarketDataService` + `providers/*` + `CsvStockCatalog` |
| A2 计算金融指标 | `core/indicators` + `FinancialAnalyzer` |
| A3 历史与横向/跨期比较 | `FinancialAnalyzer.compare` / `compare_periods` |
| B1 监控自选/公司 | `Watchlist` 聚合根 + `RefreshService` + 前端自选面板 |
| B2 事件检测（行情 + 公告） | `AlertRule` 族 + `NoticeRule` 族 + `EventMonitor` |
| B3 事件后调查 | `InvestigationAgent` + 三个 Tool + `InvestigationReport` |
| C1 可配置监控与预警 | `AlertConfigService` + `alert_rule` 表 + 前端表单 |
| C2 自然语言追问 | `ConversationAgent` + `/api/chat` + 前端对话面板 |
| C3 表格/图表/结构化解释 | 前端 `PriceChart` / `NetValueChart` / `CorrelationMatrix` + 表格 |
| C4 证据可追溯 | `Evidence`（来源/时间/链接/片段）+ 报告与追问的引用编号 |
| D1 自动异常检测 | `ZScoreRule`（无需用户写规则） |
| D2 多步骤调查 | `InvestigationTask` 列表 + 逐任务执行（见 HANDOFF 的不足说明） |
| D3 跨资产分析 | `CrossAssetAnalyzer` + 指数基准 + 前端跨资产面板 |
| D4 情景分析 | 未实现（指标计算与数据已具备） |
