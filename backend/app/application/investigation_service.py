# -*- coding: utf-8 -*-
"""事件调查服务（应用层）。

对应评分项 **B3（事件后自动检索并分析成因）** 与 **D2（多步骤调查）**。

结构：
    InvestigationAgent     编排器：拆任务 -> 依次调工具 -> 组装报告
      InvestigationTool    工具体协议（策略/命令）：新闻检索、公告检索、指标分析
      LLMClient            可选：接入大模型做归纳（不接也能出报告）

关键设计（对应提案 4.3 与 4.7 风险二）：
  **证据收集与结论生成分离**。工具只产出 Evidence（事实），
  结论由 agent 组装，且事实(facts)与推测(hypotheses)分栏输出，
  避免把「可能相关」说成「已经证实」。
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

from ..domain.events import MarketEvent
from ..domain.investigation import (Evidence, InvestigationReport,
                                    InvestigationTask)
from .analysis_service import FinancialAnalyzer


# ============================================================
# 协议
# ============================================================
class InvestigationTool(Protocol):
    """调查工具：给定标的与时间窗，产出证据。"""
    name: str
    kind: str          # news / notice / indicator

    def run(self, code: str, start: str, end: str,
            context: dict) -> list[Evidence]:
        ...


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str:
        ...


# ============================================================
# 工具实现
# ============================================================
class NewsSearchTool:
    """从本地新闻库检索与该股票相关的新闻（已做实体链接）。"""

    name = "news_search"
    kind = "news"

    def __init__(self, news_repo, limit: int = 8, log=print):
        self.news_repo = news_repo
        self.limit = limit
        self.log = log

    def run(self, code, start, end, context=None) -> list[Evidence]:
        if self.news_repo is None:
            return []
        try:
            rows = self.news_repo.find_by_stock(code, start=start, end=end,
                                                limit=self.limit)
        except Exception as e:
            if self.log:
                self.log(f"  [news] 检索失败 {type(e).__name__}")
            return []
        return [Evidence(kind=self.kind, source=r.get("source") or "新闻",
                         title=r.get("title") or "",
                         url=r.get("url"),
                         published_at=r.get("published_at"),
                         excerpt=(r.get("title") or "")[:120],
                         confidence=0.9) for r in rows]


class NoticeSearchTool:
    """从巨潮检索公告；deep=True 时下载 PDF 抽正文作为引用片段。"""

    name = "notice_search"
    kind = "notice"

    def __init__(self, notice_provider, limit: int = 5, deep: bool = False, log=print):
        self.provider = notice_provider
        self.limit = limit
        self.deep = deep
        self.log = log

    def run(self, code, start, end, context=None) -> list[Evidence]:
        if self.provider is None:
            return []
        items = self.provider.list_notices(code, start, end, limit=self.limit)
        out = []
        for it in items:
            excerpt = ""
            if self.deep and it.get("url"):
                text = self.provider.fetch_text(it["url"], max_pages=5)
                excerpt = " ".join(text.split())[:300] if text else ""
            out.append(Evidence(
                kind=self.kind, source="巨潮资讯",
                title=it.get("title") or "",
                url=it.get("url"),
                published_at=it.get("published_at"),
                excerpt=excerpt, confidence=1.0))
        return out


class IndicatorTool:
    """把区间内的价格与指标变化也作为证据（事实层）。"""

    name = "indicator_analysis"
    kind = "indicator"

    def __init__(self, analyzer: FinancialAnalyzer, log=print):
        self.analyzer = analyzer
        self.log = log

    def run(self, code, start, end, context=None) -> list[Evidence]:
        ind = self.analyzer.analyze(code, start, end)
        if ind is None:
            return []
        pct = lambda v: "—" if v is None else f"{v*100:+.2f}%"
        num = lambda v: "—" if v is None else f"{v:.2f}"
        text = (f"{ind.start} ~ {ind.end}（{ind.n_days} 个交易日）："
                f"累计收益 {pct(ind.total_return)}，年化波动 {pct(ind.annualized_volatility)}，"
                f"最大回撤 {pct(ind.max_drawdown)}；PE(TTM) {num(ind.pe_ttm)}，"
                f"PB {num(ind.pb)}")
        return [Evidence(kind=self.kind, source=f"计算({ind.source})",
                         title="区间行情与指标", url=None,
                         published_at=ind.end, excerpt=text, confidence=1.0)]


# ============================================================
# 编排器
# ============================================================
class InvestigationAgent:
    def __init__(self, tools: Sequence[InvestigationTool],
                 llm: Optional[LLMClient] = None, log=print):
        self.tools = list(tools)
        self.llm = llm
        self.log = log

    # ---------------- 主流程 ----------------
    def investigate(self, event: MarketEvent, days: int = 7,
                    question: str = "") -> InvestigationReport:
        """围绕一个事件做调查。days 表示往前看多少天。"""
        end = event.trade_date
        start = (datetime.strptime(event.trade_date, "%Y-%m-%d")
                 - timedelta(days=days)).strftime("%Y-%m-%d")

        report = InvestigationReport(
            code=event.code, name=event.name, event=event,
            question=question or f"{event.name or event.code} 在 {event.trade_date} "
                                 f"发生「{event.event_type}」，可能原因是什么？")

        # 1) 拆任务（D2：多步骤）
        for tool in self.tools:
            report.tasks.append(InvestigationTask(
                question=f"用 {tool.name} 收集 {start} ~ {end} 的相关信息",
                tool=tool.name))

        # 2) 逐任务执行
        for task, tool in zip(report.tasks, self.tools):
            task.status = "running"
            try:
                evs = tool.run(event.code, start, end, context=event.to_dict())
                task.result_count = len(evs)
                task.status = "done"
                for ev in evs:
                    report.add_evidence(ev)
            except Exception as e:
                task.status = "failed"
                task.note = f"{type(e).__name__}: {e}"
                if self.log:
                    self.log(f"  [agent] 任务 {tool.name} 失败: {type(e).__name__}")

        # 3) 事实层（有证据支持）
        self._build_facts(report, start, end)
        # 4) 推测层（未证实，明确区分）
        self._build_hypotheses(report)
        # 5) 结论
        self._conclude(report)
        return report

    # ---------------- 内部 ----------------
    def _build_facts(self, report: InvestigationReport, start: str, end: str) -> None:
        ev = report.event
        if ev is not None:
            report.add_fact(f"{ev.trade_date} 检测到 {ev.event_type}：{ev.detail}")
        news = report.evidence_by_kind("news")
        notices = report.evidence_by_kind("notice")
        inds = report.evidence_by_kind("indicator")
        if inds:
            report.add_fact(inds[0].excerpt)
        if notices:
            report.add_fact(f"{start} ~ {end} 期间公司共披露 {len(notices)} 条公告，"
                            f"最近一条为「{notices[0].title}」")
        if news:
            report.add_fact(f"{start} ~ {end} 期间检索到 {len(news)} 条相关新闻，"
                            f"最新一条为「{news[0].title}」")
        if not news and not notices:
            report.add_fact("在该时间窗内未检索到相关公告或新闻（信息可能滞后，"
                            "或该标的关注度较低）")

    def _build_hypotheses(self, report: InvestigationReport) -> None:
        """只给「可能性」，措辞刻意保守——不把推测写成结论。"""
        notices = report.evidence_by_kind("notice")
        news = report.evidence_by_kind("news")
        ev = report.event

        for n in notices[:3]:
            title = n.title
            if any(k in title for k in ("业绩", "季度报告", "年度报告", "半年度")):
                report.add_hypothesis(
                    f"可能受财报披露影响（公告：{title}），需要核对披露时点与股价反应是否吻合")
            elif any(k in title for k in ("澄清", "异常波动")):
                report.add_hypothesis(
                    f"公司已就异动发布说明（公告：{title}），可作为官方口径参考")
            elif any(k in title for k in ("回购", "增持", "减持", "股权")):
                report.add_hypothesis(
                    f"可能涉及股东或资本运作（公告：{title}）")
        if news:
            report.add_hypothesis(
                f"新闻侧有 {len(news)} 条相关报道，可能反映市场情绪或行业事件，"
                f"但新闻与股价的因果关系需要进一步验证")
        if ev is not None and ev.event_type == "volume_spike":
            report.add_hypothesis("成交量放大通常伴随信息冲击或资金调仓，"
                                  "需结合公告与行业指数共同判断")
        if not notices and not news:
            report.add_hypothesis("缺乏可核实的公开信息，暂不能给出成因判断")

    def _conclude(self, report: InvestigationReport) -> None:
        news_n = len(report.evidence_by_kind("news"))
        notice_n = len(report.evidence_by_kind("notice"))
        total = len(report.evidences)

        if self.llm is not None:
            prompt = self._build_prompt(report)
            try:
                report.conclusion = self.llm.complete(prompt).strip()
            except Exception as e:
                if self.log:
                    self.log(f"  [agent] LLM 调用失败: {type(e).__name__}")
                report.conclusion = self._fallback_conclusion(report, news_n, notice_n)
        else:
            report.conclusion = self._fallback_conclusion(report, news_n, notice_n)

        # 置信度：证据越多、越权威（公告 > 新闻）越高
        report.confidence = min(0.9, 0.15 * min(total, 3) + 0.15 * min(notice_n, 2)
                                + 0.1 * min(news_n, 3))

    @staticmethod
    def _fallback_conclusion(report: InvestigationReport,
                             news_n: int, notice_n: int) -> str:
        parts = []
        if notice_n:
            parts.append(f"公司在该期间披露了 {notice_n} 条公告")
        if news_n:
            parts.append(f"检索到 {news_n} 条相关新闻")
        if not parts:
            return ("未检索到可支撑成因判断的公告或新闻。"
                    "该异动可能是市场整体或行业层面的联动，建议扩大检索范围。")
        return (f"{'，'.join(parts)}。上述证据只能说明「期间发生了什么」，"
                f"尚不足以确证「是该事件导致价格变化」。"
                f"建议结合行业指数同步表现与更长窗口进一步验证。")

    def _build_prompt(self, report: InvestigationReport) -> str:
        facts = "\n".join(f"- {f}" for f in report.facts)
        cites = "\n".join(f"- {e.cite()}" for e in report.evidences[:15])
        return (
            "你是金融分析助手。请仅依据下面列出的事实与证据，"
            "判断该价格异动可能的成因，并明确区分「有证据支持的事实」与「推测」。\n"
            "如果证据不足以判断，必须直说，不要编造。\n\n"
            f"事件：{report.event.describe() if report.event else ''}\n\n"
            f"事实：\n{facts}\n\n证据来源：\n{cites}\n\n"
            "请用 3~5 句话给出结论，并标注置信度高低。")
