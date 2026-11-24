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


def _set_float(obj, field: str, value) -> None:
    """把可能为字符串/NaN 的外部值写进 dataclass 字段；非法值保持 None。"""
    if value in (None, "", "nan", "None"):
        setattr(obj, field, None)
        return
    try:
        setattr(obj, field, float(value))
    except (TypeError, ValueError):
        setattr(obj, field, None)


class FinancialAnalyzer:
    def __init__(self, market: MarketDataService, rf: float = 0.0, log=print,
                 financial=None):
        self.market = market
        self.rf = rf          # 年化无风险利率
        self.log = log
        # 财务快照来源（A1）。None 时退回申万映射表里的静态快照
        self.financial = financial

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
        self._apply_financials(result, series.code, meta)
        return result

    def _apply_financials(self, result: IndicatorSet, code: str, meta: dict) -> None:
        """填盈利/成长字段。

        优先级：**财务快照（实时抓取，A1）> 申万映射表静态快照**。
        后者是构建行业映射时的副产物，只在财务服务没取到数据时兜底，
        这样「A1 已接外部财务接口」这件事在结果里体现为 `financial_source`。
        """
        snap = None
        if self.financial is not None:
            try:
                snap = self.financial.get(code)
            except Exception:                           # noqa: BLE001
                snap = None

        # 三个历史字段的名字与新快照不同，做一次映射
        legacy = {"roe": "roe", "profit_growth": "net_profit_growth",
                  "revenue_growth": "revenue_growth"}
        for target, source in legacy.items():
            v = (snap or {}).get(source)
            if v in (None, "", "nan"):
                v = meta.get(target)
            _set_float(result, target, v)

        # 新增字段只来自财务快照
        for f in ("net_margin", "gross_margin", "debt_ratio", "eps"):
            _set_float(result, f, (snap or {}).get(f))

        _set_float(result, "market_cap", meta.get("market_cap"))
        if snap:
            result.financial_report_date = snap.get("report_date")
            result.financial_source = snap.get("source")

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
