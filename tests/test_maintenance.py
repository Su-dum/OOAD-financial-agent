# -*- coding: utf-8 -*-
"""保留策略、自选股、一键刷新的测试（全部离线）。

这三块直接决定「库会不会无限膨胀」和「用户要不要手动敲命令」，
所以必须有测试锁住行为。
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
from backend.app.domain.watchlist import WatchItem, Watchlist
from backend.app.infrastructure.repositories.event_repository import SqliteEventRepository
from backend.app.infrastructure.repositories.watchlist_repository import (
    SqliteWatchlistRepository)


def days_ago(n: int, with_time: bool = True) -> str:
    d = datetime.now() - timedelta(days=n)
    return d.strftime("%Y-%m-%d %H:%M:%S" if with_time else "%Y-%m-%d")


@pytest.fixture()
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.db")
    dbmod.init_schema(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


def insert_news(con, published_at, title="t", source="test"):
    con.execute("INSERT INTO news(source,title,content,published_at,url,content_hash,"
                "fetched_at) VALUES(?,?,?,?,?,?,?)",
                (source, title, "c", published_at, None, f"{title}-{published_at}",
                 published_at))
    con.commit()


# ============================================================
# 1. 保留策略
# ============================================================
def test_policy_cutoffs():
    p = RetentionPolicy(news_days=90, event_days=180)
    d = p.describe()
    assert d["news_days"] == 90 and d["event_days"] == 180
    # 新闻截断点应该是 90 天前
    assert d["news_cutoff"][:10] == days_ago(90, with_time=False)
    assert d["event_cutoff"][:10] == days_ago(180, with_time=False)


def test_prune_deletes_old_keeps_new(con):
    insert_news(con, days_ago(120), "old")
    insert_news(con, days_ago(30), "new")
    m = MaintenanceService(con, RetentionPolicy(news_days=90), log=None)
    res = m.prune(vacuum=False)
    assert res.news_deleted == 1
    titles = [r[0] for r in con.execute("SELECT title FROM news")]
    assert titles == ["new"]


def test_prune_cascades_news_stock(con):
    insert_news(con, days_ago(120), "old")
    nid = con.execute("SELECT id FROM news").fetchone()[0]
    con.execute("INSERT INTO news_stock(news_id,stock_code,stock_name,match_type,"
                "confidence) VALUES(?,?,?,?,?)", (nid, "600519", "贵州茅台", "name", 0.9))
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM news_stock").fetchone()[0] == 1

    MaintenanceService(con, RetentionPolicy(news_days=90), log=None).prune(vacuum=False)
    assert con.execute("SELECT COUNT(*) FROM news_stock").fetchone()[0] == 0


def test_prune_dry_run_does_not_delete(con):
    insert_news(con, days_ago(120), "old")
    m = MaintenanceService(con, RetentionPolicy(news_days=90), log=None)
    res = m.prune(dry_run=True)
    assert res.news_deleted == 1                     # 报告将删 1 条
    assert con.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 1   # 实际没删


def test_prune_respects_max_delete_guard(con):
    """配置错误（比如 news_days 写成 0）时不能把库删空。"""
    for i in range(5):
        insert_news(con, days_ago(10), f"t{i}")
    m = MaintenanceService(con, RetentionPolicy(news_days=30, max_delete=2), log=None)
    res = m.prune(vacuum=False)
    assert res.news_deleted == 0
    assert con.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 5


def test_prune_deletes_old_events(con):
    con.execute("INSERT INTO event(code,name,event_type,trade_date,detected_at,severity,"
                "value,threshold,detail,rule_name) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("600519", "茅台", "price_drop", days_ago(200, False), "now",
                 "high", -0.08, -0.05, "旧事件", "r"))
    con.execute("INSERT INTO event(code,name,event_type,trade_date,detected_at,severity,"
                "value,threshold,detail,rule_name) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("600519", "茅台", "price_drop", days_ago(10, False), "now",
                 "high", -0.08, -0.05, "新事件", "r2"))
    con.commit()
    res = MaintenanceService(con, RetentionPolicy(event_days=180), log=None).prune(vacuum=False)
    assert res.events_deleted == 1
    assert [r[0] for r in con.execute("SELECT detail FROM event")] == ["新事件"]


# ============================================================
# 2. 自选股
# ============================================================
def test_watchlist_add_dedupe_remove():
    wl = Watchlist()
    assert wl.add("600519", name="贵州茅台") is True
    assert wl.add("600519") is False                 # 幂等
    assert len(wl) == 1
    assert wl.has("600519.SH") is True               # 兼容带后缀
    assert wl.remove("600519") is True
    assert wl.remove("600519") is False
    assert len(wl) == 0


def test_watchlist_extend_with_catalog():
    class Cat:
        def name_of(self, c): return {"600519": "贵州茅台"}.get(c, "")
        def industry_of(self, c): return {"600519": "食品饮料"}.get(c, "")

    wl = Watchlist()
    n = wl.extend(["600519", "000001", "600519"], catalog=Cat())
    assert n == 2                                    # 去重后新增 2 条
    assert wl.get("600519").industry == "食品饮料"
    assert wl.codes == ["600519", "000001"]


def test_watchlist_repository_roundtrip(con):
    repo = SqliteWatchlistRepository(con, log=None)
    repo.save_item(WatchItem(code="600519", name="贵州茅台", industry="食品饮料",
                             added_at=days_ago(0)))
    wl = repo.load()
    assert len(wl) == 1 and wl.get("600519").name == "贵州茅台"
    assert repo.delete("600519") is True
    assert len(repo.load()) == 0


def test_watchlist_seed_defaults_only_when_empty(con):
    repo = SqliteWatchlistRepository(con, log=None)
    n1 = repo.seed_defaults()
    assert n1 > 0
    n2 = repo.seed_defaults()                        # 已有数据，不再 seed
    assert n2 == 0


# ============================================================
# 3. 一键刷新编排
# ============================================================
class FakeNewsService:
    def __init__(self):
        self.em_calls = 0
        self.snapshot_calls = 0

    def backfill_em(self, **kw):
        self.em_calls += 1
        return IngestStats(source="东财", fetched=10, inserted=3, skipped=7,
                           pages=1, stopped_by="known")

    def collect_latest(self):
        self.snapshot_calls += 1
        return [IngestStats(source="快讯", fetched=5, inserted=2, stopped_by="snapshot")]


class FakeMonitor:
    def __init__(self, events_per_stock=2, fail_on=()):
        self.n = events_per_stock
        self.fail_on = set(fail_on)
        self.scanned = []

    def scan(self, code, start, end, source=None):
        self.scanned.append(code)
        if code in self.fail_on:
            raise RuntimeError("行情获取失败")
        return [MarketEvent(code=code, name="x", event_type="price_drop",
                            trade_date=days_ago(5, False), detected_at="now",
                            severity="high", value=-0.09, threshold=-0.05,
                            detail="跌", rule_name=f"r{i}")
                for i in range(self.n)]


def test_refresh_orchestrates_all_steps(con):
    repo = SqliteWatchlistRepository(con, log=None)
    repo.seed_defaults()
    news = FakeNewsService()
    monitor = FakeMonitor()
    ev_repo = SqliteEventRepository(con, log=None)
    maint = MaintenanceService(con, RetentionPolicy(news_days=90), log=None)

    svc = RefreshService(news=news, monitor=monitor, event_repo=ev_repo,
                         watchlist_repo=repo, maintenance=maint, con=con, log=None)
    res = svc.run(news_days=1, max_pages=2, detect_days=30)

    # 新闻两步都跑了
    assert news.em_calls == 1 and news.snapshot_calls == 1
    assert len(res.news) == 2
    # 每只自选股都扫了，事件落库
    assert res.stocks_scanned == len(repo.load())
    assert res.events_detected == res.stocks_scanned * 2
    assert res.events_saved > 0
    assert con.execute("SELECT COUNT(*) FROM event").fetchone()[0] > 0
    # 清理也执行了
    assert "freed_rows" in res.prune


def test_refresh_survives_failing_stock(con):
    repo = SqliteWatchlistRepository(con, log=None)
    repo.seed_defaults()
    monitor = FakeMonitor(fail_on={"600519"})
    svc = RefreshService(news=FakeNewsService(), monitor=monitor,
                         event_repo=SqliteEventRepository(con, log=None),
                         watchlist_repo=repo,
                         maintenance=MaintenanceService(con, log=None),
                         con=con, log=None)
    res = svc.run(news_days=1, max_pages=1)
    assert "600519" in res.failed_stocks
    assert res.stocks_scanned == len(repo.load()) - 1     # 其余股票仍被扫描
    assert res.note                                          # 有提示


def test_refresh_triggers_prune(con):
    """刷新应当顺手裁掉过期数据（防止无限增长）。"""
    insert_news(con, days_ago(200), "very-old")
    repo = SqliteWatchlistRepository(con, log=None)
    repo.seed_defaults()
    svc = RefreshService(news=FakeNewsService(), monitor=FakeMonitor(0),
                         event_repo=SqliteEventRepository(con, log=None),
                         watchlist_repo=repo,
                         maintenance=MaintenanceService(con, RetentionPolicy(news_days=90),
                                                        log=None),
                         con=con, log=None)
    res = svc.run(news_days=1, max_pages=1, prune=True)
    assert res.prune["news_deleted"] == 1
    assert con.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 0
