# -*- coding: utf-8 -*-
"""行情服务（应用层）。

职责：按优先级编排多个 PriceProvider，实现**降级链**。

关键设计：这里**没有 if/elif 分支**。所有数据源都满足 `PriceProvider` 协议，
统一放进列表按 priority 排序后依次调用。新增数据源 = 往列表里加一个对象，
本文件一行不改（开闭原则）。

## 失败冷却（circuit breaker）

一个数据源失败后，后续请求不该继续在它身上浪费 6~20 秒（baostock 半挂起时尤其明显）。
所以 `ProviderChain` 会记住「谁刚失败过」，在 `fail_cooldown` 秒内**跳过**它：

    首次请求：baostock 超时（6s）-> 记冷却 -> 新浪返回（2s）
    后续请求：直接走新浪（不再碰 baostock，直到冷却结束）

失效是暂时的：冷却到期后 baostock 会自动回到链首，恢复「口径最可信」的优先级。
"""
import time
from typing import Optional, Sequence

from ..domain.models import PriceSeries
from ..domain.ports import PriceProvider


class ProviderChain:
    """按优先级排列的 Provider 集合，实现链式降级。"""

    def __init__(self, providers: Sequence[PriceProvider], log=print,
                 fail_cooldown: float = 300.0):
        # 去重 + 按 priority 升序（数值越小越可信）
        seen, uniq = set(), []
        for p in providers:
            if p.name not in seen:
                seen.add(p.name)
                uniq.append(p)
        self.providers = sorted(uniq, key=lambda p: p.priority)
        self.log = log
        self.fail_cooldown = fail_cooldown
        self._cooldown: dict[str, float] = {}     # name -> 恢复时间戳

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

    def in_cooldown(self, name: str) -> bool:
        return self._cooldown.get(name, 0.0) > time.time()

    def _mark_failed(self, name: str) -> None:
        self._cooldown[name] = time.time() + self.fail_cooldown
        if self.log:
            self.log(f"  [cooldown] {name} 失败，{self.fail_cooldown:.0f}s 内跳过")

    def fetch(self, code: str, start: str, end: str, adjust: str = "qfq",
              prefer: Optional[str] = None, require_returns: bool = False,
              refresh: bool = False) -> Optional[PriceSeries]:
        for p in self.ordered(prefer=prefer, require_returns=require_returns):
            if self.in_cooldown(p.name) and p.name != prefer:
                if self.log:
                    self.log(f"  [skip] {p.name} 处于冷却期，直接降级")
                continue
            if self.log:
                self.log(f"  [try] {p.name} {code} {adjust}")
            ser = p.fetch(code, start, end, adjust=adjust, refresh=refresh)
            if ser is not None and len(ser) > 1:
                return ser
            self._mark_failed(p.name)
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
        # baostock：socket 超时 5s + 不重试（失败后立刻走链式降级并进入冷却期）。
        # 重试交给新浪/东财，避免一个半挂起的源把交互请求拖到几十秒。
        providers = [BaostockProvider(cache=cache, log=log, attempts=1,
                                      base_wait=0.5, timeout=5.0),
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
