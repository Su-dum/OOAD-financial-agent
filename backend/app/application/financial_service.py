# -*- coding: utf-8 -*-
"""财务数据服务（应用层，A1）。

职责：把「财务快照从哪来」收敛成一个入口：

    get(code)            只读本地（用户交互路径不打外部接口）
    ensure(code)         过期才刷新（刷新按钮 / 首次分析时调用）
    refresh(code)        强制刷新（用户显式点「更新财务数据」）

TTL 默认 7 天：财务是季频，一周刷一次足够；这样「一键更新」不会每次都
为 6 只自选股各打一次新浪接口。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from ..domain.financials import FinancialSnapshot


@dataclass
class FinancialIngestStats:
    code: str = ""
    source: str = ""
    report_date: str = ""
    updated: bool = False
    stopped_by: str = ""        # ok / fresh / no_provider / empty / error

    def to_dict(self) -> dict:
        return dict(code=self.code, source=self.source,
                    report_date=self.report_date, updated=self.updated,
                    stopped_by=self.stopped_by)


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except ValueError:
            continue
    return None


class FinancialService:
    def __init__(self, repo, provider=None, log=print, ttl_days: int = 7):
        self.repo = repo
        self.provider = provider
        self.log = log
        self.ttl_days = ttl_days

    # ---------------- 读 ----------------
    def get(self, code: str) -> Optional[dict]:
        if self.repo is None:
            return None
        try:
            return self.repo.get(code)
        except Exception as e:                          # noqa: BLE001
            if self.log:
                self.log(f"  [financial] {code} 读取失败: {type(e).__name__}")
            return None

    def is_stale(self, code: str) -> bool:
        row = self.get(code)
        if not row:
            return True
        ts = _parse_ts(row.get("fetched_at"))
        if ts is None:
            return True
        return datetime.now() - ts > timedelta(days=self.ttl_days)

    # ---------------- 写 ----------------
    def refresh(self, code: str, years: int = 3) -> FinancialIngestStats:
        c = str(code).split(".")[0]
        st = FinancialIngestStats(code=c)
        if self.provider is None:
            st.stopped_by = "no_provider"
            return st
        try:
            snap: Optional[FinancialSnapshot] = self.provider.fetch(c, years=years)
        except Exception as e:                          # noqa: BLE001
            if self.log:
                self.log(f"  [financial] {c} 刷新异常: {type(e).__name__}")
            st.stopped_by = "error"
            return st
        if snap is None or snap.empty:
            st.stopped_by = "empty"
            return st
        st.source = snap.source
        st.report_date = snap.report_date
        if self.repo is not None:
            try:
                self.repo.upsert(snap)
                st.updated = True
                st.stopped_by = "ok"
            except Exception as e:                      # noqa: BLE001
                if self.log:
                    self.log(f"  [financial] {c} 落库失败: {type(e).__name__}")
                st.stopped_by = "error"
        else:
            st.stopped_by = "ok"
        return st

    def ensure(self, code: str, force: bool = False,
               years: int = 3) -> Optional[dict]:
        """缺失或过期才刷新；force=True 时无条件刷新。返回最新本地快照。"""
        if force or self.is_stale(code):
            st = self.refresh(code, years=years)
            if st.stopped_by not in ("ok", "fresh"):
                if self.log and st.stopped_by not in ("no_provider",):
                    self.log(f"  [financial] {code} 刷新未成功（{st.stopped_by}），"
                             f"沿用本地快照")
        return self.get(code)

    def ensure_many(self, codes: Sequence[str], force: bool = False,
                    max_codes: int = 8, years: int = 3) -> list[FinancialIngestStats]:
        out = []
        for c in list(codes)[:max_codes]:
            if not force and not self.is_stale(c):
                out.append(FinancialIngestStats(code=str(c), stopped_by="fresh"))
                continue
            out.append(self.refresh(c, years=years))
        return out

    # ---------------- 展示 ----------------
    def describe(self, code: str) -> dict:
        row = self.get(code) or {}
        return dict(code=code, snapshot=row or None,
                    ttl_days=self.ttl_days,
                    fetched_at=(row or {}).get("fetched_at"),
                    stale=self.is_stale(code))
