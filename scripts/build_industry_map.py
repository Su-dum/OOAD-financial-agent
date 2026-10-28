# -*- coding: utf-8 -*-
"""构建申万行业分类映射表并落库（可断点续跑）。

决策：行业分类体系固定为【申万一级】（31 个行业）。
理由：历史最长（1999 年至今）、自带 PE/PB/股息率、31 个粒度对课程作业足够、
      且 akshare 提供稳定的 `sw_index_*` 系列接口。

产出（均可提交）：
  data/seed/sw_industry.csv        行业三级结构（一级/二级/三级 + 估值）
  data/seed/sw_stock_map.csv       个股 -> 申万一级行业 + 估值/成长快照
  data/sw_industry.db              SQLite（.gitignore 忽略，可由本脚本随时重建）

用法：
  python scripts/build_industry_map.py              # 增量：只补缺失的行业
  python scripts/build_industry_map.py --force      # 全量重抓
  python scripts/build_industry_map.py --delay 2    # 放慢请求间隔

  被限流时（429 / 504）用更强的退避：
  python scripts/build_industry_map.py --delay 25 --backoff 40 --retries 4

注意：
  legulegu.com 有激进的限流。连续抓几次就会返回 429，之后变成 504
  （`div#level1Items` 消失 -> AttributeError）。
  本脚本因此支持断点续跑：已抓到的行业会缓存到 CSV，下次只补缺的。
"""
import os
import sys
import io
import time
import random
import sqlite3
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import akshare as ak
import pandas as pd
import requests
from io import StringIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_DIR = os.path.join(ROOT, "data", "seed")
DB_PATH = os.path.join(ROOT, "data", "sw_industry.db")
IND_CSV = os.path.join(SEED_DIR, "sw_industry.csv")
STK_CSV = os.path.join(SEED_DIR, "sw_stock_map.csv")
os.makedirs(SEED_DIR, exist_ok=True)

FORCE = "--force" in sys.argv
DELAY = 1.2
if "--delay" in sys.argv:
    try:
        DELAY = float(sys.argv[sys.argv.index("--delay") + 1])
    except Exception:
        pass

# legulegu 的限流很凶：几次请求就 429 / 504。重试退避强度可调。
RETRIES = 3
BACKOFF = 3.0
if "--retries" in sys.argv:
    try:
        RETRIES = int(sys.argv[sys.argv.index("--retries") + 1])
    except Exception:
        pass
if "--backoff" in sys.argv:
    try:
        BACKOFF = float(sys.argv[sys.argv.index("--backoff") + 1])
    except Exception:
        pass

NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# legulegu 把 JSON-LD 嵌进 <th>，列名形如 '价格  {"@context":...}'。
# akshare 的清洗函数对部分行业会抛 ValueError，故自行清洗。
_TABLE_URL = "https://legulegu.com/stockdata/index-composition?industryCode={code}.SI"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TEXT_COLS = {"序号", "股票代码", "股票简称", "纳入时间", "细分概念",
              "申万级别", "申万1级", "申万2级", "申万3级"}

STOCK_FIELDS = ["code", "name", "industry_l1_code", "industry_l1_name", "list_date",
                "price", "pe", "pe_ttm", "pb", "roe", "dividend_yield",
                "market_cap", "profit_growth", "revenue_growth", "updated_at"]


def log(s=""):
    print(str(s), flush=True)


def _clean_header(c):
    s = str(c).split("{")[0].strip()
    return s or "unnamed"


