# -*- coding: utf-8 -*-
"""新闻采集服务（应用层）。

把「回溯补齐」与「实时快照」的逻辑从脚本里收上来，这样 API、定时任务、
命令行脚本共用同一份实现，不会出现两套行为不一致。

`scripts/backfill_news.py` 现在只是这个服务的 CLI 外壳。
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from ..infrastructure.providers import news_sources as src


@dataclass
class IngestStats:
    source: str = ""
    fetched: int = 0
    inserted: int = 0
    skipped: int = 0
    linked: int = 0
    pages: int = 0
    stopped_by: str = ""      # boundary / known / max_pages / empty / error

    def to_dict(self) -> dict:
        return dict(source=self.source, fetched=self.fetched,
                    inserted=self.inserted, skipped=self.skipped,
                    linked=self.linked, pages=self.pages,
                    stopped_by=self.stopped_by)


class NewsIngestService:
    def __init__(self, news_repo, log=print, delay: float = 0.8):
        self.repo = news_repo
        self.log = log
        self.delay = delay

    # ---------------- 工具 ----------------
    @staticmethod
    def cutoff(days: float) -> str:
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    def _save(self, rows):
        ins, skip = self.repo.save(rows)
        return ins, skip

    # ---------------- 实时快照 ----------------
    def collect_latest(self) -> list[IngestStats]:
        out = []
        for name, fn in (("东财快讯", src.fetch_em_flash),
                         ("财联社电报", src.fetch_cls_snapshot)):
            rows = fn(log=self.log)
            st = IngestStats(source=name)
            if not rows:
                st.stopped_by = "error"
                out.append(st)
                continue
            ins, skip = self._save(rows)
            st.fetched, st.inserted, st.skipped = len(rows), ins, skip
            st.stopped_by = "snapshot"
            out.append(st)
        return out

    # ---------------- 东财回溯 ----------------
    def backfill_em(self, days: float = 2, page_size: int = 20,
                    max_pages: int = 15, stop_on_known: int = 8,
                    column: str = "345") -> IngestStats:
        cut = self.cutoff(days)
        st = IngestStats(source="东财新闻列表")
        known_streak = 0
        for page in range(1, max_pages + 1):
            rows = src.fetch_em_list(page_index=page, page_size=page_size,
                                     column=column, log=self.log)
            if rows is None:
                st.stopped_by = "error"
                break
            if not rows:
                st.stopped_by = "empty"
                break
            oldest = min((r["published_at"] for r in rows if r["published_at"]),
                         default=None)
            ins, skip = self._save(rows)
            st.pages += 1
            st.fetched += len(rows)
            st.inserted += ins
            st.skipped += skip
            if ins == 0:
                known_streak += 1
            else:
                known_streak = 0
            if oldest and oldest < cut:
                st.stopped_by = "boundary"
                break
            if stop_on_known and known_streak >= stop_on_known:
                st.stopped_by = "known"
                break
            time.sleep(self.delay)
        return st

    # ---------------- 财联社回溯 ----------------
    def backfill_cls(self, days: float = 1, max_pages: int = 20,
                     stop_on_known: int = 8) -> IngestStats:
        cut = self.cutoff(days)
        st = IngestStats(source="财联社电报")
        known_streak = 0
        last_time = None
        for page in range(1, max_pages + 1):
            rows = src.fetch_cls_page(last_time=last_time, rn=20, log=self.log)
            if rows is None:
                st.stopped_by = "error"
                break
            if not rows:
                st.stopped_by = "empty"
                break
            stamps = [r["published_at"] for r in rows if r["published_at"]]
            oldest = min(stamps) if stamps else None
            ins, skip = self._save(rows)
            st.pages += 1
            st.fetched += len(rows)
            st.inserted += ins
            st.skipped += skip
            if ins == 0:
                known_streak += 1
            else:
                known_streak = 0
            if oldest and oldest < cut:
                st.stopped_by = "boundary"
                break
            if stop_on_known and known_streak >= stop_on_known:
                st.stopped_by = "known"
                break
            if not oldest:
                break
            last_time = int(datetime.strptime(oldest, "%Y-%m-%d %H:%M:%S").timestamp()) - 1
            time.sleep(self.delay)
        return st
