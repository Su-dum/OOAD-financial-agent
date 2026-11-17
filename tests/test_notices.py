# -*- coding: utf-8 -*-
"""公告事件（B2 的 earnings announcements / major corporate events）测试。

全部离线：
  分类器是纯函数（`domain/notices.py`）
  规则只吃 list[dict]（`domain/events.py:NoticeEventRule`）
  仓储跑在 tmp_path 的临时库上
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.monitoring_service import EventMonitor
from backend.app.domain.events import MarketEvent, NoticeEventRule, NoticeRule
from backend.app.domain.notices import (CATEGORIES, classify_notice, clean_title,
                                        material_categories)
from backend.app.infrastructure.repositories.notice_repository import (
    SqliteNoticeRepository)


def notice(title="", notice_type="", published_at="2026-08-15", url=None,
           code="600519", source="eastmoney"):
    return dict(code=code, name="贵州茅台", title=title,
                notice_type=notice_type, published_at=published_at,
                url=url, source=source)


# ============================================================
# 1. 分类器：87 种公告类型 -> 有限事件类别
# ============================================================
@pytest.mark.parametrize("notice_type,title,expected", [
    ("半年度报告摘要", "贵州茅台:2026年半年度报告摘要", "earnings"),
    ("业绩预告", "2026年半年度业绩预告", "earnings"),
    ("分配方案实施", "2025年年度权益分派实施公告", "dividend"),
    ("回购进展情况", "关于回购股份的进展公告", "buyback"),
    ("股东/实际控制人股份增持", "关于股东增持公司股份的公告", "insider_increase"),
    ("权益变动报告书", "关于股东减持股份的公告", "insider_decrease"),
    ("股权转让", "关于股权转让暨关联交易的公告", "major_deal"),
    ("澄清公告", "股票交易异常波动澄清公告", "clarification"),
    ("上交所股票监管工作函", "关于收到上交所监管工作函的公告", "regulatory"),
    ("法律意见书", "2026年第一次临时股东大会法律意见书", "procedural"),
    ("其他", "关于会计政策变更的公告", "procedural"),
])
def test_classify_covers_documented_types(notice_type, title, expected):
    cat = classify_notice(notice_type, title)
    assert cat is not None, (notice_type, title)
    assert cat.key == expected


def test_classify_falls_back_to_title_when_type_is_noise_bucket():
    """东财实测 229 条类型是「股票」、110 条是「其他」——真信号只在标题里。"""
    cat = classify_notice("其他", "关于以集中竞价方式回购股份的公告")
    assert cat is not None and cat.key == "buyback"

    cat = classify_notice("股票", "2026年半年度报告")
    assert cat is not None and cat.key == "earnings"


def test_classify_empty_returns_none():
    assert classify_notice("", "") is None


def test_material_categories_exclude_procedural():
    keys = {c.key for c in material_categories()}
    assert "procedural" not in keys
    assert {"earnings", "dividend", "buyback", "clarification"} <= keys


def test_hard_noise_beats_keyword_matches():
    """制度文件里会出现「关联交易」这类词，但它不是交易事件。"""
    cat = classify_notice("其他", "关联交易决策管理制度（2025年11月修订）")
    assert cat.key == "procedural" and cat.material is False

    cat = classify_notice("", "关于修订《回购股份管理办法》的公告")
    assert cat.key == "procedural"


def test_all_event_types_are_unique():
    types = [c.event_type for c in CATEGORIES]
    assert len(types) == len(set(types))
    assert all(t.startswith("notice_") for t in types)


def test_categories_are_hashable_and_ordered():
    """类别是 frozen dataclass，可以作为分组键。"""
    cat = classify_notice("", "澄清公告")
    assert {cat: 1}[cat] == 1
    # 澄清优先于其它类别：标题里同时出现「澄清」与「回购」时按澄清算
    assert classify_notice("", "关于回购股份的澄清公告").key == "clarification"


# ============================================================
# 1.5 标题清洗：去掉「名称:标题」前缀
# ============================================================
@pytest.mark.parametrize("raw,name,expected", [
    ("贵州茅台:贵州茅台2026年第三季度报告", "贵州茅台", "2026年第三季度报告"),
    ("贵州茅台:关于回购股份实施结果的公告", "贵州茅台", "关于回购股份实施结果的公告"),
    ("贵州茅台:贵州茅台:公告标题", "贵州茅台", "公告标题"),
    ("关于回购股份的公告", "", "关于回购股份的公告"),
    # 保守：冒号前不是股票简称、后面也不是同一段文字时不动
    ("关于XX:YY的公告", "", "关于XX:YY的公告"),
])
def test_clean_title(raw, name, expected):
    assert clean_title(raw, name) == expected


def test_repository_stores_clean_titles(con):
    repo = SqliteNoticeRepository(con, log=None)
    repo.save_many([notice("贵州茅台:贵州茅台2026年第三季度报告", "三季度报告全文")])
    (row,) = repo.find_by_stock("600519")
    assert row["title"] == "2026年第三季度报告"


# ============================================================
# 2. NoticeEventRule：公告 -> 事件
# ============================================================
def test_rule_emits_event_per_category_per_day():
    rows = [
        notice("2026年半年度报告", "半年度报告全文"),
        notice("2026年半年度报告摘要", "半年度报告摘要"),
        notice("关于回购股份的进展公告", "回购进展情况"),
    ]
    events = NoticeEventRule().evaluate(rows, code="600519", name="贵州茅台")
    by_type = {e.event_type: e for e in events}
    assert set(by_type) == {"notice_earnings", "notice_buyback"}
    # 同一天同类的两条财报公告合并成一条，数量写进 value
    assert by_type["notice_earnings"].value == 2
    assert "共 2 条" in by_type["notice_earnings"].detail
    assert all(isinstance(e, MarketEvent) for e in events)


def test_rule_ignores_procedural_notices():
    rows = [
        notice("2026年第一次临时股东大会法律意见书", "法律意见书"),
        notice("公司章程修订", "公司章程"),
        notice("关于召开2026年半年度业绩说明会的公告", "其他"),
    ]
    assert NoticeEventRule().evaluate(rows) == []


def test_rule_sets_severity_and_source_url():
    rows = [notice("股票交易异常波动澄清公告", "澄清公告",
                   url="http://www.cninfo.com.cn/new/disclosure/detail?x=1")]
    (ev,) = NoticeEventRule().evaluate(rows)
    assert ev.event_type == "notice_clarification"
    assert ev.severity == "high"
    assert ev.source_url.startswith("http://www.cninfo.com.cn")
    assert ev.trade_date == "2026-08-15"
    assert ev.rule_name == "notice_event"
    # 事件对外展示的是中文名，不是内部标识
    assert ev.label == "异动澄清"
    assert ev.to_dict()["label"] == "异动澄清"
    assert "异动澄清" in ev.describe()


def test_rule_severity_filter():
    rows = [notice("分配方案实施", "分配方案实施"),
            notice("收到监管工作函", "上交所股票监管工作函")]
    assert len(NoticeEventRule().evaluate(rows)) == 2
    only_high = NoticeEventRule(min_severity="high").evaluate(rows)
    assert [e.event_type for e in only_high] == ["notice_regulatory"]


def test_rule_include_exclude():
    rows = [notice("2026年半年度报告", "半年度报告全文"),
            notice("关于回购股份的进展公告", "回购进展情况")]
    only_buyback = NoticeEventRule(include=["buyback"]).evaluate(rows)
    assert [e.event_type for e in only_buyback] == ["notice_buyback"]
    no_buyback = NoticeEventRule(exclude=["buyback"]).evaluate(rows)
    assert [e.event_type for e in no_buyback] == ["notice_earnings"]


def test_rule_can_be_disabled_and_is_polymorphic():
    rule = NoticeEventRule(enabled=False)
    assert isinstance(rule, NoticeRule)
    assert rule.evaluate([notice("2026年半年度报告", "半年度报告全文")]) == []


def test_rule_skips_rows_without_date():
    rows = [notice("2026年半年度报告", "半年度报告全文", published_at="")]
    assert NoticeEventRule().evaluate(rows) == []


def test_rule_sorted_by_date_desc():
    rows = [notice("2026年半年度报告", "半年度报告全文", published_at="2026-08-15"),
            notice("2026年一季度报告全文", "一季度报告全文", published_at="2026-04-25")]
    events = NoticeEventRule().evaluate(rows)
    assert [e.trade_date for e in events] == ["2026-08-15", "2026-04-25"]


# ============================================================
# 3. EventMonitor：两条规则链并列，互不影响
# ============================================================
class FakeMarket:
    """行情永远拿不到——用来验证「行情挂了公告事件照样出」。"""

    def __init__(self, series=None):
        self._series = series

    def get_series(self, *a, **k):
        return self._series

    def name_of(self, code):
        return "贵州茅台"


class FakeNoticeRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def find_by_stock(self, code, start=None, end=None, limit=200):
        self.calls += 1
        return [r for r in self.rows if r["code"] == code][:limit]

    def save_many(self, items):
        return len(items)


def test_monitor_emits_notice_events_even_without_price_data():
    repo = FakeNoticeRepo([notice("2026年半年度报告", "半年度报告全文")])
    monitor = EventMonitor(FakeMarket(series=None), rules=[],
                           notice_rules=[NoticeEventRule()], notices=repo,
                           log=None)
    events = monitor.scan("600519", "2026-01-01", "2026-12-31")
    assert len(events) == 1
    assert events[0].event_type == "notice_earnings"
    assert repo.calls == 1


def test_monitor_without_notice_repo_only_runs_price_rules():
    monitor = EventMonitor(FakeMarket(series=None), rules=[],
                           notice_rules=[NoticeEventRule()], notices=None,
                           log=None)
    assert monitor.scan("600519", "2026-01-01", "2026-12-31") == []


def test_monitor_include_notices_switch():
    repo = FakeNoticeRepo([notice("2026年半年度报告", "半年度报告全文")])
    monitor = EventMonitor(FakeMarket(series=None), rules=[],
                           notice_rules=[NoticeEventRule()], notices=repo,
                           log=None)
    assert monitor.scan("600519", "2026-01-01", "2026-12-31",
                        include_notices=False) == []
    assert repo.calls == 0


def test_monitor_survives_broken_notice_repo():
    class Boom:
        def find_by_stock(self, *a, **k):
            raise RuntimeError("库坏了")

    monitor = EventMonitor(FakeMarket(series=None), rules=[],
                           notice_rules=[NoticeEventRule()], notices=Boom(),
                           log=None)
    assert monitor.scan("600519", "2026-01-01", "2026-12-31") == []


# ============================================================
# 4. 仓储：落库、去重、按区间查询
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


def test_notice_repository_roundtrip(con):
    repo = SqliteNoticeRepository(con, log=None)
    rows = [notice("2026年半年度报告", "半年度报告全文", url="http://a"),
            notice("关于回购股份的进展公告", "回购进展情况")]
    assert repo.save_many(rows) == 2
    assert repo.count("600519") == 2
    # 重复写入不会产生新行（UNIQUE(code,title,published_at)）
    assert repo.save_many(rows) == 0
    assert repo.count("600519") == 2

    got = repo.find_by_stock("600519", start="2026-08-01", end="2026-08-31")
    assert len(got) == 2
    by_title = {r["title"]: r for r in got}
    assert by_title["2026年半年度报告"]["notice_type"] == "半年度报告全文"
    assert by_title["2026年半年度报告"]["url"] == "http://a"
    assert all(r["published_at"] == "2026-08-15" for r in got)
    assert repo.latest_date("600519") == "2026-08-15"


def test_notice_repository_filters_range(con):
    repo = SqliteNoticeRepository(con, log=None)
    repo.save_many([notice("旧公告", published_at="2025-01-10"),
                    notice("新公告", published_at="2026-08-15")])
    assert len(repo.find_by_stock("600519", start="2026-01-01")) == 1
    assert len(repo.find_by_stock("600519", end="2025-12-31")) == 1
    assert repo.stats()["notices"] == 2


def test_notice_repository_skips_invalid_rows(con):
    repo = SqliteNoticeRepository(con, log=None)
    assert repo.save_many([dict(code="600519", title="", published_at="2026-08-15"),
                           dict(code="", title="x", published_at="2026-08-15")]) == 0


def test_migration_adds_source_url_to_old_event_table():
    """老库的 event 表没有 source_url，init_schema 必须能补上（幂等）。"""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE event (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
            name TEXT, event_type TEXT NOT NULL, trade_date TEXT NOT NULL,
            detected_at TEXT NOT NULL, severity TEXT, value REAL,
            threshold REAL, detail TEXT, rule_name TEXT,
            UNIQUE(code, event_type, trade_date, rule_name));
    """)
    assert "source_url" not in [r[1] for r in con.execute("PRAGMA table_info(event)")]
    dbmod.migrate(con)
    assert "source_url" in [r[1] for r in con.execute("PRAGMA table_info(event)")]
    assert dbmod.migrate(con) == 0        # 幂等
    con.close()

def test_investigation_fact_does_not_duplicate_event_label():
    """公告事件的 detail 已含类别，事实行不能再拼一次「财报披露：」。"""
    from backend.app.application.investigation_service import InvestigationAgent

    (ev,) = NoticeEventRule().evaluate(
        [notice("2026年第三季度报告", "三季度报告全文")], code="600519",
        name="贵州茅台")
    agent = InvestigationAgent([], llm=None, log=None)
    report = agent.investigate(ev, days=7)
    assert report.facts[0] == "2026-08-15 财报披露：2026年第三季度报告"
    assert "财报披露：财报披露" not in report.facts[0]