def fetch_cons(code, retries=3, base=3):
    """自抓成份股表：清洗带 JSON-LD 的列名，并容错转数值。"""
    for i in range(retries):
        try:
            r = requests.get(_TABLE_URL.format(code=code),
                             headers={"User-Agent": _UA,
                                      "Referer": "https://legulegu.com/"},
                             timeout=30)
            r.raise_for_status()
            tables = pd.read_html(StringIO(r.text))
            if not tables:
                raise ValueError("页面上没有表格")
            t = max(tables, key=len)
            if not any("股票代码" in str(c) for c in t.columns):
                raise ValueError("表头异常（可能被反爬）")

            cols, seen = [], {}
            for c in t.columns:
                n = _clean_header(c)
                if n in seen:
                    seen[n] += 1
                    n = f"{n}_{seen[n]}"
                else:
                    seen[n] = 0
                cols.append(n)
            t.columns = cols

            for c in t.columns:
                if c in _TEXT_COLS:
                    continue
                t[c] = pd.to_numeric(
                    t[c].astype(str)
                        .str.replace("%", "", regex=False)
                        .str.replace(",", "", regex=False)
                        .str.strip(),
                    errors="coerce")
            return t
        except Exception as e:
            msg = str(e)
            # 429 说明被限流了，多等一会儿
            wait = base * (2 ** i)
            if "429" in msg:
                wait = max(wait, base * 3)
            log(f"    [retry {i+1}/{retries}] {code} {type(e).__name__}: "
                f"{msg[:60]} -> wait {wait:.0f}s")
            if i < retries - 1:
                time.sleep(wait)
    return None


def num(x):
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        return float(x)
    except Exception:
        return None


def txt(x):
    """安全转字符串；把 NaN / 'nan' / 空串统一成 None。"""
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    return None if s.lower() in ("nan", "none", "nat", "") else s


def norm_code(x):
    if x is None:
        return None
    s = str(x).strip()
    return s.split(".")[0] if "." in s else s


# ============================================================
# 1. 行业层级（优先复用缓存 CSV）
# ============================================================
log("=" * 70)
log("构建申万行业映射  (申万一级 31 个行业)" + ("  [全量重抓]" if FORCE else "  [增量]"))
log("=" * 70)

ind_df = None
if not FORCE and os.path.exists(IND_CSV):
    ind_df = pd.read_csv(IND_CSV, encoding="utf-8-sig", dtype={"code": str, "parent_code": str})
    log(f"\n[1] 行业层级：复用缓存 {os.path.basename(IND_CSV)}（{len(ind_df)} 行）")

if ind_df is None:
    log("\n[1] 行业层级：在线拉取")
    l1 = ak.sw_index_first_info()
    l2 = ak.sw_index_second_info()
    l3 = ak.sw_index_third_info()
    log(f"    一级 {len(l1)} / 二级 {len(l2)} / 三级 {len(l3)}")

    l1_name2code = {str(r["行业名称"]).strip(): norm_code(r["行业代码"]) for _, r in l1.iterrows()}
    l2_name2code = {str(r["行业名称"]).strip(): norm_code(r["行业代码"]) for _, r in l2.iterrows()}

    rows = []

    def add(df, level, parent_lookup):
        for _, r in df.iterrows():
            pname = str(r["上级行业"]).strip() if "上级行业" in df.columns else None
            rows.append(dict(
                code=norm_code(r["行业代码"]), level=level,
                name=str(r["行业名称"]).strip(),
                parent_code=parent_lookup.get(pname) if pname else None,
                parent_name=pname,
                stock_count=int(r["成份个数"]) if pd.notna(r.get("成份个数")) else None,
                pe_static=num(r.get("静态市盈率")),
                pe_ttm=num(r.get("TTM(滚动)市盈率")),
                pb=num(r.get("市净率")),
                dividend_yield=num(r.get("静态股息率")),
                updated_at=NOW))

    add(l1, 1, {})
    add(l2, 2, l1_name2code)
    add(l3, 3, l2_name2code)
    ind_df = pd.DataFrame(rows).sort_values(["level", "code"])
    ind_df.to_csv(IND_CSV, index=False, encoding="utf-8-sig")
    log(f"    已写入 {IND_CSV}")

l1_df = ind_df[ind_df["level"] == 1].reset_index(drop=True)
log(f"    一级行业 {len(l1_df)} 个")

