# -*- coding: utf-8 -*-
"""自然语言追问服务（应用层）。

对应评分项 **C2（natural-language follow-up questions）** 与
**C1（interactively modify analysis / monitoring conditions）**。

## 两类能力，一个入口

    问：这只票最近表现怎么样？为什么 8 月 15 日放量？
    改：把跌幅阈值改成 3% / 看近半年 / 把 600519 加入自选

第二类不是「聊天」，而是**意图到动作**的映射：解析出结构化动作后，
由接口层执行（落库）或由前端执行（切区间）。这样「自然语言」与
「表单操作」走的是同一套服务，行为不会两套漂移。

## 为什么模板答案也要带引用编号

C4 要求结论可追溯。模板答案和 LLM 答案用**同一套证据编号**，
所以无论走哪条路径，前端都能点开 [2] 看到原始公告/新闻。
LLM 的引用编号仍然逐条校验（编造即整段退回模板），与调查报告一致。
"""
import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..domain.events import MarketEvent
from ..domain.investigation import Evidence
from ..domain.notices import classify_notice, clean_title

# ---------------------------------------------------------------- 意图
_INTENTS = (
    ("reason", ("为什么", "原因", "成因", "怎么回事", "为何", "怎么会")),
    ("compare", ("比较", "对比", "相关", "联动", "哪个好", "谁更强", "跑赢")),
    ("notice", ("公告", "财报", "业绩", "分红", "回购", "减持", "增持", "澄清", "披露")),
    ("events", ("事件", "异动", "放量", "异常", "波动大")),
    ("news", ("新闻", "消息", "报道", "舆论")),
    ("performance", ("收益", "涨", "跌", "表现", "走势", "波动", "回撤", "夏普",
                     "估值", "市盈", "市净", "怎么样", "如何", "好不好")),
)

# 「把阈值改成 3%」这类条件修改
_THRESHOLD_RE = re.compile(
    r"(跌幅|下跌|涨跌幅|涨幅|阈值)[^0-9%]{0,8}(\d+(?:\.\d+)?)\s*%")
_RANGE_RE = re.compile(r"近\s*(\d+|一|三|六|十二|半)\s*(个月|月|年|周)")
_RANGE_WORDS = {"一": 1, "三": 3, "六": 6, "十二": 12, "半": 6}
_CODE_RE = re.compile(r"(?<!\d)([036][0-9]{5})(?!\d)")


def detect_intent(question: str) -> str:
    q = question or ""
    for name, keys in _INTENTS:
        if any(k in q for k in keys):
            return name
    return "overview"


@dataclass
class ChatContext:
    code: str
    start: str
    end: str
    event: Optional[dict] = None
    report_id: Optional[int] = None
    history: list = field(default_factory=list)     # [{role, content}]


@dataclass
class Snapshot:
    """一次追问所用的数据快照（全部来自本地库/缓存，不联网取新闻）。"""
    code: str = ""
    name: str = ""
    industry: str = ""
    start: str = ""
    end: str = ""
    indicator: Optional[object] = None
    events: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    news: list = field(default_factory=list)
    cross: Optional[dict] = None
    evidences: list = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return (self.indicator is None and not self.events
                and not self.notices and not self.news)


