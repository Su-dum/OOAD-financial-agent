# 跨资产分析（D3：relative performance / correlations / common drivers）

> 评分原文：*Analyze relationships between multiple financial assets, companies, or industries,
> such as relative performance, correlations, or common market drivers.*
>
> 上一版只有一个「指标并列排序」的 `compare()`，没有相关系数、没有净值对比、
> 没有基准联动——本文记录补齐后的口径、公式与实测。

## 一、先对齐，再计算

跨资产分析最容易错的地方不是公式，而是**对齐**：

| 做法 | 问题 |
|---|---|
| 各算各的收益率，再按索引配对 | 停牌/上市晚会让两边的「第 100 天」不是同一天，相关系数无意义 |
| 取日期并集 + 前值填充 | 填充会人为制造 0 收益，压低波动率、扭曲相关性 |
| 不复权直接算 | 除权日的假跌会被当成真实波动（参见 `docs/datasource-eval.md` §7） |

`CrossAssetAnalyzer.align()` 只用**共同交易日（交集）**，并且要求每条序列都来自
`require_returns=True` 的源（东财 qfq 会被自动排除）。任何口径问题只改这一处。

## 二、公式

按 `net_value = close / close_first * 100` 归一化（首日 = 100），
这样茅台（1200 元）和平安银行（11 元）能画在同一张图上比较相对强弱。

| 统计量 | 公式 | 代码位置 |
|---|---|---|
| 日收益率 | `r_t = P_t / P_{t-1} - 1` | `core/indicators.daily_returns` |
| 皮尔逊相关系数 | `cov(a,b) / (σ_a σ_b)` | `core/indicators.pearson` |
| Beta（相对基准） | `cov(r_a, r_b) / var(r_b)` | `core/indicators.beta` |
| 跟踪误差 | `stdev(r_a - r_b) * √252` | `core/indicators.tracking_error` |
| 超额收益 | `累计收益(标的) - 累计收益(基准)` | `application/cross_asset_service` |

全部是**纯函数**，可离线单测（`tests/test_cross_asset.py`），并与 pandas 交叉验证过：

```
pandas: corr = -0.0280   beta = -0.0368
本项目: corr = -0.0280   beta = -0.0368     # 2026-11-17 实测，完全一致
```

## 三、数据源

| 数据 | 源 | 说明 |
|---|---|---|
| 个股日线 | baostock 前复权（降级 新浪 -> 东财） | 复用 `MarketDataService`，口径与指标页一致 |
| **行业指数** | **申万** `index_hist_sw`（`SwIndustryIndexProvider`） | 代码以 `801` 开头（`801120` 食品饮料、`801080` 电子、`801780` 银行）；日频、**不复权**、同一套 CSV 缓存 |
| 基准指数 | **新浪** `index_zh_daily_sina`（旧名 `stock_zh_index_daily`） | 沪深300 `sh000300`；实测 6017 行、2002 年起、0.4s |
| 缓存 | `CsvPriceCache` | 指数也走同一套 CSV 缓存，key 带 `index_sina` / `industry_sw` 前缀 |

指数单独成链（`SinaIndexProvider`），**不混进**股票价格链：`000001` 既是平安银行
也是上证指数，混在一条链里迟早选错源。所以指数代码必须带交易所前缀（`sh000300`）。

行业指数同样单独一条链，由 `CrossAssetAnalyzer.is_industry_code()` 按 `801` 前缀分流：

```python
if self.is_industry_code(key):        # 801xxx -> 行业链，adjust="none"
    s = self._fetch_industry(key, start, end)
else:                                  # 其余 -> 股票链
    s = self.market.get_series(...)
```

这样 D3 满足 PDF 原文的 *"multiple financial assets, companies, **or industries**"*：
个股 vs 行业、行业 vs 行业都能算。

## 四、接口

```bash
# 个股之间
GET /api/stocks/cross?codes=600519,000001,300750&start=2025-11-17&end=2026-11-17&benchmark=sh000300

# 个股 vs 行业 / 行业 vs 行业（801xxx 混填即可）
GET /api/stocks/cross?codes=600519,801120,801080&start=2025-11-26&end=2026-11-26
```

返回三块：