# ============================================================
# 2. 成份股（增量：只抓缺失的行业）
# ============================================================
stocks = {}
if not FORCE and os.path.exists(STK_CSV):
    old = pd.read_csv(STK_CSV, encoding="utf-8-sig", dtype={"code": str,
                                                             "industry_l1_code": str})
    for _, r in old.iterrows():
        rec = {k: (None if pd.isna(r.get(k)) else r.get(k)) for k in STOCK_FIELDS}
        if not txt(rec.get("name")):
            rec["name"] = rec["code"]
        stocks[r["code"]] = rec
    log(f"\n[2] 成份股：已有缓存 {len(stocks)} 只（覆盖 "
        f"{old['industry_l1_code'].nunique()} 个行业）")

have = {}
for s in stocks.values():
    have[s["industry_l1_code"]] = have.get(s["industry_l1_code"], 0) + 1

todo = []
for _, r in l1_df.iterrows():
    code = norm_code(r["code"])
    expect = int(r["stock_count"]) if pd.notna(r["stock_count"]) else 0
    got = have.get(code, 0)
    if got < expect:
        todo.append((code, r["name"], expect, got))

log(f"\n[2] 成份股：待补 {len(todo)} 个行业"
    + (f" -> {[t[1] for t in todo]}" if todo else "（已完整）"))

failed = []
for i, (code, name, expect, got) in enumerate(todo, 1):
    d = fetch_cons(code, retries=RETRIES, base=BACKOFF)
    if d is None or len(d) == 0:
        failed.append(f"{code} {name}")
        log(f"    [{i:2d}/{len(todo)}] {name:<8} 失败")
        time.sleep(DELAY)
        continue

    added = 0
    c_profit = next((c for c in d.columns if str(c).startswith("净利润增速")), None)
    c_rev = next((c for c in d.columns if str(c).startswith("营收增速")), None)
    for _, s in d.iterrows():
        sc = norm_code(s["股票代码"])
        if not sc or sc in stocks:
            continue
        nm = txt(s["股票简称"]) or sc          # 源里个别股票无简称，用代码兜底
        stocks[sc] = dict(
            code=sc, name=nm,
            industry_l1_code=code, industry_l1_name=name,
            list_date=(txt(s["纳入时间"]) or "")[:10] or None,
            price=num(s.get("价格")), pe=num(s.get("市盈率")),
            pe_ttm=num(s.get("市盈率ttm")), pb=num(s.get("市净率")),
            roe=num(s.get("ROE(%)")), dividend_yield=num(s.get("股息率")),
            market_cap=num(s.get("市值")),
            profit_growth=num(s[c_profit]) if c_profit else None,
            revenue_growth=num(s[c_rev]) if c_rev else None,
            updated_at=NOW)
        added += 1
    log(f"    [{i:2d}/{len(todo)}] {name:<8} 取到 {len(d):4d} 只，新增 {added:4d}"
        + ("" if len(d) == expect else f"  ⚠️ 期望 {expect}"))
    # 增量落盘，避免中途失败丢进度
    pd.DataFrame(list(stocks.values())).to_csv(STK_CSV, index=False, encoding="utf-8-sig")
    time.sleep(DELAY + random.uniform(0, 0.4))

# ============================================================
# 3. 校验
# ============================================================
log("\n[3] 数据校验")
have = {}
for s in stocks.values():
    have[s["industry_l1_code"]] = have.get(s["industry_l1_code"], 0) + 1
log(f"    股票总数 {len(stocks)}  |  覆盖 {len(have)} / {len(l1_df)} 个一级行业")
declared = int(l1_df["stock_count"].fillna(0).sum())
log(f"    一级行业声明成份数之和 {declared}  |  实取 {len(stocks)}  |  差 {declared - len(stocks)}")

short = []
for _, r in l1_df.iterrows():
    c = norm_code(r["code"])
    exp = int(r["stock_count"] or 0)
    got = have.get(c, 0)
    if got < exp:
        short.append(f"{r['name']} {got}/{exp}")
if short:
    log(f"    ⚠️ 未补齐的行业 {len(short)} 个: {short}")
