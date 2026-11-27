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


# ============================================================
# A3 跨期比较（FinancialAnalyzer.compare_periods）—— 字段与区间真实性
# ============================================================
class _StubMarket:
    """按请求区间返回固定序列；可选地「真实序列比请求区间短」。"""

    def __init__(self, short_by=0):
        self.short_by = short_by
        self.requests = []

    def get_series(self, code, start, end, adjust="qfq", source=None,
                  require_returns=True, refresh=False):
        from backend.app.domain.models import PriceRecord, PriceSeries
        self.requests.append((start, end))
        closes = [100.0, 101.0, 99.0, 102.0, 103.0]
        dates = [f"2026-01-{i+1:02d}" for i in range(len(closes))]
        if self.short_by:
            closes = closes[self.short_by:]
            dates = dates[self.short_by:]
        return PriceSeries(code=code, adjust=adjust, source="baostock",
                           records=[PriceRecord(code=code, date=d, open=c, high=c,
                                                low=c, close=c, adjust=adjust,
                                                source="baostock")
                                    for d, c in zip(dates, closes)])

    def meta(self, code):
        return dict(name="贵州茅台", industry_l1_name="食品饮料")


def _analyzer(short_by=0):
    from backend.app.application.analysis_service import FinancialAnalyzer
    return FinancialAnalyzer(_StubMarket(short_by), log=None)


def test_compare_periods_fields_match_single_stock_metrics():
    """跨期表字段要与单标的指标对等，否则两处看不到同一个东西。"""
    rows = _analyzer().compare_periods(
        "600519", [("上半年", "2026-01-01", "2026-06-30")])
    for f in ("period", "start", "end", "n_days", "total_return",
              "annualized_return", "annualized_volatility", "downside_deviation",
              "max_drawdown", "sharpe", "sortino", "win_rate", "adjust", "source"):
        assert f in rows[0], f
    assert rows[0]["total_return"] == pytest.approx(0.03)
    assert rows[0]["win_rate"] == pytest.approx(3 / 4)     # 100→101→99→102→103


def test_compare_periods_reports_actual_range_not_requested():
    """实际序列比请求区间短时，要回报**真实**起止日，不能沿用请求值。"""
    full = _analyzer(short_by=0).compare_periods(
        "600519", [("近1年", "2025-01-01", "2026-06-30")])[0]
    short = _analyzer(short_by=2).compare_periods(
        "600519", [("近1年", "2025-01-01", "2026-06-30")])[0]
    assert full["n_days"] == 5
    assert short["n_days"] == 3
    # 关键：short 的 start 是真实首日（2026-01-03），不是请求的 2025-01-01
    assert short["start"] == "2026-01-03"
    assert full["start"] == "2026-01-01"


def test_compare_periods_handles_empty_window():
    class Empty(_StubMarket):
        def get_series(self, *a, **k):
            return None

    from backend.app.application.analysis_service import FinancialAnalyzer
    rows = FinancialAnalyzer(Empty(), log=None).compare_periods(
        "600519", [("空窗", "2020-01-01", "2020-02-01")])
    assert rows[0]["n_days"] == 0
    assert rows[0]["total_return"] is None
    assert rows[0]["start"] == "2020-01-01"      # 退回请求区间，仍是合法值
