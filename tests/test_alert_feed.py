# -*- coding: utf-8 -*-
"""重大事件提醒（B3 的通知面）的测试。

核心是**过滤口径**：提醒按 `detected_at`（刚刚发现了什么）而不是 `trade_date`
（历史上哪天发生的）。一次刷新会把 180 天内的老事件全部重检，若按事件日过滤，
用户一开页面就会被历史事件糊满——这条必须被锁住。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.alert_feed_service import (AlertFeedService,
                                                        MAX_LOOKBACK_HOURS)
from backend.app.domain.events import MarketEvent
from backend.app.domain.investigation import InvestigationReport
from backend.app.infrastructure.repositories.event_repository import (
    SqliteEventRepository)
from backend.app.infrastructure.repositories.report_repository import (
    SqliteReportRepository)


@pytest.fixture()
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.db")
    dbmod.init_schema(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


def ts(delta_minutes: int = 0) -> str:
    return (datetime.now() + timedelta(minutes=delta_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S")


def ev(code="600519", name="贵州茅台", event_type="notice_earnings",
       trade_date="2026-10-31", severity="medium", scope="stock",
       detected_at=None):
    return MarketEvent(code=code, name=name, event_type=event_type,
                       trade_date=trade_date,
                       detected_at=detected_at or ts(0),
                       severity=severity, value=1.0, detail="财报披露：三季报",
                       rule_name="notice_event", scope=scope)


def build(con, min_severity="high"):
    return AlertFeedService(SqliteEventRepository(con, log=None),
                            SqliteReportRepository(con, log=None),
                            min_severity=min_severity, log=None), \
        SqliteEventRepository(con, log=None), SqliteReportRepository(con, log=None)


# ============================================================
# 1. 时间窗口
# ============================================================
def test_no_since_uses_floor_not_full_history(con):
    """不传 since 时只回看固定窗口，绝不返回全部历史。"""
    feed, evrepo, _ = build(con)
    out = feed.recent()
    expect = (datetime.now() - timedelta(hours=MAX_LOOKBACK_HOURS)).strftime(
        "%Y-%m-%d %H:%M")
    assert out["since"].startswith(expect)      # 秒级差允许
    assert out["since_clamped"] is False


def test_too_old_since_is_clamped(con):
    feed, _, _ = build(con)
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    out = feed.recent(since=old)
    assert out["since_clamped"] is True
    assert out["since"] > old


def test_recent_since_kept_as_is(con):
    feed, _, _ = build(con)
    s = ts(-5)
    out = feed.recent(since=s)
    assert out["since"] == s
    assert out["since_clamped"] is False


# ============================================================
# 2. 过滤口径：detected_at 而不是 trade_date
# ============================================================
def test_filters_by_detected_at_not_trade_date(con):
    """老事件（trade_date 很久以前）如果是**刚检测到**的，应该进提醒。"""
    feed, evrepo, _ = build(con, min_severity="high")
    evrepo.save_many([ev(trade_date="2025-01-02", severity="high",
                         detected_at=ts(-1))])
    out = feed.recent(since=ts(-10))
    assert out["count"] == 1
    assert out["items"][0]["trade_date"] == "2025-01-02"


def test_old_detection_excluded_by_since(con):
    """检测时间早于 since 的，不该重复弹。"""
    feed, evrepo, _ = build(con, min_severity="high")
    evrepo.save_many([ev(severity="high", detected_at=ts(-120))])
    out = feed.recent(since=ts(-10))
    assert out["count"] == 0


# ============================================================
# 3. 等级与 scope
# ============================================================
def test_min_severity_high_only(con):
    feed, evrepo, _ = build(con, min_severity="high")
    evrepo.save_many([
        ev(event_type="notice_earnings", severity="high"),
        ev(event_type="notice_dividend", severity="medium"),
        ev(event_type="notice_buyback", severity="low"),
    ])
    out = feed.recent(since=ts(-10), min_severity="high")
    assert out["count"] == 1
    assert out["items"][0]["severity"] == "high"


def test_min_severity_medium_includes_high(con):
    feed, evrepo, _ = build(con)
    evrepo.save_many([
        ev(event_type="notice_earnings", severity="high"),
        ev(event_type="notice_dividend", severity="medium"),
        ev(event_type="notice_buyback", severity="low"),
    ])
    out = feed.recent(since=ts(-10), min_severity="medium")
    assert {i["severity"] for i in out["items"]} == {"high", "medium"}


def test_industry_events_excluded(con):
    """提醒只针对个股：行业事件没有「公司」锚点，调查工具也接不上。"""
    feed, evrepo, _ = build(con, min_severity="high")
    evrepo.save_many([
        ev(code="600519", severity="high"),
        ev(code="801080", name="电子", severity="high", scope="industry"),
    ])
    out = feed.recent(since=ts(-10))
    assert [i["code"] for i in out["items"]] == ["600519"]


# ============================================================
# 4. 与 AI 报告的关联
# ============================================================
def _report(code="600519", event_date="2026-10-31",
            event_type="notice_earnings", auto=True, degraded=False,
            conclusion="本次事件属于财报披露 [1]。净利润同比增长 3.78% [2]。"):
    evt = MarketEvent(code=code, name="贵州茅台", event_type=event_type,
                      trade_date=event_date, detected_at=ts(0),
                      severity="high", detail="财报披露")
    r = InvestigationReport(code=code, name="贵州茅台", event=evt,
                            question="可能原因是什么？")
    r.conclusion = conclusion
    r.confidence = 0.42
    r.llm_meta = dict(provider="custom", model="deepseek-flash",
                      cited_evidence_ids=[1, 2], degraded=degraded, auto=auto)
    return r


def test_alert_without_report_not_ready(con):
    feed, evrepo, _ = build(con, min_severity="high")
    evrepo.save_many([ev(severity="high")])
    item = feed.recent(since=ts(-10))["items"][0]
    assert item["report_ready"] is False
    assert item["report_id"] is None
    assert item["headline"] == ""


def test_alert_with_report_carries_llm_meta(con):
    _, evrepo, reprepo = build(con)
    evrepo.save_many([ev(severity="high")])
    rid = reprepo.save(_report())

    feed = AlertFeedService(evrepo, reprepo, min_severity="high", log=None)
    item = feed.recent(since=ts(-10))["items"][0]
    assert item["report_ready"] is True
    assert item["report_id"] == rid
    assert item["llm_model"] == "deepseek-flash"
    assert item["confidence"] == pytest.approx(0.42)
    assert item["degraded"] is False
    # 提醒里只放第一句，不能整段塞进来
    assert item["headline"].endswith("。")
    assert "净利润" not in item["headline"]


def test_degraded_report_is_flagged(con):
    feed, evrepo, reprepo = build(con, min_severity="high")
    evrepo.save_many([ev(severity="high")])
    reprepo.save(_report(degraded=True))
    item = feed.recent(since=ts(-10))["items"][0]
    assert item["degraded"] is True


# ============================================================
# 5. 输出形状（前端依赖这些键）
# ============================================================
def test_item_shape_for_frontend(con):
    feed, evrepo, _ = build(con, min_severity="high")
    evrepo.save_many([ev(severity="high")])
    out = feed.recent(since=ts(-10))
    for key in ("count", "since", "since_clamped", "min_severity", "now", "items"):
        assert key in out
    item = out["items"][0]
    for key in ("code", "name", "event_type", "label", "trade_date", "detected_at",
                "severity", "detail", "report_id", "report_ready", "confidence",
                "headline", "llm_model", "degraded"):
        assert key in item, key
    # 中文事件名复用领域层，不能把 notice_earnings 这种内部标识给用户
    assert item["label"] == "财报披露"


def test_limit_respected(con):
    feed, evrepo, _ = build(con, min_severity="high")
    evrepo.save_many([
        ev(event_type=f"notice_t{i}", severity="high") for i in range(8)
    ])
    assert feed.recent(since=ts(-10), limit=3)["count"] == 3
