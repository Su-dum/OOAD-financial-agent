# 系统架构（面向对象设计）

> 本文说明项目的分层、类职责、设计模式与依赖方向。
> 对应 OOAD 课程要求的「设计与实现一致」——本文每一条都能在代码里找到对应文件。

## 一、总览：依赖方向

```
┌──────────────────────────────────────────────────────────┐
│  接口层  api/                                             │
│    app.py  deps.py  routes/{stocks,events}.py             │
└───────────────────────┬──────────────────────────────────┘
                        │ 只依赖应用服务
┌───────────────────────▼──────────────────────────────────┐
│  应用层  application/                                     │
│    MarketDataService   FinancialAnalyzer                  │
│    EventMonitor        InvestigationAgent                 │
└───────────────────────┬──────────────────────────────────┘
                        │ 只依赖抽象（ports）
┌───────────────────────▼──────────────────────────────────┐
│  领域层  domain/            core/                         │
│    models / ports / events / investigation                │
│    core/indicators（纯函数计算）                          │
└───────────────────────▲──────────────────────────────────┘
                        │ 实现 ports
┌───────────────────────┴──────────────────────────────────┐
│  基础设施层  infrastructure/                              │
│    providers/{baostock,sina,eastmoney,cninfo,...}         │
│    repositories/{news,event,report}   catalog             │
└──────────────────────────────────────────────────────────┘
```

**关键：箭头方向。** `domain` 不认识 `infrastructure`；依赖倒置由 `deps.py` 这个
Composition Root 在启动时装配。所以换数据源只改 `infrastructure/` 与 `deps.py`，
领域逻辑一行不动。

## 二、目录 → 层

| 目录 | 层 | 内容 |
|---|---|---|
| `domain/` | 领域 | `models.py` 值对象与实体；`ports.py` 抽象契约；`events.py` 事件与规则；`investigation.py` 证据与报告；`entity_linking.py` 实体链接 |
| `core/` | 领域（计算） | `indicators.py` 纯函数指标计算 |
| `application/` | 应用 | `market_service.py` `analysis_service.py` `monitoring_service.py` `investigation_service.py` |
| `infrastructure/` | 基础设施 | `providers/` 数据源适配器；`repositories/` 持久化；`catalog.py` 静态参考数据 |
| `api/` | 接口 | FastAPI 路由与依赖装配 |
| `frontend/` | 表现层 | React + TS：`models/`（DTO 与视图对象）`services/`（API 客户端）`components/`（纯展示） |

## 三、类清单与职责

### 领域层

| 类 / 协议 | 类型 | 职责 |
|---|---|---|
| `StockRef` | 值对象 | 股票标识，含 `bs_code` / `sina_code` 格式转换 |
| `PriceRecord` | 值对象 | 一根日线，**显式记录 `adjust` 与 `source`** |
| `PriceSeries` | 实体 | 一段价格序列，提供 `closes` / `start` / `end` |
| `IndicatorSet` | 值对象 | 一次分析的全部指标结果 |
| `PriceProvider` | **协议** | 行情源契约（`name` / `priority` / `returns_trustworthy` / `fetch`） |
| `PriceCache` | 协议 | 缓存契约 |
| `NewsRepository` / `EventRepository` / `ReportRepository` | 协议 | 持久化契约 |
| `MarketEvent` | 值对象（frozen） | 一个被检测到的事件 |
| `AlertRule` | **抽象基类** | 预警规则策略的父类 |
| `ThresholdRule` / `VolumeSpikeRule` / `ZScoreRule` | 策略 | 三种检测算法 |
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
| `EventMonitor` | 把序列喂给规则列表，汇总事件（B2 / D1） |
| `InvestigationTool` | 调查工具协议 |
| `NewsSearchTool` / `NoticeSearchTool` / `IndicatorTool` | 三个具体工具，各自产出 `Evidence` |
| `InvestigationAgent` | 拆任务 → 调工具 → 组装报告（B3 / D2） |
| `LLMClient` | 协议：可选的大模型客户端，不接也能出报告 |

### 基础设施层

| 类 | 实现什么 |
|---|---|
| `BasePriceProvider` | **模板方法**：`fetch()` 固定「缓存 → 重试 → 解析 → 回写」，子类只填 `_request` / `_parse` |
| `BaostockProvider` | 口径完美（复权恒等式偏差 0），带 PE/PB |
| `SinaProvider` | 口径正确（偏差 6.95e-06），无 PE/PB |
| `EastmoneyProvider` | 字段最全，但 `returns_trustworthy = False` |
| `CninfoNoticeProvider` | 巨潮公告列表 + PDF 正文抽取 |
| `CsvPriceCache` | `PriceCache` 实现，CSV 落盘 + TTL |
| `SqliteNewsRepository` / `SqliteEventRepository` / `SqliteReportRepository` | 仓储实现 |
| `CsvStockCatalog` | 申万行业映射（5229 只） |

## 四、用到的设计模式

