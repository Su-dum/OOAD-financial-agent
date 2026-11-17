# -*- coding: utf-8 -*-
"""指数行情适配器（D3 的基准源）。

数据源评估（`docs/datasource-eval.md` §10.1）实测 4 个源都可用，
这里选**新浪**做主源：6017 行、2002 年起、0.4 秒，最快且历史最长。

为什么不把指数塞进 `MarketDataService` 的价格链？
    因为股票代码和指数代码会撞（`000001` 既是平安银行也是上证指数）。
    价格链的 key 是「6 位股票代码」，指数必须显式带交易所前缀（`sh000300`），
    混在一条链里迟早选错源。所以指数单独成链，只在跨资产分析里用。

⚠️ 指数的 `adjust` 无意义，一律传 "none"；这里保留参数只为满足 `PriceProvider` 协议。
"""
from typing import Optional

from .base import BasePriceProvider, to_float
from .akshare_compat import call as akcall
from ...domain.models import PriceRecord, StockRef

_PREFIX = ("sh", "sz", "bj")


def normalize_symbol(code: str) -> str:
    """`000300` -> `sh000300`，`399001` -> `sz399001`，已带前缀则原样返回。"""
    s = str(code).strip().lower()
    if s.startswith(_PREFIX):
        return s
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return s
    # 沪市指数：000xxx / 880xxx；深市：399xxx / 980xxx
    return ("sh" if digits.startswith(("000", "880")) else "sz") + digits


class SinaIndexProvider(BasePriceProvider):
    name = "index_sina"
    priority = 10
    returns_trustworthy = True
    supports_valuation = False
    date_fmt = "%Y%m%d"

    def cache_key(self, code: str, start: str, end: str, adjust: str) -> str:
        return f"{self.name}_{normalize_symbol(code)}_{start}_{end}"

    def _request(self, ref: StockRef, start: str, end: str, adjust: str):
        symbol = normalize_symbol(ref.code)
        # akshare 1.20.44+：stock_zh_index_daily -> index_zh_daily_sina
        df = akcall("stock_zh_index_daily", symbol=symbol)
        if df is None or len(df) == 0:
            return None
        keep = df.copy()
        dates = keep["date"].astype(str).str[:10]
        iso_start = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        iso_end = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        keep = keep[(dates >= iso_start) & (dates <= iso_end)]
        return keep if len(keep) > 0 else None

    def _parse(self, raw, code: str, adjust: str) -> list[PriceRecord]:
        out = []
        for _, r in raw.iterrows():
            close = to_float(r.get("close"))
            if close is None:
                continue
            out.append(PriceRecord(
                code=normalize_symbol(code), date=str(r["date"])[:10],
                open=to_float(r.get("open")) or close,
                high=to_float(r.get("high")) or close,
                low=to_float(r.get("low")) or close,
                close=close,
                volume=to_float(r.get("volume")),
                adjust="none", source=self.name))
        return out
