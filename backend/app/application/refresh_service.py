# -*- coding: utf-8 -*-
"""一键刷新服务（应用层）。

对应前端那个「更新数据」按钮。一次调用完成七件事：

    1. 新闻增量补齐（只补最近 N 天，页数有上限，避免请求太久）
    2. 实时快照（东财快讯 + 财联社电报）
    3. 自选股公告增量（B2 的公告事件靠它）
    4. 自选股财务快照（A1；按 TTL 决定要不要打外部接口）
    5. 自选股事件检测并落库（行情类规则 + 公告类规则）
    6. **对高等级事件自动发起调查**（B3 的 "autonomously"）
    7. 按保留策略裁剪旧数据

## 自动调查为什么要限流

调查会调工具（新闻/公告/指标）并生成报告；若每次都把新事件全查一遍，
刷新会从 20 秒变成几分钟，而且报告列表会被低价值事件淹没。所以：

  - 只自动调查 **high** 等级事件（阈值可配）
  - 每次最多 `max_auto_reports` 条（默认 2）
  - 同一个 (code, 事件日, 事件类型) 只查一次（`report_repo.has_event` 去重）
  - 默认用**模板结论**（不调 LLM），保证刷新时长可控；用户仍可手动点「调查」拿 LLM 版
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .maintenance_service import MaintenanceService, RetentionPolicy
from .monitoring_service import EventMonitor
from .news_service import IngestStats, NewsIngestService

_SEV_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class RefreshResult:
    started_at: str = ""
    elapsed_sec: float = 0.0
    news: list[dict] = field(default_factory=list)
    notices: list[dict] = field(default_factory=list)
    financials: list[dict] = field(default_factory=list)
    events_detected: int = 0
    events_saved: int = 0
    notice_events: int = 0
    stocks_scanned: int = 0
    failed_stocks: list[str] = field(default_factory=list)
    industry_events: dict = field(default_factory=dict)
    auto_reports: list[dict] = field(default_factory=list)
    auto_failed: list[dict] = field(default_factory=list)
    prune: dict = field(default_factory=dict)
    news_total_before: int = 0
    news_total_after: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return dict(started_at=self.started_at,
                    elapsed_sec=round(self.elapsed_sec, 1),
                    news=self.news,
                    notices=self.notices,
                    financials=self.financials,
                    events_detected=self.events_detected,
                    events_saved=self.events_saved,
                    notice_events=self.notice_events,
                    stocks_scanned=self.stocks_scanned,
                    failed_stocks=self.failed_stocks,
                    industry_events=self.industry_events,
                    auto_reports=self.auto_reports,
                    auto_failed=self.auto_failed,
                    prune=self.prune,
                    news_total_before=self.news_total_before,
                    news_total_after=self.news_total_after,
                    note=self.note)


class RefreshService:
    def __init__(self, news: NewsIngestService, monitor: EventMonitor,
                 event_repo, watchlist_repo, maintenance: MaintenanceService,
                 con, notice_ingest=None, financial=None, agent=None,
                 report_repo=None, industry=None, auto_investigate: bool = True,
                 max_auto_reports: int = 2, auto_min_severity: str = "high",
                 log=print):
        self.news = news
        self.monitor = monitor
        self.event_repo = event_repo
        self.watchlist_repo = watchlist_repo
        self.maintenance = maintenance
        self.con = con
        self.notice_ingest = notice_ingest      # 可选：没有就跳过公告增量
        self.financial = financial              # 可选：没有就跳过财务刷新
        self.agent = agent                      # 可选：没有就不做自动调查
        self.report_repo = report_repo
        self.industry = industry                # 可选：行业监控服务
        self.auto_investigate = auto_investigate
        self.max_auto_reports = max_auto_reports
        self.auto_min_severity = (auto_min_severity
                                  if auto_min_severity in _SEV_ORDER else "high")
        self.log = log

    # ---------------- 主流程 ----------------
    def run(self, news_days: float = 2, max_pages: int = 12,
            detect_days: int = 90, price_source: str = "sina",
            prune: bool = True, dry_run_prune: bool = False,
            include_notices: bool = True, notice_days: int = 400,
            max_notice_stocks: int = 12,
            include_financials: bool = True, max_financial_codes: int = 8,
            include_industries: bool = True,
            auto_investigate: Optional[bool] = None) -> RefreshResult:
        t0 = time.time()
        res = RefreshResult(started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        res.news_total_before = self._count_news()
        wl = self._watchlist()
        do_auto = self.auto_investigate if auto_investigate is None else auto_investigate

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

        # 3) 自选股公告增量
        if include_notices:
            self._ingest_notices(res, wl.codes[:max_notice_stocks],
                                 days=notice_days)

        # 4) 自选股财务快照（TTL 内不重复请求）
        if include_financials:
            self._ingest_financials(res, wl.codes[:max_financial_codes])

        # 5) 自选股事件检测
        detected: list = []
        self._detect_watchlist_events(res, wl, detect_days=detect_days,
                                      price_source=price_source,
                                      sink=detected)

        # 5.5) 行业监控：对已加入监控的行业指数跑同一套规则（B1）
        if include_industries and self.industry is not None:
            try:
                res.industry_events = self.industry.refresh(
                    days=detect_days, event_repo=self.event_repo)
            except Exception as e:                    # noqa: BLE001
                if self.log:
                    self.log(f"  [refresh] 行业监控失败: {type(e).__name__}")
                res.industry_events = {"error": f"{type(e).__name__}: {e}"}

        # 6) 高等级事件自动调查（B3）
        if do_auto and self.agent is not None:
            self._auto_investigate(res, detected)

        # 7) 保留期裁剪
        if prune:
            try:
                pr = self.maintenance.prune(dry_run=dry_run_prune)
                res.prune = pr.to_dict()
            except Exception as e:                    # noqa: BLE001
                res.prune = {"error": f"{type(e).__name__}: {e}"}

        res.news_total_after = self._count_news()
        res.elapsed_sec = time.time() - t0
        notes = []
        if res.failed_stocks:
            notes.append(f"{len(res.failed_stocks)} 只股票行情获取失败（可能被限流）")
        if res.auto_reports:
            notes.append(f"自动生成 {len(res.auto_reports)} 份调查报告")
        if res.auto_failed:
            notes.append(f"{len(res.auto_failed)} 个事件自动调查失败")
        res.note = "；".join(notes)
        return res

    # ---------------- 内部 ----------------
    def _count_news(self) -> int:
        try:
            return self.con.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        except Exception:                             # noqa: BLE001
            return 0

    def _watchlist(self):
        wl = self.watchlist_repo.load()
        if len(wl) == 0:
            self.watchlist_repo.seed_defaults()
            wl = self.watchlist_repo.load()
        return wl

    def _ingest_notices(self, res: RefreshResult, codes, days: int) -> None:
        if self.notice_ingest is None:
            return
        for code in codes:
            try:
                st = self.notice_ingest.fetch(code, days=days)
                res.notices.append(st.to_dict())
            except Exception as e:                    # noqa: BLE001
                if self.log:
                    self.log(f"  [refresh] {code} 公告采集失败: {type(e).__name__}")
                res.notices.append(dict(code=code, source="", fetched=0,
                                        inserted=0, classified=0,
                                        stopped_by=f"error:{type(e).__name__}"))

    def _ingest_financials(self, res: RefreshResult, codes) -> None:
        if self.financial is None:
            return
        try:
            for st in self.financial.ensure_many(codes):
                res.financials.append(st.to_dict())
        except Exception as e:                        # noqa: BLE001
            if self.log:
                self.log(f"  [refresh] 财务刷新失败: {type(e).__name__}")
            res.financials.append(dict(code="", stopped_by=f"error:{type(e).__name__}"))

    def _detect_watchlist_events(self, res: RefreshResult, wl,
                                 detect_days: int, price_source: str,
                                 sink: Optional[list] = None) -> None:
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
            res.notice_events += sum(1 for e in events
                                     if e.event_type.startswith("notice_"))
            if events:
                try:
                    res.events_saved += self.event_repo.save_many(events)
                except Exception:                     # noqa: BLE001
                    pass
                if sink is not None:
                    sink.extend(events)

    def _auto_investigate(self, res: RefreshResult, events: list) -> None:
        """对高等级、且还没调查过的事件自动生成报告（B3）。"""
        floor = _SEV_ORDER[self.auto_min_severity]
        seen = set()
        candidates = []
        for ev in sorted(events, key=lambda e: (e.trade_date,
                                                _SEV_ORDER.get(e.severity, 0)),
                         reverse=True):
            if _SEV_ORDER.get(ev.severity, 0) < floor:
                continue
            key = (ev.code, ev.trade_date, ev.event_type)
            if key in seen:
                continue
            seen.add(key)
            if self.report_repo is not None:
                try:
                    if self.report_repo.has_event(*key):
                        continue
                except Exception:                     # noqa: BLE001
                    pass
            candidates.append(ev)
            if len(candidates) >= self.max_auto_reports:
                break

        for ev in candidates:
            try:
                report = self.agent.investigate(ev, days=7)
                report.llm_meta = dict(report.llm_meta or {}, auto=True)
                rid = (self.report_repo.save(report)
                       if self.report_repo is not None else 0)
                res.auto_reports.append(dict(
                    report_id=rid, code=ev.code, name=ev.name,
                    trade_date=ev.trade_date, event_type=ev.event_type,
                    severity=ev.severity, question=report.question)
                )
                if self.log:
                    self.log(f"  [refresh] 自动调查 {ev.code} {ev.trade_date} "
                             f"{ev.event_type} -> 报告 {rid}")
            except Exception as e:                    # noqa: BLE001
                res.auto_failed.append(dict(code=ev.code, trade_date=ev.trade_date,
                                            event_type=ev.event_type,
                                            error=f"{type(e).__name__}: {e}"))
                if self.log:
                    self.log(f"  [refresh] 自动调查失败 {ev.code}: "
                             f"{type(e).__name__}")
