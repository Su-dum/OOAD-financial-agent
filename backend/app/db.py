# -*- coding: utf-8 -*-
"""SQLite 连接与建表。新闻库独立于行情库，放在 data/news.db。"""
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
NEWS_DB = DATA_DIR / "news.db"
INDUSTRY_DB = DATA_DIR / "sw_industry.db"
STOCK_MAP_CSV = SEED_DIR / "sw_stock_map.csv"


def connect(db_path=None):
    path = Path(db_path) if db_path else NEWS_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _has_trigram(con):
    try:
        con.execute("CREATE VIRTUAL TABLE _t USING fts5(x, tokenize='trigram')")
        con.execute("DROP TABLE _t")
        return True
    except sqlite3.Error:
        return False


def init_schema(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS stock (
        code            TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        industry_l1_name TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_stock_name ON stock(name);

    CREATE TABLE IF NOT EXISTS news (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        source       TEXT NOT NULL,
        channel      TEXT,
        title        TEXT NOT NULL,
        content      TEXT,
        published_at TEXT NOT NULL,
        url          TEXT,
        content_hash TEXT NOT NULL UNIQUE,
        fetched_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_news_pub ON news(published_at DESC);
    CREATE INDEX IF NOT EXISTS idx_news_src ON news(source, published_at DESC);

    CREATE TABLE IF NOT EXISTS news_stock (
        news_id     INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
        stock_code  TEXT NOT NULL,
        stock_name  TEXT,
        match_type  TEXT NOT NULL,
        confidence  REAL NOT NULL,
        PRIMARY KEY (news_id, stock_code)
    );
    CREATE INDEX IF NOT EXISTS idx_ns_stock ON news_stock(stock_code);
    CREATE INDEX IF NOT EXISTS idx_ns_conf ON news_stock(stock_code, confidence DESC);

    CREATE TABLE IF NOT EXISTS collect_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at     TEXT NOT NULL,
        source     TEXT,
        fetched    INTEGER,
        inserted   INTEGER,
        skipped    INTEGER,
        linked     INTEGER,
        note       TEXT
    );

    -- 事件（B2）：同一标的、同一类型、同一交易日、同一规则只记一条
    CREATE TABLE IF NOT EXISTS event (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        code        TEXT NOT NULL,
        name        TEXT,
        event_type  TEXT NOT NULL,
        trade_date  TEXT NOT NULL,
        detected_at TEXT NOT NULL,
        severity    TEXT,
        value       REAL,
        threshold   REAL,
        detail      TEXT,
        rule_name   TEXT,
        UNIQUE(code, event_type, trade_date, rule_name)
    );
    CREATE INDEX IF NOT EXISTS idx_event_code_date ON event(code, trade_date DESC);

    -- 调查报告（B3）：JSON 原文 + 冗余 markdown
    CREATE TABLE IF NOT EXISTS report (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        code       TEXT NOT NULL,
        name       TEXT,
        question   TEXT,
        created_at TEXT NOT NULL,
        payload    TEXT NOT NULL,
        markdown   TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_report_code ON report(code, id DESC);

    -- 高置信度关联视图：confidence>=0.85。
    -- 3 字简称（如「机器人」=300024）以及行业通用词会被降权到 0.40~0.70，
    -- 默认查询走这个视图即可过滤掉「人形机器人赛道」这类误匹配。
    CREATE VIEW IF NOT EXISTS v_news_stock_high AS
        SELECT ns.news_id, ns.stock_code, ns.stock_name, ns.match_type, ns.confidence,
               n.published_at, n.source, n.title, n.url
        FROM news_stock ns
        JOIN news n ON n.id = ns.news_id
        WHERE ns.confidence >= 0.85;
    """)

    # 全文检索：优先 trigram（中文子串可用），退化到 unicode61
    try:
        con.execute("SELECT 1 FROM news_fts LIMIT 1")
    except sqlite3.Error:
        tok = "trigram" if _has_trigram(con) else "unicode61"
        try:
            con.execute(f"CREATE VIRTUAL TABLE news_fts USING fts5("
                        f"title, content, tokenize='{tok}')")
            con.execute("""
                CREATE TRIGGER IF NOT EXISTS news_fts_ai AFTER INSERT ON news BEGIN
                    INSERT INTO news_fts(rowid, title, content)
                    VALUES (new.id, new.title, new.content);
                END;""")
            con.execute("""
                CREATE TRIGGER IF NOT EXISTS news_fts_ad AFTER DELETE ON news BEGIN
                    DELETE FROM news_fts WHERE rowid = old.id;
                END;""")
            con.execute(f"PRAGMA user_version=1")
            print(f"[db] FTS5 已启用（tokenize={tok}）")
        except sqlite3.Error as e:
            print(f"[db] FTS5 建表失败，跳过：{e}")
    con.commit()
    return con


def sync_stocks(con):
    """把申万映射表同步进新闻库的 stock 表，便于按行业聚合。"""
    import csv
    if not STOCK_MAP_CSV.exists():
        print(f"[db] 未找到 {STOCK_MAP_CSV}，跳过股票同步")
        return 0
    rows = []
    with open(STOCK_MAP_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = (r.get("code") or "").strip()
            if not code:
                continue
            rows.append((code, (r.get("name") or code).strip(),
                         (r.get("industry_l1_name") or "").strip() or None))
    con.executemany(
        "INSERT INTO stock(code,name,industry_l1_name) VALUES(?,?,?) "
        "ON CONFLICT(code) DO UPDATE SET name=excluded.name, "
        "industry_l1_name=excluded.industry_l1_name", rows)
    con.commit()
    print(f"[db] 已同步股票 {len(rows)} 只")
    return len(rows)
