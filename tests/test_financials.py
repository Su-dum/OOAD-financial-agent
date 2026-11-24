# -*- coding: utf-8 -*-
"""财务数据（A1）的测试：列名映射、快照仓储、TTL、与指标结果的优先级。

用 pandas 造一个「新浪财务指标」形状的 DataFrame，不联网。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.analysis_service import FinancialAnalyzer
from backend.app.application.financial_service import FinancialService
from backend.app.domain.financials import FinancialSnapshot, describe_fields
from backend.app.domain.models import PriceRecord, PriceSeries
from backend.app.infrastructure.providers.sina_financial_provider import (
    SinaFinancialProvider, parse_financial_frame)
from backend.app.infrastructure.repositories.financial_repository import (
    SqliteFinancialRepository)


def frame(rows=None):
    rows = rows or [
        {"日期": "2026-06-30", "净资产收益率(%)": 15.2, "净利润增长率(%)": 10.5,
         "主营业务收入增长率(%)": 8.1, "销售净利率(%)": 50.1,
         "销售毛利率(%)": 73.2, "资产负债率(%)": 12.3,
         "摊薄每股收益(元)": 30.5, "每股净资产_调整前(元)": 200.1},
        {"日期": "2026-09-30", "净资产收益率(%)": 23.77, "净利润增长率(%)": -0.2715,
         "主营业务收入增长率(%)": 1.9595, "销售净利率(%)": 50.94,
         "销售毛利率(%)": 73.718, "资产负债率(%)": 11.9016,
         "摊薄每股收益(元)": 53.37, "每股净资产_调整前(元)": 224.32},
    ]
    return pd.DataFrame(rows)


# ============================================================
# 1. 列名映射（纯函数）
# ============================================================
def test_parse_picks_latest_report():
    snap = parse_financial_frame(frame(), "600519")
    assert snap.report_date == "2026-09-30"
    assert snap.roe == pytest.approx(23.77)
    assert snap.net_profit_growth == pytest.approx(-0.2715)
    assert snap.revenue_growth == pytest.approx(1.9595)
    assert snap.net_margin == pytest.approx(50.94)
    assert snap.gross_margin == pytest.approx(73.718)
    assert snap.debt_ratio == pytest.approx(11.9016)
    assert snap.eps == pytest.approx(53.37)
    assert snap.bps == pytest.approx(224.32)
    assert snap.source == "sina_financial"


def test_parse_handles_nan_and_missing_columns():
    df = frame([
        {"日期": "2026-09-30", "净资产收益率(%)": float("nan"),
         "净利润增长率(%)": "-", "销售净利率(%)": 40.0},
    ])
    snap = parse_financial_frame(df, "600519")
    assert snap.roe is None                 # nan -> None
    assert snap.net_profit_growth is None  # "-" -> None
    assert snap.net_margin == pytest.approx(40.0)
    assert snap.eps is None                # 列不存在 -> None


def test_parse_empty_frame_returns_none():
    assert parse_financial_frame(None, "600519") is None
    assert parse_financial_frame(pd.DataFrame(), "600519") is None


def test_parse_unsorted_rows_still_picks_latest():
    rows = frame()
    shuffled = rows.iloc[[1, 0]].reset_index(drop=True)
    assert parse_financial_frame(shuffled, "600519").report_date == "2026-09-30"


def test_describe_fields_covers_all():
    fields = [f["field"] for f in describe_fields()]
    assert "roe" in fields and "eps" in fields
    assert all(f["label"] for f in describe_fields())


# ============================================================
# 2. 快照仓储
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


def snap(roe=23.77, report="2026-09-30", fetched=None):
    return FinancialSnapshot(
        code="600519", report_date=report, roe=roe, net_profit_growth=-0.27,
        revenue_growth=1.96, net_margin=50.94, gross_margin=73.72,
        debt_ratio=11.9, eps=53.37, bps=224.32, source="sina_financial",
        fetched_at=fetched or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def test_repository_upsert_and_get(con):
    repo = SqliteFinancialRepository(con, log=None)
    assert repo.get("600519") is None
    repo.upsert(snap())
    row = repo.get("600519")
    assert row["report_date"] == "2026-09-30"
    assert row["roe"] == pytest.approx(23.77)
    # 同一只票只保留一行（更新而不是新增）
    repo.upsert(snap(roe=25.0, report="2026-12-31"))
    assert repo.count() == 1
    assert repo.get("600519")["roe"] == pytest.approx(25.0)
    assert repo.stats()["latest_report"] == "2026-12-31"


# ============================================================
# 3. 服务：TTL 与降级
# ============================================================
class FakeProvider:
    name = "fake_financial"

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    def fetch(self, code, years=3):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def test_service_refresh_stores_snapshot(con):
    repo = SqliteFinancialRepository(con, log=None)
    svc = FinancialService(repo, FakeProvider(snap()), log=None)
    st = svc.refresh("600519")
    assert st.stopped_by == "ok" and st.updated is True
    assert repo.get("600519")["report_date"] == "2026-09-30"


def test_service_ensure_skips_when_fresh(con):
    repo = SqliteFinancialRepository(con, log=None)
    repo.upsert(snap(fetched=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    provider = FakeProvider(snap())
    svc = FinancialService(repo, provider, log=None, ttl_days=7)
    assert svc.is_stale("600519") is False
    svc.ensure("600519")
    assert provider.calls == 0           # 未过期，不请求


def test_service_ensure_refreshes_when_stale(con):
    repo = SqliteFinancialRepository(con, log=None)
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    repo.upsert(snap(fetched=old))
    provider = FakeProvider(snap(roe=30.0))
    svc = FinancialService(repo, provider, log=None, ttl_days=7)
    assert svc.is_stale("600519") is True
    svc.ensure("600519")
    assert provider.calls == 1
    assert repo.get("600519")["roe"] == pytest.approx(30.0)


def test_service_keeps_old_data_when_provider_fails(con):
    repo = SqliteFinancialRepository(con, log=None)
    repo.upsert(snap(roe=20.0, fetched="2020-01-01 00:00:00"))
    svc = FinancialService(repo, FakeProvider(exc=RuntimeError("boom")), log=None)
    st = svc.refresh("600519")
    assert st.stopped_by == "error"
    assert repo.get("600519")["roe"] == pytest.approx(20.0)   # 旧快照还在


def test_service_without_provider_is_graceful():
    svc = FinancialService(None, None, log=None)
    assert svc.get("600519") is None
    assert svc.refresh("600519").stopped_by == "no_provider"
    assert svc.ensure("600519") is None


# ============================================================
# 4. 指标集成：财务快照优先于申万静态快照
# ============================================================
class StubMarket:
    def __init__(self, meta):
        self._meta = meta

    def meta(self, code):
        return dict(self._meta)

    def name_of(self, code):
        return self._meta.get("name", "")

    def industry_of(self, code):
        return self._meta.get("industry_l1_name", "")


def make_series():
    dates = ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"]
    closes = [100.0, 101.0, 99.5, 102.0]
    return PriceSeries(code="600519", source="fake", records=[
        PriceRecord(code="600519", date=d, open=c, high=c, low=c, close=c,
                    volume=1000.0) for d, c in zip(dates, closes)])


META = dict(name="贵州茅台", industry_l1_name="食品饮料",
            roe="17.95", profit_growth="-1.95", revenue_growth="2.42",
            market_cap="2225.86")


def test_analyzer_prefers_financial_snapshot():
    market = StubMarket(META)
    financial = FinancialService(None, None, log=None)
    financial.get = lambda code: dict(snap().to_dict())     # type: ignore
    r = FinancialAnalyzer(market, financial=financial).from_series(make_series())
    assert r.roe == pytest.approx(23.77)                    # 财务快照优先
    assert r.profit_growth == pytest.approx(-0.27)
    assert r.net_margin == pytest.approx(50.94)
    assert r.financial_report_date == "2026-09-30"
    assert r.financial_source == "sina_financial"


def test_analyzer_falls_back_to_catalog():
    market = StubMarket(META)
    financial = FinancialService(None, None, log=None)
    r = FinancialAnalyzer(market, financial=financial).from_series(make_series())
    assert r.roe == pytest.approx(17.95)      # 没有快照 -> 用申万映射表
    assert r.profit_growth == pytest.approx(-1.95)
    assert r.net_margin is None
    assert r.financial_report_date is None


def test_analyzer_without_financial_service_still_works():
    r = FinancialAnalyzer(StubMarket(META)).from_series(make_series())
    assert r.roe == pytest.approx(17.95)
    assert r.market_cap == pytest.approx(2225.86)
