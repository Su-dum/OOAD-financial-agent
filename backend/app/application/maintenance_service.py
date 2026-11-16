# -*- coding: utf-8 -*-
"""数据保留策略（应用层）。

## 为什么要裁剪

新闻按实测约 **300 条/天** 增长（50 天 15,058 条）。不设限的话：
    1 年 ≈ 11 万条 ≈ 300 MB
其中大部分对「近期事件调查」毫无价值——调查窗口通常只有 7~30 天。

## 分档策略

| 数据 | 默认保留 | 理由 |
|---|---|---|
| `news` | **90 天** | 事件调查主要看近期；再往前的新闻基本不参与推理 |
| `event` | **180 天** | 行很小（~200 字节），保留久一点便于回看历史异动 |
| `report` | **永久** | 是最终交付物，且数量很少 |

`news_stock` 通过外键 `ON DELETE CASCADE` 随新闻一起删；
全文索引 `news_fts` 由删除触发器自动维护。

## 为什么不是「归档」而是「删除」

课程项目的数据都可以用 `backfill_news.py` 重新拉（东财可回溯 200 天），
归档成 parquet 只会增加复杂度而没有收益。真要做长期存档，再加一层。
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


@dataclass
class RetentionPolicy:
    news_days: int = _env_int("NEWS_RETENTION_DAYS", 90)
    event_days: int = _env_int("EVENT_RETENTION_DAYS", 180)
    # 单次清理最多删多少行（防止误配置把库删空）
    max_delete: int = 200_000

    def news_cutoff(self) -> str:
        return (datetime.now() - timedelta(days=self.news_days)).strftime("%Y-%m-%d %H:%M:%S")

    def event_cutoff(self) -> str:
        return (datetime.now() - timedelta(days=self.event_days)).strftime("%Y-%m-%d")

    def describe(self) -> dict:
        return dict(news_days=self.news_days, event_days=self.event_days,
                    news_cutoff=self.news_cutoff(),
                    event_cutoff=self.event_cutoff())


@dataclass
class PruneResult:
    news_deleted: int = 0
    events_deleted: int = 0
    vacuumed: bool = False
    news_before: int = 0
    news_after: int = 0

    def to_dict(self) -> dict:
        return dict(news_deleted=self.news_deleted,
                    events_deleted=self.events_deleted,
                    vacuumed=self.vacuumed,
                    news_before=self.news_before,
                    news_after=self.news_after,
                    freed_rows=self.news_deleted + self.events_deleted)


class MaintenanceService:
    """按保留策略裁剪数据。"""

    def __init__(self, con, policy: RetentionPolicy | None = None, log=print):
        self.con = con
        self.policy = policy or RetentionPolicy()
        self.log = log

    def stats(self) -> dict:
        q = lambda s: self.con.execute(s).fetchone()[0]
        oldest = q("SELECT MIN(published_at) FROM news")
        return dict(
            policy=self.policy.describe(),
            news=q("SELECT COUNT(*) FROM news"),
            news_oldest=oldest,
            news_links=q("SELECT COUNT(*) FROM news_stock"),
            events=q("SELECT COUNT(*) FROM event"),
            reports=q("SELECT COUNT(*) FROM report"),
        )

    def prune(self, dry_run: bool = False, vacuum: bool = True) -> PruneResult:
        p = self.policy
        n_before = self.con.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        news_cut = p.news_cutoff()
        ev_cut = p.event_cutoff()

        # 先算要删多少（dry-run 与安全阀都要用）
        n_news = self.con.execute(
            "SELECT COUNT(*) FROM news WHERE published_at < ?", (news_cut,)).fetchone()[0]
        n_events = self.con.execute(
            "SELECT COUNT(*) FROM event WHERE trade_date < ?", (ev_cut,)).fetchone()[0]

        if n_news + n_events > p.max_delete:
            if self.log:
                self.log(f"  [maintenance] 待删 {n_news + n_events:,} 行超过上限 "
                         f"{p.max_delete:,}，拒绝执行（检查 NEWS_RETENTION_DAYS 配置）")
            return PruneResult(news_before=n_before, news_after=n_before)

        if dry_run:
            if self.log:
                self.log(f"  [maintenance] dry-run：将删除新闻 {n_news:,} 条"
                         f"（早于 {news_cut}）、事件 {n_events:,} 条（早于 {ev_cut}）")
            return PruneResult(news_deleted=n_news, events_deleted=n_events,
                               news_before=n_before, news_after=n_before)

        res = PruneResult(news_before=n_before)
        if n_news:
            self.con.execute("DELETE FROM news WHERE published_at < ?", (news_cut,))
            res.news_deleted = n_news
        if n_events:
            self.con.execute("DELETE FROM event WHERE trade_date < ?", (ev_cut,))
            res.events_deleted = n_events
        self.con.commit()

        res.news_after = self.con.execute("SELECT COUNT(*) FROM news").fetchone()[0]

        # 大批删除后回收空间（VACUUM 会重建文件，几十 MB 量级很快）
        if vacuum and (res.news_deleted + res.events_deleted) > 0:
            try:
                self.con.execute("VACUUM")
                res.vacuumed = True
            except Exception as e:                      # noqa: BLE001
                if self.log:
                    self.log(f"  [maintenance] VACUUM 跳过: {type(e).__name__}")

        if self.log:
            self.log(f"  [maintenance] 清理完成：新闻 -{res.news_deleted:,} "
                     f"事件 -{res.events_deleted:,}"
                     + (f"，已回收空间" if res.vacuumed else ""))
        return res
