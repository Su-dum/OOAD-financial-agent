# -*- coding: utf-8 -*-
"""东财行情适配器。

⚠️ 只用于**展示原始价格**（字段最全：换手率、振幅、涨跌幅）。
它的 `adjust="qfq"` 收盘价在非除权日不满足「复权收益 == 不复权收益」
（675 天里 470 天不符），直接拿来算收益率会让年化波动率虚高 1.23pp。

因此 `returns_trustworthy = False`，ProviderChain 会在需要算收益率的场景跳过它。
"""
from .base import BasePriceProvider, to_float
from ...domain.models import PriceRecord, StockRef

_ADJ = {"qfq": "qfq", "hfq": "hfq", "none": ""}


class EastmoneyProvider(BasePriceProvider):
    name = "eastmoney"
    priority = 90
    returns_trustworthy = False     # 关键：不参与收益率计算
    supports_valuation = False
    date_fmt = "%Y%m%d"

    def _request(self, ref: StockRef, start: str, end: str, adjust: str):
        import akshare as ak
        adj = _ADJ.get(adjust)
        if adj is None:
            raise ValueError(f"adjust 只能是 {list(_ADJ)}，收到 {adjust}")
        return ak.stock_zh_a_hist(symbol=ref.code, period="daily",
                                  start_date=start, end_date=end, adjust=adj)

    def _parse(self, raw, code: str, adjust: str) -> list[PriceRecord]:
        out = []
        for _, r in raw.iterrows():
            close = to_float(r.get("收盘"))
            if close is None:
                continue
            out.append(PriceRecord(
                code=code, date=str(r["日期"])[:10],
                open=to_float(r.get("开盘")) or close,
                high=to_float(r.get("最高")) or close,
                low=to_float(r.get("最低")) or close,
                close=close,
                volume=to_float(r.get("成交量")),
                amount=to_float(r.get("成交额")),
                turnover=to_float(r.get("换手率")),
                pct_change=to_float(r.get("涨跌幅")),
                adjust=adjust, source=self.name))
        return out
