# -*- coding: utf-8 -*-
"""金融指标计算（纯函数，不做任何 I/O）。

设计原则（对应提案 4.3）：
  「金融指标计算和明确的阈值判断优先由确定性程序逻辑完成，不由 LLM 代劳。」

所有函数输入都是同一条**复权后**的价格序列，输出为百分比小数（0.12 = 12%）。
年化统一按 252 个交易日。
"""
from math import sqrt
from typing import Sequence

TRADING_DAYS = 252

__all__ = [
    "daily_returns", "total_return", "annualized_return", "annualized_volatility",
    "max_drawdown", "downside_deviation", "sharpe", "sortino", "win_rate",
    "percentile_rank", "analyze_series",
]


# ---------------------------------------------------------------- 收益
def daily_returns(closes: Sequence[float]) -> list[float]:
    """简单日收益率 r_t = P_t / P_{t-1} - 1。长度比价格少 1。"""
    out = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev is None or prev <= 0:
            out.append(0.0)
            continue
        out.append(closes[i] / prev - 1.0)
    return out


def total_return(closes: Sequence[float]) -> float | None:
    """区间累计收益（含首日到末日）。"""
    if len(closes) < 2 or closes[0] <= 0:
        return None
    return closes[-1] / closes[0] - 1.0


def annualized_return(closes: Sequence[float], periods: int = TRADING_DAYS) -> float | None:
    """几何年化。用交易日数量换算，比用自然日更贴合 A 股。"""
    n = len(closes) - 1
    if n <= 0 or closes[0] <= 0:
        return None
    growth = closes[-1] / closes[0]
    if growth <= 0:
        return None
    return growth ** (periods / n) - 1.0


def win_rate(rets: Sequence[float]) -> float | None:
    if not rets:
        return None
    return sum(1 for r in rets if r > 0) / len(rets)


# ---------------------------------------------------------------- 风险
def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _stdev(xs: Sequence[float]) -> float | None:
    """样本标准差（n-1）。少于 2 个点返回 None。"""
    n = len(xs)
    if n < 2:
        return None
    m = _mean(xs)
    return sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def annualized_volatility(rets: Sequence[float], periods: int = TRADING_DAYS) -> float | None:
    sd = _stdev(rets)
    return None if sd is None else sd * sqrt(periods)


def downside_deviation(rets: Sequence[float], mar: float = 0.0,
                       periods: int = TRADING_DAYS) -> float | None:
    """下行标准差：只统计低于目标收益 mar 的部分。"""
    if len(rets) < 2:
        return None
    downs = [min(0.0, r - mar) ** 2 for r in rets]
    return sqrt(sum(downs) / (len(rets) - 1)) * sqrt(periods)


def max_drawdown(closes: Sequence[float]):
    """最大回撤。返回 (回撤值, 峰值日期索引, 谷值日期索引)。

    回撤值 <= 0（例如 -0.25 表示从峰值跌 25%）。
    """
    if len(closes) < 2:
        return None, None, None
    peak = closes[0]
    peak_i = 0
    best = 0.0
    best_peak = best_trough = 0
    for i, p in enumerate(closes):
        if p > peak:
            peak, peak_i = p, i
        if peak > 0:
            dd = p / peak - 1.0
            if dd < best:
                best, best_peak, best_trough = dd, peak_i, i
    return best, best_peak, best_trough


def sharpe(rets: Sequence[float], rf: float = 0.0,
           periods: int = TRADING_DAYS) -> float | None:
    """夏普比率。rf 为**年化**无风险利率，内部换算成日频。"""
    sd = _stdev(rets)
    if not sd or sd == 0:
        return None
    excess_daily = _mean(rets) - rf / periods
    return excess_daily / sd * sqrt(periods)


def sortino(rets: Sequence[float], rf: float = 0.0,
            periods: int = TRADING_DAYS) -> float | None:
    dd = downside_deviation(rets, mar=rf / periods, periods=periods)
    if not dd or dd == 0:
        return None
    return (_mean(rets) - rf / periods) / dd * sqrt(periods)


# ---------------------------------------------------------------- 估值
def percentile_rank(series: Sequence[float], value: float) -> float | None:
    """value 在 series 中的分位（0~1）。0.1 表示处于历史低位 10%。"""
    vals = [v for v in series if v is not None]
    if not vals or value is None:
        return None
    below = sum(1 for v in vals if v <= value)
    return below / len(vals)


# ---------------------------------------------------------------- 汇总
def analyze_series(dates: Sequence[str], closes: Sequence[float],
                   pe_series: Sequence[float] | None = None,
                   pb_series: Sequence[float] | None = None,
                   rf: float = 0.0) -> dict:
    """把一条价格序列压成一组指标。纯计算，不关心数据从哪来。"""
    rets = daily_returns(closes)
    mdd, pk, tr = max_drawdown(closes)
    pe_last = pe_series[-1] if pe_series else None
    pb_last = pb_series[-1] if pb_series else None
    return dict(
        n_days=len(closes),
        first_close=closes[0] if closes else None,
        last_close=closes[-1] if closes else None,
        total_return=total_return(closes),
        annualized_return=annualized_return(closes),
        win_rate=win_rate(rets),
        annualized_volatility=annualized_volatility(rets),
        downside_deviation=downside_deviation(rets),
        max_drawdown=mdd,
        max_drawdown_peak=dates[pk] if pk is not None and pk < len(dates) else None,
        max_drawdown_trough=dates[tr] if tr is not None and tr < len(dates) else None,
        sharpe=sharpe(rets, rf=rf),
        sortino=sortino(rets, rf=rf),
        pe_ttm=pe_last,
        pb=pb_last,
        pe_ttm_percentile=percentile_rank(pe_series, pe_last) if pe_series and pe_last else None,
        pb_percentile=percentile_rank(pb_series, pb_last) if pb_series and pb_last else None,
    )
