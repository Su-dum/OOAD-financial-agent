# -*- coding: utf-8 -*-
"""申万行业指数适配器（B1：行业级监控）。

数据：`index_hist_sw(symbol="801010", period="day")`
—— 申万一级行业指数，实测 6479 行、1999-12-30 起（见 `docs/datasource-eval.md` §10.2）。

为什么行业指数不复用股票价格链：
    行业代码是 6 位（801010），同样会被误认为股票代码；
    且指数的复权无意义。所以行业指数和宽基指数一样，**单独一个 Provider**。

返回的 `PriceSeries.code` 是行业代码，`source` 是 `industry_sw`，
上层（`EventMonitor.evaluate_series`）拿它跑同一套行情规则即可，
不需要为行业写第二套检测逻辑。
"""
from typing import Optional

from .akshare_compat import call as akcall
from .base import BasePriceProvider, to_float
from ...domain.models import PriceRecord, StockRef

_COL = {"date": ("日期", "date"), "open": ("开盘", "open"),
        "high": ("最高", "high"), "low": ("最低", "low"),
        "close": ("收盘", "close"), "volume": ("成交量", "volume"),
        "amount": ("成交额", "amount")}


def _pick(row, names):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


class SwIndustryIndexProvider(BasePriceProvider):
    name = "industry_sw"
    priority = 10
    returns_trustworthy = True
    supports_valuation = False
    date_fmt = "%Y%m%d"

    def cache_key(self, code: str, start: str, end: str, adjust: str) -> str:
        return f"industry_sw_{str(code).strip()}_{start}_{end}"

    def _request(self, ref: StockRef, start: str, end: str, adjust: str):
        df = akcall("index_hist_sw", symbol=str(ref.code).strip(), period="day")
        if df is None or len(df) == 0:
            return None
        dates = df[_COL["date"][0]].astype(str).str[:10]
        iso_start = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        iso_end = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        sliced = df[(dates >= iso_start) & (dates <= iso_end)]
        return sliced if len(sliced) > 0 else None

    def _parse(self, raw, code: str, adjust: str) -> list[PriceRecord]:
        out = []
        for _, r in raw.iterrows():
            close = to_float(_pick(r, _COL["close"]))
            if close is None:
                continue
            row = r.to_dict()
            out.append(PriceRecord(
                code=str(code).strip(),
                date=str(_pick(row, _COL["date"]))[:10],
                open=to_float(_pick(row, _COL["open"])) or close,
                high=to_float(_pick(row, _COL["high"])) or close,
                low=to_float(_pick(row, _COL["low"])) or close,
                close=close,
                volume=to_float(_pick(row, _COL["volume"])),
                amount=to_float(_pick(row, _COL["amount"])),
                adjust="none", source=self.name))
        return out