| 模式 | 落在哪 | 解决什么问题 |
|---|---|---|
| **适配器** | `providers/*` 实现 `Ports` | baostock / 新浪 / 东财 接口各不相同，统一成 `PriceProvider` |
| **模板方法** | `BasePriceProvider.fetch()` | 三个数据源的缓存/重试/解析逻辑不再复制粘贴 |
| **策略** | `AlertRule` 及其三个子类 | 检测算法可互换，新增规则不改 `EventMonitor` |
| **链式职责** | `ProviderChain` | 数据源降级，顺序可配、可插拔 |
| **仓储** | `repositories/*` | 领域层不认识 SQLite 表结构 |
| **门面** | `MarketDataService` / `FinancialAnalyzer` | 给接口层一个简单入口，隐藏内部编排 |
| **依赖倒置** | `ports.py` + `deps.py` | 上层依赖抽象，具体实现由 Composition Root 注入 |
| **值对象** | `PriceRecord` / `MarketEvent` / `Evidence`（frozen） | 不可变，避免共享状态被意外修改 |

## 五、三个刻意的设计取舍

### 1. 指标计算保持纯函数，不封装成类

`core/indicators.py` 是 11 个无副作用的函数。**这是资产不是债**：

- 可精确单测（19 个用例，含与 O(n²) 暴力实现比对最大回撤）
- `FinancialAnalyzer` 只在外面做编排，符合「计算归计算、编排归编排」
- 如果把公式塞进类里，只会增加耦合，不增加任何能力

### 2. Provider 用 `Protocol` 而不是强制继承

`PriceProvider` 是结构化类型（typing.Protocol）。好处：

- 假替身（测试用）不需要继承真实基类
- 天然支持鸭子类型，第三方实现零侵入
- `BasePriceProvider` 只是**可选的**复用骨架，不是强制父类

### 3. 事实与推测在类型层面就分开

`InvestigationReport` 有 `facts` 和 `hypotheses` 两个字段，`Evidence` 只描述
「我看到了什么」。这是对提案 4.7「风险二：AI 生成的解释不可靠」的设计级应对——
**不可能把推测写成事实**，因为它们在结构上不是一回事。

## 六、可测试性（架构是否有效的直接证据）

```
$ pytest tests -q
37 passed in 0.09s
```

- `tests/test_indicators.py`（19 个）：纯函数计算
- `tests/test_architecture.py`（18 个）：**完全不联网**，用假 Provider / 假工具注入

架构测试覆盖：

| 验证点 | 说明 |
|---|---|
| `isinstance(FakeProvider(), PriceProvider)` | 结构化类型成立 |
| 按 `priority` 排序 | 优先级策略生效 |
| 首个失败自动降级 | 链式职责生效 |
| `require_returns=True` 时跳过东财类源 | 口径约束被架构强制 |
| 缓存命中不重复请求 | 模板方法生效 |
| `prefer` 把源移到队首 | 可运行时切换 |
| 三种规则都能跑同一序列 | 策略多态成立 |
| Agent 在工具抛异常时仍出报告 | 容错边界清晰 |
| 事实 / 推测分离 | 领域约束可断言 |

**能做到「不联网跑通全链路」，就是解耦成功的证据**——如果代码里到处是
`if src == "baostock"`，这些替身根本插不进去。

## 七、演进方式：改需求时动哪个文件

| 变化 | 需要改 | 不需要改 |
|---|---|---|
| 新增一个行情数据源 | 写一个 `BasePriceProvider` 子类 + 在 `deps.py` 加一行 | 应用层、领域层、接口层 |
| 新增一种异常检测算法 | 写一个 `AlertRule` 子类 + `monitor.add_rule()` | `EventMonitor`、报告流程 |
| 换数据库 | 换 `repositories/` 的实现 | 领域层、应用层 |
| 接入大模型 | 写一个满足 `LLMClient` 协议的类，注入 `InvestigationAgent` | 报告结构、证据收集 |
| 换前端框架 | 重写 `frontend/` | 后端全部 |

## 八、与评分项对应

| 评分项 | 架构落点 |
|---|---|
| A1 获取行情与财务 | `MarketDataService` + `providers/*` + `CsvStockCatalog` |
| A2 计算金融指标 | `core/indicators` + `FinancialAnalyzer` |
| A3 历史与横向比较 | `FinancialAnalyzer.compare` / `compare_periods` |
| B2 事件监控 | `domain/events` + `EventMonitor` |
| B3 事件后调查 | `InvestigationAgent` + 三个 Tool + `InvestigationReport` |
| C4 证据可追溯 | `Evidence`（来源/时间/链接/原文片段）+ 报告引用列表 |
| D1 自动异常检测 | `ZScoreRule`（无需用户写规则） |
| D2 多步骤调查 | `InvestigationTask` 列表 + 逐任务执行 |
| D3 跨资产分析 | `compare` + 指数/行业数据源（已在数据层验证） |
| D4 情景分析 | 待实现（数据已具备） |
