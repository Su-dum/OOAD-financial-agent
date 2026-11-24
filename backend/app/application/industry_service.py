# -*- coding: utf-8 -*-
"""行业监控服务（应用层，B1）。

职责：
    list()      31 个申万一级行业 + 是否已加入监控
    watch/unwatch   维护监控列表
    series()    行业指数走势（前端图表）
    scan()      对某个行业指数跑行情规则 -> scope=industry 的事件
    refresh()   对已监控行业批量采集 + 检测 + 落库（一键刷新时调用）

关键设计：**行业事件与个股事件走同一套规则**。
`EventMonitor.evaluate_series(series, name, rules, scope="industry")` 是为此抽出的公共入口，
行业不需要第二套检测算法，只需要换一条价格序列。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from ..domain.events import MarketEvent


def _range_of(days: int) -> tuple:
    end = datetime.now()
    start = end - timedelta(days=int(days))
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _sample(records: list, max_points: int = 300) -> list:
    n = len(records)
    if n <= max_points:
        return records
    step = n / float(max_points)
    idx = sorted({int(i * step) for i in range(max_points)} | {0, n - 1})
    return [records[i] for i in idx if i < n]


class IndustryService:
    def __init__(self, repo, provider, monitor=None, catalog=None, log=print):
        self.repo = repo
        self.provider = provider        # 行业指数 PriceProvider
        self.monitor = monitor          # 只用它的 evaluate_series + 规则配置
        self.catalog = catalog
        self.log = log

    # ---------------- 列表 ----------------
    def list_all(self) -> list[dict]:
        watched = set(self.repo.codes()) if self.repo is not None else set()
        out = []
        for row in (self.catalog.industries() if self.catalog else []):
            item = dict(row)
            item["watched"] = item["code"] in watched
            out.append(item)
        return out

    def watched(self) -> list[dict]:
        if self.repo is None:
            return []
        out = []
        for row in self.repo.load():
            meta = self.catalog.industry(row["code"]) if self.catalog else {}
            out.append(dict(code=row["code"], name=row["name"],
                            added_at=row.get("added_at"),
                            stock_count=(meta or {}).get("stock_count"),
                            pe_ttm=(meta or {}).get("pe_ttm"),
                            pb=(meta or {}).get("pb")))
        return out

    # ---------------- 监控列表 ----------------
    def watch(self, code: str) -> dict:
        row = self.catalog.industry(code) if self.catalog else {}
        if not row:
            raise ValueError(f"未知行业 {code}（只支持申万一级 31 个）")
        self.repo.add(row["code"], row.get("name") or "")
        return dict(code=row["code"], name=row.get("name") or "", watched=True)

    def unwatch(self, code: str) -> bool:
        return bool(self.repo.remove(code))

    # ---------------- 指数序列 ----------------
    def series(self, code: str, days: int = 365,
               max_points: int = 300) -> Optional[dict]:
        row = self.catalog.industry(code) if self.catalog else {}
        if not row:
            return None
        start, end = _range_of(days)
        s = self.provider.fetch(row["code"], start, end, adjust="none")
        if s is None or len(s) < 2:
            return None
        recs = _sample(s.records, max_points)
        return dict(code=row["code"], name=row.get("name") or "",
                    start=s.start, end=s.end, n_days=len(s),
                    source=s.source, adjust=s.adjust,
                    points=[dict(date=r.date, close=r.close, volume=r.volume,
                                 pe_ttm=None, pb=None) for r in recs])

    # ---------------- 事件检测 ----------------
    def scan(self, code: str, days: int = 365,
             persist: bool = False, event_repo=None) -> list[MarketEvent]:
        row = self.catalog.industry(code) if self.catalog else {}
        if not row:
            raise ValueError(f"未知行业 {code}")
        start, end = _range_of(days)
        s = self.provider.fetch(row["code"], start, end, adjust="none")
        if s is None or len(s) < 2:
            return []
        rules = self.monitor.rules_for(row["code"])[0] if self.monitor else []
        events = (self.monitor.evaluate_series(s, name=row.get("name") or "",
                                               rules=rules, scope="industry")
                  if self.monitor else [])
        events.sort(key=lambda e: e.trade_date, reverse=True)
        if persist and event_repo is not None and events:
            try:
                event_repo.save_many(events)
            except Exception as e:                      # noqa: BLE001
                if self.log:
                    self.log(f"  [industry] 事件落库失败: {type(e).__name__}")
        return events

    # ---------------- 批量刷新 ----------------
    def refresh(self, days: int = 365, event_repo=None,
                codes: Optional[Sequence[str]] = None) -> dict:
        targets = list(codes) if codes is not None else [
            r["code"] for r in (self.repo.load() if self.repo is not None else [])]
        detected = 0
        saved = 0
        failed = []
        for code in targets:
            try:
                events = self.scan(code, days=days)
            except Exception as e:                      # noqa: BLE001
                if self.log:
                    self.log(f"  [industry] {code} 检测失败: {type(e).__name__}")
                failed.append(code)
                continue
            detected += len(events)
            if events and event_repo is not None:
                try:
                    saved += event_repo.save_many(events)
                except Exception:                       # noqa: BLE001
                    pass
        return dict(scanned=len(targets), events_detected=detected,
                    events_saved=saved, failed=failed)
