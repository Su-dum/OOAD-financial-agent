# -*- coding: utf-8 -*-
"""决定性检验：非除权日，复权收益率必须等于不复权收益率。哪家不满足，哪家复权有误。"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import akshare as ak
import pandas as pd
import baostock as bs

import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT, exist_ok=True)
LOG = []
def log(s=""):
    print(s); LOG.append(str(s))

def em_hist(adjust):
    for i in range(5):
        try:
            return ak.stock_zh_a_hist(symbol="600519", period="daily",
                                      start_date="20240101", end_date="20261028",
                                      adjust=adjust)
        except Exception as e:
            time.sleep(4 * 2 ** i)
    return None

def bs_hist(flag):
    rs = bs.query_history_k_data_plus(
        "sh.600519", "date,close,pctChg", start_date="2024-01-01",
        end_date="2026-10-28", frequency="d", adjustflag=flag)
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    d = pd.DataFrame(rows, columns=["date", "close", "pctChg"])
    d["close"] = d["close"].astype(float)
    return d

log("=" * 74)
log("决定性检验：非除权日的复权收益率是否等于不复权收益率")
log("=" * 74)

log("\n[1] 取数")
em_qfq = em_hist("qfq"); time.sleep(3)
em_raw = em_hist("")
log(f"    东财 qfq {len(em_qfq) if em_qfq is not None else 0} 行 / 不复权 "
    f"{len(em_raw) if em_raw is not None else 0} 行")

bs.login()
bs_qfq = bs_hist("2")
bs_raw = bs_hist("3")
rf = bs.query_adjust_factor(code="sh.600519", start_date="2024-01-01", end_date="2026-10-28")
exdiv = []
while rf.error_code == "0" and rf.next():
    exdiv.append(rf.get_row_data()[1])   # dividOperateDate
bs.logout()
log(f"    baostock qfq {len(bs_qfq)} 行 / 不复权 {len(bs_raw)} 行")
log(f"    除权除息日 {len(exdiv)} 个: {exdiv}")

if em_qfq is not None and em_raw is not None:
    e = em_qfq.copy()
    e["date"] = pd.to_datetime(e["日期"]).dt.strftime("%Y-%m-%d")
    e["qfq"] = e["收盘"].astype(float)
    r = em_raw.copy()
    r["date"] = pd.to_datetime(r["日期"]).dt.strftime("%Y-%m-%d")
    r["raw"] = r["收盘"].astype(float)
    E = e[["date", "qfq"]].merge(r[["date", "raw"]], on="date").sort_values("date")
    E["r_qfq"] = E["qfq"].pct_change()
    E["r_raw"] = E["raw"].pct_change()
    E["d"] = (E["r_qfq"] - E["r_raw"]).abs()
    E["is_exdiv"] = E["date"].isin(exdiv)

    B = bs_qfq[["date", "close"]].rename(columns={"close": "qfq"}).copy()
    Br = bs_raw[["date", "close"]].rename(columns={"close": "raw"})
    B = B.merge(Br, on="date").sort_values("date")
    B["r_qfq"] = B["qfq"].pct_change()
    B["r_raw"] = B["raw"].pct_change()
    B["d"] = (B["r_qfq"] - B["r_raw"]).abs()
    B["is_exdiv"] = B["date"].isin(exdiv)

    for name, D in (("东财", E), ("baostock", B)):
        non = D[~D["is_exdiv"]].dropna(subset=["d"])
        ex = D[D["is_exdiv"]].dropna(subset=["d"])
        log(f"\n[{name}]")
        log(f"    非除权日 {len(non)} 个：|复权收益 - 不复权收益| 最大={non['d'].max():.8f} "
            f"均值={non['d'].mean():.8f}  >0.01%的天数={(non['d']>0.0001).sum()}")
        log(f"    除权日   {len(ex)} 个：该差值应为正（分红需还原）={list(ex['d'].round(6))}")

log("\n[2] 结论")
if em_qfq is not None and em_raw is not None:
    nonE = E[~E["is_exdiv"]].dropna(subset=["d"])
    nonB = B[~B["is_exdiv"]].dropna(subset=["d"])
    okE = nonE["d"].max() < 1e-4
    okB = nonB["d"].max() < 1e-4
    log(f"    东财   非除权日吻合: {okE}  (最大偏差 {nonE['d'].max():.6f})")
    log(f"    baostock 非除权日吻合: {okB}  (最大偏差 {nonB['d'].max():.6f})")
    if okE and not okB:
        log("    -> 东财前复权口径正确，baostock 前复权有问题（可能是等差复权或分红处理不同）")
    elif okB and not okE:
        log("    -> baostock 前复权口径正确，东财有问题")
    elif okE and okB:
        log("    -> 两家在非除权日都吻合，差异应来自除权日还原方式或复权基准日")
    else:
        log("    -> 两家在非除权日都不吻合，需人工核查")

log("\n" + "=" * 74)
with open(f"{OUT}\\06_adjust_correctness.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
