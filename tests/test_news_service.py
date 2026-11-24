# -*- coding: utf-8 -*-
"""新闻采集的边界测试（离线，用假数据源）。

这几条边界决定「一键更新」会不会卡死或无限翻页：
  - 翻到页数上限要正常停（stopped_by=max_pages）
  - 撞到已采过的页要提前停（stopped_by=known）
  - 越过时间边界要停（stopped_by=boundary）
  - 数据源报错要停且不抛异常（stopped_by=error）
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.application import news_service


class FakeRepo:
    def __init__(self, insert=True):
        self.insert = insert
        self.saved = []

    def save(self, rows):
        self.saved.extend(rows)
        return (len(rows), 0) if self.insert else (0, len(rows))


def ts(hours_ago: float = 1) -> str:
    """「一小时前」的时间戳。

    不要写死日期：这些用例断言的是「没有越过 days 边界」，
    一旦写死某个日期，过几天（或环境时钟推进）就会变成 boundary 而不是 max_pages。
    """
    return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def row(i, published_at=None):
    return dict(source="em", channel="快讯", title=f"新闻 {i}", content="内容",
                published_at=published_at or ts(), url=None)


@pytest.fixture()
def svc():
    return news_service.NewsIngestService(FakeRepo(), log=None, delay=0)


def test_backfill_stops_on_max_pages(monkeypatch, svc):
    monkeypatch.setattr(news_service.src, "fetch_em_list",
                        lambda **kw: [row(kw["page_index"])])
    st = svc.backfill_em(days=2, max_pages=3)
    assert st.pages == 3
    assert st.fetched == 3 and st.inserted == 3
    assert st.stopped_by == "max_pages"


def test_backfill_stops_on_known(monkeypatch):
    repo = FakeRepo(insert=False)
    service = news_service.NewsIngestService(repo, log=None, delay=0)
    monkeypatch.setattr(news_service.src, "fetch_em_list",
                        lambda **kw: [row(kw["page_index"])])
    st = service.backfill_em(days=2, max_pages=20, stop_on_known=3)
    assert st.stopped_by == "known"
    assert st.pages == 3


def test_backfill_stops_on_time_boundary(monkeypatch, svc):
    monkeypatch.setattr(news_service.src, "fetch_em_list",
                        lambda **kw: [row(kw["page_index"], "2020-01-01 10:00:00")])
    st = svc.backfill_em(days=2, max_pages=20)
    assert st.stopped_by == "boundary"
    assert st.pages == 1


def test_backfill_handles_source_error(monkeypatch, svc):
    monkeypatch.setattr(news_service.src, "fetch_em_list", lambda **kw: None)
    st = svc.backfill_em(days=2, max_pages=5)
    assert st.stopped_by == "error"
    assert st.pages == 0


def test_backfill_handles_empty_page(monkeypatch, svc):
    monkeypatch.setattr(news_service.src, "fetch_em_list", lambda **kw: [])
    st = svc.backfill_em(days=2, max_pages=5)
    assert st.stopped_by == "empty"


def test_collect_latest_reports_stats(monkeypatch):
    service = news_service.NewsIngestService(FakeRepo(), log=None, delay=0)
    monkeypatch.setattr(news_service.src, "fetch_em_flash", lambda log=None: [row(1)])
    monkeypatch.setattr(news_service.src, "fetch_cls_snapshot", lambda log=None: None)
    stats = service.collect_latest()
    assert [s.source for s in stats] == ["东财快讯", "财联社电报"]
    assert stats[0].inserted == 1 and stats[0].stopped_by == "snapshot"
    assert stats[1].stopped_by == "error"       # 空结果按错误处理，不抛异常
