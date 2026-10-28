# -*- coding: utf-8 -*-
"""调查报告仓储（满足 domain.ports.ReportRepository）。

报告正文以 JSON 存 payload，同时冗余一份 markdown 便于直接展示。
"""
import json
from typing import Optional

from ...domain.investigation import Evidence, InvestigationReport, InvestigationTask


class SqliteReportRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    def save(self, report: InvestigationReport) -> int:
        payload = json.dumps(report.to_dict(), ensure_ascii=False)
        md = report.to_markdown()
        cur = self.con.execute(
            "INSERT INTO report(code,name,question,created_at,payload,markdown) "
            "VALUES(?,?,?,?,?,?)",
            (report.code, report.name, report.question, report.created_at, payload, md))
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

    def list_recent(self, code: Optional[str] = None, limit: int = 20) -> list[dict]:
        sql = "SELECT id,code,name,question,created_at FROM report"
        args: list = []
        if code:
            sql += " WHERE code=?"
            args.append(str(code).split(".")[0])
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(id=r[0], code=r[1], name=r[2], question=r[3], created_at=r[4])
                for r in self.con.execute(sql, args)]
