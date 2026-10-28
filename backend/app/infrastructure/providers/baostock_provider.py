# -*- coding: utf-8 -*-
"""baostock 行情适配器。

口径最可信：非除权日「前复权收益」与「不复权收益」完全一致（偏差 0），
且同一次请求就带回 peTTM / pbMRQ / psTTM / pcfNcfTTM。
缺点：服务端不稳定（实测 3s 恶化到 57s 甚至挂起），所以必须配缓存。
"""
import io
import contextlib
import threading

from .base import BasePriceProvider, to_float
from ...domain.models import PriceRecord, StockRef

# baostock 内部维护全局连接，必须串行；且会直接 print，需要静音
_LOCK = threading.Lock()

_FIELDS = ("date,code,open,high,low,close,preclose,volume,amount,turn,"
           "pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM")

_ADJ = {"hfq": "1", "qfq": "2", "none": "3"}   # baostock 的 adjustflag


class BaostockProvider(BasePriceProvider):
    name = "baostock"
    priority = 10
    returns_trustworthy = True
    supports_valuation = True
    date_fmt = "%Y-%m-%d"

    def _request(self, ref: StockRef, start: str, end: str, adjust: str):
        flag = _ADJ.get(adjust)
        if flag is None:
            raise ValueError(f"adjust 只能是 {list(_ADJ)}，收到 {adjust}")
        import baostock as bs
        with _LOCK:
            with contextlib.redirect_stdout(io.StringIO()):
                lg = bs.login()
            try:
                if lg.error_code != "0":
                    raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
                rs = bs.query_history_k_data_plus(
                    ref.bs_code, _FIELDS, start_date=start, end_date=end,
                    frequency="d", adjustflag=flag)
                if rs.error_code != "0":
                    raise RuntimeError(f"baostock 查询失败: {rs.error_msg}")
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                return rs.fields, rows
            finally:
                with contextlib.redirect_stdout(io.StringIO()):
                    bs.logout()

    def _parse(self, raw, code: str, adjust: str) -> list[PriceRecord]:
        fields, rows = raw
        idx = {n: i for i, n in enumerate(fields)}
        out = []
        for row in rows:
            close = to_float(row[idx["close"]])
            if close is None:
                continue
            out.append(PriceRecord(
                code=code, date=row[idx["date"]],
                open=to_float(row[idx["open"]]) or close,
                high=to_float(row[idx["high"]]) or close,
                low=to_float(row[idx["low"]]) or close,
                close=close,
                volume=to_float(row[idx["volume"]]),
                amount=to_float(row[idx["amount"]]),
                turnover=to_float(row[idx["turn"]]),
                pct_change=to_float(row[idx["pctChg"]]),
                pe_ttm=to_float(row[idx["peTTM"]]),
                pb=to_float(row[idx["pbMRQ"]]),
                ps_ttm=to_float(row[idx["psTTM"]]),
                pcf_ttm=to_float(row[idx["pcfNcfTTM"]]),
                adjust=adjust, source=self.name))
        return out
