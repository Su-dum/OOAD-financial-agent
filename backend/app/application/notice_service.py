# -*- coding: utf-8 -*-
"""公告采集服务（应用层）。

对应 B2 的数据准备：**先把公告拉到本地，再谈「把公告变成事件」**。

设计要点与新闻采集一致（`news_service.py`）：

  - 采集是**写路径**，只在一键刷新 / 显式刷新时发生；用户查事件、点调查只读本地库
  - 多个公告源按顺序降级：东财（带类型）-> 巨潮（只有标题）
  - 单个标的失败不影响其它标的，失败信息写进结果里而不是抛异常

为什么不复用 `ProviderChain`？那是「同一份数据、不同来源」的价格链，
粒度是「一条序列」。公告是「一批记录」，还要落库去重，语义不同，
硬套会把缓存/重试逻辑搅在一起。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from ..domain.notices import classify_notice


@dataclass
class NoticeIngestStats:
    code: str = ""
    source: str = ""
    fetched: int = 0
    inserted: int = 0
    classified: int = 0        # 归到「重大事件」类别的条数
    stopped_by: str = ""       # ok / no_provider / error

    def to_dict(self) -> dict:
        return dict(code=self.code, source=self.source, fetched=self.fetched,
                    inserted=self.inserted, classified=self.classified,
                    stopped_by=self.stopped_by)


class NoticeIngestService:
    def __init__(self, repo, providers: Sequence, log=print,
                 days: int = 400, limit: int = 500):
        self.repo = repo
        self.providers = [p for p in providers if p is not None]
        self.log = log
        self.days = days
        self.limit = limit

    # ---------------- 单标的 ----------------
    def fetch(self, code: str, days: Optional[int] = None,
              limit: Optional[int] = None) -> NoticeIngestStats:
        c = str(code).split(".")[0]
        days = self.days if days is None else days
        limit = self.limit if limit is None else limit
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        st = NoticeIngestStats(code=c)
        if not self.providers:
            st.stopped_by = "no_provider"
            return st

        for p in self.providers:
            try:
                rows = p.list_notices(c, start, end, limit=limit) or []
            except Exception as e:                        # noqa: BLE001
                if self.log:
                    self.log(f"  [notice] {c} 源 {getattr(p, 'name', '?')} 失败: "
                             f"{type(e).__name__}")
                continue
            if not rows:
                continue
            st.source = getattr(p, "name", "")
            st.fetched = len(rows)
            st.inserted = self.repo.save_many(rows) if self.repo is not None else 0
            st.classified = sum(1 for r in rows if self._is_material(r))
            st.stopped_by = "ok"
            if self.log:
                self.log(f"  [notice] {c} {st.source}: 取 {st.fetched} 条，"
                         f"新增 {st.inserted}，重大类 {st.classified}")
            return st

        st.stopped_by = "error"
        return st

    @staticmethod
    def _is_material(row: dict) -> bool:
        cat = classify_notice(row.get("notice_type") or "", row.get("title") or "")
        return bool(cat is not None and cat.material)

    # ---------------- 批量 ----------------
    def fetch_many(self, codes: Sequence[str], days: Optional[int] = None,
                   limit: Optional[int] = None) -> list[NoticeIngestStats]:
        out = []
        for c in codes:
            out.append(self.fetch(c, days=days, limit=limit))
        return out
