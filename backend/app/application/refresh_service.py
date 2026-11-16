# -*- coding: utf-8 -*-
"""一键刷新服务（应用层）。

对应前端那个「更新数据」按钮。一次调用完成四件事：

    1. 新闻增量补齐（只补最近 N 天，页数有上限，避免请求太久）
    2. 实时快照（东财快讯 + 财联社电报）
    3. 自选股事件检测并落库（前端事件列表直接读它）
    4. 按保留策略裁剪旧数据（防止无限增长）

设计要点：**限时限量**。这是个同步 HTTP 请求，必须保证能在用户可接受的
时间（约 20~60 秒）内返回，所以每一步都有明确上限，并把过程写进结果里
（哪一步做了什么、为什么停）。
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .maintenance_service import MaintenanceService, RetentionPolicy
from .monitoring_service import EventMonitor
from .news_service import IngestStats, NewsIngestService


@dataclass
class RefreshResult:
    started_at: str = ""
    elapsed_sec: float = 0.0
    news: list[dict] = field(default_factory=list)
    events_detected: int = 0
    events_saved: int = 0
    stocks_scanned: int = 0
    failed_stocks: list[str] = field(default_factory=list)
    prune: dict = field(default_factory=dict)
    news_total_before: int = 0
    news_total_after: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return dict(started_at=self.started_at,
                    elapsed_sec=round(self.elapsed_sec, 1),
                    news=self.news,
                    events_detected=self.events_detected,
                    events_saved=self.events_saved,
                    stocks_scanned=self.stocks_scanned,
                    failed_stocks=self.failed_stocks,
                    prune=self.prune,
                    news_total_before=self.news_total_before,
                    news_total_after=self.news_total_after,
                    note=self.note)


class RefreshService:
    def __init__(self, news: NewsIngestService, monitor: EventMonitor,
                 event_repo, watchlist_repo, maintenance: MaintenanceService,
                 con, log=print):
        self.news = news
        self.monitor = monitor
        self.event_repo = event_repo
        self.watchlist_repo = watchlist_repo
        self.maintenance = maintenance
        self.con = con
        self.log = log

    # ---------------- 主流程 ----------------
    def run(self, news_days: float = 2, max_pages: int = 12,
            detect_days: int = 90, price_source: str = "sina",
            prune: bool = True, dry_run_prune: bool = False) -> RefreshResult:
        t0 = time.time()
        res = RefreshResult(started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        res.news_total_before = self._count_news()

        # 1) 新闻增量
        try:
            em = self.news.backfill_em(days=news_days, max_pages=max_pages,
                                       stop_on_known=6)
            res.news.append(em.to_dict())
        except Exception as e:                        # noqa: BLE001
            res.news.append(IngestStats(source="东财新闻列表",
                                        stopped_by=f"error:{type(e).__name__}").to_dict())
        # 2) 实时快照
        try:
            for st in self.news.collect_latest():
                res.news.append(st.to_dict())
        except Exception as e:                        # noqa: BLE001
            res.news.append(IngestStats(source="实时快照",
                                        stopped_by=f"error:{type(e).__name__}").to_dict())

        # 3) 自选股事件检测
        self._detect_watchlist_events(res, detect_days=detect_days,
                                      price_source=price_source)

        # 4) 保留期裁剪
        if prune:
            try:
                pr = self.maintenance.prune(dry_run=dry_run_prune)
                res.prune = pr.to_dict()
            except Exception as e:                    # noqa: BLE001
                res.prune = {"error": f"{type(e).__name__}: {e}"}

        res.news_total_after = self._count_news()
        res.elapsed_sec = time.time() - t0
        if res.failed_stocks:
            res.note = f"{len(res.failed_stocks)} 只股票行情获取失败（可能被限流），事件可能不全"
        return res

    # ---------------- 内部 ----------------
    def _count_news(self) -> int:
        try:
            return self.con.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        except Exception:                             # noqa: BLE001
            return 0

    def _detect_watchlist_events(self, res: RefreshResult,
                                 detect_days: int, price_source: str) -> None:
        wl = self.watchlist_repo.load()
        if len(wl) == 0:
            self.watchlist_repo.seed_defaults()
            wl = self.watchlist_repo.load()

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=detect_days)).strftime("%Y-%m-%d")

        for item in wl:
            try:
                # 监控场景优先用快源（新浪约 2s；baostock 实测可能 60s+）
                events = self.monitor.scan(item.code, start, end, source=price_source)
            except Exception as e:                    # noqa: BLE001
                if self.log:
                    self.log(f"  [refresh] {item.code} 检测失败: {type(e).__name__}")
                res.failed_stocks.append(item.code)
                continue
            res.stocks_scanned += 1
            res.events_detected += len(events)
            if events:
                try:
                    res.events_saved += self.event_repo.save_many(events)
                except Exception:                     # noqa: BLE001
                    pass
