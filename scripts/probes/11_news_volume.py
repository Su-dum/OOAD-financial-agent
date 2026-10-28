# -*- coding: utf-8 -*-
"""估算新闻采集的存储开销。

方法：
  1. 拉真实数据，量出「每条记录的实际字节数」
  2. 从时间戳跨度反推「每日新增条数」（财联社只有当日 20 条，无法直接数）
  3. 造一个真实 schema 的 SQLite，把样本塞进去，量出「每行实际占用的磁盘字节」
  4. 按 1 / 3 / 6 / 12 个月投影，并对比加 FTS5 全文索引后的开销
"""
import os, sys, io, time, json, sqlite3, hashlib
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)
LOG_PATH = os.path.join(OUT, "11_news_volume.txt")
open(LOG_PATH, "w", encoding="utf-8").close()
TMP_DB = os.path.join(OUT, "_volume_test.db")

WATCH_STOCKS = ["600519", "000001", "300750", "601318", "000858",
                "600036", "002594", "601899", "600030", "000651"]


def log(s=""):
    line = str(s)
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


import akshare as ak
import pandas as pd


def retry(fn, name, n=3, base=4):
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            log(f"    [retry {i+1}/{n}] {name}: {type(e).__name__}")
            if i < n - 1:
                time.sleep(base * 2 ** i)
    log(f"    [FAIL] {name}")
    return None


log("=" * 72)
log("新闻采集 存储开销估算")
log("=" * 72)

records = []   # 统一结构的样本

# ---------- 1. 财联社电报 ----------
log("\n[1] 财联社电报 stock_info_global_cls")
cls = retry(lambda: ak.stock_info_global_cls(symbol="全部"), "财联社")
if cls is not None:
    log(f"    {len(cls)} 条，列 {list(cls.columns)}")
    for _, r in cls.iterrows():
        ts = f"{r['发布日期']} {r['发布时间']}"
        records.append(dict(source="cls", title=r["标题"], content=r["内容"],
                            published_at=ts, url=None))
    def _span(df, datecol, timecol):
        try:
            t = pd.to_datetime(df[datecol].astype(str) + " " + df[timecol].astype(str))
            return (t.max() - t.min()).total_seconds() / 86400
        except Exception:
            return None
    sp = _span(cls, "发布日期", "发布时间")
    log(f"    时间跨度 {sp:.3f} 天" if sp else "    跨度未知")
    if sp and sp > 0:
        log(f"    按此速度外推: {len(cls)/sp:.0f} 条/天")

# ---------- 2. 东财快讯 ----------
log("\n[2] 东财全球快讯 stock_info_global_em")
em = retry(lambda: ak.stock_info_global_em(), "东财快讯")
if em is not None:
    log(f"    {len(em)} 条，列 {list(em.columns)}")
    for _, r in em.iterrows():
        records.append(dict(source="em_flash", title=r["标题"], content=r["摘要"],
                            published_at=str(r["发布时间"]), url=r["链接"]))
    try:
        t = pd.to_datetime(em["发布时间"].astype(str))
        sp2 = (t.max() - t.min()).total_seconds() / 86400
        log(f"    时间跨度 {sp2:.3f} 天 -> 按此速度 {len(em)/sp2:.0f} 条/天" if sp2 > 0 else "")
    except Exception as e:
        sp2 = None
        log(f"    跨度计算失败 {e}")

# ---------- 3. 个股新闻 ----------
log(f"\n[3] 个股新闻 stock_news_em（抽样 {len(WATCH_STOCKS)} 只自选股）")
per_stock_rate = []
for code in WATCH_STOCKS[:5]:
    d = retry(lambda c=code: ak.stock_news_em(symbol=c), f"news {code}", n=2, base=3)
    if d is None or len(d) == 0:
        continue
    for _, r in d.iterrows():
        records.append(dict(source="em_stock", title=r["新闻标题"], content=r["新闻内容"],
                            published_at=str(r["发布时间"]), url=r["新闻链接"]))
    try:
        t = pd.to_datetime(d["发布时间"].astype(str))
        sp3 = (t.max() - t.min()).total_seconds() / 86400
        if sp3 > 0:
            per_stock_rate.append(len(d) / sp3)
            log(f"    {code}: {len(d)} 条 / {sp3:.2f} 天 -> {len(d)/sp3:.1f} 条/天")
    except Exception:
        pass
    time.sleep(1.0)

log(f"\n    累计样本 {len(records)} 条")

# ---------- 4. 单条记录字节数 ----------
log("\n[4] 单条记录字节数")
sizes = []
for r in records:
    blob = (str(r["title"]) + str(r["content"]) + str(r["published_at"])
            + str(r["url"]) + str(r["source"])).encode("utf-8")
    sizes.append(len(blob))
s = pd.Series(sizes)
log(f"    有效内容 UTF-8 字节: 均值 {s.mean():.0f}  中位 {s.median():.0f}  "
    f"最大 {s.max()}  P95 {s.quantile(0.95):.0f}")
cjk = pd.Series([len(str(r["content"])) for r in records])
log(f"    正文字数: 均值 {cjk.mean():.0f}  中位 {cjk.median():.0f}  最大 {cjk.max()}")

