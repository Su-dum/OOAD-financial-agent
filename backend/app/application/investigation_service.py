# -*- coding: utf-8 -*-
"""事件调查服务（应用层）。

对应评分项 **B3（事件后自动检索并分析成因）** 与 **D2（多步骤调查）**。

## D2 的两个动词，分别落在哪

    decompose into subtasks     -> 每一步记一条 `InvestigationTask`，
                                   `question` 写的是「要回答什么问题」，不是「调用哪个工具」
    dynamically determine       -> `InvestigationPlanner` 根据**已有证据**决定下一步 / 何时停

流程（不是固定三连跑）：

    while 未超预算:
        看当前证据 -> 规划器选下一步 -> 执行工具 -> 证据并入 -> 回到开头
    规划器说 stop / 步数用完 / 无可执行动作 -> 结束

所以同一批不同类型的异动会走出不同路径：
    个股新闻查到很多       -> 不扩窗，直接进结论
    个股新闻一条都没查到   -> 换关键词 + 放宽时间窗重试，再查行业指数确认是否行业联动
    公告只有标题           -> 下 PDF 正文补实质内容

## 证据收集与结论生成仍然分离

工具只产出 `Evidence`（事实），结论由结论策略（模板 / LLM + 引用校验）生成，
事实 `facts` 与推测 `hypotheses` 分栏输出，避免把「可能相关」说成「已经证实」。
"""
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

from ..core import indicators as ind
from ..domain.events import MarketEvent
from ..domain.investigation import (Evidence, InvestigationReport,
                                    InvestigationTask)
from ..domain.notices import classify_notice, clean_title
from .analysis_service import FinancialAnalyzer
from .investigation_planner import (Decision, HeuristicPlanner,
                                    InvestigationPlanner, LLMPlanner,
                                    PlannerState, label_of, question_of)


def _shift(date_str: str, days: int) -> str:
    """YYYY-MM-DD 平移若干天（负数往前）。"""
    try:
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str
    return (d + timedelta(days=days)).strftime("%Y-%m-%d")


def _day_of(ts) -> str:
    return str(ts or "")[:10]


def _in_range(ts, start: str, end: str) -> bool:
    d = _day_of(ts)
    return bool(d) and start <= d <= end


# ============================================================
# 协议
# ============================================================
class InvestigationTool(Protocol):
    """调查工具：给定标的与时间窗，产出证据。

    `actions` 声明它能服务哪些动作名——一个工具可服务多个动作
    （例如新闻工具既能按个股检索、也能扩窗换关键词检索）。
    """
    name: str
    kind: str          # news / notice / indicator / industry
    actions: tuple

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
    """从本地新闻库检索与该股票相关的新闻（已做实体链接）。

    支持两种用法（由规划器决定用哪种）：
        news_search  按个股检索
        news_widen   换关键词 + 放宽时间窗（个股一条都查不到时用这个）
    """

    name = "news_search"
    kind = "news"
    actions = ("news_search", "news_widen")

    def __init__(self, news_repo, limit: int = 8, log=print):
        self.news_repo = news_repo
        self.limit = limit
        self.log = log

    def run(self, code, start, end, context=None) -> list[Evidence]:
        if self.news_repo is None:
            return []
        ctx = context or {}
        keyword = str(ctx.get("keyword") or "").strip()
        widen = int(ctx.get("widen_days") or 0)
        lo = _shift(start, -widen) if widen > 0 else start
        try:
            if keyword:
                # 关键词检索范围更宽（行业/板块词），回来后再按时间窗过滤
                rows = self.news_repo.find_by_keyword(
                    keyword, limit=max(self.limit * 5, 40))
                rows = [r for r in rows if _in_range(r.get("published_at"), lo, end)]
            else:
                rows = self.news_repo.find_by_stock(code, start=lo, end=end,
                                                    limit=self.limit)
        except Exception as e:                                # noqa: BLE001
            if self.log:
                self.log(f"  [news] 检索失败 {type(e).__name__}")
            return []
        rows = rows[:self.limit]
        return [Evidence(kind=self.kind, source=r.get("source") or "新闻",
                         title=r.get("title") or "",
                         url=r.get("url"),
                         published_at=r.get("published_at"),
                         excerpt=(r.get("title") or "")[:120],
                         confidence=0.9) for r in rows]


