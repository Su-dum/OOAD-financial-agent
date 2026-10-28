# -*- coding: utf-8 -*-
"""新浪行情适配器。

口径已验证可用：非除权日「前复权收益」与「不复权收益」最大偏差 6.95e-06
（仅舍入噪声，对年化波动率影响约 0.0026pp，比东财小 467 倍）。
缺点：不带 PE / PB，估值字段需要另取。
2026-10-28 实测：东财、baostock 双双不可用时，它仍然 2.4s 取到 3 年 923 行。
"""
from .base import BasePriceProvider, to_float
from ...domain.models import PriceRecord, StockRef

_ADJ = {"qfq": "qfq", "hfq": "hfq", "none": ""}


class SinaProvider(BasePriceProvider):
    name = "sina"
    priority = 20
    returns_trustworthy = True
    supports_valuation = False
    date_fmt = "%Y%m%d"

    def _request(self, ref: StockRef, start: str, end: str, adjust: str):
        import akshare as ak
        adj = _ADJ.get(adjust)
        if adj is None:
            raise ValueError(f"adjust 只能是 {list(_ADJ)}，收到 {adjust}")
        return ak.stock_zh_a_daily(symbol=ref.sina_code, start_date=start,
                                   end_date=end, adjust=adj)

    def _parse(self, raw, code: str, adjust: str) -> list[PriceRecord]:
        out = []
        for _, r in raw.iterrows():
            close = to_float(r.get("close"))
            if close is None:
                continue
            out.append(PriceRecord(
                code=code, date=str(r["date"])[:10],
                open=to_float(r.get("open")) or close,
                high=to_float(r.get("high")) or close,
                low=to_float(r.get("low")) or close,
                close=close,
                volume=to_float(r.get("volume")),
                amount=to_float(r.get("amount")),
                turnover=to_float(r.get("turnover")),
                adjust=adjust, source=self.name))
        return out
