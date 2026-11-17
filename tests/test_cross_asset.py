# -*- coding: utf-8 -*-
"""跨资产分析（D3）与相关系数的测试（全部离线）。

相关性很容易「算出一个漂亮但错误的数字」：
  - 序列没对齐（各算各的收益率）
  - 用并集对齐后填充缺失值
  - 停牌日被当成 0 收益
这几条都会让相关系数偏移，所以这里专门锁住对齐与矩阵性质。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.application.cross_asset_service import CrossAssetAnalyzer
from backend.app.core import indicators as ind
from backend.app.domain.models import PriceRecord, PriceSeries


def make_series(code, dates, closes, source="fake"):
    return PriceSeries(
        code=code, source=source,
        records=[PriceRecord(code=code, date=d, open=c, high=c, low=c,
                            close=c, volume=1000.0)
                 for d, c in zip(dates, closes)])


class FakeMarket:
    """只回放预置序列的假行情服务。"""

    def __init__(self, series: dict):
        self.series = series

    def get_series(self, code, start, end, adjust="qfq", source=None,
                   require_returns=True):
        s = self.series.get(code)
        if s is None:
            return None
        recs = [r for r in s.records if start <= r.date <= end]
        if len(recs) < 2:
            return None
        return PriceSeries(code=s.code, records=recs, adjust=s.adjust,
                           source=s.source)

    def name_of(self, code):
        return {"600519": "贵州茅台", "000001": "平安银行",
                "300750": "宁德时代"}.get(code, "")


class StubCatalog:
    def get(self, code):
        return {"name": {"600519": "贵州茅台", "000001": "平安银行",
                         "300750": "宁德时代"}.get(code, ""),
                "industry_l1_name": {"600519": "食品饮料", "000001": "银行",
                                     "300750": "电力设备"}.get(code, "")}

    def name_of(self, code):
        return self.get(code)["name"]


# ============================================================
# 1. 纯函数：pearson / beta / tracking_error
# ============================================================
def test_pearson_perfect_and_inverse():
    assert ind.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert ind.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_pearson_zero_variance_is_none():
    assert ind.pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None


def test_pearson_too_short_is_none():
    assert ind.pearson([1, 2], [1, 2]) is None


def test_pearson_bounded_even_with_float_noise():
    r = ind.pearson([0.1] * 10 + [0.1 + 1e-12], [0.1] * 11)
    assert r is None or -1.0 <= r <= 1.0


def test_beta_known_values():
    bench = [0.01, -0.02, 0.03, 0.00, -0.01]
    doubled = [2 * r for r in bench]
    assert ind.beta(doubled, bench) == pytest.approx(2.0)
    assert ind.beta([-r for r in bench], bench) == pytest.approx(-1.0)


def test_beta_zero_variance_bench_is_none():
    assert ind.beta([0.01, 0.02, 0.03], [0.01, 0.01, 0.01]) is None


def test_tracking_error_zero_for_identical_series():
    rets = [0.01, -0.02, 0.03, 0.005]
    assert ind.tracking_error(rets, rets) == pytest.approx(0.0)


# ============================================================
# 2. 对齐：只用共同交易日
# ============================================================
def test_align_uses_intersection_of_dates():
    a = make_series("600519", ["2026-01-05", "2026-01-06", "2026-01-07"],
                    [10.0, 11.0, 12.0])
    b = make_series("000001", ["2026-01-06", "2026-01-07", "2026-01-08"],
                    [20.0, 21.0, 22.0])
    dates, aligned = CrossAssetAnalyzer.align({"600519": a, "000001": b})
    assert dates == ["2026-01-06", "2026-01-07"]
    assert aligned["600519"] == [11.0, 12.0]
    assert aligned["000001"] == [20.0, 21.0]


def test_align_empty_when_no_overlap():
    a = make_series("a", ["2026-01-05"], [10.0])
    b = make_series("b", ["2026-02-05"], [20.0])
    dates, aligned = CrossAssetAnalyzer.align({"a": a, "b": b})
    assert dates == [] and aligned == {}


# ============================================================
# 3. 相关性矩阵
# ============================================================
def test_correlation_matrix_shape_and_symmetry():
    base = [100.0]
    for i in range(30):
        base.append(base[-1] * (1.004 if i % 2 else 0.997))
    same = list(base)
    inverse = [200.0 - (x - 100.0) for x in base]
    matrix = CrossAssetAnalyzer.correlation_matrix(
        {"a": base, "b": same, "c": inverse})
    m = matrix["matrix"]
    assert matrix["codes"] == ["a", "b", "c"]
    assert all(m[i][i] == 1.0 for i in range(3))
    assert m[0][1] == pytest.approx(1.0, abs=1e-6)
    assert m[0][2] < -0.9                       # 反向走势
    assert m[1][2] == pytest.approx(m[2][1])    # 对称


def test_net_value_starts_at_100():
    assert CrossAssetAnalyzer.net_value([10.0, 11.0, 9.0]) == [100.0, 110.0, 90.0]
    assert CrossAssetAnalyzer.net_value([]) == []


# ============================================================
# 4. compare()：整条编排
# ============================================================
DATES = [f"2026-05-{d:02d}" for d in range(1, 31)]


def _alt_closes(start: float, up: float, down: float, n: int) -> list:
    """交替等比涨跌，构造**二进制可精确表示**的收益率序列。

    为什么不用 `100 * 1.01**i`：那种序列的日收益率是「近似常数」，
    浮点误差会让协方差里全是舍入噪声，相关系数会算出 0.16 这种怪值。
    这里用 ×1.5 / ×0.75（都是 2 的幂次组合），收益率严格等于 +0.5 / -0.25。
    """
    out, v = [start], start
    for i in range(n - 1):
        v = v * (up if i % 2 == 0 else down)
        out.append(v)
    return out


CLOSES_A = _alt_closes(100.0, 1.5, 0.75, 30)     # 收益 +50% / -25%
CLOSES_B = _alt_closes(200.0, 0.5, 1.25, 30)     # 收益 -50% / +25%（严格 = -A）


def build_analyzer(with_bench=False):
    market = FakeMarket({
        "600519": make_series("600519", DATES, CLOSES_A),
        "000001": make_series("000001", DATES, CLOSES_B),
    })
    bench = None
    if with_bench:
        class Bench:
            def fetch(self, symbol, start, end, adjust="none"):
                return make_series(symbol, DATES, [300.0 + (i % 3) for i in range(30)],
                                   source="index_sina")
        bench = Bench()
    return CrossAssetAnalyzer(market, catalog=StubCatalog(), benchmark=bench,
                              log=None)


def test_compare_builds_assets_correlation_and_net_value():
    body = build_analyzer().compare(["600519", "000001", "999999"],
                                    DATES[0], DATES[-1])
    assert body["n_days"] == 30
    assert [a["code"] for a in body["assets"]] == ["600519", "000001"]
    assert body["assets"][0]["name"] == "贵州茅台"
    assert body["assets"][0]["industry_l1"] == "食品饮料"
    assert body["correlation"]["codes"] == ["600519", "000001"]
    # 单调上涨 vs 单调下跌 -> 强负相关
    assert body["correlation"]["matrix"][0][1] < -0.9
    assert body["net_value"]["series"][0]["values"][0] == 100.0
    assert len(body["net_value"]["dates"]) == 30
    assert body["benchmark"] is None
    assert "beta" not in body["assets"][0]


def test_compare_with_benchmark_adds_beta():
    body = build_analyzer(with_bench=True).compare(
        ["600519", "000001"], DATES[0], DATES[-1], benchmark="sh000300")
    bench = body["benchmark"]
    assert bench["symbol"] == "sh000300" and bench["name"] == "沪深300"
    assert len(bench["net_value"]) == body["n_days"]
    for a in body["assets"]:
        assert "beta" in a and "corr_to_benchmark" in a


def test_compare_returns_note_when_nothing_available():
    body = build_analyzer().compare(["999999"], DATES[0], DATES[-1])
    assert body["assets"] == []
    assert "共同交易日" in body["note"]


def test_compare_respects_max_points():
    body = build_analyzer().compare(["600519", "000001"], DATES[0], DATES[-1],
                                    max_points=10)
    assert len(body["net_value"]["dates"]) <= 11
    assert body["n_days"] == 30          # 统计仍基于全部交易日


# ============================================================
# 5. 单标的序列（前端图表）
# ============================================================
def test_series_points_returns_chart_payload():
    body = build_analyzer().series_points("600519", DATES[0], DATES[-1])
    assert body["code"] == "600519" and body["name"] == "贵州茅台"
    assert len(body["points"]) == 30
    assert body["points"][0]["date"] == DATES[0]
    assert "volume" in body["points"][0] and "pe_ttm" in body["points"][0]


def test_series_points_missing_code_returns_none():
    assert build_analyzer().series_points("999999", DATES[0], DATES[-1]) is None