class NoticeSearchTool:
    """检索公告作为证据。

    取数顺序：**本地公告库 -> 外部源**。
        - 本地库是 B2 采集时落下的同一批公告，点「调查」不该再打外部接口
        - 本地为空（比如新加的标的还没刷新过）才回落到公告 Provider
        - `notice_deep` 动作会显式要求下载 PDF 正文抽片段（较慢，仅在规划器选择时发生）
    """

    name = "notice_search"
    kind = "notice"
    actions = ("notice_search", "notice_deep")

    def __init__(self, notice_provider=None, repo=None, limit: int = 5,
                 deep: bool = False, log=print):
        self.provider = notice_provider
        self.repo = repo
        self.limit = limit
        self.deep = deep
        self.log = log

    def _from_local(self, code, start, end) -> list[dict]:
        if self.repo is None:
            return []
        try:
            return self.repo.find_by_stock(code, start=start, end=end,
                                           limit=self.limit) or []
        except Exception as e:                                # noqa: BLE001
            if self.log:
                self.log(f"  [notice] 本地公告读取失败: {type(e).__name__}")
            return []

    def _from_provider(self, code, start, end) -> list[dict]:
        if self.provider is None:
            return []
        try:
            return self.provider.list_notices(code, start, end, limit=self.limit) or []
        except Exception as e:                                # noqa: BLE001
            if self.log:
                self.log(f"  [notice] 外部公告检索失败: {type(e).__name__}")
            return []

    def run(self, code, start, end, context=None) -> list[Evidence]:
        ctx = context or {}
        explicit_deep = bool(ctx.get("deep"))

        # 取数顺序：平时「本地优先」（用户点调查不该再打外部接口）；
        # 但**要下正文**时必须先走 Provider —— 本地公告多来自东财，
        # 它的 url 是详情页而不是 PDF 直链，抽不出正文。巨潮给的才是权威 PDF。
        if explicit_deep and self.provider is not None:
            items = self._from_provider(code, start, end)
            from_local = False
            if not items:
                items = self._from_local(code, start, end)
                from_local = True
        else:
            items = self._from_local(code, start, end)
            from_local = bool(items)
            if not items:
                items = self._from_provider(code, start, end)
        items = items[:self.limit]

        # 下正文很慢（每份 PDF 几百 KB ~ 几 MB），显式深挖时也只取前几份
        max_deep = int(ctx.get("max_deep") or 2)
        deep_used = 0
        out = []
        for it in items:
            title = clean_title(it.get("title") or "", it.get("name") or "")
            excerpt = ""
            cat = classify_notice(it.get("notice_type") or "", title)
            if cat is not None:
                excerpt = f"公告类别：{cat.label}"
            # deep 有两种来源：工具默认（只在回落外部源时下正文）、
            # 规划器显式要求（本地库里的公告也下正文）
            want_pdf = ((explicit_deep or (self.deep and not from_local))
                        and deep_used < max_deep)
            kind = self.kind
            if want_pdf and it.get("url") and self.provider is not None:
                text = self.provider.fetch_text(it["url"], max_pages=5)
                if text:
                    deep_used += 1
                    excerpt = (" ".join(text.split())[:300] + " "
                               + (f"（{excerpt}）" if excerpt else "")).strip()
                    # 正文单独一类：否则和「检索公告」那一步的标题证据重复，
                    # 同一条公告会在证据列表里出现两次
                    kind = "notice_text"
            raw_source = (it.get("source") or "").strip()
            if from_local:
                source = {"eastmoney": "东财公告", "cninfo": "巨潮资讯"}.get(
                    raw_source, "本地公告库")
            else:
                source = "巨潮资讯" if raw_source == "cninfo" else "公告源"
            out.append(Evidence(
                kind=kind, source=source,
                title=(f"[{cat.label}] {title}" if cat is not None else title),
                url=it.get("url"),
                published_at=it.get("published_at"),
                excerpt=excerpt, confidence=1.0))
        return out


class IndicatorTool:
    """把区间内的价格与指标变化也作为证据（事实层）。"""

    name = "indicator_analysis"
    kind = "indicator"
    actions = ("indicator",)

    def __init__(self, analyzer: FinancialAnalyzer, log=print):
        self.analyzer = analyzer
        self.log = log

    def run(self, code, start, end, context=None) -> list[Evidence]:
        ind_set = self.analyzer.analyze(code, start, end)
        if ind_set is None:
            return []
        pct = lambda v: "—" if v is None else f"{v*100:+.2f}%"       # noqa: E731
        num = lambda v: "—" if v is None else f"{v:.2f}"             # noqa: E731
        text = (f"{ind_set.start} ~ {ind_set.end}（{ind_set.n_days} 个交易日）："
                f"累计收益 {pct(ind_set.total_return)}，"
                f"年化波动 {pct(ind_set.annualized_volatility)}，"
                f"最大回撤 {pct(ind_set.max_drawdown)}；"
                f"PE(TTM) {num(ind_set.pe_ttm)}，PB {num(ind_set.pb)}")
        return [Evidence(kind=self.kind, source=f"计算({ind_set.source})",
                         title="区间行情与指标", url=None,
                         published_at=ind_set.end, excerpt=text, confidence=1.0)]


