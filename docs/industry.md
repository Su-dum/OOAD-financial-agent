# 行业监控（B1：Monitor selected assets, companies, or industries）

> 评分原文要求监控对象包含 **industries**。此前行业只作为个股的标签展示，
> 没有任何「行业级」的监控与检测。本文记录补法、口径与实测。

## 一、为什么监控「行业指数」而不是「成分股聚合」

| 做法 | 问题 |
|---|---|
| 把行业里所有成分股等权平均 | 等于自己造一个指数，权重、调整时点都没有公信力 |
| 按市值加权自行计算 | 需要全市场自由流通市值，数据成本高，且与公开指数不一致 |
| **直接监控申万行业指数** | 交易所/申万编制，口径统一、历史从 1999 年起、31 个行业互相可比 |

申万一级 31 个行业指数实测（`docs/datasource-eval.md` §10.2）：
**6479 行、1999-12-30 起、单次请求约 1 秒**，而且自带 PE/PB/股息率。

## 二、数据链路

```
data/seed/sw_industry.csv          31 个一级行业（代码/名称/成分股数/PE/PB）
        │
        ├─> CsvStockCatalog.industries()    行业清单（不联网）
        │
        └─> SwIndustryIndexProvider         index_hist_sw(801010, day)
                    │                       6479 行日线，CSV 缓存
                    ▼
            PriceSeries(code="801010", source="industry_sw", adjust="none")
                    │
                    ▼
        EventMonitor.evaluate_series(series, name, rules, scope="industry")
                    │
                    ▼
            MarketEvent(scope="industry")  -> event 表
```

关键点：

1. **行业指数单独一个 Provider**，不混进股票价格链——`801010` 是 6 位数字，
   和股票代码长得一样，混链必错（`docs/architecture.md` 的决策表里记了这条）。
2. **同一套规则**：涨跌幅 / 放量 / z-score 三个 `AlertRule` 直接复用，
   只是事件多一个 `scope="industry"` 标记。行业不需要第二套检测算法。
3. **事件与服务共用一张表**：`event.scope` 区分 `stock` / `industry`，
   查询时按需过滤（自选股面板只看 stock）。

## 三、接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/industries` | 31 个行业 + 是否已监控 |
| GET | `/api/industries/watched` | 已监控行业（附最近一次事件） |
| POST | `/api/industries/{code}/watch` | 加入监控 |
| DELETE | `/api/industries/{code}/watch` | 移出监控 |
| GET | `/api/industries/{code}/series?days=365` | 行业指数走势（图表） |
| GET | `/api/industries/{code}/events?days=365` | 行业事件（同一套规则） |
| POST | `/api/industries/refresh?days=365` | 批量检测已监控行业并落库 |

「一键更新」里也包含行业检测：`POST /api/refresh` 的第 5.5 步会对
**已监控行业**逐个跑规则并落库，结果放在 `industry_events` 字段。

## 四、实测（2026-11-24）

```
已监控行业：3 个（电子 801080 / 食品饮料 801120 / 银行 801780）
刷新耗时：   19.9 秒（含新闻、财务、个股事件、行业事件、自动调查）
行业检测：   3 个行业 -> 19 个事件（落库 19）
单行业示例： 电子指数 496 只成分股、PE(TTM) 38.45、PB 5.8
             近 1 年 240 个交易日、指数 5333 → 12719 区间、24 个事件
```

## 五、前端

`IndustryPanel.tsx`：

- 「已监控」chips（点名字看走势，点 × 移出）
- 31 个行业下拉 + 「加入监控」
- 行业指数走势图（复用 `PriceChart`，事件点直接画在指数曲线上）
- 行业事件列表（`EventList`，不显示「调查」按钮——见限制 3）

## 六、已知限制

1. **按需刷新而非常驻**：行业检测发生在「一键更新」或「刷新行业事件」时，
   没有后台定时任务（项目整体是「按需刷新」模式）。
2. **只支持申万一级**：二级/三级行业虽然也在 seed CSV 里，但没有单独做监控入口；
   行业体系混用会让跨行业分析错乱（`docs/datasource-eval.md` §10.4）。
3. **行业事件暂不支持「调查」**：`InvestigationAgent` 的新闻/公告工具是按**股票代码**
   检索的，行业事件要用行业名做关键词检索才能接上（下一步工作）。
4. **行业事件不参与自动调查**：`RefreshService` 的自动调查只处理个股事件
   （`severity=high`），避免把「行业普涨」也生成一堆报告。
5. **指数无复权概念**：行业指数一律 `adjust="none"`，与个股前复权序列比较时
   会有「个股含分红、指数不含」的小口径差。
