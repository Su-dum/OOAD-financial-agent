# -*- coding: utf-8 -*-
"""行情服务（应用层）。

职责：按优先级编排多个 PriceProvider，实现**降级链**。

关键设计：这里**没有 if/elif 分支**。所有数据源都满足 `PriceProvider` 协议，
统一放进列表按 priority 排序后依次调用。新增数据源 = 往列表里加一个对象，
本文件一行不改（开闭原则）。
"""
from typing import Optional, Sequence

from ..domain.models import PriceSeries
from ..domain.ports import PriceProvider


class ProviderChain:
    """按优先级排列的 Provider 集合，实现链式降级。"""

    def __init__(self, providers: Sequence[PriceProvider], log=print):
        # 去重 + 按 priority 升序（数值越小越可信）
        seen, uniq = set(), []
        for p in providers:
            if p.name not in seen:
                seen.add(p.name)
                uniq.append(p)
        self.providers = sorted(uniq, key=lambda p: p.priority)
        self.log = log

    def __len__(self):
        return len(self.providers)

    def names(self) -> list[str]:
        return [p.name for p in self.providers]

    def ordered(self, prefer: Optional[str] = None,
                require_returns: bool = False) -> list[PriceProvider]:
        out = [p for p in self.providers
               if not require_returns or p.returns_trustworthy]
        if prefer:
            head = [p for p in out if p.name == prefer]
            tail = [p for p in out if p.name != prefer]
            return head + tail
        return out

    def fetch(self, code: str, start: str, end: str, adjust: str = "qfq",
              prefer: Optional[str] = None, require_returns: bool = False,
              refresh: bool = False) -> Optional[PriceSeries]:
        for p in self.ordered(prefer=prefer, require_returns=require_returns):
            if self.log:
                self.log(f"  [try] {p.name} {code} {adjust}")
            ser = p.fetch(code, start, end, adjust=adjust, refresh=refresh)
            if ser is not None and len(ser) > 1:
                return ser
        return None

    def __repr__(self) -> str:
        return f"<ProviderChain {self.names()}>"


class MarketDataService:
    """对外暴露的唯一行情入口。"""

    def __init__(self, chain: ProviderChain, catalog=None, log=print):
        self.chain = chain
        self.catalog = catalog
        self.log = log

    # ---------------- 工厂 ----------------
    @classmethod
    def default(cls, cache=None, catalog=None, log=print) -> "MarketDataService":
        from ..infrastructure.providers.baostock_provider import BaostockProvider
        from ..infrastructure.providers.sina_provider import SinaProvider
        from ..infrastructure.providers.eastmoney_provider import EastmoneyProvider
        providers = [BaostockProvider(cache=cache, log=log),
                     SinaProvider(cache=cache, log=log),
                     EastmoneyProvider(cache=cache, log=log)]
        return cls(ProviderChain(providers, log=log), catalog=catalog, log=log)

    # ---------------- 查询 ----------------
    def get_series(self, code: str, start: str, end: str, adjust: str = "qfq",
                   source: Optional[str] = None, require_returns: bool = True,
                   refresh: bool = False) -> Optional[PriceSeries]:
        return self.chain.fetch(code, start, end, adjust=adjust, prefer=source,
                                require_returns=require_returns, refresh=refresh)

    def meta(self, code: str) -> dict:
        return self.catalog.get(code) if self.catalog else {}

    def name_of(self, code: str) -> str:
        return self.catalog.name_of(code) if self.catalog else ""

    def industry_of(self, code: str) -> str:
        return self.catalog.industry_of(code) if self.catalog else ""
