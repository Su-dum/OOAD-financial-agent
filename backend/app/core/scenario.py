# -*- coding: utf-8 -*-
"""情景分析的纯计算（D4）。

对应评分项 **Scenario Analysis**：
*Allow users to modify selected assumptions or market conditions and analyze
their potential impact on financial assets or portfolios.*

## 这里实现什么

情景分析本质上是「给定一组假设，重算风险指标」。所有数学都在本文件里，
不做 I/O、不碰数据库，因此可以离线单测（`tests/test_scenario.py`）。

四类假设：

    市场冲击      s_m       基准一次性涨跌（例如 -10%）
    波动率倍数    k         所有标的波动率乘以 k（风险偏好/恐慌）
    相关性压力    λ         资产间相关性向 1 靠拢（危机时「一起跌」）
    直接回撤      d         组合直接承受一次回撤（压力测试口径）

组合口径：权重 w（归一化），日收益 r_p = Σ w_i r_i（每日再平衡），
年化波动 = σ_p · √252，参数法 VaR/ES 用正态分位。

## 为什么用参数法而不是历史模拟

历史模拟（直接取历史最差窗口）也在做（`worst_rolling_window`），
但**改假设**必须能算出「如果没有这段历史、但波动率翻倍会怎样」，
参数法把 σ 显式暴露出来，才能做「波动率 ×k」「相关性 →1」这类假设。
两种口径并列输出，互为佐证。
"""
from math import sqrt
from typing import Optional

TRADING_DAYS = 252

# 标准正态分位 z 与密度 φ(z)（alpha 为置信水平，如 0.95）
_Z = {0.90: 1.2815515655446004, 0.95: 1.6448536269514722, 0.99: 2.3263478740408408}
_PDF = {0.90: 0.17549779411713348, 0.95: 0.10313564037537181,
        0.99: 0.026652143702712114}


# ---------------------------------------------------------------- 基础统计
def mean(xs):
    return sum(xs) / len(xs) if xs else None


def stdev(xs):
    n = len(xs)
    if n < 2:
        return None
    m = mean(xs)
    return sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def covariance(xs, ys):
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mx, my = mean(xs[:n]), mean(ys[:n])
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / (n - 1)


def covariance_matrix(series):
    """[[cov(i,j)]]。输入是若干条等长收益率序列。"""
    k = len(series)
    out = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            c = covariance(series[i], series[j]) or 0.0
            out[i][j] = out[j][i] = c
    return out


def volatilities(cov):
    return [sqrt(max(cov[i][i], 0.0)) for i in range(len(cov))]


def correlation_matrix(cov):
    vols = volatilities(cov)
    n = len(cov)
    out = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            denom = vols[i] * vols[j]
            c = cov[i][j] / denom if denom > 0 else 0.0
            out[i][j] = out[j][i] = max(-1.0, min(1.0, c))
    return out


# ---------------------------------------------------------------- 组合
def normalize_weights(weights, n=None):
    """去掉负数、归一化到和为 1；全零/空时退回等权。"""
    ws = [max(0.0, float(w)) for w in (weights or [])]
    if n is not None and len(ws) != n:
        ws = ws[:n] + [0.0] * max(0, n - len(ws))
    total = sum(ws)
    if total <= 0:
        if not n:
            return []
        return [1.0 / n] * n
    return [w / total for w in ws]


def weighted_mean(weights, values):
    return sum(w * v for w, v in zip(weights, values))


def portfolio_volatility(weights, cov):
    """σ_p = √(wᵀ Σ w)。"""
    n = len(weights)
    if n == 0 or len(cov) != n:
        return None
    var = 0.0
    for i in range(n):
        for j in range(n):
            var += weights[i] * weights[j] * cov[i][j]
    return sqrt(max(var, 0.0))


def portfolio_series(weights, returns_by_asset):
    """每日再平衡的组合收益率序列。"""
    if not returns_by_asset:
        return []
    n = min(len(r) for r in returns_by_asset)
    out = []
    for t in range(n):
        out.append(sum(w * returns_by_asset[i][t]
                       for i, w in enumerate(weights)))
    return out


def cumulative_return(rets):
    if not rets:
        return None
    value = 1.0
    for r in rets:
        value *= (1.0 + r)
    return value - 1.0


def annualized_return(rets, periods=TRADING_DAYS):
    n = len(rets)
    if n < 1:
        return None
    growth = 1.0 + (cumulative_return(rets) or 0.0)
    if growth <= 0:
        return None
    return growth ** (periods / n) - 1.0


def annualized_volatility(rets, periods=TRADING_DAYS):
    sd = stdev(rets)
    return None if sd is None else sd * sqrt(periods)


