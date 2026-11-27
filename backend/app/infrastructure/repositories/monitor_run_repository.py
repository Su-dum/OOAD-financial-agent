# -*- coding: utf-8 -*-
"""定时巡检日志仓储（B1 的可观测性）。

只做一件事：把每次巡检的结果落一行，让「昨晚 21:00 到底跑没跑」这种问题
能从库里查出来，而不是只活在进程内存里（重启即失忆）。
"""
from typing import Optional

_COLUMNS = ("profile", "slot", "started_at", "finished_at", "ok", "elapsed_sec",
            "events_detected", "notice_events", "industry_events",
            "auto_reports", "stocks_scanned", "error", "note")


class SqliteMonitorRunRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    def save(self, record: dict) -> int:
        row = {k: record.get(k) for k in _COLUMNS}
        row["ok"] = 1 if record.get("ok", True) else 0
        cur = self.con.execute(
            f"INSERT INTO monitor_run({','.join(_COLUMNS)}) "
            f"VALUES({','.join('?' * len(_COLUMNS))})",
            tuple(row[k] for k in _COLUMNS))
        self.con.commit()
        return int(cur.lastrowid or 0)

    def list_recent(self, limit: int = 10) -> list[dict]:
        r = self.con.execute(
            f"SELECT id,{','.join(_COLUMNS)} FROM monitor_run "
            f"ORDER BY id DESC LIMIT ?", (int(limit),))
        return [dict(id=row[0], ok=bool(row[5]),
                     profile=row[1], slot=row[2], started_at=row[3],
                     finished_at=row[4], elapsed_sec=row[6],
                     events_detected=row[7], notice_events=row[8],
                     industry_events=row[9], auto_reports=row[10],
                     stocks_scanned=row[11], error=row[12], note=row[13])
                for row in r]

    def last(self) -> Optional[dict]:
        rows = self.list_recent(1)
        return rows[0] if rows else None

    def prune(self, keep_days: int = 30) -> int:
        """只保留最近 N 天，避免巡检日志无限增长（一天最多 14 行）。"""
        cur = self.con.execute(
            "DELETE FROM monitor_run WHERE started_at < "
            "datetime('now', 'localtime', ?)", (f"-{int(keep_days)} days",))
        self.con.commit()
        return cur.rowcount or 0

    def stats(self) -> dict:
        q = lambda s: self.con.execute(s).fetchone()[0]     # noqa: E731
        return dict(runs=q("SELECT COUNT(*) FROM monitor_run"),
                    last_run=q("SELECT MAX(started_at) FROM monitor_run"))
