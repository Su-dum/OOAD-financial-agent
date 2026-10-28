# -*- coding: utf-8 -*-
"""数据源可行性探针：验证 akshare 能否覆盖 行情 / 公告 / 新闻 / 财务指标"""
import sys, io, time, traceback
from datetime import date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import akshare as ak

TODAY = date.today()
D0 = (TODAY - timedelta(days=365)).strftime("%Y%m%d")
D1 = TODAY.strftime("%Y%m%d")
N0 = (TODAY - timedelta(days=120)).strftime("%Y%m%d")
N1 = D1
CODE = "600519"

results = []


def probe(name, fn, note=""):
    t0 = time.time()
    try:
        df = fn()
        dt = time.time() - t0
        if df is None or len(df) == 0:
            results.append(f"[EMPTY] {name} ({dt:.1f}s) 返回空表")
            return
        cols = list(df.columns)
        results.append(
            f"[OK]    {name} ({dt:.1f}s)  rows={len(df)}  cols={len(cols)}\n"
            f"        columns = {cols}"
        )
        head = df.head(1).to_dict("records")[0]
        sample = {k: (str(v)[:60]) for k, v in list(head.items())[:12]}
        results.append(f"        sample  = {sample}")
        if note:
            results.append(f"        note    = {note}")
    except Exception as e:
        dt = time.time() - t0
        results.append(f"[FAIL]  {name} ({dt:.1f}s)  {type(e).__name__}: {str(e)[:200]}")


print("=" * 70)
print("数据源探针  标的=600519 贵州茅台  今天=", TODAY, "  akshare=", ak.__version__)
print("=" * 70)

# ---------- 1. 行情 ----------
print("\n### 1. 行情数据 (OHLCV)")
probe(
    "stock_zh_a_hist(前复权, 近1年)",
    lambda: ak.stock_zh_a_hist(symbol=CODE, period="daily", start_date=D0, end_date=D1, adjust="qfq"),
    "东财日线，含成交量/成交额/换手率/振幅",
)

# ---------- 2. 公告 ----------
print("\n### 2. 公司公告")
probe(
    "stock_zh_a_disclosure_report_cninfo(巨潮资讯)",
    lambda: ak.stock_zh_a_disclosure_report_cninfo(
        symbol=CODE, market="沪深京", start_date=N0, end_date=N1
    ),
    "巨潮=交易所指定披露平台，最权威",
)
probe(
    "stock_individual_notice_report(东财个股公告)",
    lambda: ak.stock_individual_notice_report(security=CODE),
    "东财公告，含PDF链接",
)
probe(
    "stock_notice_report(东财全市场公告, 按日期)",
    lambda: ak.stock_notice_report(symbol="全部", date=N1),
    "全市场当日公告，适合发现式扫描",
)

# ---------- 3. 新闻 ----------
print("\n### 3. 市场新闻")
probe(
    "stock_news_em(东财个股新闻)",
    lambda: ak.stock_news_em(symbol=CODE),
    "个股维度新闻",
)
probe(
    "stock_info_global_cls(财联社电报)",
    lambda: ak.stock_info_global_cls(symbol="全部"),
    "7x24快讯，全市场维度",
)
probe(
    "stock_info_global_em(东财全球财经快讯)",
    lambda: ak.stock_info_global_em(),
    "快讯备源",
)

# ---------- 4. 财务指标 / 估值 ----------
print("\n### 4. 财务指标与估值")
probe(
    "stock_financial_analysis_indicator(新浪财务指标)",
    lambda: ak.stock_financial_analysis_indicator(symbol=CODE, start_year="2022"),
    "ROE/毛利率/净利率/营收增长率等",
)
probe(
    "stock_financial_abstract(财务摘要)",
    lambda: ak.stock_financial_abstract(symbol=CODE),
    "三表摘要",
)
probe(
    "stock_zh_valuation_baidu(市盈率TTM)",
    lambda: ak.stock_zh_valuation_baidu(symbol=CODE, indicator="市盈率(TTM)", period="近一年"),
    "估值比率历史序列",
)

# ---------- 5. 辅助 ----------
print("\n### 5. 辅助数据(A股特有坑)")
probe("tool_trade_date_hist_sina(交易日历)", lambda: ak.tool_trade_date_hist_sina(), "交易日对齐")
probe("stock_tfp_em(停复牌)", lambda: ak.stock_tfp_em(date=N1), "停牌股不能算收益")
probe("stock_board_industry_name_em(行业板块)", lambda: ak.stock_board_industry_name_em(), "跨行业分析D3的基础")

print("\n" + "=" * 70)
print("汇总")
print("=" * 70)
ok = sum(1 for r in results if r.startswith("[OK]"))
fail = sum(1 for r in results if r.startswith("[FAIL]"))
empty = sum(1 for r in results if r.startswith("[EMPTY]"))
print(f"OK={ok}  FAIL={fail}  EMPTY={empty}")

with open(os.path.join(OUT, "01_core_coverage.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(results))
