# -*- coding: utf-8 -*-
"""行业监控（B1）的测试：行业清单、监控列表、指数序列、行业事件。

全部离线：行业指数用假 Provider，规则用真实的 `ThresholdRule`。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.industry_service import IndustryService
from backend.app.application.monitoring_service import EventMonitor
from backend.app.domain.events import MarketEvent, ThresholdRule
from backend.app.domain.models import PriceRecord, PriceSeries
from backend.app.infrastructure.catalog import CsvStockCatalog
from backend.app.infrastructure.repositories.industry_watch_repository import (
    SqliteIndustryWatchRepository)


# ============================================================
# 1. 行业清单（用仓库里提交的 seed CSV）
# ============================================================
def test_catalog_lists_31_level1_industries():
    catalog = CsvStockCatalog()
    inds = catalog.industries()
    assert len(inds) == 31
    codes = {i["code"] for i in inds}
    assert "801010" in codes and "801780" in codes
    bank = catalog.industry("801780")
    assert bank["name"] == "银行"
    assert bank["stock_count"] > 0


def test_catalog_industry_lookup_by_name_and_unknown():
    catalog = CsvStockCatalog()
    assert catalog.industry("银行")["code"] == "801780"
    assert catalog.industry("不存在的行业") == {}
    assert catalog.industry_name("801780") == "银行"


# ============================================================
# 2. 监控列表仓储
# ============================================================
@pytest.fixture()
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.db")
    dbmod.init_schema(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


def test_watch_repository_roundtrip(con):
    repo = SqliteIndustryWatchRepository(con, log=None)
    assert repo.add("801780", "银行") is True
    assert repo.add("801780", "银行") is False          # 幂等
    assert repo.has("801780") is True
    assert repo.codes() == ["801780"]
    assert repo.count() == 1
    assert repo.remove("801780") is True
    assert repo.remove("801780") is False
    assert repo.count() == 0


def test_watch_repository_seed_defaults(con):
    repo = SqliteIndustryWatchRepository(con, log=None)
    n = repo.seed_defaults(CsvStockCatalog())
    assert n == 3
    assert repo.seed_defaults(CsvStockCatalog()) == 0   # 已有数据不重复 seed
    assert len(repo.codes()) == 3


# ============================================================
# 3. 服务：列表 / 加监控 / 序列 / 事件
# ============================================================
def _series(code="801780", closes=(100.0, 90.0, 89.0)):
    dates = ["2026-05-01", "2026-05-02", "2026-05-03"]
    return PriceSeries(code=code, source="industry_sw", adjust="none", records=[
        PriceRecord(code=code, date=d, open=c, high=c, low=c, close=c,
                    volume=1000.0, adjust="none", source="industry_sw")
        for d, c in zip(dates[:len(closes)], closes)])


class FakeProvider:
    def __init__(self, series=None, fail_codes=()):
        self.series = series or _series()
        self.fail_codes = set(fail_codes)
        self.calls = []

    def fetch(self, code, start, end, adjust="none"):
        self.calls.append(code)
        if code in self.fail_codes:
            raise RuntimeError("行业指数取数失败")
        return self.series


class FakeEventRepo:
    def __init__(self):
        self.saved = []

    def save_many(self, events):
        self.saved.extend(events)
        return len(events)


def build(con, provider=None, monitor=None):
    repo = SqliteIndustryWatchRepository(con, log=None)
    repo.seed_defaults(CsvStockCatalog())
    monitor = monitor or EventMonitor(None, rules=[ThresholdRule(drop=-0.05)],
                                      notice_rules=[], log=None)
    return IndustryService(repo, provider or FakeProvider(), monitor=monitor,
                           catalog=CsvStockCatalog(), log=None)


def test_list_marks_watched(con):
    svc = build(con)
    items = svc.list_all()
    assert len(items) == 31
    watched = {i["code"] for i in items if i["watched"]}
    assert watched == {"801780", "801120", "801080"}


def test_watch_and_unwatch(con):
    svc = build(con)
    assert svc.watch("801010")["name"] == "农林牧渔"
    assert "801010" in [w["code"] for w in svc.watched()]
    assert svc.unwatch("801010") is True
    assert "801010" not in [w["code"] for w in svc.watched()]
    with pytest.raises(ValueError, match="未知行业"):
        svc.watch("999999")


def test_series_payload(con):
    svc = build(con)
    body = svc.series("801780", days=365)
    assert body["name"] == "银行"
    assert len(body["points"]) == 3
    assert body["points"][0]["date"] == "2026-05-01"
    assert body["source"] == "industry_sw"


def test_scan_produces_industry_scoped_events(con):
    svc = build(con)      # 100 -> 90 = -10%，触发 -5% 阈值
    events = svc.scan("801780", days=365)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "price_drop"
    assert ev.scope == "industry"
    assert ev.code == "801780"
    assert ev.name == "银行"
    assert ev.value == pytest.approx(-0.1)


def test_scan_unknown_industry_raises(con):
    svc = build(con)
    with pytest.raises(ValueError):
        svc.scan("999999", days=365)


def test_refresh_persists_and_survives_failure(con):
    repo = FakeEventRepo()
    provider = FakeProvider(fail_codes={"801080"})
    svc = build(con, provider=provider)
    res = svc.refresh(days=365, event_repo=repo)
    assert res["scanned"] == 3
    assert res["events_detected"] == 2        # 银行 + 食品饮料 各 1 个（同一个假序列）
    assert res["events_saved"] == 2
    assert res["failed"] == ["801080"]        # 电子取数失败但不影响其它
    assert all(e.scope == "industry" for e in repo.saved)


# ============================================================
# 4. 通用：EventMonitor.evaluate_series 的 scope 标记
# ============================================================
def test_evaluate_series_defaults_to_stock_scope():
    monitor = EventMonitor(None, rules=[ThresholdRule(drop=-0.05)],
                           notice_rules=[], log=None)
    events = monitor.evaluate_series(_series(), name="银行")
    assert events[0].scope == "stock"


def test_evaluate_series_tags_scope():
    monitor = EventMonitor(None, rules=[ThresholdRule(drop=-0.05)],
                           notice_rules=[], log=None)
    events = monitor.evaluate_series(_series(), name="银行", scope="industry")
    assert events[0].scope == "industry"


def test_scope_survives_roundtrip():
    """scope 要能落库再读出来（否则行业事件会被当成个股事件）。"""
    import tempfile
    from backend.app.infrastructure.repositories.event_repository import (
        SqliteEventRepository)

    with tempfile.TemporaryDirectory() as d:
        con = dbmod.connect(Path(d) / "t.db")
        dbmod.init_schema(con)
        repo = SqliteEventRepository(con, log=None)
        ev = MarketEvent(code="801780", name="银行", event_type="price_drop",
                         trade_date="2026-05-02", detected_at="now",
                         severity="medium", value=-0.1, threshold=-0.05,
                         detail="跌 10%", rule_name="threshold",
                         scope="industry")
        repo.save_many([ev])
        got = repo.list_recent(limit=10, scope="industry")
        assert len(got) == 1 and got[0].scope == "industry"
        assert repo.list_recent(limit=10, scope="stock") == []
        con.close()
