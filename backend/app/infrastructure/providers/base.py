# -*- coding: utf-8 -*-
"""行情 Provider 基类。

用**模板方法**固定取数骨架，子类只实现两个钩子：

    fetch()          <- 模板方法，本类实现（缓存 -> 重试 -> 解析 -> 回写）
      _request()     <- 子类实现：怎么发请求、返回什么原始数据
      _parse()       <- 子类实现：原始数据 -> list[PriceRecord]

新增一个数据源只需写两个钩子（约 30 行），缓存、重试、日期归一化、
异常处理全部复用，不会再出现三份复制粘贴。
"""
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from ...domain.models import PriceRecord, PriceSeries, StockRef


def to_float(x) -> Optional[float]:
    try:
        if x is None or x == "" or x == "None":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def norm_date(d: str, fmt: str = "%Y-%m-%d") -> str:
    d = str(d).strip()
    for f in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(d, f).strftime(fmt)
        except ValueError:
            continue
    return d


def retry_call(fn, name: str = "", attempts: int = 4, base: float = 3.0, log=print):
    """指数退避。东财实测会从 ConnectionError 升级成持续拒绝，所以重试是必须的。"""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            wait = base * (2 ** i)
            if log:
                log(f"  [retry {i+1}/{attempts}] {name}: {type(e).__name__} "
                    f"{str(e)[:70]} -> {wait:.0f}s")
            if i < attempts - 1:
                time.sleep(wait)
    if log:
        log(f"  [FAIL] {name} 重试耗尽")
    return None


class BasePriceProvider(ABC):
    """所有行情数据源的父类。子类只需声明元信息 + 实现两个钩子。"""

    name: str = "base"
    priority: int = 100                 # 越小越优先
    returns_trustworthy: bool = True    # 该源的复权序列能否用来算收益率
    supports_valuation: bool = False    # 是否自带 PE/PB
    date_fmt: str = "%Y-%m-%d"          # _request 期望的日期格式

    def __init__(self, cache=None, log=print, attempts: int = 4, base_wait: float = 3.0):
        self.cache = cache
        self.log = log
        self.attempts = attempts
        self.base_wait = base_wait

    # ---------------- 模板方法 ----------------
    def fetch(self, code: str, start: str, end: str,
              adjust: str = "qfq", refresh: bool = False) -> Optional[PriceSeries]:
        ref = StockRef(code=str(code).split(".")[0])
        s = norm_date(start, self.date_fmt)
        e = norm_date(end, self.date_fmt)
        key = self.cache_key(ref.code, s, e, adjust)

        if not refresh and self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None and len(hit) > 1:
                if self.log:
                    self.log(f"  [cache] {self.name} {ref.code} {adjust} {len(hit)} 行")
                return hit

        raw = retry_call(lambda: self._request(ref, s, e, adjust),
                         f"{self.name} {ref.code} {s}~{e}",
                         attempts=self.attempts, base=self.base_wait, log=self.log)
        if raw is None:
            return None

        recs = [r for r in self._parse(raw, ref.code, adjust) if r is not None]
        if not recs:
            return None

        series = PriceSeries(code=ref.code, records=recs,
                             adjust=adjust, source=self.name)
        if len(series) > 1 and self.cache is not None:
            self.cache.put(key, series)
        return series

    # ---------------- 供子类覆盖 ----------------
    def cache_key(self, code: str, start: str, end: str, adjust: str) -> str:
        return f"{self.name}_{code}_{adjust}_{start}_{end}"

    @abstractmethod
    def _request(self, ref: StockRef, start: str, end: str, adjust: str) -> Any:
        """发请求，返回原始数据（DataFrame / (fields, rows) 均可）。"""

    @abstractmethod
    def _parse(self, raw: Any, code: str, adjust: str) -> list[PriceRecord]:
        """原始数据 -> 领域对象列表。"""

    # ---------------- 辅助 ----------------
    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name} priority={self.priority}>"
