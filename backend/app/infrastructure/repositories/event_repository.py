# -*- coding: utf-8 -*-
"""事件仓储（满足 domain.ports.EventRepository）。

`scope` 区分个股事件（stock）与行业事件（industry）：
两者共用一张表，但查询时通常要分开（自选股面板只看 stock）。
"""
from typing import Optional, Sequence

from ...domain.events import MarketEvent

_COLUMNS = ("code,name,event_type,trade_date,detected_at,severity,value,"
            "threshold,detail,rule_name,source_url,scope")

# 最低等级 -> 允许的等级集合（等级有序，所以「medium 及以上」= medium + high）
_SEV_ALLOWED = {
    "low": ("low", "medium", "high"),
    "medium": ("medium", "high"),
    "high": ("high",),
}


class SqliteEventRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    def save_many(self, events: Sequence[MarketEvent]) -> int:
        if not events:
            return 0
        rows = [(e.code, e.name, e.event_type, e.trade_date, e.detected_at,
                 e.severity, e.value, e.threshold, e.detail, e.rule_name,
                 getattr(e, "source_url", None), getattr(e, "scope", "stock") or "stock")
                for e in events]
        cur = self.con.executemany(
            "INSERT OR IGNORE INTO event(code,name,event_type,trade_date,detected_at,"
            "severity,value,threshold,detail,rule_name,source_url,scope) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.con.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def list_recent(self, code: Optional[str] = None, limit: int = 50,
                    event_prefix: Optional[str] = None,
                    scope: Optional[str] = None) -> list[MarketEvent]:
        sql = f"SELECT {_COLUMNS} FROM event"
        args: list = []
        where = []
        if code:
            where.append("code=?")
            args.append(str(code).split(".")[0])
        if event_prefix:
            where.append("event_type LIKE ?")
            args.append(f"{event_prefix}%")
        if scope:
            where.append("COALESCE(scope, 'stock')=?")
            args.append(scope)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY trade_date DESC, id DESC LIMIT ?"
        args.append(limit)
        return [MarketEvent(
            code=r[0], name=r[1] or "", event_type=r[2], trade_date=r[3],
            detected_at=r[4] or "", severity=r[5] or "low",
            value=r[6], threshold=r[7], detail=r[8] or "", rule_name=r[9] or "",
            source_url=r[10], scope=r[11] or "stock")
            for r in self.con.execute(sql, args)]

    def list_since(self, since: Optional[str] = None, min_severity: str = "high",
                   limit: int = 10, scope: Optional[str] = "stock",
                   include_notice: bool = True) -> list[dict]:
        """取「自 since 之后被**检测到**」的高等级事件（给右上角提醒用）。

        注意过滤的是 `detected_at` 而不是 `trade_date`：
        提醒的语义是「刚刚发现了什么」，不是「历史上发生过什么」——
        一次性刷新会把 180 天前的老事件也检出来，那些不该弹提醒。
        """
        allowed = _SEV_ALLOWED.get(min_severity, _SEV_ALLOWED["high"])
        sql = (f"SELECT id,{_COLUMNS} FROM event WHERE severity IN "
               f"({','.join('?' * len(allowed))})")
        args: list = list(allowed)
        if since:
            sql += " AND detected_at > ?"
            args.append(since)
        if not include_notice:
            sql += " AND event_type NOT LIKE 'notice_%'"
        if scope:
            sql += " AND COALESCE(scope, 'stock')=?"
            args.append(scope)
        sql += " ORDER BY detected_at DESC, id DESC LIMIT ?"
        args.append(int(limit))
        return [dict(id=r[0], code=r[1], name=r[2], event_type=r[3],
                     trade_date=r[4], detected_at=r[5], severity=r[6],
                     value=r[7], threshold=r[8], detail=r[9], rule_name=r[10],
                     source_url=r[11], scope=r[12])
                for r in self.con.execute(sql, args)]
