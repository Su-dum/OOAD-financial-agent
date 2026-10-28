# -*- coding: utf-8 -*-
"""精查：东财前复权 vs baostock前复权 —— 是「整体缩放」还是「收益率就不同」"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import akshare as ak
import pandas as pd

import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT, exist_ok=True)
LOG = []
def log(s=""):
    print(s); LOG.append(str(s))

log("=" * 74)
log("东财 qfq  vs  baostock 前复权：口径差异的本质")
log("=" * 74)

em = None
for i in range(4):
    try:
        em = ak.stock_zh_a_hist(symbol="600519", period="daily",
                                start_date="20240101", end_date="20261028", adjust="qfq")
        break
    except Exception as e:
        log(f"  东财第{i+1}次失败 {type(e).__name__}，退避 {4*2**i}s")
        time.sleep(4 * 2 ** i)

import baostock as bs
bs.login()
rs = bs.query_history_k_data_plus(
    "sh.600519", "date,close", start_date="2024-01-01", end_date="2026-10-28",
    frequency="d", adjustflag="2")
rows = []
while rs.error_code == "0" and rs.next():
    rows.append(rs.get_row_data())
bs.logout()
bst = pd.DataFrame(rows, columns=["date", "close_bs"])
log(f"  东财 {len(em) if em is not None else 0} 行 | baostock {len(bst)} 行")

if em is not None and len(bst):
    e = em.copy()
    e["date"] = pd.to_datetime(e["日期"]).dt.strftime("%Y-%m-%d")
    e["close_em"] = e["收盘"].astype(float)
    e = e[["date", "close_em"]]
    bst["close_bs"] = bst["close_bs"].astype(float)
    m = e.merge(bst, on="date").sort_values("date").reset_index(drop=True)
    log(f"  重叠交易日 {len(m)} 个：{m['date'].iloc[0]} ~ {m['date'].iloc[-1]}")

    # 1) 价格水平比值
    m["ratio"] = m["close_bs"] / m["close_em"]
    log(f"\n  [1] 价格水平比值 close_bs/close_em")
    log(f"      均值={m['ratio'].mean():.6f}  标准差={m['ratio'].std():.8f}  "
        f"最小={m['ratio'].min():.6f} 最大={m['ratio'].max():.6f}")
    log(f"      极差/均值 = {(m['ratio'].max()-m['ratio'].min())/m['ratio'].mean():.6%}")

    # 2) 日收益率对比
    m["r_em"] = m["close_em"].pct_change()
    m["r_bs"] = m["close_bs"].pct_change()
    d = (m["r_em"] - m["r_bs"]).abs().dropna()
    log(f"\n  [2] 日收益率差异 |r_em - r_bs|")
    log(f"      均值={d.mean():.8f}  最大={d.max():.8f}  中位={d.median():.8f}")
    log(f"      >0.01% 的天数: {(d>0.0001).sum()} / {len(d)}")
    log(f"      相关系数: {m['r_em'].corr(m['r_bs']):.10f}")

    # 3) 累计收益
    log(f"\n  [3] 区间累计收益")
    log(f"      东财 qfq      {m['close_em'].iloc[-1]/m['close_em'].iloc[0]-1:+.4%}")
    log(f"      baostock 前复权 {m['close_bs'].iloc[-1]/m['close_bs'].iloc[0]-1:+.4%}")
    log(f"      差异 {(m['close_bs'].iloc[-1]/m['close_bs'].iloc[0]) - (m['close_em'].iloc[-1]/m['close_em'].iloc[0]):+.4%}")

    # 4) 差异最大的日子
    m["dr"] = (m["r_em"] - m["r_bs"]).abs()
    top = m.nlargest(5, "dr")[["date", "close_em", "close_bs", "r_em", "r_bs", "dr"]]
    log(f"\n  [4] 收益率差异最大的 5 个交易日")
    for _, r in top.iterrows():
        log(f"      {r['date']}  东财={r['close_em']:.2f} baostock={r['close_bs']:.2f}  "
            f"r_em={r['r_em']:+.4%} r_bs={r['r_bs']:+.4%} 差={r['dr']:.4%}")

    # 5) 波动率对比（这才是我们真正要算的指标）
    log(f"\n  [5] 年化波动率（我们真正要交付的指标）")
    log(f"      东财 qfq      {m['r_em'].std()*(252**0.5):.4%}")
    log(f"      baostock 前复权 {m['r_bs'].std()*(252**0.5):.4%}")

log("\n" + "=" * 74)
with open(f"{OUT}\\05_adjust_source_diff.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
