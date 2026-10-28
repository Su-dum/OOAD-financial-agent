# -*- coding: utf-8 -*-
"""事件仓储（满足 domain.ports.EventRepository）。"""
from typing import Optional, Sequence

from ...domain.events import MarketEvent


class SqliteEventRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    def save_many(self, events: Sequence[MarketEvent]) -> int:
        if not events:
            return 0
        rows = [(e.code, e.name, e.event_type, e.trade_date, e.detected_at,
                 e.severity, e.value, e.threshold, e.detail, e.rule_name)
                for e in events]
        cur = self.con.executemany(
            "INSERT OR IGNORE INTO event(code,name,event_type,trade_date,detected_at,"
            "severity,value,threshold,detail,rule_name) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        self.con.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def list_recent(self, code: Optional[str] = None, limit: int = 50) -> list[MarketEvent]:
        sql = ("SELECT code,name,event_type,trade_date,detected_at,severity,value,"
               "threshold,detail,rule_name FROM event")
        args: list = []
        if code:
            sql += " WHERE code=?"
            args.append(str(code).split(".")[0])
        sql += " ORDER BY trade_date DESC, id DESC LIMIT ?"
        args.append(limit)
        return [MarketEvent(
            code=r[0], name=r[1] or "", event_type=r[2], trade_date=r[3],
            detected_at=r[4] or "", severity=r[5] or "low",
            value=r[6], threshold=r[7], detail=r[8] or "", rule_name=r[9] or "")
            for r in self.con.execute(sql, args)]
