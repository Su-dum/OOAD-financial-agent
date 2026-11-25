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

from ..application.alert_config_service import AlertConfigService
from ..application.analysis_service import FinancialAnalyzer
from ..application.conversation_service import ConversationAgent
from ..application.cross_asset_service import CrossAssetAnalyzer
from ..application.financial_service import FinancialService
from ..application.industry_service import IndustryService
from ..application.investigation_service import (IndicatorTool, InvestigationAgent,
                                                NewsSearchTool, NoticeSearchTool)
from ..application.maintenance_service import MaintenanceService, RetentionPolicy
from ..application.market_service import MarketDataService
from ..application.monitoring_service import EventMonitor
from ..application.news_service import NewsIngestService
from ..application.notice_service import NoticeIngestService
from ..application.refresh_service import RefreshService
from ..application.scenario_service import ScenarioService
from ..application.task_service import AnalysisTaskService
from ..infrastructure.catalog import CsvStockCatalog
from ..infrastructure.llm.client import LLMConfig, OpenAIChatClient, load_dotenv
from ..infrastructure.providers.cache import CsvPriceCache
from ..infrastructure.providers.cninfo_provider import CninfoNoticeProvider
from ..infrastructure.providers.eastmoney_notice_provider import (
    EastmoneyNoticeProvider)
from ..infrastructure.providers.sina_financial_provider import SinaFinancialProvider
from ..infrastructure.providers.sina_index_provider import SinaIndexProvider
from ..infrastructure.providers.sw_industry_index_provider import (
    SwIndustryIndexProvider)
from ..infrastructure.repositories.event_repository import SqliteEventRepository
from ..infrastructure.repositories.alert_rule_repository import (
    SqliteAlertRuleRepository)
from ..infrastructure.repositories.analysis_task_repository import (
    SqliteAnalysisTaskRepository)
from ..infrastructure.repositories.financial_repository import (
    SqliteFinancialRepository)
from ..infrastructure.repositories.industry_watch_repository import (
    SqliteIndustryWatchRepository)
