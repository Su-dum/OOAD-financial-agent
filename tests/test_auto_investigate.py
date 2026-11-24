# -*- coding: utf-8 -*-
"""B3「检测到事件后自动调查」的测试。

验证四件事：
  1. 只查高等级事件（阈值可配），且每次有条数上限
  2. 同一 (code, 事件日, 事件类型) 只查一次（去重）
  3. 单个事件调查失败不影响刷新整体
  4. 自动报告带 `auto=True` 标记，与用户手动调查区分
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.maintenance_service import (MaintenanceService,
                                                        RetentionPolicy)
from backend.app.application.news_service import IngestStats
from backend.app.application.refresh_service import RefreshService
from backend.app.domain.events import MarketEvent
from backend.app.domain.investigation import InvestigationReport
from backend.app.infrastructure.repositories.event_repository import (
    SqliteEventRepository)
from backend.app.infrastructure.repositories.watchlist_repository import (
    SqliteWatchlistRepository)


class FakeNews:
    def backfill_em(self, **kw):
        return IngestStats(source="东财", fetched=3, inserted=1, stopped_by="known")

    def collect_latest(self):
        return [IngestStats(source="快照", fetched=1, inserted=1,
                            stopped_by="snapshot")]


class FakeMonitor:
    def __init__(self, events):
        self.events = events

    def scan(self, code, start, end, source=None, **kw):
        return [e for e in self.events if e.code == code]


class FakeReportRepo:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.saved = []
        self._id = 100

    def has_event(self, code, event_date, event_type):
        return (code, event_date, event_type) in self.existing

    def save(self, report):
        self._id += 1
        self.saved.append(report)
        return self._id


class FakeAgent:
    def __init__(self, fail_on=(), auto_raises=False):
        self.calls = []
        self.fail_on = set(fail_on)

    def investigate(self, event, days=7, question=""):
        self.calls.append((event.code, event.trade_date, event.event_type))
        if event.event_type in self.fail_on:
            raise RuntimeError("调查工具全挂了")
        return InvestigationReport(code=event.code, name=event.name, event=event,
                                   question=f"自动调查 {event.event_type}",
                                   conclusion="模板结论", confidence=0.3)


def event(code="600519", event_type="price_drop", severity="high", days_ago=1):
    d = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return MarketEvent(code=code, name="贵州茅台", event_type=event_type,
                       trade_date=d, detected_at="now", severity=severity,
                       value=-0.08, threshold=-0.05, detail="单日下跌 8%",
                       rule_name="threshold")


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
def wl(con):
    repo = SqliteWatchlistRepository(con, log=None)
    repo.seed_defaults()
    return repo


def build(con, wl, events, agent, report_repo=None, **kw):
    return RefreshService(
        news=FakeNews(), monitor=FakeMonitor(events),
        event_repo=SqliteEventRepository(con, log=None),
        watchlist_repo=wl,
        maintenance=MaintenanceService(con, RetentionPolicy(), log=None),
        con=con, agent=agent, report_repo=report_repo or FakeReportRepo(),
        log=None, **kw)


def test_auto_investigate_high_severity(con, wl):
    agent = FakeAgent()
    reports = FakeReportRepo()
    svc = build(con, wl, [event()], agent, reports)
    res = svc.run(news_days=1, max_pages=1, prune=False,
                  include_notices=False, include_financials=False)
    assert len(agent.calls) == 1
    assert len(res.auto_reports) == 1
    assert res.auto_reports[0]["code"] == "600519"
    assert res.auto_reports[0]["severity"] == "high"
    # 自动报告打了标记，前端/报告页可以与手动调查区分
    assert reports.saved[0].llm_meta.get("auto") is True
    assert "自动生成 1 份调查报告" in res.note


def test_auto_investigate_can_be_disabled(con, wl):
    agent = FakeAgent()
    svc = build(con, wl, [event()], agent)
    res = svc.run(news_days=1, max_pages=1, prune=False,
                  include_notices=False, include_financials=False,
                  auto_investigate=False)
    assert agent.calls == []
    assert res.auto_reports == []


def test_auto_investigate_skips_medium_when_threshold_is_high(con, wl):
    agent = FakeAgent()
    svc = build(con, wl, [event(severity="medium")], agent)
    res = svc.run(news_days=1, max_pages=1, prune=False,
                  include_notices=False, include_financials=False)
    assert agent.calls == []
    assert res.auto_reports == []


def test_auto_investigate_respects_min_severity_option(con, wl):
    agent = FakeAgent()
    svc = build(con, wl, [event(severity="medium")], agent,
                auto_min_severity="medium")
    svc.run(news_days=1, max_pages=1, prune=False,
            include_notices=False, include_financials=False)
    assert len(agent.calls) == 1


def test_auto_investigate_respects_max_reports(con, wl):
    agent = FakeAgent()
    events = [event(event_type=t, days_ago=i)
              for i, t in enumerate(("price_drop", "price_surge", "zscore_return"),
                                     start=1)]
    svc = build(con, wl, events, agent, max_auto_reports=1)
    res = svc.run(news_days=1, max_pages=1, prune=False,
                  include_notices=False, include_financials=False)
    assert len(agent.calls) == 1
    assert len(res.auto_reports) == 1


def test_auto_investigate_dedupes_by_event(con, wl):
    ev = event()
    reports = FakeReportRepo(existing={(ev.code, ev.trade_date, ev.event_type)})
    agent = FakeAgent()
    svc = build(con, wl, [ev], agent, reports)
    svc.run(news_days=1, max_pages=1, prune=False,
            include_notices=False, include_financials=False)
    assert agent.calls == []          # 已经调查过，不再重复
    assert reports.saved == []


def test_auto_investigate_failure_does_not_break_refresh(con, wl):
    agent = FakeAgent(fail_on={"price_drop"})
    reports = FakeReportRepo()
    svc = build(con, wl, [event()], agent, reports)
    res = svc.run(news_days=1, max_pages=1, prune=False,
                  include_notices=False, include_financials=False)
    assert len(res.auto_reports) == 0
    assert len(res.auto_failed) == 1
    assert "自动调查失败" in res.note
    assert res.elapsed_sec >= 0        # 刷新本身正常结束


def test_auto_investigate_without_agent_is_noop(con, wl):
    svc = RefreshService(
        news=FakeNews(), monitor=FakeMonitor([event()]),
        event_repo=SqliteEventRepository(con, log=None), watchlist_repo=wl,
        maintenance=MaintenanceService(con, RetentionPolicy(), log=None),
        con=con, agent=None, report_repo=None, log=None)
    res = svc.run(news_days=1, max_pages=1, prune=False,
                  include_notices=False, include_financials=False)
    assert res.auto_reports == [] and res.auto_failed == []
