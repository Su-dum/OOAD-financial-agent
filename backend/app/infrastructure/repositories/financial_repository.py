# -*- coding: utf-8 -*-
"""财务快照仓储（满足 domain.ports.FinancialRepository）。

一只票一行（最近一期报告），不做时间序列：
财务是季频，4 个点/年，存历史序列对「事件调查」没有额外价值，
而 `backfill` 一次就能从数据源重新取回。

TTL 逻辑放在应用层（`FinancialService`），仓储只负责存/取。
"""
from typing import Optional

from ...domain.financials import FIELDS, FinancialSnapshot

_COLUMNS = ("code", "report_date") + FIELDS + ("source", "fetched_at")
_SELECT = ", ".join(_COLUMNS)


class SqliteFinancialRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    def get(self, code: str) -> Optional[dict]:
        c = str(code).split(".")[0]
        r = self.con.execute(f"SELECT {_SELECT} FROM financial WHERE code=?",
                             (c,)).fetchone()
        return dict(zip(_COLUMNS, r)) if r else None

    def upsert(self, snapshot: FinancialSnapshot) -> None:
        row = snapshot.to_dict()
        placeholders = ",".join("?" for _ in _COLUMNS)
        updates = ",".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "code")
        self.con.execute(
            f"INSERT INTO financial({', '.join(_COLUMNS)}) VALUES({placeholders}) "
            f"ON CONFLICT(code) DO UPDATE SET {updates}",
            tuple(row.get(c) for c in _COLUMNS))
        self.con.commit()

    def count(self) -> int:
        r = self.con.execute("SELECT COUNT(*) FROM financial").fetchone()
        return r[0] if r else 0

    def stats(self) -> dict:
        q = lambda s: self.con.execute(s).fetchone()[0]     # noqa: E731
        return dict(financials=q("SELECT COUNT(*) FROM financial"),
                    latest_report=q("SELECT MAX(report_date) FROM financial"))