else:
    log("    ✅ 31 个一级行业全部补齐")
if failed:
    log(f"    ⚠️ 本轮抓取失败 {len(failed)} 个: {failed}（再次运行可续抓）")

# ============================================================
# 4. 落库
# ============================================================
log("\n[4] 写入 SQLite 与 CSV")
stk_df = pd.DataFrame([{k: s.get(k) for k in STOCK_FIELDS} for s in stocks.values()])
stk_df = stk_df.sort_values("code")
ind_df.to_csv(IND_CSV, index=False, encoding="utf-8-sig")
stk_df.to_csv(STK_CSV, index=False, encoding="utf-8-sig")
log(f"    {IND_CSV}  ({len(ind_df)} 行)")
log(f"    {STK_CSV}  ({len(stk_df)} 行)")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
con = sqlite3.connect(DB_PATH)
con.execute("PRAGMA foreign_keys = ON")
con.executescript("""
CREATE TABLE sw_industry (
    code TEXT PRIMARY KEY, level INTEGER NOT NULL, name TEXT NOT NULL,
    parent_code TEXT, parent_name TEXT, stock_count INTEGER,
    pe_static REAL, pe_ttm REAL, pb REAL, dividend_yield REAL, updated_at TEXT
);
CREATE INDEX idx_ind_level ON sw_industry(level);
CREATE INDEX idx_ind_parent ON sw_industry(parent_code);

CREATE TABLE stock (
    code TEXT PRIMARY KEY, name TEXT NOT NULL,
    industry_l1_code TEXT NOT NULL, industry_l1_name TEXT NOT NULL,
    list_date TEXT, price REAL, pe REAL, pe_ttm REAL, pb REAL, roe REAL,
    dividend_yield REAL, market_cap REAL, profit_growth REAL,
    revenue_growth REAL, updated_at TEXT
);
CREATE INDEX idx_stock_industry ON stock(industry_l1_code);

CREATE VIEW v_industry_l1 AS
SELECT i.code, i.name, i.stock_count AS declared_count,
       COUNT(s.code) AS actual_count,
       i.pe_static, i.pe_ttm, i.pb, i.dividend_yield
FROM sw_industry i
LEFT JOIN stock s ON s.industry_l1_code = i.code
WHERE i.level = 1
GROUP BY i.code;
""")
ind_df.to_sql("sw_industry", con, if_exists="append", index=False)
stk_df.to_sql("stock", con, if_exists="append", index=False)
con.commit()

# ============================================================
# 5. 回读确认
# ============================================================
log("\n[5] 回读确认")
cur = con.cursor()
log(f"    sw_industry: {cur.execute('SELECT COUNT(*) FROM sw_industry').fetchone()[0]} 行")
log(f"    stock:       {cur.execute('SELECT COUNT(*) FROM stock').fetchone()[0]} 行")
log("    一级行业覆盖（实际 / 声明）：")
incomplete = []
for row in cur.execute("SELECT name, declared_count, actual_count FROM v_industry_l1 "
                       "ORDER BY actual_count DESC"):
    flag = "" if row[1] == row[2] else "  ⚠️"
    if row[1] != row[2]:
        incomplete.append(f"{row[0]} {row[2]}/{row[1]}")
    log(f"        {row[0]:<8} {row[2]:>4} / {row[1]:>4}{flag}")
if incomplete:
    log(f"    未补齐: {incomplete}")
log("\n    抽样（行业 + 估值 + 成长）:")
for row in cur.execute(
        "SELECT code, name, industry_l1_name, pe_ttm, pb, roe, profit_growth "
        "FROM stock WHERE code IN ('600519','000001','300750','601318','600313')"):
    log(f"        {row[0]} {str(row[1]):<6} {str(row[2]):<8} "
        f"peTTM={row[3]} pb={row[4]} roe={row[5]} 净利润增速={row[6]}")
con.close()
log(f"\n完成。数据库：{DB_PATH}")
