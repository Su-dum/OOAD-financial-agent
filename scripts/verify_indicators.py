#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真实数据验收：指标算得对不对。

四重复核：
  [2] 复权恒等式 —— 非除权日「复权收益」必须等于「不复权收益」（仅 baostock 源可验）
  [3] 独立实现交叉验证 —— 用 pandas 的 cummax / pct_change 重算一遍，与手写实现比对
  [4] 结果可读性 —— 打印指标表，肉眼确认数量级合理
  [5] 跨标的 / 跨期对比（A3）

用法：
  python scripts/verify_indicators.py                    # baostock（口径正确，可能很慢）
  python scripts/verify_indicators.py --source sina       # 新浪（快，口径也正确）
  python scripts/verify_indicators.py --check-adjust --compare
"""
import os
import sys
import math
import time
import argparse
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.app.core import indicators as ind                        # noqa: E402
from backend.app.infrastructure.catalog import CsvStockCatalog        # noqa: E402
from backend.app.infrastructure.providers.cache import CsvPriceCache  # noqa: E402
from backend.app.application.market_service import MarketDataService  # noqa: E402
from backend.app.application.analysis_service import FinancialAnalyzer  # noqa: E402

OUT = os.path.join(ROOT, "scripts", "probes", "outputs")
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, "verify_indicators.txt")
open(LOG, "w", encoding="utf-8").close()


def log(s=""):
    line = str(s)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="600519")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--source", default="baostock",
                    choices=["baostock", "sina", "eastmoney"])
    ap.add_argument("--refresh", action="store_true", help="忽略磁盘缓存")
    ap.add_argument("--check-adjust", action="store_true",
                    help="额外验证复权恒等式（需要再拉一次不复权数据，慢）")
    ap.add_argument("--compare", action="store_true",
                    help="额外跑跨标的 / 跨期对比（需要多拉几只票）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=int(args.years * 365))).strftime("%Y-%m-%d")
    nl = (lambda *a, **k: None) if args.quiet else print

    log("=" * 78)
    log(f"指标计算验收   标的={args.code}   区间={start} ~ {end}   优先源={args.source}")
    log("=" * 78)

    # ---- 组装对象图：与 API 层同一套装配方式 ----
    cache = CsvPriceCache(os.path.join(ROOT, "data", "cache", "market"))
    market = MarketDataService.default(cache=cache, catalog=CsvStockCatalog(), log=nl)
    analyzer = FinancialAnalyzer(market, log=nl)
    log(f"可用数据源（按优先级）: {market.chain.names()}")

    # ---------------- 1. 取数 ----------------
    log("\n[1] 取数")
    t0 = time.time()
    series = market.get_series(args.code, start, end, source=args.source,
                               require_returns=True, refresh=args.refresh)
    log(f"    {len(series) if series else 0} 行  ({time.time()-t0:.1f}s)  "
        f"source={getattr(series, 'source', '?')}  adjust={getattr(series, 'adjust', '?')}")
    if series is None or len(series) < 2:
        log("    ✗ 取数失败，终止")
        return 1
    log(f"    区间 {series.start} ~ {series.end}")

    # ---------------- 2. 复权恒等式 ----------------
    log("\n[2] 复权恒等式：非除权日「qfq 收益」应等于「raw 收益」")
    if not args.check_adjust:
        log("    - 跳过（加 --check-adjust 开启；已由探针 06 用 674 个交易日证明，偏差 0）")
    elif series.source != "baostock":
        log(f"    - 当前源为 {series.source}，该项只对 baostock 有定义，跳过")
    else:
        exdiv = set()
        try:
            import io
            import contextlib
            import baostock as bs
            ref = f"sh.{args.code}" if args.code.startswith(("6", "9")) else f"sz.{args.code}"
            with contextlib.redirect_stdout(io.StringIO()):
                bs.login()
            rf = bs.query_adjust_factor(code=ref, start_date=start, end_date=end)
            while rf.error_code == "0" and rf.next():
                exdiv.add(rf.get_row_data()[1])
            with contextlib.redirect_stdout(io.StringIO()):
                bs.logout()
        except Exception as e:
            log(f"    取除权日失败（跳过）：{type(e).__name__}")
        log(f"    区间内除权除息 {len(exdiv)} 次: {sorted(exdiv)}")

        raw = market.get_series(args.code, start, end, adjust="none",
                                source="baostock", require_returns=False,
                                refresh=args.refresh)
        qmap = {r.date: r.close for r in series.records}
        rmap = {r.date: r.close for r in (raw.records if raw else [])}
        common = sorted(set(qmap) & set(rmap))
        diffs = []
        for i in range(1, len(common)):
            d, prev = common[i], common[i - 1]
            if d in exdiv or prev in exdiv:
                continue
            if rmap[prev] <= 0 or qmap[prev] <= 0:
                continue
            diffs.append((d, abs(qmap[d] / qmap[prev] - rmap[d] / rmap[prev])))
        if diffs:
            worst = max(diffs, key=lambda x: x[1])
            bad = [x for x in diffs if x[1] > 1e-6]
            log(f"    非除权日 {len(diffs)} 个；最大偏差 {worst[1]:.10f}（{worst[0]}）")
            log("    ✓ 全部一致，前复权口径正确" if not bad
                else f"    ✗ 有 {len(bad)} 天不一致")
        else:
            log("    - 可比日期不足，跳过")

    # ---------------- 3. 独立实现交叉验证 ----------------
    log("\n[3] 独立实现交叉验证：pandas 重算 vs 我们的实现")
    import pandas as pd
    import numpy as np

    df = pd.DataFrame({"date": series.dates, "close": series.closes})
    df["ret"] = df["close"].pct_change()
    n = len(df)

    ref_total = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
    ref_vol = float(df["ret"].std(ddof=1) * math.sqrt(252))
    ref_mdd = float((df["close"] / df["close"].cummax() - 1).min())
    logret = float(np.log(df["close"].iloc[-1] / df["close"].iloc[0]))
    ref_ann = math.exp(logret * 252 / (n - 1)) - 1

    ours = ind.analyze_series(series.dates, series.closes,
                              pe_series=[r.pe_ttm for r in series.records],
                              pb_series=[r.pb for r in series.records])
    all_ok = True

    def cmp(name, a, b, tol=1e-9):
        nonlocal all_ok
        ok = (a is None and b is None) or (
            a is not None and b is not None and abs(float(a) - float(b)) <= tol)
        all_ok &= ok
        av = f"{a:.10g}" if isinstance(a, (int, float)) else repr(a)
        bv = f"{b:.10g}" if isinstance(b, (int, float)) else repr(b)
        log(f"    {'✓' if ok else '✗'} {name:<18} ours={av:<22} ref={bv}")

    cmp("交易日数", ours["n_days"], n, 0)
    cmp("累计收益", ours["total_return"], ref_total)
    cmp("年化收益", ours["annualized_return"], ref_ann)
    cmp("年化波动率", ours["annualized_volatility"], ref_vol)
    cmp("最大回撤", ours["max_drawdown"], ref_mdd)
    log(f"    -> {'全部通过 ✅' if all_ok else '存在差异 ❌'}")

    # ---------------- 4. 指标汇总 ----------------
    log("\n[4] 指标汇总（生产代码路径 FinancialAnalyzer.analyze）")
    t0 = time.time()
    r = analyzer.analyze(args.code, start, end, source=args.source)
    log(f"    耗时 {time.time()-t0:.1f}s")
    if r is not None:
        log(f"    {FinancialAnalyzer.describe(r)}\n")
        rows = [
            ("标的", f"{r.code} {r.name}（{r.industry_l1}）"),
            ("区间 / 交易日", f"{r.start} ~ {r.end}  {r.n_days} 天"),
            ("复权口径 / 来源", f"{r.adjust} / {r.source}"),
            ("首末价", f"{r.first_close:.2f} → {r.last_close:.2f}"),
            ("累计收益", f"{r.total_return:+.2%}" if r.total_return is not None else "—"),
            ("年化收益", f"{r.annualized_return:+.2%}" if r.annualized_return is not None else "—"),
            ("年化波动率", f"{r.annualized_volatility:.2%}" if r.annualized_volatility is not None else "—"),
            ("最大回撤", f"{r.max_drawdown:.2%}" if r.max_drawdown is not None else "—"),
            ("回撤区间", f"{r.max_drawdown_peak} → {r.max_drawdown_trough}"),
            ("夏普 / 索提诺", f"{r.sharpe if r.sharpe is None else round(r.sharpe, 3)} / "
                              f"{r.sortino if r.sortino is None else round(r.sortino, 3)}"),
            ("胜率", f"{r.win_rate:.2%}" if r.win_rate is not None else "—"),
            ("PE(TTM) / 分位", f"{r.pe_ttm} / "
                              f"{'—' if r.pe_ttm_percentile is None else f'{r.pe_ttm_percentile:.0%}'}"),
            ("PB / 分位", f"{r.pb} / "
                         f"{'—' if r.pb_percentile is None else f'{r.pb_percentile:.0%}'}"),
            ("ROE / 净利润增速", f"{r.roe} / {r.profit_growth}"),
        ]
        for k, v in rows:
            log(f"      {k:<16} {v}")

    # ---------------- 5. 跨标的 / 跨期 ----------------
    if not args.compare:
        log("\n[5][6] 跨标的 / 跨期对比：跳过（加 --compare 开启）")
    else:
        log("\n[5] 跨标的横向比较（A3）")
        for c in analyzer.compare(["600519", "000001", "300750"], start, end,
                                  source=args.source):
            log(f"    {FinancialAnalyzer.describe(c)}")

        log("\n[6] 同一标的跨期对比（A3 的另一面）")
        y = datetime.now().year
        periods = [("近 1 年", f"{y-1}-01-01", end), ("近 3 年", f"{y-3}-01-01", end)]
        for row in analyzer.compare_periods(args.code, periods, source=args.source):
            p = lambda v, s="%": "—" if v is None else f"{v*100:+.2f}{s}"
            log(f"    {row['period']:<8} {row['start']} ~ {row['end']}  "
                f"{row['n_days']:>4} 天  收益 {p(row['total_return']):>8}  "
                f"波动 {p(row['annualized_volatility']):>7}  回撤 {p(row['max_drawdown']):>7}")

    log("\n" + "=" * 78)
    log(f"原始输出：{LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
