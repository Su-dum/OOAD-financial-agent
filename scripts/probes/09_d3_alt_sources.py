# -*- coding: utf-8 -*-
"""D3 换源验证：绕开东财，验证「指数行情」与「行业指数历史」是否有可用替代源。

候选源：
  指数   —— 腾讯 / 新浪 / 中证官方 / baostock
  行业   —— 同花顺板块 / 申万行业 / 中证行业指数
逐步 flush 落盘，便于中断后仍能看到已得结果。
"""
import os, sys, time, inspect, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE, "outputs", "09_d3_alt_sources.txt")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
open(LOG_PATH, "w", encoding="utf-8").close()


def log(s=""):
    line = str(s)
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


import akshare as ak

log("=" * 74)
log("D3 换源验证：非东财的指数与行业数据源")
log("=" * 74)

# ---------- 0. 候选函数 ----------
names = [n for n in dir(ak) if not n.startswith("_")]
log("\n[0] 相关候选函数")
for kw in ("_tx", "csindex", "_ths", "sw_", "index_daily"):
    hits = sorted([n for n in names if kw in n])[:14]
    log(f"  {kw:<12} {hits}")

# ---------- 1. 指数行情 ----------
log("\n[1] 指数行情 备源")

def try_call(name, fn, argdesc):
    try:
        t0 = time.time()
        d = fn()
        log(f"  [OK]   {name} ({argdesc})  rows={len(d)}  {time.time()-t0:.1f}s")
        log(f"         columns={list(d.columns)}")
        if len(d):
            log(f"         first={d.iloc[0].to_dict()}")
            log(f"         last ={d.iloc[-1].to_dict()}")
        return d
    except Exception as e:
        log(f"  [FAIL] {name} ({argdesc})  {type(e).__name__}: {str(e)[:120]}")
        return None

for fn_name, kw in (("stock_zh_index_daily_tx", dict(symbol="sh000300")),
                    ("stock_zh_index_daily", dict(symbol="sh000300")),
                    ("stock_zh_index_hist_csindex", dict(symbol="000300",
                                                         start_date="20250101",
                                                         end_date="20261028"))):
    f = getattr(ak, fn_name, None)
    if f is None:
        log(f"  [SKIP] {fn_name} 不存在")
        continue
    try:
        log(f"  签名 {fn_name}{inspect.signature(f)}")
    except Exception:
        pass
    try_call(fn_name, lambda f=f, kw=kw: f(**kw), ", ".join(f"{k}={v}" for k, v in kw.items()))
    time.sleep(1)

# ---------- 2. 行业指数历史 ----------
log("\n[2] 行业指数历史 备源")

# 2a. 同花顺行业板块
ths_names = None
f = getattr(ak, "stock_board_industry_name_ths", None)
if f is not None:
    try:
        log(f"  签名 stock_board_industry_name_ths{inspect.signature(f)}")
    except Exception:
        pass
    ths_names = try_call("stock_board_industry_name_ths", lambda: f(), "")

if ths_names is not None and len(ths_names):
    col = [c for c in ths_names.columns if "名称" in str(c)]
    sample = list(ths_names[col[0]])[:5] if col else list(ths_names.iloc[:5, 0])
    log(f"  同花顺行业前 5 个: {sample}")
    f2 = getattr(ak, "stock_board_industry_index_ths", None)
    if f2 is not None:
        try:
            log(f"  签名 stock_board_industry_index_ths{inspect.signature(f2)}")
        except Exception:
            pass
        for nm_ in sample[:2]:
            try_call(f"stock_board_industry_index_ths", 
                     lambda nm_=nm_: f2(symbol=nm_, start_date="20250101", end_date="20261028"),
                     f"symbol={nm_}")
            time.sleep(1)

# 2b. 申万行业
log("\n  申万行业指数:")
sw_list = [n for n in names if n.startswith("sw_")][:12]
log(f"    候选: {sw_list}")
f = getattr(ak, "sw_index_first_info", None)
if f is not None:
    try_call("sw_index_first_info", lambda: f(), "")
    time.sleep(1)
f = getattr(ak, "index_hist_sw", None)
if f is not None:
    try:
        log(f"    签名 index_hist_sw{inspect.signature(f)}")
    except Exception:
        pass
    try_call("index_hist_sw", lambda: f(symbol="801010", period="day"), "symbol=801010")

# 2c. 中证行业指数
log("\n  中证行业指数:")
f = getattr(ak, "stock_zh_index_value_csindex", None)
if f is not None:
    try:
        log(f"    签名 stock_zh_index_value_csindex{inspect.signature(f)}")
    except Exception:
        pass
    try_call("stock_zh_index_value_csindex", lambda: f(symbol="H30184"), "symbol=H30184")

# 2d. 概念板块（同花顺）
log("\n  同花顺概念板块:")
f = getattr(ak, "stock_board_concept_name_ths", None)
if f is not None:
    try_call("stock_board_concept_name_ths", lambda: f(), "")
f = getattr(ak, "stock_board_concept_index_ths", None)
if f is not None:
    try:
        log(f"    签名 stock_board_concept_index_ths{inspect.signature(f)}")
    except Exception:
        pass

# ---------- 3. baostock 指数 ----------
log("\n[3] baostock 指数行情（免费、无东财限频）")
try:
    import baostock as bs
    lg = bs.login()
    log(f"  login={lg.error_code}")
    for code in ["sh.000300", "sh.000001", "sz.399001"]:
        try:
            t0 = time.time()
            rs = bs.query_history_k_data_plus(
                code, "date,open,high,low,close,volume,amount,pctChg",
                start_date="2023-01-01", end_date="2026-10-28", frequency="d")
            rows = []
            n = 0
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
                n += 1
                if n > 5000:
                    break
            log(f"  [{'OK' if rows else 'EMPTY'}] {code} rows={len(rows)} "
                f"err={rs.error_code} ({time.time()-t0:.1f}s)")
            if rows:
                log(f"         fields={rs.fields}")
                log(f"         first={rows[0]}")
                log(f"         last ={rows[-1]}")
        except Exception as e:
            log(f"  [FAIL] {code} {type(e).__name__}: {str(e)[:120]}")
    bs.logout()
    log("  logout ok")
except Exception as e:
    log(f"  [FAIL] baostock {type(e).__name__}: {str(e)[:150]}")

log("\n=== DONE ===")
