# -*- coding: utf-8 -*-
"""领域层抽象契约（Ports）。

这一层只声明「系统需要什么能力」，不关心「谁来实现、怎么实现」。
上层（application）只依赖这些协议，不依赖任何具体数据源或数据库。

设计意图（对应 OOAD 的依赖倒置原则）：
    application  --->  ports  <---  infrastructure
                          ^
                    domain/models

新增一个数据源 / 换一个数据库，只需在 infrastructure 里加一个实现，
application 与 domain 一行都不用改。
"""
from typing import Protocol, Sequence, Optional, Any, runtime_checkable

from .models import PriceSeries


@runtime_checkable
class PriceProvider(Protocol):
    """行情数据源。任何数据源只要满足这组属性与方法，就能插进 ProviderChain。"""

    name: str
    # 数值越小越优先（口径越可信）
    priority: int
    # 这条序列的收益率能不能用来算波动率（东财的 qfq 不行）
    returns_trustworthy: bool
    # 是否自带 PE/PB 等估值字段
    supports_valuation: bool

    def fetch(self, code: str, start: str, end: str,
              adjust: str = "qfq", refresh: bool = False) -> Optional[PriceSeries]:
        ...


@runtime_checkable
class PriceCache(Protocol):
    """行情缓存。key 由调用方拼装（源 + 代码 + 复权 + 区间）。"""

    def get(self, key: str) -> Optional[PriceSeries]:
        ...

    def put(self, key: str, series: PriceSeries) -> None:
        ...


@runtime_checkable
class NewsProvider(Protocol):
    """新闻源。快照与历史翻页分开声明，因为两者能力不同。"""

    name: str

    def fetch_latest(self, limit: int = 20) -> list[dict]:
        """取最新一批（快照）。"""
        ...

    def fetch_history(self, before: Optional[str] = None, limit: int = 20) -> list[dict]:
        """向前翻页取历史。返回空列表表示到头了。"""
        ...


@runtime_checkable
class NoticeProvider(Protocol):
    """公告源。权威全文（巨潮）与结构化列表（东财）都能实现这个协议。"""

    name: str

    def list_notices(self, code: str, start: str, end: str,
                     limit: int = 30) -> list[dict]:
        ...

    def fetch_text(self, url: str) -> str:
        """下载公告 PDF 并抽取正文（用于 Evidence 引用）。"""
        ...


@runtime_checkable
class NewsRepository(Protocol):
    """新闻持久化。上层只关心「存」和「按股票查」，不关心是 SQLite 还是别的。"""

    def save(self, items: Sequence[dict]) -> tuple[int, int]:
        """返回 (新增数, 重复数)。"""
        ...

    def find_by_stock(self, code: str, start: Optional[str] = None,
                      end: Optional[str] = None, limit: int = 20,
                      min_confidence: float = 0.85) -> list[dict]:
        ...

    def find_by_keyword(self, keyword: str, limit: int = 20) -> list[dict]:
        ...

    def stats(self) -> dict:
        ...


@runtime_checkable
class EventRepository(Protocol):
    """事件持久化。"""

    def save_many(self, events: Sequence[Any]) -> int:
        ...

    def list_recent(self, code: Optional[str] = None, limit: int = 50) -> list[Any]:
        ...


@runtime_checkable
class ReportRepository(Protocol):
    """调查报告持久化。"""

    def save(self, report: Any) -> int:
        ...

    def get(self, report_id: int) -> Any:
        ...
