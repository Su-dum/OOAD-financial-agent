# 公告事件（B2：earnings announcements / major corporate events）

> 评分原文要求监测并检测「earnings announcements」「major corporate events」。
> 上一版只把公告当**调查时的证据**，没有把公告变成**事件触发器**——本文记录怎么补上的。

## 一、为什么公告要单独成一层

行情类事件（涨跌幅、放量、z-score）只看价格序列，一条 `PriceSeries` 就够。
公告不是序列，是**流**：一条公告有类型、有日期、有标题、有原文链接。
硬塞进 `AlertRule.evaluate(series)` 会破坏里氏替换（参数含义完全不同），
所以领域层有两个**并列**的策略族：

```
AlertRule   吃 PriceSeries  -> ThresholdRule / VolumeSpikeRule / ZScoreRule
NoticeRule  吃 list[dict]  -> NoticeEventRule
                ↓
          同一个 MarketEvent（下游落库 / 调查 / 前端完全不用区分）
```

`EventMonitor` 同时持有两条链，**任一条失败都不影响另一条**：
行情源被限流时，公告事件照常产出（`tests/test_notices.py` 锁住了这个行为）。

## 二、87 种公告类型 -> 11 个类别

东财 `stock_individual_notice_report` 的 `公告类型` 实测有 87 种
（600519 近 1074 条公告的分布见 `scripts/probes/outputs/07_notice_types.txt`）。
把 87 个字符串写死成 if/elif 既不可读也会随交易所改版失效，
所以改成「关键词表 + 按具体度排序」：

| 类别 | 事件类型 | 级别 | 命中关键词（节选） | 构成事件 |
|---|---|---|---|---|
| 异动澄清 | `notice_clarification` | high | 澄清、股票交易异常波动、风险提示 | ✅ |
| 监管事项 | `notice_regulatory` | high | 监管工作函、问询函、立案调查、行政处罚 | ✅ |
| 财报披露 | `notice_earnings` | medium | 年度报告、半年度报告、季度报告、业绩预告、业绩快报 | ✅ |
| 分红派息 | `notice_dividend` | medium | 分配预案、分配方案、权益分派、现金分红 | ✅ |
| 股份回购 | `notice_buyback` | medium | 回购 | ✅ |
| 股东增持 | `notice_insider_increase` | medium | 股份增持、增持计划、股东增持 | ✅ |
| 股东减持 | `notice_insider_decrease` | medium | 股份减持、减持计划、减持进展 | ✅ |
| 重大交易 | `notice_major_deal` | medium | 股权转让、资产重组、关联交易、签订协议、收购、中标 | ✅ |
| 股本变动 | `notice_equity_change` | low | 股本变动、证券简称变更、注册地址变更 | ❌ 只归类 |
| 高管变动 | `notice_management` | low | 高管人员任职变动、董事长辞职、聘任、换届 | ❌ 只归类 |
| 程序性公告 | `notice_procedural` | low | 法律意见书、议事规则、董事会决议、独立董事… | ❌ 只归类 |

匹配文本是「公告类型 + 标题」：类型字段并不可靠——东财实测 **229 条类型是 `股票`、110 条是 `其他`**，
真正的信号只在标题里（例如「关于回购股份的进展公告」类型字段仍写 `其他`）。

## 三、两条过滤规则（都踩过坑）

### 1. 硬噪音优先于关键词（`_HARD_NOISE`）

标题「关联交易决策管理制度（2025年11月修订）」会先命中 `重大交易` 的「关联交易」，
但它其实是一份**制度文件**，不是交易。所以命中下列词时直接判为程序性公告，
不再往下匹配：议事规则 / 实施细则 / 管理制度 / 管理办法 / 公司章程 /
法律意见书 / 独立董事 / 述职报告 / 候选人 / 保荐 / 核查意见 / 通知债权人 / 会议资料。

### 2. 标题前缀清洗

东财原始标题形如 `贵州茅台:贵州茅台2026年第三季度报告`——公司名重复两遍，
直接进事件摘要与报告很难看。`clean_title()` 在**入库处**统一清洗：

```
贵州茅台:贵州茅台2026年第三季度报告        -> 2026年第三季度报告
贵州茅台:关于回购股份实施结果的公告        -> 关于回购股份实施结果的公告
关于XX:YY的公告                          -> 原样保留（保守，不误删）
```

