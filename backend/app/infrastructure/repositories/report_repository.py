# -*- coding: utf-8 -*-
"""调查报告仓储（满足 domain.ports.ReportRepository）。

报告正文以 JSON 存 payload，同时冗余一份 markdown 便于直接展示。

## 为什么要额外存 event_date / event_type

B3 的「检测到事件后自动调查」需要**去重**：同一只票、同一天、同一类事件
刷新十次也只该自动生成一份报告。payload 里虽然有 event，但 JSON 里查不方便，
所以把这两个字段提升成列（`has_event()` 一条 SELECT 就能判断）。
"""
import json
from typing import Optional

from ...domain.investigation import InvestigationReport


class SqliteReportRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    @staticmethod
    def _event_fields(report: InvestigationReport) -> tuple:
        ev = getattr(report, "event", None)
        if ev is None:
            return None, None
        return (getattr(ev, "trade_date", None),
                getattr(ev, "event_type", None))

    def save(self, report: InvestigationReport) -> int:
        payload = json.dumps(report.to_dict(), ensure_ascii=False)
        md = report.to_markdown()
        event_date, event_type = self._event_fields(report)
        cur = self.con.execute(
            "INSERT INTO report(code,name,question,event_date,event_type,"
            "created_at,payload,markdown) VALUES(?,?,?,?,?,?,?,?)",
            (report.code, report.name, report.question, event_date, event_type,
             report.created_at, payload, md))
        self.con.commit()
        return int(cur.lastrowid or 0)

    def get(self, report_id: int) -> Optional[dict]:
        r = self.con.execute(
            "SELECT id,code,name,question,created_at,payload,markdown FROM report "
            "WHERE id=?", (report_id,)).fetchone()
        if not r:
            return None
        return dict(id=r[0], code=r[1], name=r[2], question=r[3],
                    created_at=r[4], payload=json.loads(r[5]), markdown=r[6])

    def has_event(self, code: str, event_date: Optional[str],
                  event_type: Optional[str]) -> bool:
        """是否已经针对「这个事件」生成过报告（自动调查去重用）。"""
        if not event_date or not event_type:
            return False
        r = self.con.execute(
            "SELECT 1 FROM report WHERE code=? AND event_date=? AND event_type=? "
            "LIMIT 1",
            (str(code).split(".")[0], event_date, event_type)).fetchone()
        return r is not None

    def list_recent(self, code: Optional[str] = None, limit: int = 20) -> list[dict]:
        sql = "SELECT id,code,name,question,event_date,event_type,created_at FROM report"
        args: list = []
        if code:
            sql += " WHERE code=?"
            args.append(str(code).split(".")[0])
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(id=r[0], code=r[1], name=r[2], question=r[3],
                     event_date=r[4], event_type=r[5], created_at=r[6])
                for r in self.con.execute(sql, args)]

    def find_by_event(self, code: str, event_date: Optional[str],
                      event_type: Optional[str]) -> Optional[dict]:
        """按「事件」取报告摘要（给右上角提醒：这条事件有没有 AI 分析）。

        只返回摘要而不是整份 payload——提醒里只需要一行结论 + 置信度，
        点开时前端再按 id 拉全文。
        """
        if not event_date or not event_type:
            return None
        r = self.con.execute(
            "SELECT id,created_at,payload FROM report "
            "WHERE code=? AND event_date=? AND event_type=? "
            "ORDER BY id DESC LIMIT 1",
            (str(code).split(".")[0], event_date, event_type)).fetchone()
        if not r:
            return None
        try:
            payload = json.loads(r[2])
        except (TypeError, ValueError):
            payload = {}
        meta = payload.get("llm_meta") or {}
        conclusion = (payload.get("conclusion") or "").strip()
        return dict(
            id=r[0], created_at=r[1], confidence=payload.get("confidence"),
            conclusion=conclusion,
            headline=_first_sentence(conclusion, 90),
            model=meta.get("model") or "",
            provider=meta.get("provider") or "",
            degraded=bool(meta.get("degraded")),
            auto=bool(meta.get("auto")),
        )


def _first_sentence(text: str, limit: int) -> str:
    """提醒里只放一句话：截到第一个句号/分号，再兜底截断。"""
    if not text:
        return ""
    t = " ".join(text.split())
    for sep in ("。", "；", "\n"):
        i = t.find(sep)
        if 0 < i <= limit:
            return t[:i + 1]
    return t[:limit] + ("…" if len(t) > limit else "")
