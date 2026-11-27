# -*- coding: utf-8 -*-
"""D2「动态多步调查」的测试（完全离线，用假工具/假 LLM）。

验收标准就三条（也是本项目对 D2 的定义）：

    1. 同一批不同类型的异动，调查**路径不同**（不是固定三连跑）
    2. 能看到「因为上一步证据不足，所以追加检索」的痕迹
    3. 步数不固定：信息够了就停，不够就多查；且有预算上限

另外验证兜底：LLM 给出非法/重复动作、或直接报错时，退回规则规划器，调查不挂。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.application.investigation_planner import (Decision,
                                                           HeuristicPlanner,
                                                           LLMPlanner,
                                                           PlannerState)
from backend.app.application.investigation_service import (
    InvestigationAgent, IndustryCompareTool, NewsSearchTool, NoticeSearchTool)
from backend.app.domain.events import MarketEvent
from backend.app.domain.investigation import Evidence


# ============================================================
# 夹具
# ============================================================
def ev(event_type="price_drop", code="600519", name="贵州茅台",
       trade_date="2026-11-25", severity="high"):
    return MarketEvent(code=code, name=name, event_type=event_type,
                       trade_date=trade_date, detected_at="2026-11-25 16:00:00",
                       severity=severity, value=-0.08, threshold=-0.05,
                       detail="单日下跌 8%")


def news(n=2):
    return [Evidence(kind="news", source="财联社", title=f"新闻{i}",
                     published_at="2026-11-24", excerpt="标题摘要") for i in range(n)]


def notices(n=2):
    return [Evidence(kind="notice", source="东财公告", title=f"[财报披露] 公告{i}",
                     url="http://x", published_at="2026-11-23") for i in range(n)]


def indicator():
    return [Evidence(kind="indicator", source="计算(baostock)", title="区间行情与指标",
                     published_at="2026-11-25", excerpt="累计收益 -8.00%")]


def industry():
    return [Evidence(kind="industry", source="申万行业指数", title="食品饮料 行业指数同期表现",
                     published_at="2026-11-25", excerpt="区间收益 -7.50%")]


class FakeTool:
    """按动作返回预设证据；记录每次调用收到的 context。"""

    def __init__(self, name, kind, actions, result=None, exc=None):
        self.name = name
        self.kind = kind
        self.actions = actions
        self.result = result if result is not None else []
        self.exc = exc
        self.calls = []

    def run(self, code, start, end, context=None):
        self.calls.append(dict(context or {}))
        if self.exc:
            raise self.exc
        return list(self.result)


def full_tools(news_n=2, notice_n=2):
    """完整菜单：indicator / notice_search / (notice_deep) / news_search / (news_widen) / industry"""
    return [
        FakeTool("indicator_analysis", "indicator", ("indicator",), indicator()),
        FakeTool("notice_search", "notice", ("notice_search", "notice_deep"),
                 notices(notice_n)),
        FakeTool("news_search", "news", ("news_search", "news_widen"), news(news_n)),
        FakeTool("industry_compare", "industry", ("industry",), industry()),
    ]


def agent(tools, **kw):
    kw.setdefault("llm", None)
    kw.setdefault("log", None)
    return InvestigationAgent(tools, **kw)


def actions_of(report):
    """按**动作**（而不是工具名）看路径——一个工具可服务多个动作。"""
    return [t.action for t in report.tasks]


def state(evidences, tried=(), menu=None, step=0, budget=5):
    return PlannerState(event=ev(), menu=menu or (
        "indicator", "notice_search", "news_search", "news_widen",
        "industry", "notice_deep"),
        tried=list(tried), evidences=list(evidences), step=step, budget=budget)


# ============================================================
# 1. 规则规划器：缺什么补什么（决策层单测）
# ============================================================
def test_heuristic_starts_with_cheapest_fact():
    d = HeuristicPlanner(log=None).decide(state([]))
    assert d.action == "indicator"
    assert d.reason          # 必须给出理由


def test_heuristic_adds_notice_then_news():
    p = HeuristicPlanner(log=None)
    assert p.decide(state(indicator(), tried=["indicator"])).action == "notice_search"
    assert p.decide(state(indicator() + notices(), tried=["indicator", "notice_search"])
                    ).action == "news_search"


def test_heuristic_switches_strategy_when_news_empty():
    """个股新闻一条都没有 -> 换关键词扩窗（这是"动态"最直观的一步）。"""
    evs = indicator() + notices()
    d = HeuristicPlanner(log=None).decide(
        state(evs, tried=["indicator", "notice_search", "news_search"]))
    assert d.action == "news_widen"
    assert "没查到新闻" in d.reason
    assert d.args.get("widen_days") == 30


def test_heuristic_skips_widen_when_news_found():
    evs = indicator() + notices() + news(3)
    d = HeuristicPlanner(log=None).decide(
        state(evs, tried=["indicator", "notice_search", "news_search"]))
    assert d.action != "news_widen"


def test_heuristic_adds_industry_when_company_info_thin():
    evs = indicator() + news(2)     # 没有公告 -> 公司层面证据不足
    d = HeuristicPlanner(log=None).decide(
        state(evs, tried=["indicator", "notice_search", "news_search"]))
    assert d.action == "industry"


def test_heuristic_downloads_pdf_when_only_titles():
    evs = indicator() + notices(2) + news(2)
    d = HeuristicPlanner(log=None).decide(
        state(evs, tried=["indicator", "notice_search", "news_search"]))
    assert d.action == "notice_deep"


def test_heuristic_stops_when_everything_covered():
    evs = indicator() + notices(2) + news(2) + industry()
    d = HeuristicPlanner(log=None).decide(
        state(evs, tried=["indicator", "notice_search", "news_search",
                          "notice_deep", "industry"]))
    assert d.action == "stop"
    assert d.reason


def test_heuristic_falls_back_to_unknown_actions():
    """自定义工具（动作名不在优先级表里）也要被调用一次。"""
    d = HeuristicPlanner(log=None).decide(state([], menu=("boom",)))
    assert d.action == "boom"


# ============================================================
# 2. LLM 规划器：模型决定，但任何异常都退回规则
# ============================================================
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


def test_llm_planner_uses_model_choice():
    p = LLMPlanner(FakeLLM({"action": "news_widen", "reason": "个股没新闻，扩窗试试"}),
                   log=None)
    d = p.decide(state(indicator(), tried=["indicator"]))
    assert d.action == "news_widen"
    assert "扩窗" in d.reason


def test_llm_planner_honours_stop():
    p = LLMPlanner(FakeLLM({"action": "stop", "reason": "证据够了"}), log=None)
    d = p.decide(state(indicator() + notices() + news()))
    assert d.action == "stop"
    assert "够了" in d.reason


def test_llm_planner_rejects_action_outside_menu():
    p = LLMPlanner(FakeLLM({"action": "hack_the_planet"}), log=None)
    d = p.decide(state([]))
    assert d.action == "indicator"            # 退回规则
    assert "规则兜底" in d.reason


def test_llm_planner_rejects_repeated_action():
    p = LLMPlanner(FakeLLM({"action": "indicator"}), log=None)
    d = p.decide(state(indicator(), tried=["indicator"]))
    assert d.action != "indicator"
    assert "规则兜底" in d.reason


def test_llm_planner_falls_back_on_exception():
    p = LLMPlanner(FakeLLM(exc=RuntimeError("网关 503")), log=None)
    d = p.decide(state([]))
    assert d.action == "indicator"
    assert "规则兜底" in d.reason


def test_llm_prompt_lists_menu_and_progress():
    llm = FakeLLM({"action": "indicator"})
    p = LLMPlanner(llm, log=None)
    p.decide(state(indicator(), tried=["notice_search"], step=1, budget=5))
    assert "可选动作" in llm.last
    assert "第 2 / 5 步" in llm.last
    assert "notice_search" in llm.last


# ============================================================
# 3. Agent：路径随证据变化（D2 的核心验收）
# ============================================================
def test_path_differs_when_news_is_empty():
    """有新闻 vs 没新闻 -> 走出的路径必须不同（不是固定三连跑）。"""
    rich = agent(full_tools(news_n=3)).investigate(ev(), days=7, max_steps=5)
    poor = agent(full_tools(news_n=0)).investigate(ev(), days=7, max_steps=5)
    assert actions_of(rich) != actions_of(poor)
    # 没新闻那条必须出现「扩窗」或「行业联动」这类追加步骤
    assert "news_search" in actions_of(poor)
    assert ("news_widen" in actions_of(poor)) or ("industry" in actions_of(poor))


def test_empty_news_triggers_extra_lookup():
    report = agent(full_tools(news_n=0)).investigate(ev(), days=7, max_steps=6)
    names = actions_of(report)
    assert names[:3] == ["indicator", "notice_search", "news_search"]
    assert "news_widen" in names          # ← 因为上一步 0 条，才追加
    widen_task = [t for t in report.tasks if t.action == "news_widen"][0]
    assert "没查到新闻" in widen_task.reason


def test_steps_are_numbered_and_reasoned():
    report = agent(full_tools()).investigate(ev(), days=7)
    assert report.tasks
    assert [t.step for t in report.tasks] == list(range(1, len(report.tasks) + 1))
    assert all(t.reason for t in report.tasks)


def test_question_is_problem_not_tool_name():
    """子任务问的是「要回答什么问题」，不是「用哪个工具收集」。"""
    report = agent(full_tools()).investigate(ev(), days=7)
    for t in report.tasks:
        assert not t.question.startswith("用 ")
        assert "收集" not in t.question
    # 行业联动那一步必须提到行业名
    industry_tasks = [t for t in report.tasks if t.action == "industry"]
    if industry_tasks:
        assert "行业" in industry_tasks[0].question


def test_budget_is_respected():
    report = agent(full_tools(), max_steps=3).investigate(ev(), days=7)
    assert len(report.tasks) <= 3
    assert "上限" in report.stop_reason


def test_stop_reason_recorded():
    report = agent(full_tools(news_n=3)).investigate(ev(), days=7, max_steps=8)
    assert report.stop_reason          # 要么"已覆盖"要么"上限"
    assert report.planner == "heuristic"


def test_llm_planner_drives_the_agent():
    """模型选什么就跑什么，且报告标注 planner=llm。"""
    plans = [{"action": "indicator", "reason": "先看价格事实"},
             {"action": "industry", "reason": "怀疑板块联动"},
             {"action": "stop", "reason": "够了"}]

    class SeqLLM:
        def __init__(self):
            self.i = 0

        def complete_json(self, prompt, system=None):
            p = plans[min(self.i, len(plans) - 1)]
            self.i += 1
            return dict(p)

    report = InvestigationAgent(full_tools(), llm=SeqLLM(), log=None).investigate(
        ev(), days=7, max_steps=5)
    assert report.planner == "llm"
    assert actions_of(report) == ["indicator", "industry"]
    assert report.stop_reason
    assert "先看价格事实" in report.tasks[0].reason


def test_allow_deep_false_removes_pdf_step():
    report = agent(full_tools(), allow_deep=False).investigate(ev(), days=7,
                                                              max_steps=6)
    assert "notice_deep" not in actions_of(report)


def test_allow_deep_true_can_download_pdf():
    report = agent(full_tools()).investigate(ev(), days=7, max_steps=6)
    assert "notice_deep" in actions_of(report)


def test_failing_step_is_recorded_and_investigation_continues():
    tools = full_tools()
    tools[1].exc = RuntimeError("公告库锁住了")
    report = agent(tools).investigate(ev(), days=7)
    failed = [t for t in report.tasks if t.status == "failed"]
    assert failed and "公告库锁住了" in failed[0].note
    assert report.conclusion          # 不影响后续与结论
    assert len(report.tasks) > 1


def test_report_serialises_plan_metadata():
    report = agent(full_tools()).investigate(ev(), days=7)
    d = report.to_dict()
    assert d["planner"] == "heuristic"
    assert d["stop_reason"]
    assert all("step" in t and "reason" in t for t in d["tasks"])
    md = report.to_markdown()
    assert "为什么：" in md and "结束原因" in md


# ============================================================
# 4. 真实工具的参数传递（离线、不联网）
# ============================================================
class StubNewsRepo:
    def __init__(self, by_stock=None, by_keyword=None):
        self.by_stock = by_stock or []
        self.by_keyword = by_keyword or []
        self.calls = []

    def find_by_stock(self, code, start=None, end=None, limit=20, **kw):
        self.calls.append(("stock", code, start, end))
        return list(self.by_stock)

    def find_by_keyword(self, keyword, limit=20):
        self.calls.append(("keyword", keyword))
        return list(self.by_keyword)


def test_news_tool_widen_uses_keyword_and_window():
    repo = StubNewsRepo(
        by_stock=[],
        by_keyword=[dict(source="cls", title="板块大跌", url=None,
                         published_at="2026-11-20 10:00:00")])
    tool = NewsSearchTool(repo, log=None)
    got = tool.run("600519", "2026-11-18", "2026-11-25",
                   context=dict(keyword="食品饮料", widen_days=30))
    assert len(got) == 1
    assert repo.calls[-1] == ("keyword", "食品饮料")


def test_news_tool_normal_search_uses_stock():
    repo = StubNewsRepo(by_stock=[dict(source="cls", title="个股新闻", url=None,
                                       published_at="2026-11-24 10:00:00")])
    tool = NewsSearchTool(repo, log=None)
    got = tool.run("600519", "2026-11-18", "2026-11-25", context={})
    assert len(got) == 1
    assert repo.calls[-1][0] == "stock"


class StubNoticeRepo:
    def __init__(self, rows):
        self.rows = rows

    def find_by_stock(self, code, start=None, end=None, limit=200):
        return list(self.rows)


class StubNoticeProvider:
    """记录被要求下载正文的 URL。"""

    def __init__(self, text="正文内容" * 20):
        self.text = text
        self.fetched = []

    def list_notices(self, code, start, end, limit=30):
        return []

    def fetch_text(self, url, max_pages=None):
        self.fetched.append(url)
        return self.text


def test_notice_tool_deep_only_when_asked():
    provider = StubNoticeProvider()
    repo = StubNoticeRepo([dict(code="600519", title="2026年三季度报告",
                                notice_type="", published_at="2026-11-20",
                                url="http://a.pdf", source="eastmoney", name="600519")])
    tool = NoticeSearchTool(provider, repo=repo, deep=False, log=None)

    plain = tool.run("600519", "2026-11-18", "2026-11-25", context={})
    assert provider.fetched == []                       # 没被要求就不下正文

    deep = tool.run("600519", "2026-11-18", "2026-11-25", context=dict(deep=True))
    assert provider.fetched == ["http://a.pdf"]
    assert "正文内容" in deep[0].excerpt


def test_notice_tool_deep_caps_pdf_count():
    provider = StubNoticeProvider()
    rows = [dict(code="600519", title=f"公告{i}", notice_type="",
                 published_at="2026-11-20", url=f"http://{i}.pdf",
                 source="eastmoney", name="600519") for i in range(5)]
    tool = NoticeSearchTool(provider, repo=StubNoticeRepo(rows), limit=5, log=None)
    tool.run("600519", "2026-11-18", "2026-11-25",
             context=dict(deep=True, max_deep=2))
    assert len(provider.fetched) == 2                    # 只下前 2 份，控时长


def test_industry_tool_needs_catalog_and_provider():
    class Cat:
        def get(self, code):
            return dict(industry_l1_code="801120", industry_l1_name="食品饮料")

    class Series:
        start, end, source = "2026-11-18", "2026-11-25", "industry_sw"
        closes = [100.0, 98.0, 95.0, 96.0]

        def __len__(self):
            return len(self.closes)

    class Provider:
        def fetch(self, code, start, end, adjust="none"):
            assert code == "801120"
            return Series()

    tool = IndustryCompareTool(Provider(), catalog=Cat(), log=None)
    got = tool.run("600519", "2026-11-18", "2026-11-25", context={})
    assert len(got) == 1
    assert got[0].kind == "industry"
    assert "食品饮料" in got[0].title


def test_industry_tool_gracesfully_returns_empty_without_catalog():
    tool = IndustryCompareTool(None, catalog=None, log=None)
    assert tool.run("600519", "2026-11-18", "2026-11-25", context={}) == []

# ============================================================
# 5. 证据去重（动态多步的副作用：同一条会被两个动作各查一次）
# ============================================================
class RepeatTool:
    """模拟「两个动作命中同一批证据」：每次都返回同样的 3 条公告。"""
    name = "notice_search"
    kind = "notice"
    actions = ("notice_search", "notice_deep")

    def __init__(self):
        self._same = [Evidence(kind="notice", source="东财公告",
                               title=f"[财报披露] 同一份公告{i}",
                               url="http://x", published_at="2026-11-23")
                      for i in range(3)]

    def run(self, code, start, end, context=None):
        return list(self._same)


def test_duplicate_evidence_is_deduped():
    report = InvestigationAgent([RepeatTool()], llm=None, log=None,
                                allow_deep=True).investigate(ev(), days=7)
    # 两个动作各返回 3 条同样的公告 -> 去重后仍是 3 条
    assert len(report.evidences) == 3
    assert [t.action for t in report.tasks] == ["notice_search", "notice_deep"]
    assert all(t.result_count == 3 for t in report.tasks)


def test_notice_text_is_a_separate_kind():
    """下正文的证据用 notice_text，否则会和标题证据同 (kind,title) 被去重掉。"""
    from backend.app.domain.investigation import Evidence as Ev

    class TitleThenBody:
        name = "notice_search"
        kind = "notice"
        actions = ("notice_search", "notice_deep")

        def run(self, code, start, end, context=None):
            deep = bool((context or {}).get("deep"))
            if deep:
                return [Ev(kind="notice_text", source="东财公告",
                           title="[财报披露] 三季报", url="http://x",
                           published_at="2026-11-23", excerpt="正文：净利润 +3.78%")]
            return [Ev(kind="notice", source="东财公告", title="[财报披露] 三季报",
                       url="http://x", published_at="2026-11-23",
                       excerpt="公告类别：财报披露")]

    report = InvestigationAgent([TitleThenBody()], llm=None, log=None,
                                allow_deep=True).investigate(ev(), days=7)
    kinds = [e.kind for e in report.evidences]
    assert kinds == ["notice", "notice_text"]
    assert any("净利润" in e.excerpt for e in report.evidences)
