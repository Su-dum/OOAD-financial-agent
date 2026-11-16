# -*- coding: utf-8 -*-
"""LLM 结论生成的测试（全部用假客户端，不联网、不花钱）。

重点验证**防幻觉机制**：
  模型引用了不存在的证据编号  -> 整段结论作废，退回模板
  有证据但一个都没引用        -> 同样作废
  调用失败 / 返回非 JSON      -> 降级，报告仍然可用
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.domain.events import MarketEvent
from backend.app.domain.investigation import (Evidence, InvestigationReport,
                                              InvestigationTask)
from backend.app.application.llm_conclusion import (LLMConclusionWriter,
                                                   TemplateConclusionWriter)


# ============================================================
# 测试替身
# ============================================================
class FakeLLM:
    """可配置返回内容的假大模型客户端。"""

    def __init__(self, payload=None, text=None, exc=None, with_json=True):
        self._payload = payload
        self._text = text
        self._exc = exc
        self._with_json = with_json
        self.calls = 0
        self.last_prompt = ""

    def complete(self, prompt, system=None):
        self.calls += 1
        self.last_prompt = prompt
        if self._exc:
            raise self._exc
        return self._text if self._text is not None else json.dumps(self._payload or {})

    def complete_json(self, prompt, system=None):
        self.calls += 1
        self.last_prompt = prompt
        if self._exc:
            raise self._exc
        if self._payload is None:
            raise ValueError("no payload")
        return dict(self._payload)


def make_report_with_evidence(n=3):
    """构造一份带若干证据的报告。"""
    ev = MarketEvent(code="600519", name="贵州茅台", event_type="price_drop",
                     trade_date="2026-07-20", detected_at="2026-07-20 15:00:00",
                     severity="high", value=-0.08, threshold=-0.05,
                     detail="单日下跌 8.00%")
    r = InvestigationReport(code="600519", name="贵州茅台", event=ev,
                            question="为什么下跌？")
    r.tasks = [InvestigationTask(question="查新闻", tool="news_search", status="done")]
    for i in range(n):
        r.add_evidence(Evidence(kind="news", source="财联社",
                                title=f"第 {i+1} 条相关新闻",
                                published_at="2026-07-20",
                                excerpt="片段"))
    r.add_fact("2026-07-20 单日下跌 8.00%")
    return r


# ============================================================
# 1. 正常路径
# ============================================================
def test_valid_response_is_applied():
    client = FakeLLM(payload={
        "conclusion": "当天下跌 8%，同期有 3 条相关新闻 [1][2]。",
        "confidence": 0.8,
        "cited_evidence_ids": [1, 2],
        "insufficient_evidence": False,
        "hypotheses": ["可能与行业整体回调有关"],
    })
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)

    assert "8%" in r.conclusion
    assert r.confidence > 0
    assert r.llm_meta["cited_evidence_ids"] == [1, 2]
    assert r.llm_meta["degraded"] is False
    # 模型给的推测只能进 hypotheses，不能进 facts
    assert any("[LLM]" in h for h in r.hypotheses)
    assert not any("[LLM]" in f for f in r.facts)


def test_prompt_numbers_the_evidence():
    """证据必须编号，否则没法做引用校验。"""
    client = FakeLLM(payload={"conclusion": "x [1]", "confidence": 0.5,
                              "cited_evidence_ids": [1]})
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert "[1]" in client.last_prompt and "[3]" in client.last_prompt
    assert "只能引用这些编号" in client.last_prompt


# ============================================================
# 2. 防幻觉：引用校验
# ============================================================
def test_hallucinated_citation_is_rejected():
    """模型引用了不存在的编号 [9] -> 结论作废，退回模板。"""
    client = FakeLLM(payload={
        "conclusion": "公司发布了重大重组公告 [9]，因此必然上涨。",
        "confidence": 0.99,
        "cited_evidence_ids": [9],
        "insufficient_evidence": False,
    })
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)

    assert "重大重组" not in r.conclusion          # 幻觉内容没进报告
    assert r.llm_meta.get("degraded") is True
    assert "未检索到" not in r.conclusion or "证据" in r.conclusion
    assert r.confidence <= 0.9


def test_partially_invalid_citation_rejected():
    """一半合法一半非法，仍然整体作废。"""
    client = FakeLLM(payload={"conclusion": "x [1][7]", "confidence": 0.9,
                              "cited_evidence_ids": [1, 7]})
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.llm_meta.get("degraded") is True


def test_no_citation_but_evidence_exists_is_rejected():
    """有证据却一个都不引用 = 无据结论。"""
    client = FakeLLM(payload={"conclusion": "股价下跌是因为市场情绪。",
                              "confidence": 0.9, "cited_evidence_ids": []})
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.llm_meta.get("degraded") is True


def test_insufficient_evidence_allows_empty_citations():
    """模型判定「证据不足」时，不引用编号是**正确行为**，不应被拦。"""
    client = FakeLLM(payload={
        "conclusion": "现有证据都是程序性公告与区间统计，无法确定当日上涨的原因。",
        "confidence": 0.0,
        "cited_evidence_ids": [],
        "insufficient_evidence": True,
    })
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)

    assert r.llm_meta.get("degraded") is not True      # 没有被判成幻觉
    assert "无法确定" in r.conclusion
    assert r.llm_meta["insufficient_evidence"] is True
    assert r.confidence <= 0.5


def test_empty_conclusion_rejected():
    client = FakeLLM(payload={"conclusion": "   ", "confidence": 0.9,
                              "cited_evidence_ids": [1]})
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.llm_meta.get("degraded") is True


# ============================================================
# 3. 降级：调用失败 / 非 JSON
# ============================================================
def test_llm_exception_falls_back_to_template():
    client = FakeLLM(exc=RuntimeError("网络炸了"))
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.conclusion                       # 仍然有结论
    assert r.llm_meta.get("degraded") is True
    assert r.confidence > 0


def test_non_json_text_falls_back():
    client = FakeLLM(text="我认为股价下跌是因为……")     # 不是 JSON
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.llm_meta.get("degraded") is True


def test_client_without_json_method_still_works():
    """只有 complete() 的客户端也能用：从文本里抠 JSON。"""
    payload = {"conclusion": "下跌与新闻 [1] 同时发生。", "confidence": 0.6,
               "cited_evidence_ids": [1], "insufficient_evidence": False}

    class TextOnlyLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, prompt, system=None):
            self.calls += 1
            return "以下是结果：\n" + json.dumps(payload)   # 外面带了解释文字

    client = TextOnlyLLM()
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.llm_meta.get("degraded") is not True
    assert r.llm_meta["cited_evidence_ids"] == [1]
    assert client.calls == 1


# ============================================================
# 4. 置信度上限
# ============================================================
def test_confidence_is_capped_by_evidence():
    """证据只有 1 条时，模型说 0.99 也不能被接受为 0.99。"""
    client = FakeLLM(payload={"conclusion": "x [1]", "confidence": 0.99,
                              "cited_evidence_ids": [1]})
    r = make_report_with_evidence(1)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.confidence < 0.99


def test_insufficient_evidence_caps_confidence():
    client = FakeLLM(payload={"conclusion": "现有证据不足以确证成因 [1]。",
                              "confidence": 0.95, "cited_evidence_ids": [1],
                              "insufficient_evidence": True})
    r = make_report_with_evidence(3)
    LLMConclusionWriter(client, log=None).write(r)
    assert r.confidence <= 0.5
    assert r.llm_meta["insufficient_evidence"] is True


# ============================================================
# 5. 模板策略独立可用
# ============================================================
def test_template_writer_without_evidence():
    r = InvestigationReport(code="600519", name="测试")
    TemplateConclusionWriter(log=None).write(r)
    assert "未检索到" in r.conclusion


def test_template_writer_with_evidence():
    r = make_report_with_evidence(2)
    r.add_evidence(Evidence(kind="notice", source="巨潮资讯", title="2026年半年度报告"))
    TemplateConclusionWriter(log=None).write(r)
    assert "公告" in r.conclusion and "新闻" in r.conclusion
    assert 0 < r.confidence <= 0.9
