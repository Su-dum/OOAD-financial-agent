# -*- coding: utf-8 -*-
"""行业监控列表仓储（B1）。

对应「Monitor selected ... industries」：用户把感兴趣的申万一级行业加入监控，
刷新时对这些**行业指数**做同一套事件检测。
"""
from datetime import datetime
from typing import Optional

from ...domain.industry import DEFAULT_WATCH_NAMES

_COLUMNS = ("code", "name", "added_at")
_SELECT = ", ".join(_COLUMNS)


class SqliteIndustryWatchRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    def load(self) -> list[dict]:
        rows = self.con.execute(
            f"SELECT {_SELECT} FROM industry_watch ORDER BY added_at, code").fetchall()
        return [dict(zip(_COLUMNS, r)) for r in rows]

    def codes(self) -> list[str]:
        return [r["code"] for r in self.load()]

    def has(self, code: str) -> bool:
        r = self.con.execute("SELECT 1 FROM industry_watch WHERE code=?",
                             (str(code).strip(),)).fetchone()
        return r is not None

    def add(self, code: str, name: str = "") -> bool:
        c = str(code).strip()
        if not c or self.has(c):
            return False
        self.con.execute(
            "INSERT INTO industry_watch(code,name,added_at) VALUES(?,?,?)",
            (c, name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.con.commit()
        return True

    def remove(self, code: str) -> bool:
        cur = self.con.execute("DELETE FROM industry_watch WHERE code=?",
                               (str(code).strip(),))
        self.con.commit()
        return bool(cur.rowcount and cur.rowcount > 0)

    def count(self) -> int:
        r = self.con.execute("SELECT COUNT(*) FROM industry_watch").fetchone()
        return r[0] if r else 0

    def seed_defaults(self, catalog) -> int:
        """首次启动时放几个有代表性的行业，让界面不是空的（幂等）。"""
        if self.count() > 0 or catalog is None:
            return 0
        wanted = []
        for name in DEFAULT_WATCH_NAMES:
            row = catalog.industry(name)
            if row:
                wanted.append(row)
        if not wanted:
            wanted = catalog.industries()[:3]
        n = 0
        for row in wanted:
            if self.add(row["code"], row.get("name") or ""):
                n += 1
        return n
