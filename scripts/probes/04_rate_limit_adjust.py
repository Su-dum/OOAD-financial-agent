# -*- coding: utf-8 -*-
"""验证：限频退避重试是否有效 + 复权口径 + baostock 交叉校验 + 巨潮类型名"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import akshare as ak

import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT, exist_ok=True)
LOG = []
def log(s=""):
    print(s); LOG.append(str(s))


def retry(fn, name, attempts=3, base=4):
    """指数退避重试 —— 验证'偶发失败能否自愈'"""
    for i in range(attempts):
        t0 = time.time()
        try:
            r = fn()
            log(f"    [OK  ] {name} 第{i+1}次成功 ({time.time()-t0:.1f}s)")
            return r
        except Exception as e:
            log(f"    [FAIL] {name} 第{i+1}次 {type(e).__name__} ({time.time()-t0:.1f}s)")
            if i < attempts - 1:
                wait = base * (2 ** i)
                log(f"           退避 {wait}s ...")
                time.sleep(wait)
    return None


log("=" * 74)
log("待验证项 3/3：限频退避 · 复权口径 · baostock 交叉校验")
log("=" * 74)

# ---------- A. 复权口径（带重试） ----------
log("\n[A] 复权口径三态差异（东财 + 退避重试）")
kw = dict(symbol="600519", period="daily", start_date="20240101", end_date="20261028")
qfq = retry(lambda: ak.stock_zh_a_hist(**kw, adjust="qfq"), "stock_zh_a_hist(qfq)")
time.sleep(2)
raw = retry(lambda: ak.stock_zh_a_hist(**kw, adjust=""), "stock_zh_a_hist(不复权)")

if qfq is not None and raw is not None:
    m = qfq[["日期", "收盘"]].merge(raw[["日期", "收盘"]], on="日期", suffixes=("_qfq", "_raw"))
    m = m.astype({"收盘_qfq": float, "收盘_raw": float})
    m["ret_qfq"] = m["收盘_qfq"].pct_change()
    m["ret_raw"] = m["收盘_raw"].pct_change()
    m["diff"] = (m["ret_qfq"] - m["ret_raw"]).abs()
    log(f"    对齐 {len(m)} 个交易日")
    log(f"    首日  qfq={m.iloc[0]['收盘_qfq']:.2f}  raw={m.iloc[0]['收盘_raw']:.2f}")
    log(f"    末日  qfq={m.iloc[-1]['收盘_qfq']:.2f}  raw={m.iloc[-1]['收盘_raw']:.2f}")
    log(f"    区间累计收益  qfq={m['收盘_qfq'].iloc[-1]/m['收盘_qfq'].iloc[0]-1:+.2%}  "
        f"raw={m['收盘_raw'].iloc[-1]/m['收盘_raw'].iloc[0]-1:+.2%}")
    n = int((m["diff"] > 0.001).sum())
    log(f"    日收益差异 >0.1% 的交易日: {n} 个 / 共 {len(m)} 个")
    if n:
        bad = m.loc[m["diff"] > 0.001, ["日期", "ret_qfq", "ret_raw", "diff"]].head(6)
        log("    样例（这些日子不复权收益率是错的）:")
        for _, r in bad.iterrows():
            log(f"        {r['日期']}  qfq={r['ret_qfq']:+.4%}  raw={r['ret_raw']:+.4%}  "
                f"差={r['diff']:.4%}")

# ---------- B. baostock 交叉校验 ----------
log("\n[B] baostock 交叉校验（免费备源，复权因子最严谨）")
try:
    import baostock as bs
    lg = bs.login()
    log(f"    登录: {lg.error_code} {lg.error_msg}")
    if lg.error_code == "0":
        # 前复权日线
        rs = bs.query_history_k_data_plus(
            "sh.600519", "date,code,open,high,low,close,volume,amount,turn,pctChg,adjustflag",
            start_date="2024-01-01", end_date="2026-10-28",
            frequency="d", adjustflag="2")  # 2=前复权
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        log(f"    baostock 日线(前复权) {len(rows)} 行")
        if rows:
            log(f"    字段: {rs.fields}")
            log(f"    首行: {rows[0]}")
            log(f"    末行: {rows[-1]}")
        # 与东财对比
        if qfq is not None and rows:
            import pandas as pd
            b = pd.DataFrame(rows, columns=rs.fields)
            b["close"] = b["close"].astype(float)
            b["date"] = pd.to_datetime(b["date"]).dt.strftime("%Y-%m-%d")
            e = qfq.copy()
            e["日期"] = pd.to_datetime(e["日期"]).dt.strftime("%Y-%m-%d")
            e["close"] = e["收盘"].astype(float)
            j = b[["date", "close"]].merge(e[["日期", "close"]], left_on="date",
                                           right_on="日期", suffixes=("_bs", "_em"))
            if len(j):
                j["reldiff"] = (j["close_bs"] - j["close_em"]).abs() / j["close_em"]
                log(f"    重叠 {len(j)} 日；收盘价相对偏差 均值={j['reldiff'].mean():.6%} "
                    f"最大={j['reldiff'].max():.6%}")
                log(f"    -> {'两源前复权一致，可互为校验' if j['reldiff'].max() < 0.01 else '两源存在差异，需查口径'}")
        # 复权因子另一口径
        rs2 = bs.query_adjust_factor(code="sh.600519", start_date="2024-01-01", end_date="2026-10-28")
        facs = []
        while rs2.error_code == "0" and rs2.next():
            facs.append(rs2.get_row_data())
        log(f"    除权除息事件(query_adjust_factor) {len(facs)} 次: {facs[:3] if facs else '无'}")
        bs.logout()
        log("    已登出")
except Exception as e:
    log(f"    FAIL {type(e).__name__}: {str(e)[:200]}")

# ---------- C. 巨潮类型名 ----------
log("\n[C] 巨潮 announcementTypeName（可直接做事件分类标签）")
try:
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "http://www.cninfo.com.cn/"})
    payload = {"pageNum": 1, "pageSize": 20, "column": "szse", "tabName": "fulltext",
               "plate": "", "stock": "600519,gssh0600519", "searchkey": "", "secid": "",
               "category": "", "trade": "", "seDate": "2025-01-01~2026-12-31",
               "sortName": "", "sortType": "", "isHLtitle": "true"}
    anns = s.post("http://www.cninfo.com.cn/new/hisAnnouncement/query",
                  data=payload, timeout=20).json().get("announcements") or []
    seen = set()
    for a in anns:
        nm = a.get("announcementTypeName") or ""
        cod = a.get("announcementType") or ""
        if nm and nm not in seen:
            seen.add(nm)
            log(f"    {cod:<32} -> {nm}")
    log(f"    important 字段分布: {[a.get('important') for a in anns[:10]]}")
except Exception as e:
    log(f"    FAIL {type(e).__name__}: {str(e)[:150]}")

log("\n" + "=" * 74)
with open(f"{OUT}\\04_rate_limit_adjust.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