# ---------- 5. 真实 SQLite 体积 ----------
log("\n[5] 真实 SQLite 体积实测")

SCHEMA = """
CREATE TABLE news (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    content      TEXT,
    published_at TEXT NOT NULL,
    url          TEXT,
    fetched_at   TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX idx_news_pub ON news(published_at);
CREATE INDEX idx_news_source ON news(source, published_at);
"""


def build(db_path, rows, with_fts=False):
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    if with_fts:
        con.executescript("""
        CREATE VIRTUAL TABLE news_fts USING fts5(
            title, content, content='news', content_rowid='id',
            tokenize='unicode61');
        """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = []
    for i, r in enumerate(rows):
        # 测试用：把序号混进 hash，避免重复样本撞 UNIQUE 约束
        h = hashlib.md5((str(r["title"]) + str(r["content"]) + str(i)).encode("utf-8")).hexdigest()
        data.append((r["source"], r["title"], r["content"], r["published_at"],
                     r["url"], now, h))
    con.executemany("INSERT INTO news (source,title,content,published_at,url,fetched_at,"
                    "content_hash) VALUES (?,?,?,?,?,?,?)", data)
    if with_fts:
        con.execute("INSERT INTO news_fts(news_fts) VALUES('rebuild')")
    con.commit()
    con.execute("VACUUM")
    con.close()
    return os.path.getsize(db_path)


PLAN = [
    ("cls", 20, 60, "财联社电报 20 条/次，按实测速度外推"),
    ("em_flash", 200, 400, "东财快讯 200 条/次，按实测速度外推"),
    ("em_stock", 50, 30, f"自选股 {len(WATCH_STOCKS)} 只 x 约 3 条/天"),
]

log("    先实测 3 个不同规模下的每行占用（含索引、含 SQLite 页开销）:")
for n in (500, 2000, 8000):
    rows = [records[i % len(records)] for i in range(n)]
    b = build(TMP_DB, rows)
    log(f"        {n:5d} 行 -> {b/1024:8.1f} KB  ({b/n:6.0f} 字节/行)")

rows_all = [records[i % len(records)] for i in range(4000)]
b_plain = build(TMP_DB, rows_all)
b_fts = build(TMP_DB, rows_all, with_fts=True)
log(f"    4000 行：普通索引 {b_plain/1024:.0f} KB ({b_plain/4000:.0f} B/行) | "
    f"FTS5 全文索引 {b_fts/1024:.0f} KB ({b_fts/4000:.0f} B/行) | "
    f"FTS 额外 +{(b_fts/b_plain-1)*100:.0f}%")

B_PER_ROW = b_plain / 4000
B_PER_ROW_FTS = b_fts / 4000

# ---------- 6. 日增估算 ----------
log("\n[6] 日增量与投影")

# 财联社：只有当日 20 条，用「发布密度」估：一天 7x24 快讯约 100-250 条
# 用东财 200 条的实测跨度做交叉参考
daily_cls = None
if cls is not None:
    try:
        t = pd.to_datetime(cls["发布日期"].astype(str) + " " + cls["发布时间"].astype(str))
        # 20 条覆盖的小时数已说明密度
        span_h = (t.max() - t.min()).total_seconds() / 3600
        if span_h > 0:
            daily_cls = 20 / span_h * 24
    except Exception:
        pass
if em is not None:
    try:
        t = pd.to_datetime(em["发布时间"].astype(str))
        span_h = (t.max() - t.min()).total_seconds() / 3600
        daily_em = 200 / span_h * 24 if span_h > 0 else None
    except Exception:
        daily_em = None
else:
    daily_em = None

if per_stock_rate:
    daily_stock = sum(per_stock_rate) / len(per_stock_rate) * len(WATCH_STOCKS)
else:
    daily_stock = 0

log(f"    财联社    约 {daily_cls:6.0f} 条/天  (由 20 条的发布密度外推)" if daily_cls else "    财联社    未知")
log(f"    东财快讯  约 {daily_em:6.0f} 条/天  (由 200 条跨度外推)" if daily_em else "    东财快讯  未知")
log(f"    个股新闻  约 {daily_stock:6.0f} 条/天  ({len(WATCH_STOCKS)} 只自选股)")

daily = (daily_cls or 150) + (daily_em or 400) + daily_stock
log(f"\n    合计日增（估算，含重复，去重后通常为 60~80%）: {daily:.0f} 条/天")

log("\n    存储投影：三档敏感性（峰值外推会偏高，故给区间）")
log("    " + "-" * 66)
SCEN = [("保守", 300), ("中性", 600), ("激进", 1200)]
for sname, base_daily in SCEN:
    log(f"\n    【{sname}】{base_daily} 条/天，去重后 {base_daily*0.75:.0f} 条/天")
    for label, days in (("1 个月", 30), ("3 个月", 90), ("6 个月", 182),
                        ("1 年", 365), ("3 年", 1095)):
        n = base_daily * 0.75 * days
        log(f"        {label:<8} {n:>10,.0f} 行 | 普通 {n*B_PER_ROW/1024/1024:7.1f} MB | "
            f"+FTS5 {n*B_PER_ROW_FTS/1024/1024:7.1f} MB")

if os.path.exists(TMP_DB):
    os.remove(TMP_DB)
log("\n" + "=" * 72)
