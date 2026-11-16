# -*- coding: utf-8 -*-
"""依赖装配（Composition Root）。

整个应用的**对象图**只在这里拼一次：
    适配器（具体实现） -> 应用服务 -> 接口层

接口层（routes）只拿到服务对象，不关心背后是 baostock 还是新浪、SQLite 还是别的。
换数据源 / 换数据库 / 换大模型，只需要改这个文件的装配。

LLM 是否启用由环境变量决定（见 `.env.example`）：
    有 LLM_API_KEY  -> 用大模型归纳结论（带引用校验）
    没有            -> 退回模板结论，功能不缺失
"""
import os
from functools import lru_cache
from pathlib import Path

from ..application.analysis_service import FinancialAnalyzer
from ..application.investigation_service import (IndicatorTool, InvestigationAgent,
                                                NewsSearchTool, NoticeSearchTool)
from ..application.maintenance_service import MaintenanceService, RetentionPolicy
from ..application.market_service import MarketDataService
from ..application.monitoring_service import EventMonitor
from ..application.news_service import NewsIngestService
from ..application.refresh_service import RefreshService
from ..infrastructure.catalog import CsvStockCatalog
from ..infrastructure.llm.client import LLMConfig, OpenAIChatClient, load_dotenv
from ..infrastructure.providers.cache import CsvPriceCache
from ..infrastructure.providers.cninfo_provider import CninfoNoticeProvider
from ..infrastructure.repositories.event_repository import SqliteEventRepository
from ..infrastructure.repositories.news_repository import SqliteNewsRepository
from ..infrastructure.repositories.report_repository import SqliteReportRepository
from ..infrastructure.repositories.watchlist_repository import SqliteWatchlistRepository

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "data" / "cache" / "market"
MARKET_CACHE_TTL = int(os.environ.get("MARKET_CACHE_TTL", str(12 * 3600)))


class Services:
    """应用级对象容器。"""

    def __init__(self, log=None):
        self.log = log
        quiet = log if log is not None else (lambda *a, **k: None)

        # ---- 配置：.env 只填不覆盖已存在的环境变量 ----
        load_dotenv(ROOT / ".env")

        # ---- 基础设施：适配器 ----
        self.cache = CsvPriceCache(CACHE_DIR, ttl=MARKET_CACHE_TTL)
        self.catalog = CsvStockCatalog()
        self.news_repo = SqliteNewsRepository.open(log=quiet)
        self.notice_provider = CninfoNoticeProvider(log=quiet)
        self.event_repo = SqliteEventRepository(self.news_repo.con, log=quiet)
        self.report_repo = SqliteReportRepository(self.news_repo.con, log=quiet)
        self.watchlist_repo = SqliteWatchlistRepository(self.news_repo.con, log=quiet)
        self.watchlist_repo.seed_defaults(catalog=self.catalog)

        # ---- LLM（可选）----
        self.llm_config = LLMConfig.from_env()
        self.llm_client = (OpenAIChatClient(self.llm_config, log=quiet)
                           if self.llm_config.enabled else None)

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
            llm=self.llm_client,          # None 时自动退回模板结论
            log=quiet,
        )

        # ---- 运维：新闻采集、保留策略、一键刷新 ----
        self.news_ingest = NewsIngestService(self.news_repo, log=quiet)
        self.maintenance = MaintenanceService(self.news_repo.con,
                                              RetentionPolicy(), log=quiet)
        self.refresh = RefreshService(
            news=self.news_ingest, monitor=self.monitor,
            event_repo=self.event_repo, watchlist_repo=self.watchlist_repo,
            maintenance=self.maintenance, con=self.news_repo.con, log=quiet)

    # 便于健康检查
    def info(self) -> dict:
        return dict(
            providers=self.market.chain.names(),
            stocks=len(self.catalog),
            news=self.news_repo.stats(),
            cache_dir=str(CACHE_DIR),
            llm=dict(
                enabled=self.llm_client is not None,
                provider=self.llm_config.provider,
                model=self.llm_config.model,
                conclusion_writer=getattr(self.agent.writer, "name", "?"),
            ),
            retention=self.maintenance.policy.describe(),
            watchlist=len(self.watchlist_repo.load()),
        )


@lru_cache(maxsize=1)
def get_services() -> Services:
    return Services()


def reset_services() -> None:
    """测试用：丢弃已装配的对象图。"""
    get_services.cache_clear()
