# -*- coding: utf-8 -*-
"""情景分析（D4）的测试。

分两层：
  1. `core/scenario.py` 的纯数学（协方差、压力变换、VaR/ES、历史最差窗口）
  2. `ScenarioService` 的编排与校验（用假行情/假基准，不联网）
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.application.cross_asset_service import CrossAssetAnalyzer
from backend.app.application.scenario_service import (ScenarioError,
                                                       ScenarioService)
from backend.app.core import scenario as sc
from backend.app.domain.models import PriceRecord, PriceSeries


# ============================================================
# 1. 纯数学
# ============================================================
def test_covariance_matrix_symmetric_and_diagonal():
    a = [0.01, -0.01, 0.02, -0.02, 0.005]
    b = [0.02, -0.02, 0.04, -0.04, 0.01]
    cov = sc.covariance_matrix([a, b])
    assert cov[0][1] == pytest.approx(cov[1][0])
    assert cov[0][0] == pytest.approx(sc.stdev(a) ** 2)
    corr = sc.correlation_matrix(cov)
    assert corr[0][1] == pytest.approx(1.0, abs=1e-9)      # b = 2a
    assert corr[0][0] == 1.0


def test_portfolio_volatility_analytic():
    a = [0.01, -0.01, 0.02, -0.02]
    b = [-0.01, 0.01, -0.02, 0.02]        # 完全负相关
    cov = sc.covariance_matrix([a, b])
    w = [0.5, 0.5]
    assert sc.portfolio_volatility(w, cov) == pytest.approx(0.0, abs=1e-12)
    # 相关性压到 1 -> 两个同向，σ_p = Σwσ
    stressed = sc.stress_covariance(cov, vol_multiplier=1.0, corr_stress=1.0)
    vols = sc.volatilities(cov)
    assert sc.portfolio_volatility(w, stressed) == pytest.approx(vols[0], abs=1e-12)


def test_stress_multiplies_volatility():
    a = [0.01, -0.01, 0.02, -0.02, 0.03]
    cov = sc.covariance_matrix([a])
    base = sc.portfolio_volatility([1.0], cov)
    doubled = sc.portfolio_volatility([1.0], sc.stress_covariance(cov, vol_multiplier=2.0))
    assert doubled == pytest.approx(base * 2.0, rel=1e-9)


def test_stress_without_assumptions_is_identity():
    a = [0.01, -0.01, 0.02, -0.02, 0.03]
    b = [0.02, -0.02, 0.01, -0.01, 0.01]
    cov = sc.covariance_matrix([a, b])
    same = sc.stress_covariance(cov, vol_multiplier=1.0, corr_stress=0.0)
    for i in range(2):
        for j in range(2):
            assert same[i][j] == pytest.approx(cov[i][j], rel=1e-12)


def test_parametric_var_and_es_known_values():
    # 均值 0、日波动 1%：VaR95 = 1.6449%，ES95 = 2.0627%
    assert sc.parametric_var(0.0, 0.01, 0.95) == pytest.approx(0.0164485363, rel=1e-6)
    assert sc.expected_shortfall(0.0, 0.01, 0.95) == pytest.approx(0.0206271281, rel=1e-6)
    assert sc.parametric_var(0.0, 0.01, 0.99) > sc.parametric_var(0.0, 0.01, 0.95)


def test_var_never_negative():
    assert sc.parametric_var(0.05, 0.01, 0.95) == 0.0      # 收益足够高时无亏损


def test_normalize_weights():
    assert sc.normalize_weights([1, 1, 2]) == pytest.approx([0.25, 0.25, 0.5])
    assert sc.normalize_weights([-1, 1]) == pytest.approx([0.0, 1.0])   # 负数视为 0
    assert sc.normalize_weights([]) == []
    assert sc.normalize_weights(None, n=3) == pytest.approx([1 / 3] * 3)
    assert sc.normalize_weights([0, 0], n=2) == pytest.approx([0.5, 0.5])


def test_returns_helpers():
    rets = [0.1, -0.1]
    assert sc.cumulative_return(rets) == pytest.approx(-0.01)
    assert sc.max_drawdown_from_returns(rets) == pytest.approx(-0.1)
    assert sc.annualized_volatility([0.01, -0.01, 0.01, -0.01]) > 0


def test_worst_rolling_window_finds_worst():
    dates = [f"2026-01-{i:02d}" for i in range(1, 11)]
    good = [0.01] * 9
    bad = [0.0] * 9
    # 第 2~4 个位置（0-based 2..4）连跌，窗口 3 天最差
    bad[2:5] = [-0.03, -0.03, -0.03]
    got = sc.worst_rolling_window([good, bad], [0.5, 0.5], horizon=3,
                                 dates=dates[1:])
    assert got["start"] == 2
    assert got["portfolio_return"] == pytest.approx(
        0.5 * (1.01 ** 3 - 1) + 0.5 * (0.97 ** 3 - 1), rel=1e-12)
    assert got["window_start"] == dates[3]


def test_worst_rolling_window_too_short():
    assert sc.worst_rolling_window([[0.01]], [1.0], horizon=5) is None


# ============================================================
# 2. 服务编排（假行情）
# ============================================================
DATES = [f"2026-01-{i:02d}" for i in range(1, 61)]


def closes_from_returns(rets, start=100.0):
    out, v = [start], start
    for r in rets:
        v *= (1 + r)
        out.append(v)
    return out


def make_series(code, rets):
    closes = closes_from_returns(rets)
    return PriceSeries(code=code, source="fake", records=[
        PriceRecord(code=code, date=d, open=c, high=c, low=c, close=c,
                    volume=1000.0) for d, c in zip(DATES, closes)])


BASE = [0.01 * ((-1) ** i) for i in range(60)]      # 交替涨跌
RETS = {
    "600519": BASE,          # β = 1（对基准）
    "000001": [2 * x for x in BASE],   # β = 2
    "300750": [-0.5 * x for x in BASE],  # β = -0.5
}


class FakeCross:
    def __init__(self, with_benchmark=True):
        self.with_benchmark = with_benchmark
        self.sources = []

    def fetch(self, codes, start, end, source=None, **kw):
        self.sources.append(source)
        return {c: make_series(c, RETS[c]) for c in codes if c in RETS}

    def align(self, series):
        return CrossAssetAnalyzer.align(series)

    def benchmark_aligned(self, symbol, dates, start, end):
        if not self.with_benchmark:
            return None
        return dict(symbol=symbol, name="沪深300", closes=closes_from_returns(BASE),
                    total_return=0.0, annualized_volatility=0.0, source="fake")


class StubCatalog:
    def name_of(self, code):
        return {"600519": "贵州茅台", "000001": "平安银行",
                "300750": "宁德时代"}.get(code, "")


def build(with_benchmark=True):
    return ScenarioService(FakeCross(with_benchmark), catalog=StubCatalog(),
                           log=None)


def run(**kw):
    return build().run(["600519", "000001", "300750"],
                      start="2026-01-01", end="2026-03-01", **kw)


def test_run_returns_baseline_and_stress():
    body = run(market_shock=-0.10, vol_multiplier=2.0, correlation_stress=0.8)
    assert body["n_days"] == 60
    assert body["benchmark"]["available"] is True
    b, s = body["baseline"], body["stressed"]
    assert b["annualized_volatility"] > 0
    assert s["annualized_volatility"] > b["annualized_volatility"]
    assert s["var_1d_95"] > b["var_1d_95"]
    assert s["var_1d_99"] > s["var_1d_95"] > 0
    assert body["weights"] == pytest.approx({"600519": 1 / 3, "000001": 1 / 3,
                                            "300750": 1 / 3})


def test_market_shock_flows_through_beta():
    body = run(market_shock=-0.10, vol_multiplier=1.0, correlation_stress=0.0)
    assets = {a["code"]: a for a in body["assets"]}
    assert assets["600519"]["beta"] == pytest.approx(1.0, abs=1e-6)
    assert assets["000001"]["beta"] == pytest.approx(2.0, abs=1e-6)
    assert assets["300750"]["beta"] == pytest.approx(-0.5, abs=1e-6)
    # 冲击 = β × s；贡献 = w × 冲击
    assert assets["000001"]["impact"] == pytest.approx(-0.2, abs=1e-9)
    assert assets["300750"]["impact"] == pytest.approx(0.05, abs=1e-9)
    assert body["stressed"]["portfolio_impact"] == pytest.approx(
        (1 + 2 - 0.5) / 3 * -0.10, abs=1e-5)
    assert body["baseline"]["beta"] == pytest.approx(2.5 / 3, abs=1e-4)


def test_weights_are_normalized():
    body = build().run(["600519", "000001"], weights=[3, 1],
                       start="2026-01-01", end="2026-03-01")
    assert body["weights"] == pytest.approx({"600519": 0.75, "000001": 0.25})


def test_drawdown_assumption_is_reported():
    body = run(drawdown=-0.15)
    assert body["stressed"]["drawdown_impact"] == pytest.approx(-0.15)


def test_historical_replay_present():
    body = run(horizon_days=10)
    replay = body["historical_replay"]
    assert replay is not None
    assert replay["portfolio_return"] <= 0 or replay["portfolio_return"] > -1
    assert len(replay["assets"]) == 3
    assert set(replay["assets"][0]) == {"code", "name", "return"}


def test_missing_benchmark_falls_back_to_beta_one():
    body = build(with_benchmark=False).run(
        ["600519", "000001"], start="2026-01-01", end="2026-03-01",
        market_shock=-0.1)
    assert body["benchmark"]["available"] is False
    assert any("β=1" in n for n in body["notes"])
    assert body["assets"][0]["impact"] == pytest.approx(-0.1)
    assert body["baseline"]["beta"] is None


# ============================================================
# 3. 校验
# ============================================================
@pytest.mark.parametrize("kw,msg", [
    (dict(codes=["600519"]), "至少需要 2 个"),
    (dict(codes=[f"60000{i}" for i in range(9)]), "最多 8"),
    (dict(weights=[0.5]), "weights"),
    (dict(market_shock=0.8), "market_shock"),
    (dict(vol_multiplier=0.1), "vol_multiplier"),
    (dict(correlation_stress=1.5), "correlation_stress"),
    (dict(drawdown=-0.9), "drawdown"),
    (dict(horizon_days=0), "horizon_days"),
])
def test_validation_errors(kw, msg):
    codes = kw.pop("codes", ["600519", "000001"])
    with pytest.raises(ScenarioError, match=msg):
        build().run(codes, start="2026-01-01", end="2026-03-01", **kw)


def test_invalid_date_range():
    with pytest.raises(ScenarioError, match="start"):
        build().run(["600519", "000001"], start="2026-03-01", end="2026-01-01")


def test_unknown_codes_are_skipped():
    body = build().run(["600519", "999999"], start="2026-01-01",
                       end="2026-03-01")
    assert list(body["weights"].keys()) == ["600519"]


def test_source_is_passed_to_market():
    svc = build()
    svc.run(["600519", "000001"], start="2026-01-01", end="2026-03-01",
            source="sina")
    assert svc.cross.sources == ["sina"]


# ============================================================
# 4. 情景点估计：冲击 ⊕ 回撤（D4「portfolio-level impact」的另一半）
# ============================================================
from backend.app.core.scenario import combine_impacts, recovery_gain


def test_combine_is_compounded_not_added():
    """-3.3% 与 -15% 叠起来是 -17.8%（复利），不是 -18.3%（相加）。"""
    total = combine_impacts(-0.033, -0.15)
    assert total == pytest.approx(0.967 * 0.85 - 1.0)
    assert total == pytest.approx(-0.17805)
    assert total > -0.033 - 0.15          # 复利比相加"轻"


def test_combine_without_drawdown_is_just_shock():
    assert combine_impacts(-0.033, None) == pytest.approx(-0.033)


def test_combine_handles_positive_shock():
    """市场上涨 + 回撤：仍然必须算进去。"""
    assert combine_impacts(0.05, -0.15) == pytest.approx(1.05 * 0.85 - 1.0)


def test_combine_clamps_total_loss():
    """β 传导可能算出 < -100%（不可能），钳到 -99% 避免回本公式除零。"""
    assert combine_impacts(-1.7, -0.5) == pytest.approx(-0.99)


@pytest.mark.parametrize("loss,need", [
    (-0.05, 0.05 / 0.95),
    (-0.10, 0.10 / 0.90),
    (-0.20, 0.25),
    (-0.50, 1.00),
    (-0.80, 4.00),
])
def test_recovery_gain_formula(loss, need):
    assert recovery_gain(loss) == pytest.approx(need)


def test_recovery_gain_edges():
    assert recovery_gain(0.0) == 0.0          # 没亏就不用回本
    assert recovery_gain(0.02) == 0.0
    assert recovery_gain(-0.995) is None      # 近乎归零，回本无意义


def test_stressed_reports_total_impact_and_recovery():
    body = run(drawdown=-0.15)
    s = body["stressed"]
    expect = (1 + s["portfolio_impact"]) * (1 + s["drawdown_impact"]) - 1
    assert s["total_impact"] == pytest.approx(expect, abs=1e-6)
    assert s["recovery_gain"] == pytest.approx(
        -s["total_impact"] / (1 + s["total_impact"]), abs=1e-6)
    assert s["recovery_gain_drawdown"] == pytest.approx(0.15 / 0.85, abs=1e-6)


def test_total_impact_without_drawdown_equals_shock():
    s = run(drawdown=None)["stressed"]
    assert s["drawdown_impact"] is None
    assert s["total_impact"] == pytest.approx(s["portfolio_impact"])
    assert s["recovery_gain_drawdown"] is None


def test_drawdown_does_not_move_distribution_metrics():
    """回撤是点估计，**不应该**改变 VaR/波动（那是波动率假设的事）。

    这条测试是把"设计决定"钉住：以后有人想把 drawdown 揉进 σ 会立刻失败。
    """
    a = run(drawdown=None)["stressed"]
    b = run(drawdown=-0.40)["stressed"]
    for k in ("annualized_volatility", "var_1d_95", "var_1d_99",
              "es_1d_95", "var_horizon_95", "portfolio_impact"):
        assert a[k] == pytest.approx(b[k]), k
    # 但合计影响必须变
    assert a["total_impact"] != pytest.approx(b["total_impact"])


def test_drawdown_notes_explain_compounding():
    notes = " ".join(run(drawdown=-0.15)["notes"])
    assert "复利叠加" in notes and "不是相加" in notes
    assert "回本需涨幅" in notes
    assert "情景点估计" in notes


def test_no_markdown_asterisks_in_notes():
    """notes 在界面上是纯文本 li，带 ** 会原样显示出来。"""
    for n in run(drawdown=-0.2)["notes"]:
        assert "**" not in n, n