class IndustryCompareTool:
    """查所属申万行业指数的同期表现——用来区分「行业性回调」与「个股特有事件」。

    这是动态调查里最重要的一次追加：公司层面查不到消息时，
    先确认行业是否同向异动，能大幅提高结论的可解释性。
    """

    name = "industry_compare"
    kind = "industry"
    actions = ("industry",)

    def __init__(self, provider, catalog=None, log=print):
        self.provider = provider
        self.catalog = catalog
        self.log = log

    def run(self, code, start, end, context=None) -> list[Evidence]:
        if self.provider is None or self.catalog is None:
            return []
        meta = self.catalog.get(code) or {}
        ind_code = (meta.get("industry_l1_code") or "").strip()
        ind_name = (meta.get("industry_l1_name") or "").strip() or ind_code
        if not ind_code:
            return []
        try:
            s = self.provider.fetch(ind_code, start, end, adjust="none")
        except Exception as e:                                # noqa: BLE001
            if self.log:
                self.log(f"  [industry] 行业指数取数失败: {type(e).__name__}")
            return []
        if s is None or len(s) < 2:
            return []
        ret = ind.total_return(s.closes)
        mdd = ind.max_drawdown(s.closes)[0]
        pct = lambda v: "—" if v is None else f"{v*100:+.2f}%"       # noqa: E731
        text = (f"{ind_name} 行业指数 {s.start} ~ {s.end}（{len(s)} 个交易日）："
                f"区间收益 {pct(ret)}，最大回撤 {pct(mdd)}。"
                f"用于判断个股异动是否为行业性同步。")
        return [Evidence(kind=self.kind, source="申万行业指数",
                         title=f"{ind_name} 行业指数同期表现", url=None,
                         published_at=s.end, excerpt=text, confidence=1.0)]


