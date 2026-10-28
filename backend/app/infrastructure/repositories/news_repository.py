# -*- coding: utf-8 -*-
"""新闻仓储（满足 domain.ports.NewsRepository）。

作为门面把底层 `news_store` 的函数包装成对象，让应用层只依赖协议。
"""
from typing import Optional, Sequence

from ... import db as dbmod
from . import news_store


class SqliteNewsRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    @classmethod
    def open(cls, db_path=None, log=print) -> "SqliteNewsRepository":
        con = dbmod.connect(db_path)
        dbmod.init_schema(con)
        dbmod.sync_stocks(con)
        return cls(con, log=log)

    # ---------------- 写 ----------------
    def save(self, items: Sequence[dict]) -> tuple[int, int]:
        st = news_store.ingest(self.con, list(items), link=True, log=self.log,
                              source_label="repository")
        return st["inserted"], st["skipped"]

    def rebuild_links(self) -> int:
        return news_store.rebuild_links(self.con, log=self.log)

    # ---------------- 读 ----------------
    def find_by_stock(self, code: str, start: Optional[str] = None,
                      end: Optional[str] = None, limit: int = 20,
                      min_confidence: float = 0.85) -> list[dict]:
        rows = news_store.search(self.con, stock_code=code, start=start, end=end,
                                 limit=limit, min_conf=min_confidence)
        return [dict(r) for r in rows]

    def find_by_keyword(self, keyword: str, limit: int = 20) -> list[dict]:
        rows = news_store.search(self.con, keyword=keyword, limit=limit)
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        return news_store.summary(self.con)

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass
