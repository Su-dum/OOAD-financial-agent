# -*- coding: utf-8 -*-
"""预警规则配置（C1）的测试。

要点：
  1. 默认值 -> 全局覆盖 -> 个股覆盖 的三级合并；
  2. 参数越界必须**拒绝**而不是静默钳制（否则用户以为改了、其实没改）；
  3. 配置真的能改变检测行为（不是存了不用）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.alert_config_service import (DEFAULT_RULES,
                                                          AlertConfigService)
from backend.app.application.monitoring_service import EventMonitor
from backend.app.domain.events import MarketEvent, ThresholdRule
from backend.app.domain.models import PriceRecord, PriceSeries
from backend.app.infrastructure.repositories.alert_rule_repository import (
    SqliteAlertRuleRepository)


@pytest.fixture()
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.db")
    dbmod.init_schema(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


@pytest.fixture()
def svc(con):
    return AlertConfigService(SqliteAlertRuleRepository(con, log=None), log=None)


# ============================================================
# 1. 默认配置
# ============================================================
def test_defaults_describe_all_rules(svc):
    items = {it["rule_type"]: it for it in svc.describe("600519")}
    assert set(items) == set(DEFAULT_RULES)
    assert items["threshold_pct_change"]["params"] == {"drop": -0.05, "surge": 0.05}
    assert all(it["source"] == "default" for it in items.values())
    assert items["threshold_pct_change"]["label"]


def test_default_service_without_repo_still_works():
    svc = AlertConfigService(repo=None, log=None)
    assert svc.effective("600519")["zscore"]["params"]["z"] == 3.0
    price_rules, notice_rules = svc.for_code("600519")
    assert len(price_rules) == 3 and len(notice_rules) == 1


# ============================================================
# 2. 两级覆盖
# ============================================================
def test_global_override_applies_to_all_codes(svc):
    svc.update("threshold_pct_change", {"drop": -0.03})
    assert svc.effective("600519")["threshold_pct_change"]["params"]["drop"] == -0.03
    assert svc.effective("000001")["threshold_pct_change"]["params"]["drop"] == -0.03
    assert svc.effective("600519")["threshold_pct_change"]["source"] == "global"


def test_code_override_beats_global_and_isolated(svc):
    svc.update("threshold_pct_change", {"drop": -0.03})                 # 全局
    svc.update("threshold_pct_change", {"drop": -0.02}, code="600519")  # 个股
    assert svc.effective("600519")["threshold_pct_change"]["params"]["drop"] == -0.02
    assert svc.effective("600519")["threshold_pct_change"]["source"] == "code"
    assert svc.effective("000001")["threshold_pct_change"]["params"]["drop"] == -0.03


def test_partial_update_keeps_other_params(svc):
    svc.update("threshold_pct_change", {"drop": -0.02}, code="600519")
    params = svc.effective("600519")["threshold_pct_change"]["params"]
    assert params == {"drop": -0.02, "surge": 0.05}      # surge 保持默认


def test_disable_rule(svc):
    svc.update("volume_spike", {}, code="600519", enabled=False)
    assert svc.effective("600519")["volume_spike"]["enabled"] is False
    names = [r.name for r in svc.build_price_rules("600519")]
    assert "volume_spike" not in names
    assert "threshold_pct_change" in names


def test_reset_returns_to_default(svc):
    svc.update("threshold_pct_change", {"drop": -0.02}, code="600519")
    assert svc.reset("threshold_pct_change", code="600519") == 1
    assert svc.effective("600519")["threshold_pct_change"]["source"] == "default"
    assert svc.reset("threshold_pct_change", code="600519") == 0


def test_reset_all_overrides(svc):
    svc.update("threshold_pct_change", {"drop": -0.03})
    svc.update("zscore", {"z": 2.0}, code="600519")
    assert svc.reset(code="600519") >= 1


# ============================================================
# 3. 校验：不合法的配置必须被拒绝
# ============================================================
def test_unknown_rule_type_rejected(svc):
    with pytest.raises(ValueError, match="未知规则类型"):
        svc.update("no_such_rule", {})


def test_unknown_param_rejected(svc):
    with pytest.raises(ValueError, match="不认识的参数"):
        svc.update("threshold_pct_change", {"foo": 1})


@pytest.mark.parametrize("params", [
    {"drop": 0.05},          # 正数：跌阈值不能是正
    {"drop": -0.9},          # 越界
    {"surge": -0.02},        # 涨阈值不能是负
    {"drop": "abc"},         # 类型错
    {"drop": True},          # bool 不是合法数字
])
def test_invalid_threshold_rejected(svc, params):
    with pytest.raises(ValueError):
        svc.update("threshold_pct_change", params)


def test_invalid_zscore_rejected(svc):
    with pytest.raises(ValueError):
        svc.update("zscore", {"z": 0.5})
    with pytest.raises(ValueError):
        svc.update("zscore", {"window": 5000})


def test_invalid_severity_rejected(svc):
    with pytest.raises(ValueError):
        svc.update("notice_event", {"min_severity": "critical"})


def test_notice_include_exclude_accepted(svc):
    item = svc.update("notice_event", {"min_severity": "medium",
                                       "include": ["earnings", "buyback"],
                                       "exclude": ["regulatory"]})
    assert item["params"]["min_severity"] == "medium"
    assert item["params"]["include"] == ["earnings", "buyback"]
    (rule,) = svc.build_notice_rules()
    assert rule.min_severity == "medium"
    assert rule.include == {"earnings", "buyback"}


# ============================================================
# 4. 配置真的改变检测行为
# ============================================================
def make_series(closes=(100.0, 97.0, 94.0)):
    dates = [f"2026-05-0{i+1}" for i in range(len(closes))]
    return PriceSeries(code="600519", source="fake", records=[
        PriceRecord(code="600519", date=d, open=c, high=c, low=c, close=c,
                    volume=1000.0)
        for d, c in zip(dates, closes)])


class StubMarket:
    def __init__(self, series):
        self.series = series

    def get_series(self, *a, **k):
        return self.series

    def name_of(self, code):
        return "贵州茅台"


def test_rulebook_changes_monitor_behaviour(con):
    """出厂阈值 5% 抓不到 -3% 的下跌；把阈值改成 2% 后就能抓到。"""
    repo = SqliteAlertRuleRepository(con, log=None)
    svc = AlertConfigService(repo, log=None)
    market = StubMarket(make_series())          # 100 -> 97 -> 94，每日 -3%

    strict = EventMonitor(market, rules=[ThresholdRule(drop=-0.05, surge=0.05)],
                          notice_rules=[], log=None)
    assert strict.scan("600519", "2026-05-01", "2026-05-30") == []

    svc.update("threshold_pct_change", {"drop": -0.02}, code="600519")
    loose = EventMonitor(market, rules=[], notice_rules=[], rulebook=svc, log=None)
    events = loose.scan("600519", "2026-05-01", "2026-05-30")
    assert len(events) == 2
    assert all(ev.event_type == "price_drop" for ev in events)
    # 个股覆盖不影响别的票
    assert loose.scan("000001", "2026-05-01", "2026-05-30") == []


def test_broken_rulebook_falls_back_to_factory_rules():
    class Boom:
        def for_code(self, code):
            raise RuntimeError("配置坏了")

    market = StubMarket(make_series())
    monitor = EventMonitor(market, rules=[ThresholdRule(drop=-0.02)],
                           notice_rules=[], rulebook=Boom(), log=None)
    assert len(monitor.scan("600519", "2026-05-01", "2026-05-30")) == 2


def test_repository_upsert_is_idempotent(con):
    repo = SqliteAlertRuleRepository(con, log=None)
    repo.upsert("zscore", {"window": 60, "z": 2.5}, code="600519")
    repo.upsert("zscore", {"window": 60, "z": 2.0}, code="600519")
    assert repo.count() == 1
    (row,) = repo.load("600519")
    assert row["params"]["z"] == 2.0
    assert repo.delete("zscore", code="600519") is True
    assert repo.count() == 0
