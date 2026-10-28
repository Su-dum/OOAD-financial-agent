# -*- coding: utf-8 -*-
"""架构测试：验证抽象契约、多态与依赖注入真的生效。

这些测试**完全不联网**——用假的 Provider / 工具替换真实实现。
能做到这一点，本身就说明分层和解耦是有效的：
如果代码里到处是 if src == 'baostock'，就没法这样在运行时替换。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.domain.models import PriceRecord, PriceSeries, StockRef
from backend.app.domain.events import (MarketEvent, ThresholdRule, VolumeSpikeRule,
                                       ZScoreRule)
from backend.app.domain.investigation import Evidence
from backend.app.domain.ports import PriceProvider, PriceCache
from backend.app.infrastructure.providers.base import BasePriceProvider
from backend.app.application.market_service import MarketDataService, ProviderChain
from backend.app.application.analysis_service import FinancialAnalyzer
from backend.app.application.investigation_service import InvestigationAgent


# ============================================================
# 测试替身（Test Doubles）
# ============================================================
def make_records(code="600519", closes=(100.0, 110.0, 99.0, 121.0)):
    dates = [f"2026-01-{i+1:02d}" for i in range(len(closes))]
    return [PriceRecord(code=code, date=d, open=c, high=c, low=c, close=c,
                        volume=1000.0, pe_ttm=20.0, pb=5.0)
            for d, c in zip(dates, closes)]


class FakeProvider(BasePriceProvider):
    """可配置返回值的假数据源。"""
    priority = 10

    def __init__(self, name="fake", returns_trustworthy=True, closes=None,
                 fail=False, cache=None):
        super().__init__(cache=cache, log=lambda *a, **k: None, attempts=1)
        self.name = name
        self.returns_trustworthy = returns_trustworthy
        self.supports_valuation = True
        self._closes = closes or (100.0, 110.0, 99.0, 121.0)
        self._fail = fail
        self.request_count = 0

    def _request(self, ref, start, end, adjust):
        self.request_count += 1
        if self._fail:
            raise RuntimeError("模拟数据源不可用")
        return "raw"

    def _parse(self, raw, code, adjust):
        return make_records(code=code, closes=self._closes)


class MemoryCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def put(self, key, series):
        self.store[key] = series


class StubCatalog:
    def __init__(self, meta=None):
        self._meta = meta or {"name": "贵州茅台", "industry_l1_name": "食品饮料",
                              "roe": "17.95", "profit_growth": "-1.95"}

    def get(self, code):
        return dict(self._meta)

    def name_of(self, code):
        return self._meta.get("name", "")

    def industry_of(self, code):
        return self._meta.get("industry_l1_name", "")


class FakeTool:
    """假调查工具。"""
    def __init__(self, name, kind, evidences):
        self.name = name
        self.kind = kind
        self._evidences = evidences
        self.calls = 0

    def run(self, code, start, end, context=None):
        self.calls += 1
        return list(self._evidences)


# ============================================================
# 1. 协议与多态
# ============================================================
def test_fake_provider_satisfies_protocol():
    """结构化类型：只要属性和方法对得上，就算满足协议，不需要继承。"""
    assert isinstance(FakeProvider(), PriceProvider)


def test_memory_cache_satisfies_protocol():
    assert isinstance(MemoryCache(), PriceCache)


def test_provider_has_required_metadata():
    p = FakeProvider()
    assert p.name and isinstance(p.priority, int)
    assert isinstance(p.returns_trustworthy, bool)
    assert isinstance(p.supports_valuation, bool)


# ============================================================
# 2. ProviderChain：优先级 / 降级 / 过滤（无 if-elif）
# ============================================================
def test_chain_orders_by_priority():
    a, b = FakeProvider(name="a"), FakeProvider(name="b")
    a.priority, b.priority = 50, 10
    chain = ProviderChain([a, b], log=None)
    assert chain.names() == ["b", "a"]


def test_chain_falls_back_when_first_fails():
    bad = FakeProvider(name="bad", fail=True)
    good = FakeProvider(name="good")
    bad.priority, good.priority = 10, 20
    market = MarketDataService(ProviderChain([bad, good], log=None), catalog=StubCatalog())
    series = market.get_series("600519", "2026-01-01", "2026-01-05")
    assert series is not None
    assert series.source == "good"
    assert bad.request_count == 1 and good.request_count == 1


def test_chain_filters_untrustworthy_when_returns_required():
    """东财那类「复权口径不对」的源，在需要算收益率时必须被跳过。"""
    risky = FakeProvider(name="risky", returns_trustworthy=False)
    safe = FakeProvider(name="safe")
    risky.priority, safe.priority = 10, 20
    market = MarketDataService(ProviderChain([risky, safe], log=None), catalog=StubCatalog())

    s1 = market.get_series("600519", "2026-01-01", "2026-01-05", require_returns=True)
    assert s1.source == "safe"

    s2 = market.get_series("600519", "2026-01-01", "2026-01-05", require_returns=False)
    assert s2.source == "risky"      # 只看价格时可以用它


def test_chain_prefer_moves_source_to_front():
    a = FakeProvider(name="a")
    b = FakeProvider(name="b")
    a.priority, b.priority = 10, 20
    chain = ProviderChain([a, b], log=None)
    assert chain.ordered(prefer="b")[0].name == "b"


def test_chain_returns_none_when_all_fail():
    market = MarketDataService(
        ProviderChain([FakeProvider(name="x", fail=True)], log=None), catalog=StubCatalog())
    assert market.get_series("600519", "2026-01-01", "2026-01-05") is None


# ============================================================
# 3. 基类模板方法：缓存生效
# ============================================================
def test_template_method_uses_cache():
    cache = MemoryCache()
    p = FakeProvider(cache=cache)
    p.fetch("600519", "2026-01-01", "2026-01-05")
    p.fetch("600519", "2026-01-01", "2026-01-05")
    assert p.request_count == 1          # 第二次命中缓存，没有再请求
    assert len(cache.store) == 1


def test_template_method_refresh_bypasses_cache():
    cache = MemoryCache()
    p = FakeProvider(cache=cache)
    p.fetch("600519", "2026-01-01", "2026-01-05")
    p.fetch("600519", "2026-01-01", "2026-01-05", refresh=True)
    assert p.request_count == 2


# ============================================================
# 4. FinancialAnalyzer：不联网也能算
# ============================================================
def test_analyzer_from_series_computes_without_network():
    market = MarketDataService(ProviderChain([FakeProvider()], log=None),
                               catalog=StubCatalog())
    analyzer = FinancialAnalyzer(market, log=None)
    series = PriceSeries(code="600519", records=make_records(),
                         adjust="qfq", source="fake")
    r = analyzer.from_series(series)

    assert r.code == "600519"
    assert r.name == "贵州茅台"
    assert r.total_return == pytest.approx(0.21, rel=1e-6)
    assert r.max_drawdown == pytest.approx(99 / 110 - 1, rel=1e-6)
    assert r.roe == pytest.approx(17.95)
    assert r.source == "fake" and r.adjust == "qfq"     # 口径被带到结果里
    assert r.n_days == 4


# ============================================================
# 5. AlertRule 策略族
# ============================================================
def test_threshold_rule_detects_drop():
    series = PriceSeries(code="x", records=make_records(closes=(100.0, 90.0)))
    events = ThresholdRule(drop=-0.05).evaluate(series, name="测试")
    assert len(events) == 1
    assert events[0].event_type == "price_drop"
    assert events[0].value == pytest.approx(-0.10)


def test_threshold_rule_ignores_small_move():
    series = PriceSeries(code="x", records=make_records(closes=(100.0, 101.0)))
    assert ThresholdRule(drop=-0.05).evaluate(series) == []


def test_volume_spike_rule():
    recs = make_records(closes=[100.0] * 21)
    for r in recs[:-1]:
        r.volume = 1000.0
    recs[-1].volume = 5000.0            # 突然放大 5 倍
    events = VolumeSpikeRule(window=20, multiple=2.5).evaluate(
        PriceSeries(code="x", records=recs))
    assert len(events) == 1
    assert events[0].event_type == "volume_spike"


def test_zscore_rule_flags_anomaly():
    # 60 天微幅波动，最后一天暴跌 15%
    closes = [100.0]
    for i in range(60):
        closes.append(closes[-1] * (1 + (0.001 if i % 2 else -0.001)))
    closes.append(closes[-1] * 0.85)
    recs = make_records(closes=closes)
    events = ZScoreRule(window=60, z=3.0).evaluate(PriceSeries(code="x", records=recs))
    assert len(events) == 1
    assert events[0].event_type == "statistical_anomaly"
    assert abs(events[0].value) > 3.0


def test_rules_are_polymorphic():
    """同一份序列可以喂给不同规则，说明它们真的共享一个抽象。"""
    series = PriceSeries(code="x", records=make_records(closes=(100.0, 90.0)))
    for rule in (ThresholdRule(), VolumeSpikeRule(), ZScoreRule()):
        assert isinstance(rule.evaluate(series), list)


# ============================================================
# 6. InvestigationAgent：多步骤调查与事实/推测分离
# ============================================================
def test_agent_builds_report_with_separated_facts_and_hypotheses():
    news_tool = FakeTool("news_search", "news", [
        Evidence(kind="news", source="财联社", title="某新闻", published_at="2026-01-02"),
    ])
    notice_tool = FakeTool("notice_search", "notice", [
        Evidence(kind="notice", source="巨潮资讯", title="2026年半年度报告",
                 url="http://x", published_at="2026-01-02"),
    ])
    agent = InvestigationAgent([news_tool, notice_tool], llm=None, log=None)

    ev = MarketEvent(code="600519", name="贵州茅台", event_type="price_drop",
                     trade_date="2026-01-05", detected_at="2026-01-05 15:00:00",
                     severity="high", value=-0.08, threshold=-0.05, detail="跌 8%")
    report = agent.investigate(ev, days=7)

    # 多步骤：每个工具对应一个任务，且都执行了
    assert len(report.tasks) == 2
    assert all(t.status == "done" for t in report.tasks)
    assert news_tool.calls == 1 and notice_tool.calls == 1

    # 证据齐全且可追溯
    assert len(report.evidences) == 2
    assert any(e.kind == "notice" for e in report.evidences)

    # 事实与推测严格分离
    assert report.facts and report.hypotheses
    assert all(isinstance(x, str) for x in report.facts + report.hypotheses)

    # 结论不空、置信度在合理区间、markdown 结构完整
    assert report.conclusion
    assert 0.0 <= report.confidence <= 1.0
    md = report.to_markdown()
    assert "## 事实" in md and "## 推测" in md and "## 证据来源" in md


def test_agent_handles_failing_tool_gracefully():
    class BoomTool:
        name = "boom"
        kind = "news"

        def run(self, code, start, end, context=None):
            raise RuntimeError("工具坏了")

    agent = InvestigationAgent([BoomTool()], llm=None, log=None)
    ev = MarketEvent(code="600519", name="x", event_type="price_drop",
                     trade_date="2026-01-05", detected_at="now", severity="low",
                     detail="跌")
    report = agent.investigate(ev)
    assert report.tasks[0].status == "failed"
    assert report.conclusion          # 仍然产出结论，不崩
