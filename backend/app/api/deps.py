# -*- coding: utf-8 -*-
"""依赖装配（Composition Root）。

整个应用的**对象图**只在这里拼一次：
    适配器（具体实现） -> 应用服务 -> 接口层

接口层（routes）只拿到服务对象，不关心背后是 baostock 还是新浪、SQLite 还是别的。
换数据源 / 换数据库，只需要改这个文件的装配。
"""
import os
from functools import lru_cache
from pathlib import Path

from ..application.analysis_service import FinancialAnalyzer
from ..application.investigation_service import (IndicatorTool, InvestigationAgent,
                                                NewsSearchTool, NoticeSearchTool)
from ..application.market_service import MarketDataService
from ..application.monitoring_service import EventMonitor
from ..infrastructure.catalog import CsvStockCatalog
from ..infrastructure.providers.cache import CsvPriceCache
from ..infrastructure.providers.cninfo_provider import CninfoNoticeProvider
from ..infrastructure.repositories.event_repository import SqliteEventRepository
from ..infrastructure.repositories.news_repository import SqliteNewsRepository
from ..infrastructure.repositories.report_repository import SqliteReportRepository

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "data" / "cache" / "market"
MARKET_CACHE_TTL = int(os.environ.get("MARKET_CACHE_TTL", str(12 * 3600)))


class Services:
    """应用级对象容器。"""

    def __init__(self, log=None):
        self.log = log
        quiet = log if log is not None else (lambda *a, **k: None)

        # ---- 基础设施：适配器 ----
        self.cache = CsvPriceCache(CACHE_DIR, ttl=MARKET_CACHE_TTL)
        self.catalog = CsvStockCatalog()
        self.news_repo = SqliteNewsRepository.open(log=quiet)
        self.notice_provider = CninfoNoticeProvider(log=quiet)
        self.event_repo = SqliteEventRepository(self.news_repo.con, log=quiet)
        self.report_repo = SqliteReportRepository(self.news_repo.con, log=quiet)

        # ---- 应用服务 ----
        self.market = MarketDataService.default(cache=self.cache, catalog=self.catalog,
                                               log=quiet)
        self.analyzer = FinancialAnalyzer(self.market, log=quiet)
        self.monitor = EventMonitor.default(self.market, log=quiet)
        self.agent = InvestigationAgent(
            tools=[
                NewsSearchTool(self.news_repo, log=quiet),
                NoticeSearchTool(self.notice_provider, deep=False, log=quiet),
                IndicatorTool(self.analyzer, log=quiet),
            ],
            llm=None,      # 接入大模型时在这里注入一个满足 LLMClient 协议的对象
            log=quiet,
        )

    # 便于健康检查
    def info(self) -> dict:
        return dict(
            providers=self.market.chain.names(),
            stocks=len(self.catalog),
            news=self.news_repo.stats(),
            cache_dir=str(CACHE_DIR),
        )


@lru_cache(maxsize=1)
def get_services() -> Services:
    return Services()


def reset_services() -> None:
    """测试用：丢弃已装配的对象图。"""
    get_services.cache_clear()
