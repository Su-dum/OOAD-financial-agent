# -*- coding: utf-8 -*-
"""新闻入库：归一化 -> 去重 -> 落库 -> 实体链接。"""
import re
import hashlib
import sqlite3
from datetime import datetime, timezone

from ... import db as dbmod
from ...domain import entity_linking as stock_link

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[，。！？；：、“”‘’（）《》【】…—\-,.!?;:\"'()\[\]<>~`]")

_INDEX = None


def get_index():
    global _INDEX
    if _INDEX is None:
        _INDEX = stock_link.build_index(dbmod.STOCK_MAP_CSV)
    return _INDEX


def norm_text(s):
    if not s:
        return ""
    s = _WS_RE.sub(" ", str(s)).strip()
    return s


def content_hash(title, content):
    t = _PUNCT_RE.sub("", norm_text(title))
    c = _PUNCT_RE.sub("", norm_text(content))
    return hashlib.md5(f"{t}|{c[:400]}".encode("utf-8")).hexdigest()


def ingest(con, rows, link=True, log=print, source_label=None):
    """写入一批新闻并建立股票关联。返回统计 dict。"""
    idx = get_index() if link else None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = skipped = linked = 0
    invalid = 0

    for r in rows:
        title = norm_text(r.get("title"))
        content = norm_text(r.get("content"))
        pub = r.get("published_at")
        if not title or not pub:
            invalid += 1
            continue
        h = content_hash(title, content)
        try:
            cur = con.execute(
                "INSERT INTO news(source,channel,title,content,published_at,url,"
                "content_hash,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
                (r.get("source"), r.get("channel"), title, content or None,
                 pub, r.get("url"), h, now))
        except sqlite3.IntegrityError:
            skipped += 1
            continue
        nid = cur.lastrowid
        inserted += 1

        if link and idx is not None:
            hits = stock_link.extract(f"{title} {content or ''}", idx)
            if hits:
                params = [(nid, code, idx_name(code, idx), mtype, conf)
                          for code, (mtype, conf) in hits.items()]
                con.executemany(
                    "INSERT OR REPLACE INTO news_stock(news_id,stock_code,stock_name,"
                    "match_type,confidence) VALUES(?,?,?,?,?)", params)
                linked += len(params)

    con.commit()
    stats = dict(fetched=len(rows), inserted=inserted, skipped=skipped,
                 linked=linked, invalid=invalid)
    con.execute(
        "INSERT INTO collect_log(run_at,source,fetched,inserted,skipped,linked,note) "
        "VALUES(?,?,?,?,?,?,?)",
        (now, source_label or "-", len(rows), inserted, skipped, linked, None))
    con.commit()
    log(f"  -> 取 {len(rows)} 条 | 新增 {inserted} | 重复 {skipped} | "
        f"无效 {invalid} | 股票关联 {linked} 条")
    return stats


_NAME_CACHE = {}


def idx_name(code, idx):
    """反查股票简称（用于 news_stock 冗余存储）"""
    if not _NAME_CACHE:
        for name, lst in idx.names.items():
            for c, real, _, _ in lst:
                _NAME_CACHE.setdefault(c, real)
    return _NAME_CACHE.get(code)


def rebuild_links(con, log=print):
    """对库里已有新闻重算股票关联（改了词典之后可用）。"""
    idx = get_index()
    con.execute("DELETE FROM news_stock")
    rows = con.execute("SELECT id,title,content FROM news").fetchall()
    n = 0
    for r in rows:
        hits = stock_link.extract(f"{r['title']} {r['content'] or ''}", idx)
        if not hits:
            continue
        con.executemany(
            "INSERT OR REPLACE INTO news_stock(news_id,stock_code,stock_name,"
            "match_type,confidence) VALUES(?,?,?,?,?)",
            [(r["id"], c, idx_name(c, idx), t, cf) for c, (t, cf) in hits.items()])
        n += len(hits)
    con.commit()
    log(f"  重建关联：{len(rows)} 条新闻 -> {n} 条关联")
    return n


def search(con, keyword=None, stock_code=None, start=None, end=None,
           limit=20, min_conf=0.85):
    """按关键词或股票检索新闻（演示 / 调试用）。"""
    sql = ["SELECT DISTINCT n.id,n.published_at,n.source,n.title,n.url FROM news n"]
    args = []
    if stock_code:
        sql.append("JOIN news_stock ns ON ns.news_id=n.id")
    where = []
    if stock_code:
        where.append("ns.stock_code=? AND ns.confidence>=?")
        args += [stock_code, min_conf]
    if keyword:
        where.append("(n.title LIKE ? OR n.content LIKE ?)")
        args += [f"%{keyword}%", f"%{keyword}%"]
    if start:
        where.append("n.published_at>=?"); args.append(start)
    if end:
        where.append("n.published_at<=?"); args.append(end)
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY n.published_at DESC LIMIT ?")
    args.append(limit)
    return con.execute(" ".join(sql), args).fetchall()


def summary(con):
    q = lambda s: con.execute(s).fetchone()[0]
    return dict(
        news=q("SELECT COUNT(*) FROM news"),
        stocks_in_news=q("SELECT COUNT(DISTINCT stock_code) FROM news_stock"),
        links=q("SELECT COUNT(*) FROM news_stock"),
        linked_news=q("SELECT COUNT(DISTINCT news_id) FROM news_stock"),
        earliest=q("SELECT MIN(published_at) FROM news"),
        latest=q("SELECT MAX(published_at) FROM news"),
    )
