# -*- coding: utf-8 -*-
"""公告仓储（满足 domain.ports.NoticeRepository）。

为什么公告要落本地库，而新闻也落库、事件也落库？

  - 公告是「事件触发的依据」：B2 把公告变成事件，B3 又要用公告做证据，
    两次读的是**同一批数据**，必须落一次、复用两次。
  - 外部公告接口有限频（东财实测 3~4 条/秒级），用户点一下「调查」不该去打它。
  - 事件与报告都要求**可复现**：一周后回看这条事件，公告必须还在库里。
"""
import re
from datetime import datetime
from typing import Optional, Sequence

from ...domain.notices import clean_title

_FIELDS = ("code", "name", "notice_type", "title", "published_at", "url", "source")
_SELECT = ", ".join(_FIELDS)


def _clean(s) -> Optional[str]:
    if s is None:
        return None
    t = str(s).strip()
    return t or None


class SqliteNoticeRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    # ---------------- 写 ----------------
    def save_many(self, items: Sequence[dict]) -> int:
        rows = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for it in items or ():
            code = re.sub(r"[^0-9]", "", str(it.get("code") or ""))[:6]
            name = _clean(it.get("name"))
            # 在这一层统一清洗「名称:标题」前缀：所有写入路径都经过这里，
            # 比在三个 Provider 里各写一遍更不容易漏
            title = _clean(clean_title(str(it.get("title") or ""), name or ""))
            published = _clean(it.get("published_at")) or ""
            if not code or not title or not published:
                continue
            rows.append((code, name, _clean(it.get("notice_type")),
                         title, published[:10], _clean(it.get("url")),
                         _clean(it.get("source")) or "cninfo", now))
        if not rows:
            return 0
        cur = self.con.executemany(
            "INSERT OR IGNORE INTO notice(code,name,notice_type,title,published_at,"
            "url,source,fetched_at) VALUES(?,?,?,?,?,?,?,?)", rows)
        self.con.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    # ---------------- 读 ----------------
    def find_by_stock(self, code: str, start: Optional[str] = None,
                      end: Optional[str] = None, limit: int = 200) -> list[dict]:
        c = str(code).split(".")[0]
        sql = (f"SELECT {_SELECT} FROM notice WHERE code=?")
        args: list = [c]
        if start:
            sql += " AND published_at>=?"
            args.append(str(start)[:10])
        if end:
            sql += " AND published_at<=?"
            args.append(str(end)[:10])
        sql += " ORDER BY published_at DESC, id DESC LIMIT ?"
        args.append(int(limit))
        return [dict(zip(_FIELDS, r)) for r in self.con.execute(sql, args)]

    def latest_date(self, code: str) -> Optional[str]:
        c = str(code).split(".")[0]
        r = self.con.execute("SELECT MAX(published_at) FROM notice WHERE code=?",
                             (c,)).fetchone()
        return r[0] if r and r[0] else None

    def count(self, code: Optional[str] = None) -> int:
        if code:
            r = self.con.execute("SELECT COUNT(*) FROM notice WHERE code=?",
                                 (str(code).split(".")[0],)).fetchone()
        else:
            r = self.con.execute("SELECT COUNT(*) FROM notice").fetchone()
        return r[0] if r else 0

    def stats(self) -> dict:
        q = lambda s: self.con.execute(s).fetchone()[0]     # noqa: E731
        return dict(
            notices=q("SELECT COUNT(*) FROM notice"),
            codes=q("SELECT COUNT(DISTINCT code) FROM notice"),
            earliest=q("SELECT MIN(published_at) FROM notice"),
            latest=q("SELECT MAX(published_at) FROM notice"),
        )