# ============================================================
# 编排器
# ============================================================
class InvestigationAgent:
    def __init__(self, tools: Sequence[InvestigationTool],
                 llm: Optional[LLMClient] = None,
                 conclusion_writer=None, log=print,
                 planner: Optional[InvestigationPlanner] = None,
                 catalog=None, allow_deep: bool = True,
                 max_steps: int = 5):
        """结论与规划都用策略模式：

        结论：conclusion_writer / LLMConclusionWriter(llm) / TemplateConclusionWriter
        规划：planner / LLMPlanner(llm) / HeuristicPlanner
              （有 llm 就用模型决定下一步；模型失败自动退回规则，调查不会挂）
        """
        from .llm_conclusion import LLMConclusionWriter, TemplateConclusionWriter

        self.tools = list(tools)
        self.llm = llm
        self.log = log
        self.catalog = catalog
        self.allow_deep = allow_deep
        self.max_steps = max(1, int(max_steps))
        if conclusion_writer is None:
            conclusion_writer = (LLMConclusionWriter(llm, log=log)
                                 if llm is not None
                                 else TemplateConclusionWriter(log=log))
        self.writer = conclusion_writer
        self.planner: InvestigationPlanner = (
            planner if planner is not None
            else (LLMPlanner(llm, log=log) if llm is not None
                  else HeuristicPlanner(log=log)))
        # 规则规划器始终留一份：规划器给出「重复/无效动作」时用它兜底
        self._heuristic = HeuristicPlanner(log=log)

    # ---------------- 动作菜单 ----------------
    @staticmethod
    def _actions_of(tool) -> tuple:
        acts = getattr(tool, "actions", None)
        if acts:
            return tuple(acts)
        name = getattr(tool, "name", "")
        return (name,) if name else ()

    def menu(self) -> list[str]:
        out: list[str] = []
        for tool in self.tools:
            for a in self._actions_of(tool):
                if a == "notice_deep" and not self.allow_deep:
                    continue
                if a and a not in out:
                    out.append(a)
        return out

    def _tool_for(self, action: str):
        for tool in self.tools:
            if action in self._actions_of(tool):
                return tool
        return None

    def _industry_name(self, code: str) -> str:
        if self.catalog is None:
            return ""
        meta = self.catalog.get(code) or {}
        return (meta.get("industry_l1_name") or "").strip()

    def _context_for(self, decision: Decision, event: MarketEvent) -> dict:
        ctx = event.to_dict()
        if decision.action == "news_widen":
            keyword = (str(decision.args.get("keyword") or "").strip()
                       or self._industry_name(event.code)
                       or event.name or event.code)
            ctx["keyword"] = keyword
            ctx["widen_days"] = int(decision.args.get("widen_days") or 30)
        elif decision.action == "notice_deep":
            ctx["deep"] = True
        return ctx

    # ---------------- 主流程 ----------------
    def investigate(self, event: MarketEvent, days: int = 7,
                    question: str = "",
                    max_steps: Optional[int] = None) -> InvestigationReport:
        """围绕一个事件做**动态多步**调查。days 表示往前看多少天。"""
        end = event.trade_date
        start = (datetime.strptime(event.trade_date, "%Y-%m-%d")
                 - timedelta(days=days)).strftime("%Y-%m-%d")

        report = InvestigationReport(
            code=event.code, name=event.name, event=event,
            question=question or f"{event.name or event.code} 在 {event.trade_date} "
                                 f"发生「{event.label}」，可能原因是什么？")
        report.planner = self.planner.name

        menu = self.menu()
        budget = max(1, int(max_steps or self.max_steps))
        tried: list[str] = []
        industry = self._industry_name(event.code)

        for step in range(budget):
            state = PlannerState(event=event, menu=menu, tried=list(tried),
                                 evidences=list(report.evidences), step=step,
                                 budget=budget)
            decision = self.planner.decide(state)

            # 规划器给出「已执行过」或「菜单外」的动作时，用规则兜底，避免空转
            if (decision.action != "stop"
                    and (decision.action not in menu
                         or decision.action in set(tried))):
                decision = self._heuristic.decide(state)
                if decision.action != "stop" and decision.action in set(tried):
                    decision = Decision("stop", "没有可继续执行的动作")

            if decision.action == "stop":
                report.stop_reason = decision.reason or "信息已足够，结束调查"
                break

            tool = self._tool_for(decision.action)
            if tool is None:
                report.stop_reason = f"没有工具能执行动作「{decision.action}」"
                break

            tried.append(decision.action)
            task = InvestigationTask(
                question=question_of(decision.action,
                                     name=event.name or event.code,
                                     industry=industry or "所属行业",
                                     start=start, end=end)
                          or f"{label_of(decision.action)}：{event.name or event.code}",
                tool=getattr(tool, "name", decision.action),
                action=decision.action,
                status="running", step=step + 1, reason=decision.reason)
            report.tasks.append(task)

            try:
                evs = tool.run(event.code, start, end,
                               context=self._context_for(decision, event))
                task.result_count = len(evs)
                task.status = "done"
                for ev in evs:
                    self._add_evidence(report, ev)
            except Exception as e:                            # noqa: BLE001
                task.status = "failed"
                task.note = f"{type(e).__name__}: {e}"
                if self.log:
                    self.log(f"  [agent] 第 {step + 1} 步 {decision.action} 失败: "
                             f"{type(e).__name__}")
        else:
            report.stop_reason = f"达到步数上限（{budget} 步）"

        # 事实层（有证据支持）
        self._build_facts(report, start, end)
        # 推测层（未证实，明确区分）
        self._build_hypotheses(report)
        # 结论
        self._conclude(report)
        return report

    # ---------------- 内部 ----------------
    @staticmethod
    def _add_evidence(report: InvestigationReport, ev: Evidence) -> bool:
        """按 (kind, title) 去重。

        动态多步的副作用：新闻"个股检索"和"扩窗检索"可能命中同一条，
        公告"检索"与"下正文"也是同一批。重复证据会稀释引用编号、把报告撑长。
        """
        key = (ev.kind, ev.title)
        for e in report.evidences:
            if (e.kind, e.title) == key:
                return False
        report.add_evidence(ev)
        return True

    def _build_facts(self, report: InvestigationReport, start: str, end: str) -> None:
        ev = report.event
        if ev is not None:
            detail = (ev.detail or "").strip()
            # detail 里已经有中文事件名（如「…发生『财报披露』」）就不要再拼一次前缀
            head = (detail if (not detail or ev.label in detail)
                    else f"{ev.label}：{detail}" if detail else ev.label)
            report.add_fact(f"{ev.trade_date} {head or ev.label}")
        news = report.evidence_by_kind("news")
        notices = report.evidence_by_kind("notice")
        inds = report.evidence_by_kind("indicator")
        industries = report.evidence_by_kind("industry")
        if inds:
            report.add_fact(inds[0].excerpt)
        if industries:
            report.add_fact(industries[0].excerpt)
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
        industries = report.evidence_by_kind("industry")
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
        if industries:
            report.add_hypothesis(
                "行业指数的同期表现可用于区分「行业性回调」与「个股特有事件」，"
                "但方向性仍需结合资金流与持仓数据验证")
        if ev is not None and ev.event_type == "volume_spike":
            report.add_hypothesis("成交量放大通常伴随信息冲击或资金调仓，"
                                  "需结合公告与行业指数共同判断")
        if not notices and not news:
            report.add_hypothesis("缺乏可核实的公开信息，暂不能给出成因判断")

    def _conclude(self, report: InvestigationReport) -> None:
        """结论生成交给策略：模板 / LLM。写作者自己负责降级。"""
        self.writer.write(report)
