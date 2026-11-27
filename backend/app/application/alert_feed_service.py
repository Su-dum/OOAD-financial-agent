# -*- coding: utf-8 -*-
"""重大事件提醒（B3 的「通知面」）。

## 为什么需要这一层

`RefreshService` 已经会在刷新时对 high 事件**自动调查并落库报告**，但报告只是躺在
`report` 表里——前端的 `ReportService.list()` 写了却没人调用，用户根本不知道
「刚刚又出了一份 AI 分析」。等于 B3 能力做了、但没有可见的出口。

这个服务把两件事拼在一起：

    事件（刚刚检测到什么）  ×  报告（AI 分析了没有）
    -> 一条可以在界面右上角弹出的提醒

## 为什么按 `detected_at` 而不是 `trade_date` 过滤

提醒的语义是「刚刚发现了什么」，不是「历史上发生过什么」。
一次刷新会把 180 天内的老事件全部重检一遍（事件表有唯一键去重，但检测仍在跑），
按 `trade_date` 过滤会让用户一开页面就被历史事件糊满。

前端存一个「上次看到提醒的时间」（localStorage），每次带上 `since`，
后端只返回此后**新检测到**的事件——这样刷新几次也不会重复弹同一条。
"""
from datetime import datetime, timedelta
from typing import Optional

from ..domain.events import MarketEvent

# 提醒里最多带几条（再多就成信息轰炸了，前端也只渲染 3 条）
DEFAULT_LIMIT = 5
# 兜底时间窗：since 太旧（比如隔了一天没开页面）时只回看这么久，避免一次弹一堆
MAX_LOOKBACK_HOURS = 24


class AlertFeedService:
    def __init__(self, event_repo, report_repo, min_severity: str = "high",
                 log=print):
        self.events = event_repo
        self.reports = report_repo
        self.min_severity = min_severity
        self.log = log

    # ---------------- 查询 ----------------
    def recent(self, since: Optional[str] = None, limit: int = DEFAULT_LIMIT,
               min_severity: Optional[str] = None,
               include_notice: bool = True) -> dict:
        """自 `since` 之后新检测到的重大事件 + 它们的 AI 分析状态。"""
        sev = min_severity if min_severity in ("low", "medium", "high") \
            else self.min_severity
        since_eff, clamped = self._effective_since(since)

        try:
            rows = self.events.list_since(since=since_eff, min_severity=sev,
                                          limit=limit, scope="stock",
                                          include_notice=include_notice)
        except Exception as e:                          # noqa: BLE001
            if self.log:
                self.log(f"  [alert] 事件查询失败: {type(e).__name__}")
            rows = []

        items = [self._to_item(r) for r in rows]
        return dict(
            count=len(items),
            since=since_eff,
            since_clamped=clamped,
            min_severity=sev,
            now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            items=items,
        )

    # ---------------- 内部 ----------------
    def _effective_since(self, since: Optional[str]) -> tuple:
        """把 since 收敛到一个合理窗口内；返回 (生效值, 是否被截断)。"""
        now = datetime.now()
        floor = (now - timedelta(hours=MAX_LOOKBACK_HOURS)).strftime(
            "%Y-%m-%d %H:%M:%S")
        s = (since or "").strip()
        if not s:
            # 没有 since：只回看最近一段时间（首次打开页面时不会把历史事件全弹出来）
            return floor, False
        if s <= floor:
            return floor, True
        return s, False

    def _to_item(self, row: dict) -> dict:
        report = None
        if self.reports is not None:
            try:
                report = self.reports.find_by_event(
                    row["code"], row["trade_date"], row["event_type"])
            except Exception as e:                      # noqa: BLE001
                if self.log:
                    self.log(f"  [alert] 报告查询失败: {type(e).__name__}")
                report = None

        item = dict(
            code=row["code"], name=row.get("name") or "",
            event_type=row["event_type"],
            label=_label_of(row["event_type"]),
            trade_date=row["trade_date"],
            detected_at=row.get("detected_at") or "",
            severity=row.get("severity") or "medium",
            detail=row.get("detail") or "",
            source_url=row.get("source_url"),
            # 有没有现成的 AI 分析：有 -> 点开直接看；没有 -> 点开现场跑一次
            report_id=report["id"] if report else None,
            report_ready=report is not None,
            confidence=report.get("confidence") if report else None,
            headline=report.get("headline") if report else "",
            llm_model=report.get("model") if report else "",
            degraded=bool(report.get("degraded")) if report else False,
        )
        return item


def _label_of(event_type: str) -> str:
    """复用领域层的中文事件名，避免提醒和事件列表用两套叫法。"""
    return MarketEvent(code="", name="", event_type=event_type,
                       trade_date="", detected_at="",
                       severity="low").label
