# -*- coding: utf-8 -*-
"""指标计算的单元测试（完全离线，用构造数据）。

这些测试的价值在于：金融指标算错是**静默错误**——程序不报错，只是数字不对。
所以每个函数都要有可手算验证的用例。
"""
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core import indicators as ind


# ---------------------------------------------------------------- 收益
def test_daily_returns_simple():
    assert ind.daily_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])


def test_daily_returns_skips_zero_prev():
    # 前一日为 0 时不能除零，按 0 处理
    assert ind.daily_returns([0, 100]) == [0.0]


def test_daily_returns_empty_and_single():
    assert ind.daily_returns([]) == []
    assert ind.daily_returns([100]) == []


def test_total_return():
    assert ind.total_return([100, 121]) == pytest.approx(0.21)
    assert ind.total_return([100]) is None


def test_annualized_return_one_year():
    # 252 个交易日、翻倍 -> 正好 +100%
    closes = [100 * (2 ** (i / 252)) for i in range(253)]
    assert ind.annualized_return(closes) == pytest.approx(1.0, rel=1e-9)


def test_annualized_return_half_year():
    # 126 个交易日、涨 20% -> 年化应为 1.2^2 - 1 = 0.44
    closes = [100 * (1.2 ** (i / 126)) for i in range(127)]
    assert ind.annualized_return(closes) == pytest.approx(0.44, rel=1e-9)


def test_win_rate():
    assert ind.win_rate([0.1, -0.1, 0.2, 0.0]) == pytest.approx(0.5)


# ---------------------------------------------------------------- 风险
def test_annualized_volatility_zero_for_constant_returns():
    # 每日都涨 1%，波动应为 0
    rets = [0.01] * 100
    assert ind.annualized_volatility(rets) == pytest.approx(0.0, abs=1e-12)


def test_annualized_volatility_known_value():
    # 交替 +1% / -1% -> 样本 std = 0.01 * sqrt(?) 用 n-1
    rets = [0.01, -0.01] * 50
    expect = 0.01 * math.sqrt(252) * math.sqrt(100 / 99)
    assert ind.annualized_volatility(rets) == pytest.approx(expect, rel=1e-9)


def test_max_drawdown_known():
    # 100 -> 110（峰）-> 99（谷）-> 121
    mdd, pk, tr = ind.max_drawdown([100, 110, 99, 121])
    assert mdd == pytest.approx(99 / 110 - 1)
    assert (pk, tr) == (1, 2)


def test_max_drawdown_monotonic_increasing_is_zero():
    mdd, _, _ = ind.max_drawdown([1, 2, 3, 4, 5])
    assert mdd == 0.0


def test_max_drawdown_monotonic_decreasing():
    mdd, pk, tr = ind.max_drawdown([100, 80, 60])
    assert mdd == pytest.approx(-0.4)
    assert (pk, tr) == (0, 2)


def test_max_drawdown_matches_bruteforce():
    """和 O(n^2) 暴力实现比对，防止环回逻辑写错。"""
    random.seed(42)
    for _ in range(20):
        closes = [100.0]
        for _ in range(60):
            closes.append(max(1.0, closes[-1] * (1 + random.uniform(-0.08, 0.08))))
        brute = 0.0
        for i in range(len(closes)):
            for j in range(i + 1, len(closes)):
                if closes[i] > 0:
                    brute = min(brute, closes[j] / closes[i] - 1)
        mdd, _, _ = ind.max_drawdown(closes)
        assert mdd == pytest.approx(brute, rel=1e-9)


def test_sharpe_zero_variance_returns_none():
    assert ind.sharpe([0.01] * 50) is None


def test_sharpe_sign():
    # 全正收益 -> 夏普为正
    rets = [0.01, 0.02, 0.015, 0.005, 0.012]
    assert ind.sharpe(rets) > 0


def test_downside_deviation_ignores_upside():
    # 只有上涨时，下行波动应为 0
    assert ind.downside_deviation([0.01, 0.02, 0.03]) == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------- 估值
def test_percentile_rank():
    series = [10, 20, 30, 40, 50]
    assert ind.percentile_rank(series, 10) == pytest.approx(1 / 5)
    assert ind.percentile_rank(series, 50) == pytest.approx(1.0)
    assert ind.percentile_rank(series, 5) == pytest.approx(0.0)
    assert ind.percentile_rank([], 10) is None


# ---------------------------------------------------------------- 汇总
def test_analyze_series_integration():
    closes = [100, 110, 99, 121, 115]
    dates = [f"2026-01-{i+1:02d}" for i in range(len(closes))]
    out = ind.analyze_series(dates, closes, pe_series=[10, 11, 10, 12, 11.5],
                             pb_series=[1, 1.1, 1.0, 1.2, 1.15])
    assert out["n_days"] == 5
    assert out["total_return"] == pytest.approx(0.15)
    assert out["max_drawdown"] == pytest.approx(99 / 110 - 1)
    assert out["max_drawdown_peak"] == "2026-01-02"
    assert out["max_drawdown_trough"] == "2026-01-03"
    assert out["pe_ttm"] == 11.5
    assert 0.0 <= out["pe_ttm_percentile"] <= 1.0


def test_analyze_series_too_short():
    # 单点序列不应崩溃
    out = ind.analyze_series(["2026-01-01"], [100.0])
    assert out["n_days"] == 1
    assert out["annualized_volatility"] is None
