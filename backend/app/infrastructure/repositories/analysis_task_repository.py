# -*- coding: utf-8 -*-
"""分析任务仓储（C1）。

`compare_codes` 用逗号串存——最多 5 个代码，拆成关联表没有收益。
"""
from datetime import datetime
from typing import Optional, Sequence

from ...domain.analysis_task import AnalysisTask

_COLUMNS = ("id", "name", "code", "days", "compare_codes", "benchmark",
            "created_at", "last_run_at")
_SELECT = ", ".join(_COLUMNS)


class SqliteAnalysisTaskRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    @staticmethod
    def _row_to_task(r) -> AnalysisTask:
        codes = tuple(c.strip() for c in (r[4] or "").split(",") if c.strip())
        return AnalysisTask(id=r[0], name=r[1], code=r[2], days=int(r[3] or 365),
                            compare_codes=codes, benchmark=r[5],
                            created_at=r[6] or "", last_run_at=r[7] or "")

    def list(self, limit: int = 50) -> list[AnalysisTask]:
        rows = self.con.execute(
            f"SELECT {_SELECT} FROM analysis_task ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get(self, task_id: int) -> Optional[AnalysisTask]:
        r = self.con.execute(f"SELECT {_SELECT} FROM analysis_task WHERE id=?",
                             (task_id,)).fetchone()
        return self._row_to_task(r) if r else None

    def create(self, task: AnalysisTask) -> int:
        cur = self.con.execute(
            "INSERT INTO analysis_task(name,code,days,compare_codes,benchmark,"
            "created_at) VALUES(?,?,?,?,?,?)",
            (task.name, str(task.code).split(".")[0], int(task.days),
             ",".join(task.compare_codes), task.benchmark,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.con.commit()
        return int(cur.lastrowid or 0)

    def delete(self, task_id: int) -> bool:
        cur = self.con.execute("DELETE FROM analysis_task WHERE id=?", (task_id,))
        self.con.commit()
        return bool(cur.rowcount and cur.rowcount > 0)

    def touch(self, task_id: int) -> None:
        self.con.execute("UPDATE analysis_task SET last_run_at=? WHERE id=?",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
        self.con.commit()

    def count(self) -> int:
        r = self.con.execute("SELECT COUNT(*) FROM analysis_task").fetchone()
        return r[0] if r else 0
