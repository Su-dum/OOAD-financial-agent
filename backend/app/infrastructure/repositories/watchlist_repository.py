# -*- coding: utf-8 -*-
"""自选股仓储（SQLite 实现）。"""
from datetime import datetime

from ...domain.watchlist import WatchItem, Watchlist

# 首次启动时预置几条常见标的，避免界面空白
DEFAULT_CODES = ["600519", "000001", "300750", "601318", "002594", "601899"]


class SqliteWatchlistRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    # ---------------- 读 ----------------
    def load(self) -> Watchlist:
        wl = Watchlist()
        for r in self.con.execute(
                "SELECT code,name,industry,added_at,note FROM watchlist ORDER BY added_at"):
            wl.items.append(WatchItem(code=r[0], name=r[1] or "",
                                      industry=r[2] or "", added_at=r[3] or "",
                                      note=r[4] or ""))
        return wl

    # ---------------- 写 ----------------
    def save_item(self, item: WatchItem) -> None:
        self.con.execute(
            "INSERT INTO watchlist(code,name,industry,added_at,note) VALUES(?,?,?,?,?) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, "
            "industry=excluded.industry, note=excluded.note",
            (item.code, item.name, item.industry,
             item.added_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item.note))
        self.con.commit()

    def delete(self, code: str) -> bool:
        cur = self.con.execute("DELETE FROM watchlist WHERE code=?", (code.split(".")[0],))
        self.con.commit()
        return (cur.rowcount or 0) > 0

    def seed_defaults(self, catalog=None) -> int:
        """表为空时预置默认标的。"""
        n = self.con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if n:
            return 0
        added = 0
        for c in DEFAULT_CODES:
            name = catalog.name_of(c) if catalog else ""
            industry = catalog.industry_of(c) if catalog else ""
            self.save_item(WatchItem(code=c, name=name, industry=industry,
                                     added_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                     note="默认自选"))
            added += 1
        return added