```jsonc
{
  "n_days": 242,                       // 共同交易日数
  "assets": [                          // 每只标的的区间统计（按收益排序）
    {"code": "000001", "name": "平安银行", "industry_l1": "银行",
     "total_return": 0.1126, "annualized_volatility": 0.1674,
     "max_drawdown": -0.1240, "sharpe": 0.750,
     "beta": 0.010, "corr_to_benchmark": 0.010,
     "tracking_error": 0.167, "excess_return": 0.2471}
  ],
  "correlation": {"codes": ["600519", "000001", "300750"],
                  "matrix": [[1.0, 0.43, 0.23], [0.43, 1.0, 0.09], [0.23, 0.09, 1.0]]},
  "net_value": {"dates": ["2025-11-17", "..."], "series": [{"code": "...", "values": [100.0, "..."]}]},
  "benchmark": {"symbol": "sh000300", "name": "沪深300",
                "total_return": -0.1345, "net_value": [100.0, "..."]}
}
```

## 五、实测（2026-11-17，242 个共同交易日）

| 标的 | 行业 | 区间收益 | 年化波动 | 最大回撤 | Sharpe | β | 与基准相关 | 超额收益 |
|---|---|---|---|---|---|---|---|---|
| 000001 平安银行 | 银行 | +11.26% | 16.74% | −12.40% | 0.750 | 0.010 | 0.010 | +24.71% |
| 600519 贵州茅台 | 食品饮料 | +2.90% | 23.43% | −23.07% | 0.243 | −0.037 | −0.028 | +16.35% |
| 300750 宁德时代 | 电力设备 | −37.27% | 37.89% | −51.91% | −1.096 | 1.023 | 0.482 | −23.82% |
| 沪深300（基准） | — | −13.45% | 17.85% | — | — | 1 | 1 | 0 |

相关性矩阵（日收益率）：

```
          600519  000001  300750
600519     1.00    0.43    0.23
000001     0.43    1.00    0.09
300750     0.23    0.09    1.00
```

读法：宁德时代与沪深300 的相关性最高（0.48）、β≈1.02（放大市场波动），
而茅台/平安银行与基准几乎无相关（|r|<0.03）——这正是「共同驱动」分析想回答的问题。

> 以上数字来自本机 2026-11-17 的快照数据，只用于说明口径，不构成投资建议。

## 六、前端呈现

| 组件 | 内容 |
|---|---|
| `NetValueChart` | 多标的净值曲线 + 基准虚线（首日 = 100）；行业指数进图例 |
| `CorrelationMatrix` | 相关系数热力表（蓝正红负，深浅表示强度）；表头显示「行业 xxx」 |
| `CrossPanel` | 上面两块 + 区间指标表（收益/波动/回撤/夏普/β/相关/超额），行业行带 `行业` 徽标 |

颜色只表示**相关系数**，不代表涨跌——涨跌沿用项目的红涨绿跌约定。
输入框可混填个股与行业代码（`600519,801120,801080`），下方有代码示例提示。

## 七、已知限制

1. **相关不等于因果**：0.48 只说明同向波动，不代表「宁德涨导致茅台跌」。
2. **样本长度影响很大**：60 个交易日的相关系数噪声极大；本页默认 1 年（242 天），
   少于 20 天直接不计算（`pearson` 要求 ≥3 个点，服务层另有最小值）。
3. **基准对齐门槛**：基准与标的共同交易日少于 80% 时**直接丢弃基准**，
   只给相对表现与相关性（避免用一个错位的基准算 β）。
4. **不考虑停牌与涨跌停**：停牌日不在序列里，涨跌停无特殊处理。
5. **指数无复权概念**：指数一律 `adjust="none"`，与个股前复权序列比较是行业通行做法，
   但严格讲「个股含分红、指数不含」会带来小幅口径差。
6. **行业指数只认 `801` 前缀**：`is_industry_code()` 按 6 位纯数字 + `801` 开头判定；
   其他指数（宽基 `sh000300`、概念指数等）不进 `codes`，宽基只作 `benchmark`。
7. **行业与个股的交易日交集可能更短**：行业指数不停牌，但个股会；取交集后
   `n_days` 可能比个股单独分析时更少（页面顶部有明确标注）。
