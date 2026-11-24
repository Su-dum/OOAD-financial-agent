# -*- coding: utf-8 -*-
"""行业（申万一级）领域对象。

B1 要求监控对象包含 **industries**。行业不是「一串股票」，而是**行业指数**：
    申万一级 31 个，每个都有 1999 年起的日线（见 docs/datasource-eval.md §10.2）
所以行业监控 = 行业指数 + 同一套行情规则，只是事件带上 `scope="industry"`。

为什么不用「成分股聚合」：成分股等权/市值加权都是我们自己造的指数，
既不可比也不可解释；交易所/申万编制的指数才是市场公认的口径。
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class IndustryRef:
    code: str                       # 801010
    name: str                       # 农林牧渔
    stock_count: int = 0
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None

    def to_dict(self) -> dict:
        return dict(code=self.code, name=self.name,
                    stock_count=self.stock_count,
                    pe_ttm=self.pe_ttm, pb=self.pb)


# 首次启动时默认监控的行业（界面上不至于空着）；不存在就退化为前三个
DEFAULT_WATCH_NAMES = ("银行", "食品饮料", "电子")
