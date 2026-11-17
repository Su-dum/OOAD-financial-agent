# -*- coding: utf-8 -*-
"""自然语言追问（C2）与条件修改（C1）的测试。

关键点：
  1. 没有 LLM 也必须能答（模板答案）；
  2. LLM 引用编号必须真实存在，编造就退回模板（与调查报告同一套规则）；
  3. 「改条件」的句子要解析成结构化动作，而不是当成闲聊回一句。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.application.analysis_service import FinancialAnalyzer
from backend.app.application.conversation_service import (ChatContext,
                                                          ConversationAgent,
                                                          detect_intent)
from backend.app.domain.events import MarketEvent
from backend.app.domain.models import PriceRecord, PriceSeries


# ============================================================
# 测试替身
# ============================================================
DATES = [f"2026-05-{d:02d}" for d in range(1, 21)]
CLOSES = [100.0 * (1.1 if i % 2 == 0 else 0.95) ** (i // 2 + 1) for i in range(20)]


def make_series(code="600519", dates=None, closes=None):
    dates = dates or DATES
    closes = closes or CLOSES
    return PriceSeries(code=code, source="fake", records=[
        PriceRecord(code=code, date=d, open=c, high=c, low=c, close=c, volume=1000.0)
        for d, c in zip(dates, closes)])


class StubCatalog:
    def get(self, code):
        return dict(name="贵州茅台", industry_l1_name="食品饮料")

    def name_of(self, code):
        return "贵州茅台"

    def industry_of(self, code):
        return "食品饮料"


class StubMarket:
    def __init__(self, catalog=None):
        self.catalog = catalog or StubCatalog()

    def get_series(self, code, start, end, adjust="qfq", source=None,
                   require_returns=True):
        return make_series(code)

    def meta(self, code):
        return self.catalog.get(code)

    def name_of(self, code):
        return self.catalog.name_of(code)

    def industry_of(self, code):
        return self.catalog.industry_of(code)


class StubNoticeRepo:
    def __init__(self, rows):
        self.rows = rows

    def find_by_stock(self, code, start=None, end=None, limit=200):
        return self.rows[:limit]


class StubNewsRepo:
    def __init__(self, rows):
        self.rows = rows

    def find_by_stock(self, code, start=None, end=None, limit=20, min_confidence=0.85):
        return self.rows[:limit]


class StubMonitor:
    def __init__(self, events):
        self.events = events

    def scan(self, code, start, end, **kw):
        return list(self.events)


class FakeLLM:
    def __init__(self, payload=None, exc=None):
        self.payload = payload or {}
        self.exc = exc
        self.calls = 0
        self.last = ""

    def complete_json(self, prompt, system=None):
        self.calls += 1
        self.last = prompt
        if self.exc:
            raise self.exc
        return dict(self.payload)


def build(llm=None, notices=None, news=None, events=None, cross=None):
    cat = StubCatalog()
    analyzer = FinancialAnalyzer(StubMarket(cat), log=None)
    return ConversationAgent(
        analyzer,
        monitor=StubMonitor(events or []),
        notices=StubNoticeRepo(notices or []),
        news=StubNewsRepo(news or []),
        cross=cross,
        catalog=cat, llm=llm, log=None)


CTX = ChatContext(code="600519", start=DATES[0], end=DATES[-1])


def notice_row(title, notice_type="半年度报告全文", published_at="2026-05-10"):
    return dict(code="600519", title=title, notice_type=notice_type,
                published_at=published_at, url="http://x", source="eastmoney")


# ============================================================
# 1. 意图识别
# ============================================================
@pytest.mark.parametrize("q,expected", [
    ("最近表现怎么样？", "performance"),
    ("为什么 8 月 15 日放量？", "reason"),
    ("有哪些财报公告？", "notice"),
    ("和 000001 比较一下", "compare"),
    ("有什么新闻？", "news"),
    ("最近有异动吗", "events"),
    ("介绍下这只票", "overview"),
])
def test_detect_intent(q, expected):
    assert detect_intent(q) == expected


# ============================================================
# 2. 条件修改 -> 结构化动作
# ============================================================
def test_parse_threshold_action():
    agent = build()
    actions = agent.parse_actions("把跌幅阈值改成 3%", "600519")
    assert actions[0]["type"] == "set_alert"
    assert actions[0]["params"] == {"drop": -0.03}


def test_parse_surge_threshold_action():
    actions = build().parse_actions("涨幅阈值调到 8%", "600519")
    assert actions[0]["params"] == {"surge": 0.08}


@pytest.mark.parametrize("q,days", [
    ("看近半年", 183),          # 半年 = 6 个月，不是 6 年
    ("看近 3 个月", 90),
    ("看近 2 年", 730),
    ("看近 2 周", 14),
])
def test_parse_range_action(q, days):
    actions = build().parse_actions(q, "600519")
    assert [a["type"] for a in actions] == ["set_range"]
    assert actions[0]["days"] == days


def test_parse_watchlist_action():
    actions = build().parse_actions("把 000001 加入自选", "600519")
    assert actions == [{"type": "add_watchlist", "code": "000001",
                        "describe": "把 000001 加入自选"}]


def test_parse_actions_ignores_plain_questions():
    assert build().parse_actions("最近表现怎么样？", "600519") == []


# ============================================================
# 3. 数据快照与模板答案
# ============================================================
def test_answer_without_llm_uses_template_and_citations():
    body = build(events=[MarketEvent(
        code="600519", name="贵州茅台", event_type="price_drop",
        trade_date=DATES[-1], detected_at="now", severity="high",
        value=-0.06, threshold=-0.05, detail="单日下跌 6%", rule_name="threshold")],
        notices=[notice_row("2026年半年度报告")]).answer("最近表现怎么样？", CTX)

    assert body["answer"]
    assert body["llm_meta"]["enabled"] is False
    ids = body["cited_evidence_ids"]
    assert ids and all(1 <= i <= len(body["evidences"]) for i in ids)
    kinds = [e["kind"] for e in body["evidences"]]
    assert kinds[0] == "indicator"
    assert "event" in kinds and "notice" in kinds


def test_answer_handles_no_data_gracefully():
    class EmptyMarket(StubMarket):
        def get_series(self, *a, **k):
            return None

    analyzer = FinancialAnalyzer(EmptyMarket(), log=None)
    agent = ConversationAgent(analyzer, monitor=StubMonitor([]),
                              notices=StubNoticeRepo([]), news=StubNewsRepo([]),
                              catalog=StubCatalog(), llm=None, log=None)
    body = agent.answer("最近怎么样？", CTX)
    assert "没有取到" in body["answer"]
    assert body["evidences"] == []


def test_reason_intent_says_insufficient_when_nothing_found():
    body = build().answer("为什么下跌？", CTX)
    assert "不能给出成因判断" in body["answer"] or "无法证明" in body["answer"]


# ============================================================
# 4. LLM 路径与引用校验
# ============================================================
def test_llm_answer_with_valid_citations_is_used():
    llm = FakeLLM({"answer": "区间上涨且无重大公告 [1]", "cited_evidence_ids": [1],
                   "insufficient_evidence": False, "confidence": 0.7})
    body = build(llm=llm).answer("最近表现怎么样？", CTX)
    assert body["answer"] == "区间上涨且无重大公告 [1]"
    assert body["cited_evidence_ids"] == [1]
    assert body["llm_meta"]["degraded"] is False
    assert "[1]" in llm.last                       # 证据编号化


def test_hallucinated_citation_falls_back_to_template():
    llm = FakeLLM({"answer": "编造的结论 [9]", "cited_evidence_ids": [9],
                   "insufficient_evidence": False})
    body = build(llm=llm).answer("为什么上涨？", CTX)
    assert body["llm_meta"]["degraded"] is True
    assert "编造的结论" not in body["answer"]
    assert body["answer"]                       # 仍给出模板答案


def test_llm_exception_falls_back_to_template():
    body = build(llm=FakeLLM(exc=RuntimeError("网关 502"))).answer("最近怎么样？", CTX)
    assert body["llm_meta"]["degraded"] is True
    assert "502" in body["llm_meta"]["reason"]
    assert body["answer"]


def test_llm_prompt_contains_history_and_actions():
    llm = FakeLLM({"answer": "已调整 [1]", "cited_evidence_ids": [1]})
    ctx = ChatContext(code="600519", start=DATES[0], end=DATES[-1],
                      history=[dict(role="user", content="先看三个月")])
    build(llm=llm).answer("把跌幅阈值改成 3%", ctx)
    assert "对话历史" in llm.last and "先看三个月" in llm.last
    assert "系统已执行的配置变更" in llm.last


def test_actions_are_reported_in_response():
    body = build().answer("把跌幅阈值改成 3%，看近半年", CTX)
    kinds = {a["type"] for a in body["actions"]}
    assert kinds == {"set_alert", "set_range"}