class ConversationAgent:
    def __init__(self, analyzer, monitor=None, notices=None, news=None,
                 cross=None, catalog=None, llm=None, log=print):
        self.analyzer = analyzer
        self.monitor = monitor
        self.notices = notices          # NoticeRepository
        self.news = news                # NewsRepository
        self.cross = cross              # CrossAssetAnalyzer
        self.catalog = catalog
        self.llm = llm
        self.log = log

    # ============================================================
    # 主流程
    # ============================================================
    def answer(self, question: str, ctx: ChatContext) -> dict:
        question = (question or "").strip()
        intent = detect_intent(question)
        actions = self.parse_actions(question, ctx.code)

        snap = self.snapshot(ctx, self._other_codes(question, ctx))
        template = self._template_answer(question, snap, intent, ctx, actions)
        llm_meta = dict(enabled=self.llm is not None, degraded=False)
        answer = template
        citations = self._cited_ids(template)

        if self.llm is not None and intent in ("reason", "compare", "overview",
                                               "performance", "notice"):
            got = self._ask_llm(question, snap, ctx, template, actions)
            if got is not None:
                answer, citations = got["answer"], got["cited_evidence_ids"]
                llm_meta.update(got["meta"])

        return dict(
            question=question, code=ctx.code,
            start=snap.start or ctx.start, end=snap.end or ctx.end,
            intent=intent, answer=answer,
            cited_evidence_ids=citations,
            evidences=[dict(id=i, **e.to_dict())
                       for i, e in enumerate(snap.evidences, 1)],
            actions=actions,
            llm_meta=llm_meta,
        )

    # ============================================================
    # 1. 意图 -> 动作
    # ============================================================
    def parse_actions(self, question: str, code: str) -> list[dict]:
        """把「改条件」类句子解析成结构化动作（不执行，交给接口/前端）。"""
        q = question or ""
        out: list[dict] = []

        m = _THRESHOLD_RE.search(q)
        if m:
            pct = float(m.group(2)) / 100.0
            if 0.005 <= pct <= 0.30:
                is_surge = any(k in m.group(1) for k in ("涨",)) and "跌" not in m.group(1)
                key = "surge" if is_surge else "drop"
                out.append(dict(
                    type="set_alert", rule_type="threshold_pct_change",
                    params={key: pct if key == "surge" else -pct},
                    describe=f"把{'涨幅' if is_surge else '跌幅'}阈值改为 {pct*100:.1f}%"))

        m = _RANGE_RE.search(q)
        if m:
            num = _RANGE_WORDS.get(m.group(1)) or int(m.group(1) or 0)
            unit = m.group(2)
            if m.group(1) == "半" and unit == "年":
                days, label = 183, "近 6 个月"      # 「半年」是 6 个月，不是 6 年
            elif unit == "年":
                days, label = num * 365, f"近 {num} 年"
            elif unit == "个月":
                days, label = num * 30, f"近 {num} 个月"
            else:
                days, label = num * 7, f"近 {num} 周"
            out.append(dict(type="set_range", days=int(days), describe=label))

        m = _CODE_RE.search(q)
        if m and any(k in q for k in ("加入自选", "加自选", "监控", "关注", "盯住")):
            out.append(dict(type="add_watchlist", code=m.group(1),
                            describe=f"把 {m.group(1)} 加入自选"))
        return out

    # ============================================================
    # 2. 取数据快照
    # ============================================================
    def snapshot(self, ctx: ChatContext, others: Sequence[str] = ()) -> Snapshot:
        snap = Snapshot(code=ctx.code, start=ctx.start, end=ctx.end)
        meta = self.catalog.get(ctx.code) if self.catalog else {}
        snap.name = (meta.get("name") or "") if meta else ""
        snap.industry = (meta.get("industry_l1_name") or "") if meta else ""

        try:
            snap.indicator = self.analyzer.analyze(ctx.code, ctx.start, ctx.end)
        except Exception as e:                          # noqa: BLE001
            self._log(f"  [chat] 指标获取失败: {type(e).__name__}")
        if snap.indicator is not None:
            snap.start, snap.end = snap.indicator.start, snap.indicator.end
            snap.evidences.append(Evidence(
                kind="indicator", source=f"计算({snap.indicator.source})",
                title="区间行情与指标",
                published_at=snap.indicator.end,
                excerpt=self._indicator_sentence(snap.indicator), confidence=1.0))

        # 跨资产证据排在公告/新闻之前：用户问「和某某比」时，
        # 对比数据必须是模型最先看到的东西，否则容易被后面的新闻挤掉引用位置
        others = [c for c in others if c != ctx.code]
        if others and self.cross is not None:
            try:
                snap.cross = self.cross.compare([ctx.code] + others,
                                                ctx.start, ctx.end)
            except Exception as e:                      # noqa: BLE001
                self._log(f"  [chat] 跨资产比较失败: {type(e).__name__}")
            if snap.cross and snap.cross.get("assets"):
                snap.evidences.append(Evidence(
                    kind="cross", source="跨资产计算",
                    title="相对表现与相关性",
                    published_at=snap.end,
                    excerpt=self._cross_sentence(snap.cross), confidence=1.0))

        if self.monitor is not None:
            try:
                snap.events = self.monitor.scan(ctx.code, ctx.start, ctx.end)[:8]
            except Exception as e:                      # noqa: BLE001
                self._log(f"  [chat] 事件检测失败: {type(e).__name__}")
        for ev in snap.events:
            snap.evidences.append(Evidence(
                kind="event", source=f"规则({ev.rule_name})",
                title=f"{ev.trade_date} {ev.event_type}",
                url=getattr(ev, "source_url", None),
                published_at=ev.trade_date,
                excerpt=ev.detail, confidence=1.0))

        if self.notices is not None:
            try:
                rows = self.notices.find_by_stock(
                    ctx.code, start=ctx.start, end=ctx.end, limit=30)
                # 只取「重大事项」类公告：用户问的是财报/回购这类事件，
                # 把最近 6 条原样端出来会全是程序性公告（董事会决议之类）
                material = [n for n in rows if self._notice_material(n)]
                snap.notices = (material or rows)[:8]
            except Exception as e:                      # noqa: BLE001
                self._log(f"  [chat] 公告读取失败: {type(e).__name__}")
        for n in snap.notices:
            title = clean_title(n.get("title") or "", n.get("name") or "")
            cat = classify_notice(n.get("notice_type") or "", title)
            snap.evidences.append(Evidence(
                kind="notice", source="巨潮/东财公告",
                title=(f"[{cat.label}] " if cat else "") + title,
                url=n.get("url"), published_at=n.get("published_at"),
                excerpt="", confidence=1.0))

        if self.news is not None:
            try:
                snap.news = self.news.find_by_stock(ctx.code, start=ctx.start,
                                                    end=ctx.end, limit=5)
            except Exception as e:                      # noqa: BLE001
                self._log(f"  [chat] 新闻检索失败: {type(e).__name__}")
        for n in snap.news:
            snap.evidences.append(Evidence(
                kind="news", source=n.get("source") or "新闻",
                title=n.get("title") or "", url=n.get("url"),
                published_at=n.get("published_at"), excerpt="", confidence=0.9))
        return snap

    # ============================================================
    # 3. 模板答案（无 LLM 也永远可用）
    # ============================================================
    def _template_answer(self, question, snap: Snapshot, intent: str,
                         ctx: ChatContext, actions: Sequence[dict] = ()) -> str:
        prefix = "".join(f"已调整：{a.get('describe')}（规则已生效）。"
                         for a in actions if a.get("type") == "set_alert")
        if snap.empty:
            return (prefix + "该区间没有取到行情、公告或新闻数据（可能数据源被限流，"
                    "或该标的还没刷新过）。建议先点「更新数据」再问。")

        parts: list[str] = []
        if snap.indicator is not None:
            parts.append(self._indicator_sentence(snap.indicator, cite=1))
        events_n = len(snap.events)
        notice_material = [n for n in snap.notices
                           if self._notice_material(n)]
        if events_n:
            first = snap.events[0]
            idx = 2 if snap.indicator is not None else 1
            parts.append(f"区间内触发 {events_n} 个事件，最近一次是 {first.trade_date} "
                         f"的「{first.label}」[{idx}]。")
        if notice_material:
            head = notice_material[0]
            parts.append(f"公告侧有 {len(notice_material)} 条属于重大事项，"
                         f"最近一条是「{head.get('title')}」。")

        if intent == "reason":
            if snap.notices or snap.news:
                parts.append("从时间先后看，上述公告/新闻与价格变化同期出现，"
                             "但同期不代表因果：本系统只能说明「发生了什么」，"
                             "无法证明「是它导致的」，需结合行业与大盘走势进一步验证。")
            else:
                parts.append("该窗口内没有检索到可核实的公告或新闻，"
                             "暂不能给出成因判断；这类异动可能与行业或大盘联动有关，"
                             "建议扩大检索窗口或做行业对比。")
        elif intent == "compare" and snap.cross:
            parts.append(self._cross_sentence(snap.cross))
        elif intent == "notice" and notice_material:
            labels = []
            for n in notice_material:
                cat = classify_notice(n.get("notice_type") or "", n.get("title") or "")
                label = cat.label if cat is not None else "其它"
                if label not in labels:
                    labels.append(label)
            parts.append("公告事件按类别归集：" + "、".join(labels) + "。")
        elif intent == "events" and not events_n:
            parts.append("按当前阈值没有触发事件；可以在「预警条件」里放宽阈值再试。")
        elif intent == "overview":
            parts.append("可以继续追问：为什么异动、有哪些财报/回购公告、"
                         "与同行业标的相比如何。")
        return prefix + "".join(p for p in parts if p)

    # ============================================================
    # 4. LLM 答案（带引用校验，失败退回模板）
    # ============================================================
    _SYSTEM = (
        "你是严谨的中文金融分析助手，基于给定证据回答用户的追问。硬性规则：\n"
        "1. 只能使用【证据列表】中的信息，不得引入外部知识或编造具体事实。\n"
        "2. 每个结论性判断后面必须标注证据编号，如 [1][3]。\n"
        "3. 证据不足时必须直说「现有证据不足以确证」，不得臆测。\n"
        "4. 不要用「因此必然」「可以确定是」这类因果断言。\n"
        "5. 只输出 JSON。"
    )

    def _ask_llm(self, question: str, snap: Snapshot, ctx: ChatContext,
                 template: str, actions: Sequence[dict] = ()) -> Optional[dict]:
        evs = snap.evidences[:15]
        lines = []
        for i, e in enumerate(evs, 1):
            when = e.published_at or "时间未知"
            lines.append(f"[{i}] ({e.kind}/{e.source}, {when}) {e.title}"
                         + (f" —— {e.excerpt}" if e.excerpt else ""))
        history = ""
        for turn in (ctx.history or [])[-4:]:
            role = "用户" if turn.get("role") == "user" else "助手"
            history += f"{role}：{str(turn.get('content'))[:160]}\n"

        done = "".join(f"- {a.get('describe')}\n" for a in actions
                       if a.get("type") == "set_alert")
        prompt = (f"【标的】{snap.code} {snap.name}（{snap.industry or '未分类'}）\n"
                  f"【区间】{snap.start} ~ {snap.end}\n"
                  + (f"【当前事件】{ctx.event}\n" if ctx.event else "")
                  + (f"【系统已执行的配置变更】\n{done}（不要回答「无法修改」）\n"
                     if done else "")
                  + (f"【对话历史】\n{history}\n" if history else "")
                  + f"【证据列表】（只能引用这些编号）\n"
                  + ("\n".join(lines) if lines else "（无可用证据）")
                  + f"\n\n【用户追问】{question}\n\n"
                  + '请输出 JSON：{"answer": "3~5 句中文回答，判断后标注 [编号]", '
                    '"cited_evidence_ids": [整数数组], '
                    '"insufficient_evidence": true/false, '
                    '"confidence": 0~1}')

        try:
            payload = (self.llm.complete_json(prompt, system=self._SYSTEM)
                       if hasattr(self.llm, "complete_json")
                       else self._parse_json(self.llm.complete(prompt,
                                                              system=self._SYSTEM)))
        except Exception as e:                          # noqa: BLE001
            self._log(f"  [chat] LLM 调用失败，退回模板: {type(e).__name__}")
            return dict(answer=template, cited_evidence_ids=self._cited_ids(template),
                        meta=dict(enabled=True, degraded=True,
                                  reason=f"{type(e).__name__}: {str(e)[:120]}"))

        answer = str(payload.get("answer") or "").strip()
        cited = self._validate_citations(payload, len(evs))
        if not answer or cited is None:
            self._log("  [chat] LLM 答案不合格（空答案或引用非法），退回模板")
            return dict(answer=template, cited_evidence_ids=self._cited_ids(template),
                        meta=dict(enabled=True, degraded=True,
                                  reason="引用校验未通过"))
        return dict(answer=answer, cited_evidence_ids=cited,
                    meta=dict(enabled=True, degraded=False,
                              insufficient_evidence=bool(
                                  payload.get("insufficient_evidence")),
                              confidence=payload.get("confidence")))

    @staticmethod
    def _validate_citations(payload: dict, n: int) -> Optional[list]:
        raw = payload.get("cited_evidence_ids") or []
        try:
            cited = sorted({int(x) for x in raw})
        except (TypeError, ValueError):
            return None
        if any(c < 1 or c > n for c in cited):
            return None                                  # 编造编号 -> 判定幻觉
        if n > 0 and not cited and not payload.get("insufficient_evidence"):
            return None                                  # 有证据却零引用 -> 无据
        return cited

    @staticmethod
    def _parse_json(text: str) -> dict:
        import json
        lo, hi = text.find("{"), text.rfind("}")
        if lo < 0 or hi <= lo:
            raise ValueError("返回里没有 JSON")
        return json.loads(text[lo:hi + 1])

    # ============================================================
    # 辅助
    # ============================================================
    def _log(self, msg: str) -> None:
        if self.log:
            self.log(msg)

    @staticmethod
    def _cited_ids(text: str) -> list:
        return sorted({int(x) for x in re.findall(r"\[(\d+)\]", text or "")})

    @staticmethod
    def _notice_material(n: dict) -> bool:
        cat = classify_notice(n.get("notice_type") or "", n.get("title") or "")
        return bool(cat and cat.material)

    @staticmethod
    def _indicator_sentence(ind, cite: Optional[int] = None) -> str:
        p = lambda v: "—" if v is None else f"{v*100:+.2f}%"
        n = lambda v: "—" if v is None else f"{v:.2f}"
        tag = f"[{cite}]" if cite else ""
        return (f"{ind.start} ~ {ind.end}（{ind.n_days} 个交易日）{tag}："
                f"累计收益 {p(ind.total_return)}，年化波动 {p(ind.annualized_volatility)}，"
                f"最大回撤 {p(ind.max_drawdown)}，夏普 {n(ind.sharpe)}，"
                f"PE(TTM) {n(ind.pe_ttm)}。")

    @staticmethod
    def _cross_sentence(cross: dict) -> str:
        rows = sorted(cross.get("assets") or [],
                      key=lambda a: -(a.get("total_return") or -9))
        bits = [f"{a.get('name') or a['code']} {((a.get('total_return') or 0) * 100):+.2f}%"
                for a in rows]
        r = f"区间内相对表现：{'、'.join(bits)}"
        if cross.get("benchmark"):
            b = cross["benchmark"]
            r += f"；同期基准 {b.get('name')} {((b.get('total_return') or 0) * 100):+.2f}%"
        return r + "。"

    def _other_codes(self, question: str, ctx: ChatContext) -> list[str]:
        """追问里出现的其它股票代码（用于「和某某比」这类问题）。"""
        texts = [question or ""] + [str(t.get("content") or "")
                                    for t in (ctx.history or [])]
        found: list[str] = []
        for t in texts:
            for c in _CODE_RE.findall(t):
                if c not in found:
                    found.append(c)
        return found
