# -*- coding: utf-8 -*-
"""跨资产分析服务（应用层）。

对应评分项 **D3（Cross-asset Analysis）**：

    相对表现   net_value()      把多只标的归一到 100，直接比走势
    相关性     correlations()    日收益率相关系数矩阵
    共同驱动   with_benchmark()  与基准（沪深300）的 beta / 跟踪误差 / 相对强弱

三条都建立在同一件事上：**先把多个序列对齐到同一批交易日**。
这是跨资产分析最容易错的地方——不复权、不对齐、窗口不同，
相关系数就会算出一个漂亮但错误的数字（参见 docs/datasource-eval.md §7）。
所以对齐逻辑收敛在 `align()` 一个方法里，任何口径问题只改这一处。
"""
from typing import Optional, Sequence

from ..core import indicators as ind
from ..domain.models import PriceSeries


def _pct(v, digits: int = 4):
    return None if v is None else round(v, digits)


class CrossAssetAnalyzer:
    def __init__(self, market, catalog=None, benchmark=None, log=print):
        self.market = market
        self.catalog = catalog
        self.benchmark = benchmark      # 满足 PriceProvider 的指数源（可为 None）
        self.log = log

    # ---------------- 取数与对齐 ----------------
    def fetch(self, codes: Sequence[str], start: str, end: str,
              adjust: str = "qfq", source: Optional[str] = None
              ) -> dict[str, PriceSeries]:
        out: dict[str, PriceSeries] = {}
        for c in codes:
            try:
                s = self.market.get_series(c, start, end, adjust=adjust,
                                           source=source, require_returns=True)
            except Exception as e:                     # noqa: BLE001
                if self.log:
                    self.log(f"  [cross] {c} 取数失败: {type(e).__name__}")
                s = None
            if s is not None and len(s) > 2:
                out[s.code] = s
            elif self.log:
                self.log(f"  [cross] {c} 无可用序列，已跳过")
        return out

    @staticmethod
    def align(series: dict[str, PriceSeries]) -> tuple[list[str], dict[str, list[float]]]:
        """取所有序列的共同交易日，返回 (dates, {code: closes})。

        用交集而不是并集：并集要和「缺失日」打交道（停牌、上市晚），
        任何填充方式都会改变收益率序列，进而污染相关系数。
        """
        if not series:
            return [], {}
        common = None
        for s in series.values():
            days = set(s.dates)
            common = days if common is None else (common & days)
        dates = sorted(common or [])
        if not dates:
            return [], {}
        by_code: dict[str, list[float]] = {}
        for code, s in series.items():
            m = dict(zip(s.dates, s.closes))
            by_code[code] = [m[d] for d in dates]
        return dates, by_code

    # ---------------- 相关性 ----------------
    @staticmethod
    def correlation_matrix(aligned: dict[str, list[float]]) -> dict:
        codes = list(aligned.keys())
        rets = {c: ind.daily_returns(v) for c, v in aligned.items()}
        matrix = []
        for a in codes:
            row = []
            for b in codes:
                if a == b:
                    row.append(1.0)
                else:
                    r = ind.pearson(rets[a], rets[b])
                    row.append(None if r is None else round(r, 4))
            matrix.append(row)
        return {"codes": codes, "matrix": matrix}

    # ---------------- 净值 ----------------
    @staticmethod
    def net_value(closes: Sequence[float], base: float = 100.0) -> list:
        if not closes or closes[0] <= 0:
            return []
        c0 = closes[0]
        return [round(v / c0 * base, 4) for v in closes]

    # ---------------- 汇总 ----------------
    def compare(self, codes: Sequence[str], start: str, end: str,
                adjust: str = "qfq", source: Optional[str] = None,
                benchmark: Optional[str] = None, max_points: int = 400) -> dict:
        series = self.fetch(codes, start, end, adjust=adjust, source=source)
        dates, aligned = self.align(series)
        if not dates:
            return dict(start=start, end=end, n_days=0, assets=[],
                        correlation={"codes": [], "matrix": []},
                        net_value={"dates": [], "series": []},
                        benchmark=None,
                        note="所选标的没有共同交易日（可能停牌或区间太短）")

        # 基准：先用「基准源」，拿不到就退回把第一只标的当基准
        bench = self.benchmark_aligned(benchmark, dates, start, end)
        bench_rets = ind.daily_returns(bench["closes"]) if bench else None

        assets = []
        for code in aligned:
            closes = aligned[code]
            rets = ind.daily_returns(closes)
            meta = self.catalog.get(code) if self.catalog else {}
            entry = dict(
                code=code,
                name=(meta.get("name") or "") if meta else "",
                industry_l1=(meta.get("industry_l1_name") or "") if meta else "",
                total_return=_pct(ind.total_return(closes)),
                annualized_return=_pct(ind.annualized_return(closes)),
                annualized_volatility=_pct(ind.annualized_volatility(rets)),
                max_drawdown=_pct(ind.max_drawdown(closes)[0]),
                sharpe=_pct(ind.sharpe(rets), 4),
            )
            if bench_rets:
                entry["beta"] = _pct(ind.beta(rets, bench_rets), 4)
                entry["corr_to_benchmark"] = _pct(ind.pearson(rets, bench_rets), 4)
                entry["tracking_error"] = _pct(ind.tracking_error(rets, bench_rets))
                entry["excess_return"] = _pct(
                    (ind.total_return(closes) or 0) - (bench["total_return"] or 0))
            assets.append(entry)

        assets.sort(key=lambda a: (a["total_return"] is None,
                                   -(a["total_return"] or 0)))

        # 净值序列做等距抽样（前端只画折线，不需要 900 个点）
        idx = self._sample_index(len(dates), max_points)
        net = {"dates": [dates[i] for i in idx],
               "series": [dict(code=code, name=(self.catalog.name_of(code)
                                                if self.catalog else ""),
                               values=[self.net_value(aligned[code])[i] for i in idx])
                          for code in aligned]}
        if bench:
            bench_net = self.net_value(bench["closes"])
            bench["net_value"] = [bench_net[i] for i in idx]
            bench.pop("closes", None)

        return dict(start=dates[0], end=dates[-1], n_days=len(dates),
                    adjust=adjust,
                    source=(series[list(series)[0]].source if series else ""),
                    assets=assets,
                    correlation=self.correlation_matrix(aligned),
                    net_value=net,
                    benchmark=bench)

    # ---------------- 内部 ----------------
    def benchmark_aligned(self, symbol: Optional[str], dates: list,
                          start: str, end: str) -> Optional[dict]:
        """基准序列：按传入 symbol 取，并按 `dates` 严格对齐。

        公共方法（D4 情景分析也要用基准）：返回 None 表示「没有指数源 / 取数失败 /
        与标的交易日重叠不足」，调用方需要自己处理缺基准的情况。
        """
        if not symbol or self.benchmark is None:
            return None
        try:
            s = self.benchmark.fetch(symbol, start, end, adjust="none")
        except Exception as e:                         # noqa: BLE001
            if self.log:
                self.log(f"  [cross] 基准 {symbol} 取数失败: {type(e).__name__}")
            return None
        if s is None or len(s) < 3:
            return None

        by_date = dict(zip(s.dates, s.closes))
        overlap = [d for d in dates if d in by_date]
        if len(overlap) < max(3, int(len(dates) * 0.8)):
            # 基准与标的交易日重叠不足（区间不匹配），硬算 beta 会失真
            if self.log:
                self.log(f"  [cross] 基准 {symbol} 与标的交易日重叠不足，忽略基准")
            return None

        # 严格对齐：用前值填充基准在标的交易日上的缺口（保险，指数不停牌）
        closes, last = [], by_date[overlap[0]]
        for d in dates:
            if d in by_date:
                last = by_date[d]
            closes.append(last)

        return dict(symbol=symbol, name=self._benchmark_name(symbol),
                    total_return=_pct(ind.total_return(closes)),
                    annualized_volatility=_pct(ind.annualized_volatility(
                        ind.daily_returns(closes))),
                    source=s.source, closes=closes)

    @staticmethod
    def _benchmark_name(symbol: str) -> str:
        return {"sh000300": "沪深300", "sh000001": "上证指数",
                "sz399001": "深证成指", "sz399006": "创业板指",
                "sh000905": "中证500"}.get(str(symbol).lower(), str(symbol))

    @staticmethod
    def _sample_index(n: int, max_points: int) -> list:
        if n <= max_points:
            return list(range(n))
        step = n / float(max_points)
        return [i for i in sorted({int(k * step) for k in range(max_points)} | {n - 1})
                if i < n]

    # ---------------- 单标的序列（前端图表用） ----------------
    def series_points(self, code: str, start: str, end: str,
                      adjust: str = "qfq", source: Optional[str] = None,
                      max_points: int = 400) -> Optional[dict]:
        s = self.market.get_series(code, start, end, adjust=adjust,
                                   source=source, require_returns=True)
        if s is None or len(s) < 2:
            return None
        idx = self._sample_index(len(s), max_points)
        recs = [s.records[i] for i in idx]
        meta = self.catalog.get(code) if self.catalog else {}
        return dict(
            code=s.code,
            name=(meta.get("name") or "") if meta else "",
            industry_l1=(meta.get("industry_l1_name") or "") if meta else "",
            start=s.start, end=s.end, adjust=s.adjust, source=s.source,
            n_days=len(s),
            points=[dict(date=r.date, close=r.close, volume=r.volume,
                         pe_ttm=r.pe_ttm, pb=r.pb) for r in recs],
        )