from ..infrastructure.repositories.news_repository import SqliteNewsRepository
from ..infrastructure.repositories.notice_repository import SqliteNoticeRepository
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
        # 公告：东财给「类型」（用于 B2 分类），巨潮给「PDF 正文」（用于 B3 引用）
        self.notice_list_provider = EastmoneyNoticeProvider(log=quiet)
        self.notice_provider = CninfoNoticeProvider(log=quiet)
        self.event_repo = SqliteEventRepository(self.news_repo.con, log=quiet)
        self.report_repo = SqliteReportRepository(self.news_repo.con, log=quiet)
        self.watchlist_repo = SqliteWatchlistRepository(self.news_repo.con, log=quiet)
        self.notice_repo = SqliteNoticeRepository(self.news_repo.con, log=quiet)
        self.alert_repo = SqliteAlertRuleRepository(self.news_repo.con, log=quiet)
        self.financial_repo = SqliteFinancialRepository(self.news_repo.con, log=quiet)
        self.task_repo = SqliteAnalysisTaskRepository(self.news_repo.con, log=quiet)
        self.industry_repo = SqliteIndustryWatchRepository(self.news_repo.con, log=quiet)
        self.watchlist_repo.seed_defaults(catalog=self.catalog)
        self.industry_repo.seed_defaults(catalog=self.catalog)

        # ---- LLM（可选）----
        self.llm_config = LLMConfig.from_env()
        self.llm_client = (OpenAIChatClient(self.llm_config, log=quiet)
                           if self.llm_config.enabled else None)

        # ---- 预警规则配置（C1）：默认 -> 全局 -> 个股 三级合并 ----
        self.alerts = AlertConfigService(self.alert_repo, log=quiet)

        # ---- 应用服务 ----
        self.market = MarketDataService.default(cache=self.cache, catalog=self.catalog,
                                               log=quiet)
        self.financial = FinancialService(
            self.financial_repo, SinaFinancialProvider(log=quiet),
            log=quiet, ttl_days=int(os.environ.get("FINANCIAL_TTL_DAYS", "7")))
        self.analyzer = FinancialAnalyzer(self.market, log=quiet,
                                          financial=self.financial)
        # 指数单独成链：指数代码（sh000300）不能和股票代码混在一条链里
        self.index_provider = SinaIndexProvider(cache=self.cache, log=quiet)
        self.cross = CrossAssetAnalyzer(self.market, catalog=self.catalog,
                                        benchmark=self.index_provider, log=quiet)
        # 情景分析（D4）：复用 cross 的取数/对齐/基准
        self.scenario = ScenarioService(self.cross, catalog=self.catalog, log=quiet)
        self.monitor = EventMonitor.default(self.market, notices=self.notice_repo,
                                            rulebook=self.alerts, log=quiet)
        tools = [
            NewsSearchTool(self.news_repo, log=quiet),
            NoticeSearchTool(self.notice_provider, repo=self.notice_repo,
                             deep=False, log=quiet),
            IndicatorTool(self.analyzer, log=quiet),
        ]
        self.agent = InvestigationAgent(
            tools=tools,
            llm=self.llm_client,          # None 时自动退回模板结论
            log=quiet,
        )
        # 自动调查用的「快」agent：永远走模板结论，保证刷新时长可控
        self.agent_fast = InvestigationAgent(tools=tools, llm=None, log=quiet)
        # 自然语言追问（C2）：LLM 可选；没有 key 时用模板答案，功能不缺失
        self.chat = ConversationAgent(
            self.analyzer, monitor=self.monitor, notices=self.notice_repo,
            news=self.news_repo, cross=self.cross, catalog=self.catalog,
            llm=self.llm_client, log=quiet)
        # 分析任务（C1）：保存「标的 + 区间 + 对比组」，一键重跑
        self.tasks = AnalysisTaskService(
            self.task_repo, self.analyzer, monitor=self.monitor,
            cross=self.cross, catalog=self.catalog, log=quiet)
        # 行业监控（B1）：行业指数走同一套行情规则，事件 scope=industry
        self.industry_provider = SwIndustryIndexProvider(cache=self.cache, log=quiet)
        self.industries = IndustryService(
            self.industry_repo, self.industry_provider, monitor=self.monitor,
            catalog=self.catalog, log=quiet)

        # ---- 运维：新闻/公告采集、保留策略、一键刷新 ----
        self.news_ingest = NewsIngestService(self.news_repo, log=quiet)
        self.notice_ingest = NoticeIngestService(
            self.notice_repo, [self.notice_list_provider, self.notice_provider],
            log=quiet)
        self.maintenance = MaintenanceService(self.news_repo.con,
                                              RetentionPolicy(), log=quiet)
        # 自动调查（B3）：默认模板结论，保证刷新时长可控；
        # 设 AUTO_INVESTIGATE_MODE=llm 才会在刷新时调大模型（慢，演示前别开）
        auto_mode = (os.environ.get("AUTO_INVESTIGATE_MODE") or "template").lower()
        self.auto_mode = "llm" if auto_mode == "llm" else "template"
        self.auto_agent = self.agent if self.auto_mode == "llm" else self.agent_fast
        self.refresh = RefreshService(
            news=self.news_ingest, monitor=self.monitor,
            event_repo=self.event_repo, watchlist_repo=self.watchlist_repo,
            maintenance=self.maintenance, con=self.news_repo.con,
            notice_ingest=self.notice_ingest, financial=self.financial,
            agent=self.auto_agent, report_repo=self.report_repo,
            industry=self.industries,
            auto_investigate=True,
            max_auto_reports=int(os.environ.get("AUTO_INVESTIGATE_MAX", "2")),
            log=quiet)

    # 便于健康检查
    def info(self) -> dict:
        return dict(
            providers=self.market.chain.names(),
            stocks=len(self.catalog),
            news=self.news_repo.stats(),
            notices=self.notice_repo.stats(),
            financials=self.financial_repo.stats(),
            industries=self.industry_repo.count(),
            tasks=self.task_repo.count(),
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
