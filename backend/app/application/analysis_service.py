# -*- coding: utf-8 -*-
"""金融分析服务（应用层）。

对应提案 4.4 里的 `FinancialAnalyzer`：负责计算金融指标并比较不同标的的表现。

设计取舍：
  - 指标公式本身留在 `core/indicators.py` 保持**纯函数**（可单测、无副作用）
  - 本类只做**编排**：取数 -> 调纯函数 -> 组装 IndicatorSet
  - 这样既有对象承载职责（OO），又保住计算层的可测性
"""
from typing import Optional, Sequence

from ..core import indicators as ind
from ..domain.models import IndicatorSet, PriceSeries
from .market_service import MarketDataService


def _round(x):
    """数值保留 6 位小数；非数值（如回撤区间的日期字符串）原样透传。"""
    if x is None or isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return round(x, 6)
    return x


class FinancialAnalyzer:
    def __init__(self, market: MarketDataService, rf: float = 0.0, log=print):
        self.market = market
        self.rf = rf          # 年化无风险利率
        self.log = log

    # ---------------- 单标的 ----------------
    def analyze(self, code: str, start: str, end: str, adjust: str = "qfq",
                source: Optional[str] = None,
                require_returns: bool = True) -> Optional[IndicatorSet]:
        series = self.market.get_series(code, start, end, adjust=adjust,
                                       source=source,
                                       require_returns=require_returns)
        if series is None or len(series) < 2:
            return None
        return self.from_series(series)

    def from_series(self, series: PriceSeries) -> IndicatorSet:
        """从已有序列算指标（便于测试与复用，不触发网络）。"""
        pe = [r.pe_ttm for r in series.records]
        pb = [r.pb for r in series.records]
        calc = ind.analyze_series(series.dates, series.closes,
                                  pe_series=pe, pb_series=pb, rf=self.rf)

        meta = self.market.meta(series.code)
        base = dict(
            code=series.code,
            name=(meta.get("name") or ""),
            industry_l1=(meta.get("industry_l1_name") or ""),
            start=series.start, end=series.end, n_days=len(series),
            adjust=series.adjust, source=series.source,
        )
        computed = {k: _round(v) for k, v in calc.items()
                    if k in IndicatorSet.__dataclass_fields__ and k not in base}
        result = IndicatorSet(**base, **computed)

        for f in ("roe", "profit_growth", "revenue_growth", "market_cap"):
            v = meta.get(f)
            try:
                setattr(result, f, None if v in (None, "", "nan") else float(v))
            except (TypeError, ValueError):
                pass
        return result

    # ---------------- 横向比较（A3）----------------
    def compare(self, codes: Sequence[str], start: str, end: str,
                adjust: str = "qfq", source: Optional[str] = None,
                require_returns: bool = True) -> list[IndicatorSet]:
        out = []
        for c in codes:
            r = self.analyze(c, start, end, adjust=adjust, source=source,
                             require_returns=require_returns)
            if r is not None:
                out.append(r)
        out.sort(key=lambda x: (x.total_return is None, -(x.total_return or 0)))
        return out

    # ---------------- 跨期比较（A3）----------------
    def compare_periods(self, code: str, periods: Sequence[tuple],
                        adjust: str = "qfq",
                        source: Optional[str] = None) -> list[dict]:
        rows = []
        for label, s, e in periods:
            r = self.analyze(code, s, e, adjust=adjust, source=source)
            rows.append(dict(
                period=label, start=s, end=e,
                total_return=None if r is None else r.total_return,
                annualized_volatility=None if r is None else r.annualized_volatility,
                max_drawdown=None if r is None else r.max_drawdown,
                sharpe=None if r is None else r.sharpe,
                n_days=0 if r is None else r.n_days))
        return rows

    # ---------------- 展示 ----------------
    @staticmethod
    def describe(r: IndicatorSet) -> str:
        p = lambda v, s="%": "—" if v is None else f"{v*100:+.2f}{s}"
        d = lambda v, s="%": "—" if v is None else f"{v*100:.2f}{s}"
        f = lambda v: "—" if v is None else f"{v:.2f}"
        return (f"{r.code} {r.name or '':<6} {r.industry_l1 or '':<6} "
                f"区间收益 {p(r.total_return):>8}  年化波动 {d(r.annualized_volatility):>7}  "
                f"最大回撤 {d(r.max_drawdown):>7}  夏普 {f(r.sharpe):>6}  "
                f"PE(TTM) {f(r.pe_ttm):>7}  ROE {f(r.roe):>6}")
