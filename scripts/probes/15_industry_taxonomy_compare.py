# -*- coding: utf-8 -*-
"""对比三套行业分类体系：申万一级 / 同花顺板块 / 东财板块

对比维度（都是做 D3 跨行业分析真正需要的）：
  1. 分类粒度：各有多少个行业
  2. 历史深度：行业指数最早能回到哪天
  3. 自带指标：有没有 PE / PB / 股息率（能不能直接做行业估值对比）
  4. 接口稳定性：取一次要多久、失败几次

结论见 docs/datasource-eval.md §10.4。
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)
LOG_PATH = os.path.join(OUT, "15_industry_taxonomy_compare.txt")
open(LOG_PATH, "w", encoding="utf-8").close()


def log(s=""):
    line = str(s)
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


import akshare as ak
import pandas as pd

log("=" * 74)
log("三套行业分类体系对比（做跨行业分析真正需要的四个维度）")
log("=" * 74)

# ============================================================
# 1. 分类粒度
# ============================================================
log("\n[1] 分类粒度：各有多少个行业")
counts = {}


def try_count(name, fn):
    for i in range(3):
        try:
            t0 = time.time()
            d = fn()
            counts[name] = len(d)
            log(f"    {name:<12} {len(d):>4} 个   ({time.time()-t0:.1f}s)")
            return d
        except Exception as e:
            if i == 2:
                log(f"    {name:<12} FAIL {type(e).__name__}（重试 3 次）")
                counts[name] = None
            else:
                time.sleep(3 * (i + 1))


try_count("申万一级", lambda: ak.sw_index_first_info())
try_count("申万二级", lambda: ak.sw_index_second_info())
try_count("申万三级", lambda: ak.sw_index_third_info())
try_count("同花顺行业", lambda: ak.stock_board_industry_name_ths())
try_count("同花顺概念", lambda: ak.stock_board_concept_name_ths())
try_count("东财行业板块", lambda: ak.stock_board_industry_name_em())

# ============================================================
# 2. 历史深度
# ============================================================
log("\n[2] 历史深度：行业指数最早能回到哪天（取「半导体/电子」这条线）")

for code, label in (("801080", "申万 电子"), ("801010", "申万 农林牧渔")):
    try:
        t0 = time.time()
        d = ak.index_hist_sw(symbol=code, period="day")
        d["日期"] = pd.to_datetime(d["日期"])
        log(f"    {label:<14} {len(d):>5} 行   {d['日期'].min().date()} ~ {d['日期'].max().date()}"
            f"   ({time.time()-t0:.1f}s)")
        log(f"       字段: {list(d.columns)}")
    except Exception as e:
        log(f"    {label:<14} FAIL {type(e).__name__}: {str(e)[:70]}")
    time.sleep(0.8)

log("")
# 同花顺：故意从 2005 年要，看最早给到哪天（不同板块起点不一致是本项的关键发现）
for sym in ("半导体", "白酒"):
    try:
        t0 = time.time()
        d = ak.stock_board_industry_index_ths(symbol=sym, start_date="2005-01-01",
                                              end_date="2026-10-28")
        d["日期"] = pd.to_datetime(d["日期"])
        log(f"    同花顺 {sym:<10} {len(d):>5} 行   {d['日期'].min().date()} ~ {d['日期'].max().date()}"
            f"   ({time.time()-t0:.1f}s)")
        log(f"       字段: {list(d.columns)}")
    except Exception as e:
        log(f"    同花顺 {sym:<10} FAIL {type(e).__name__}: {str(e)[:70]}")
    time.sleep(1.2)

log("")
# 东财：已知限频严重，试 3 次
for sym in ("半导体",):
    for i in range(3):
        try:
            t0 = time.time()
            d = ak.stock_board_industry_hist_em(symbol=sym, start_date="20050101",
                                                end_date="20261028", period="日k", adjust="")
            d["日期"] = pd.to_datetime(d["日期"])
            log(f"    东财   {sym:<10} {len(d):>5} 行   {d['日期'].min().date()} ~ "
                f"{d['日期'].max().date()}   ({time.time()-t0:.1f}s)")
            log(f"       字段: {list(d.columns)}")
            break
        except Exception as e:
            if i == 2:
                log(f"    东财   {sym:<10} FAIL {type(e).__name__}（重试 3 次仍失败）")
            else:
                time.sleep(4 * (i + 1))

# ============================================================
# 3. 自带估值指标
# ============================================================
log("\n[3] 自带估值指标（能否直接做行业估值横向对比）")
try:
    d = ak.sw_index_first_info()
    log(f"    申万一级: {list(d.columns)}")
    log(f"       样例 {d.iloc[0].to_dict()}")
except Exception as e:
    log(f"    申万一级 FAIL {e}")

try:
    d = ak.stock_board_industry_name_ths()
    log(f"    同花顺行业: {list(d.columns)}")
except Exception as e:
    log(f"    同花顺行业 FAIL {type(e).__name__}")

try:
    d = ak.stock_board_industry_name_em()
    log(f"    东财行业:   {list(d.columns)}")
except Exception as e:
    log(f"    东财行业 FAIL {type(e).__name__}")

log("\n" + "=" * 74)