def max_drawdown_from_returns(rets):
    """由收益率序列重建净值后算最大回撤（<= 0）。"""
    if not rets:
        return None
    value, peak, worst = 1.0, 1.0, 0.0
    for r in rets:
        value *= (1.0 + r)
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return worst


# ---------------------------------------------------------------- 压力变换
def stress_covariance(cov, vol_multiplier: float = 1.0,
                      corr_stress: float = 0.0):
    """把协方差矩阵按两类假设变换。

    corr_stress = λ：R' = (1-λ)R + λJ（J 全 1 矩阵，对角线仍为 1）。
    这是两个半正定矩阵的凸组合，仍然半正定，所以 σ_p 一定可开方。
    λ=0 保持原样，λ=1 表示「所有资产完全同涨同跌」。
    """
    n = len(cov)
    if n == 0:
        return []
    vols = volatilities(cov)
    corr = correlation_matrix(cov)
    lam = max(0.0, min(1.0, float(corr_stress)))
    k = max(0.01, float(vol_multiplier))
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            r = 1.0 if i == j else corr[i][j]
            stressed = (1.0 - lam) * r + lam * 1.0
            out[i][j] = stressed * (vols[i] * k) * (vols[j] * k)
    return out


# ---------------------------------------------------------------- 风险度量
def parametric_var(mean_ret: float, vol: float, alpha: float = 0.95) -> float:
    """参数法 VaR（正数=亏损幅度）。Var = z_α·σ − μ。"""
    z = _Z.get(alpha, _Z[0.95])
    return max(0.0, z * vol - mean_ret)


def expected_shortfall(mean_ret: float, vol: float, alpha: float = 0.95) -> float:
    """参数法 ES/CVaR：σ·φ(z)/(1−α) − μ。"""
    z = _Z.get(alpha, _Z[0.95])
    pdf = _PDF.get(alpha, _PDF[0.95])
    es = vol * pdf / (1.0 - alpha) - mean_ret
    return max(0.0, es)


# ---------------------------------------------------------------- 情景叠加
def combine_impacts(shock: float, drawdown=None) -> float:
    """把「一次性冲击」与「累积回撤」叠成一个情景点估计。

    用**复利**而不是相加：先跌 shock 之后的市值再承受 drawdown，
        (1 + shock)(1 + drawdown) − 1
    相加会高估（-3.3% + -15% = -18.3% vs 复利 -17.8%）。

    假设是「先冲击、后回撤」，两者不重叠。若用户想表达"回撤已包含冲击"，
    就不该同时施加——这一点在返回的 notes 里会写清楚，不替用户假设。

    跌幅不可能超过 100%，所以结果下限钳在 -99%（避免回本公式除零）。
    """
    s = float(shock or 0.0)
    if drawdown is None:
        total = s
    else:
        total = (1.0 + s) * (1.0 + float(drawdown)) - 1.0
    return max(-0.99, total)


def recovery_gain(loss: float) -> Optional[float]:
    """从 `loss` 回到原点所需的涨幅（正数）。

        (1 + loss)(1 + g) = 1  =>  g = |loss| / (1 − |loss|)

    亏 20% 需要涨 25%，亏 50% 需要涨 100%——这是「回本比亏损更难」的量化。
    loss 必须为负数；>= 0 时不需要回本，返回 0。
    """
    if loss is None:
        return None
    l = float(loss)
    if l >= 0:
        return 0.0
    if l <= -0.99:
        return None                      # 近乎归零，回本无意义
    return -l / (1.0 + l)


# ---------------------------------------------------------------- 历史重放
def worst_rolling_window(returns_by_asset, weights, horizon: int,
                         dates=None):
    """历史最差窗口（买入持有口径）。

    对每个长度为 `horizon` 的滚动窗口，按权重买入并持有：
        R_p = Σ w_i · Π(1+r_i) − 1
    返回组合收益最低的那个窗口，以及窗口内各标的的累计收益。
    """
    if not returns_by_asset or horizon < 1:
        return None
    n = min(len(r) for r in returns_by_asset)
    if n < horizon:
        return None
    best = None
    for start in range(0, n - horizon + 1):
        asset_cum = []
        port = 0.0
        for i, rets in enumerate(returns_by_asset):
            growth = 1.0
            for r in rets[start:start + horizon]:
                growth *= (1.0 + r)
            asset_cum.append(growth - 1.0)
            port += weights[i] * growth
        port_ret = port - 1.0
        if best is None or port_ret < best["portfolio_return"]:
            best = dict(start=start, end=start + horizon - 1,
                        portfolio_return=port_ret,
                        asset_returns=asset_cum)
    if dates and best is not None:
        best["window_start"] = dates[best["start"]]
        best["window_end"] = dates[min(best["end"], len(dates) - 1)]
    return best