## 四、聚合口径：一条事件 = 一个（类别, 公告日）

一次年报会附 10+ 条相关公告（摘要、英文版、审计报告…）。如果逐条生成事件，
事件列表会被刷屏，而且 event 表的唯一键
`(code, event_type, trade_date, rule_name)` 会互相覆盖。

所以 `NoticeEventRule` 按 `(类别, 公告日)` 分组：

- `value` = 当日同类公告条数
- `detail` = `类别：首条标题`，多条时附「同日同类共 N 条：…」
- `source_url` = 组内第一条带链接的公告（前端「公告原文」）
- `trade_date` = 公告日（不是检测日，便于按时间回看）

## 五、数据链路

```
东财公告列表（带 公告类型 + 公告链接）  ─┐
                                        ├─> NoticeIngestService -> notice 表（本地库）
巨潮公告列表（带 PDF 详情链接）        ─┘                              │
                                                                     ├─> NoticeEventRule（B2 事件）
                                                                     └─> NoticeSearchTool（B3 证据）
```

为什么一定要落本地库：

1. **同一批数据用两次**：B2 生成事件、B3 当证据，不该抓两遍；
2. **不打外部接口**：用户点「调查」是交互路径，必须读本地（项目约定见 `docs/architecture.md`）；
3. **可复现**：一周后回看这条事件，公告还在库里；而东财/巨潮都有未文档化限频。

两个源的分工：

| 源 | 给什么 | 走哪个 Provider |
|---|---|---|
| 东财 `stock_individual_notice_report` | **公告类型**（分类必需）+ 标题 + 日期 + 链接 | `EastmoneyNoticeProvider` |
| 巨潮 `stock_zh_a_disclosure_report_cninfo` | 权威详情链接 + **PDF 正文**（证据引用） | `CninfoNoticeProvider` |

采集顺序是「东财 -> 巨潮」：东财拿不到时退回巨潮，此时没有类型字段，
分类退化为纯标题关键词（精度略低但不会没有事件）。

## 六、实测（2026-11-17，600519，近 400 天）

| 指标 | 数值 |
|---|---|
| 东财返回公告 | 99 条（接口一次返回全部历史，本地按日期过滤） |
| 归类为「构成事件」 | 36 条（36%） |
| 近 180 天生成公告事件 | 7 条（财报 2 / 分红 3 / 回购 1 / 重大交易 1） |
| 入库耗时 | 约 3 秒/只（一次请求） |
| 刷新时的上限 | 默认只采前 12 只自选股、每只最近 400 天 |

示例事件：

```
2026-10-31  notice_earnings    财报披露：2026年第三季度报告
2026-08-15  notice_earnings    财报披露：2026年半年度报告（同日同类共 2 条：…摘要）
2026-06-22  notice_dividend    分红派息：2025年年度权益分派实施公告
2026-05-28  notice_buyback     股份回购：关于回购股份实施结果暨股份变动的公告
2026-05-22  notice_major_deal  重大交易：关于与关联方签订《商标许可协议》的公告
```

## 七、接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/notices?code=&start=&end=&limit=` | 本地公告列表（不联网） |
| POST | `/api/notices/{code}/refresh?days=&limit=` | 刷新该股公告并**顺带重算事件** |
| GET | `/api/notices/categories` | 类别清单（公告类型 -> 事件类别的映射，给前端/文档用） |
| GET | `/api/stocks/{code}/events?include_notices=false` | 只看行情类事件 |

## 八、已知限制

1. **不判「利好/利空」**：`分红`、`回购`只说明发生了什么，不推断涨跌方向。
2. **公告日 ≠ 交易日**：周五盘后公告的 `trade_date` 是公告日，可能与价格反应差 1~2 个交易日；
   事件详情里保留公告日，调查窗口默认往前看 7 天。
3. **类型字段不可信**：东财有 30% 的公告类型是 `股票`/`其他`，分类依赖标题关键词，
   新出现的公告类型需要往关键词表里加词（`domain/notices.py` 一处即可）。
4. **PDF 正文只对巨潮链接有效**：东财给的是 `data.eastmoney.com` 详情页，
   `NoticeSearchTool(deep=True)` 只对巨潮链接抽正文；不 deep 时用标题 + 类别作为证据。
5. **公告历史不回溯补齐**：`notice` 表只存刷新时的窗口；跨年回溯要显式调
   `POST /api/notices/{code}/refresh?days=2000`。
