# -*- coding: utf-8 -*-
"""调查报告领域模型。

对应评分项 **C4（证据可追溯）** 与 **B3（事件后自动调查）**：
报告中每一条结论都必须能追到具体证据（来源 + 时间 + 链接 + 原文片段）。

设计要点：
  `Evidence` 是**值对象**（不可变），一条证据只描述「我看到了什么」，
  不描述「这意味着什么」——后者属于 `InvestigationReport`。
  这样 B3 的「区分事实与假设」（提案 4.7 风险二）在设计上就有了落点。
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Evidence:
    kind: str                       # news / notice / indicator
    source: str                     # 东财 / 财联社 / 巨潮 / 计算
    title: str
    url: Optional[str] = None
    published_at: Optional[str] = None
    excerpt: str = ""               # 原文片段，用于引用
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    def cite(self) -> str:
        """一行引用串，可直接放进报告。"""
        when = self.published_at or "时间未知"
        link = f" <{self.url}>" if self.url else ""
        return f"[{self.source} {when}] {self.title}{link}"


@dataclass
class InvestigationTask:
    """调查子任务。多步骤调查（D2）的基本单元。

    注意 `question` 是**要回答的问题**（不是"调用哪个工具"）——
    这是 D2「decompose into subtasks」与「把工具各跑一遍」的分水岭。
    `reason` 记录**为什么走这一步**（来自规划的决策），是"动态"的可观察证据。
    """
    question: str
    tool: str = ""
    status: str = "pending"         # pending / running / done / failed
    result_count: int = 0
    note: str = ""
    step: int = 0                   # 第几步（1 起）
    reason: str = ""                # 为什么选这一步（规划给出的理由）
    # 执行的是哪个**动作**（news_widen / industry / notice_deep ...）。
    # 与 `tool` 分开：一个工具可服务多个动作，只记工具名就看不出路径变化。
    action: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InvestigationReport:
    code: str
    name: str = ""
    event: Optional[object] = None          # domain.events.MarketEvent
    question: str = ""
    tasks: list[InvestigationTask] = field(default_factory=list)
    evidences: list[Evidence] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)        # 可验证的事实
    hypotheses: list[str] = field(default_factory=list)   # 推测（未证实）
    conclusion: str = ""
    confidence: float = 0.0
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # 结论是怎么来的：{provider, model, cited_evidence_ids, degraded, ...}
    llm_meta: dict = field(default_factory=dict)
    # ---- D2：多步调查的元信息 ----
    planner: str = ""               # 谁规划的：llm / heuristic
    stop_reason: str = ""           # 为什么停：信息足够 / 步数上限 / 无可执行动作

    # ---------------- 组装 ----------------
    def add_evidence(self, ev: Evidence) -> None:
        self.evidences.append(ev)

    def add_fact(self, text: str) -> None:
        self.facts.append(text)

    def add_hypothesis(self, text: str) -> None:
        self.hypotheses.append(text)

    def evidence_by_kind(self, kind: str) -> list[Evidence]:
        return [e for e in self.evidences if e.kind == kind]

    # ---------------- 输出 ----------------
    def to_dict(self) -> dict:
        return dict(
            code=self.code, name=self.name,
            event=(self.event.to_dict() if hasattr(self.event, "to_dict") else self.event),
            question=self.question,
            tasks=[t.to_dict() for t in self.tasks],
            evidences=[e.to_dict() for e in self.evidences],
            facts=self.facts, hypotheses=self.hypotheses,
            conclusion=self.conclusion, confidence=self.confidence,
            created_at=self.created_at, llm_meta=self.llm_meta,
            planner=self.planner, stop_reason=self.stop_reason)

    def to_markdown(self) -> str:
        lines = [f"# {self.code} {self.name} 事件调查报告", ""]
        if self.event is not None and hasattr(self.event, "describe"):
            lines += ["## 触发事件", "", f"> {self.event.describe()}", ""]
        if self.question:
            lines += ["## 调查问题", "", self.question, ""]
        if self.tasks:
            who = {"llm": "LLM 逐步决策", "heuristic": "规则逐步决策"}.get(
                self.planner, self.planner or "—")
            lines += [f"## 调查步骤（{len(self.tasks)} 步 · {who}）", ""]
            for t in self.tasks:
                head = f"- [{t.status}] 第 {t.step or '?'} 步 {t.question}"
                if t.reason:
                    head += f"\n  - 为什么：{t.reason}"
                head += f"\n  - 命中 {t.result_count} 条（{t.action or t.tool}）"
                lines.append(head)
            lines.append("")
            if self.stop_reason:
                lines += [f"> 结束原因：{self.stop_reason}", ""]
        if self.facts:
            lines += ["## 事实（有证据支持）", ""] + [f"- {f}" for f in self.facts] + [""]
        if self.hypotheses:
            lines += ["## 推测（尚未证实）", ""] + [f"- {h}" for h in self.hypotheses] + [""]
        if self.conclusion:
            lines += ["## 结论", "", self.conclusion,
                      f"", f"置信度：{self.confidence:.0%}", ""]
            meta = self.llm_meta or {}
            if meta.get("degraded"):
                lines += [f"> 结论由模板生成（LLM 调用降级：{meta.get('reason', '')}）", ""]
            elif meta.get("model"):
                cited = meta.get("cited_evidence_ids") or []
                lines += [f"> 结论由 {meta.get('provider')}/{meta.get('model')} 归纳，"
                          f"引用证据 {cited if cited else '无'}", ""]
        if self.evidences:
            lines += ["## 证据来源", ""]
            lines += [f"{i+1}. {e.cite()}" for i, e in enumerate(self.evidences)]
            lines.append("")
        lines.append(f"_生成于 {self.created_at}_")
        return "\n".join(lines)
