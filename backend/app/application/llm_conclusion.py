# -*- coding: utf-8 -*-
"""结论生成策略。

把「怎么得出报告结论」抽象成策略，两种实现可互换：

    TemplateConclusionWriter   模板拼接（无 LLM，永远可用）
    LLMConclusionWriter        大模型归纳 + 引用校验 + 失败自动降级

**防幻觉的关键不在 prompt，而在结构 + 校验：**

  1. 证据编号化：给模型 [1]..[n] 的编号
  2. 强制结构化输出：{conclusion, confidence, cited_evidence_ids,
     insufficient_evidence, hypotheses}
  3. 引用校验：模型引用的编号必须真实存在；编造编号 -> 判定不合格
  4. 不合格就**整段丢弃，退回模板**，绝不让编造的结论进入报告

这样即使模型胡说，报告里也不会出现无据内容——符合提案 4.7「区分事实与假设」。
"""
from typing import Optional, Protocol, Sequence

from ..domain.investigation import Evidence, InvestigationReport


# ============================================================
# 协议
# ============================================================
class ConclusionWriter(Protocol):
    name: str

    def write(self, report: InvestigationReport) -> None:
        """就地填充 report.conclusion / confidence（可选追加 hypotheses）。"""
        ...


class LLMClientProto(Protocol):
    def complete(self, prompt: str, system: Optional[str] = None) -> str: ...


class StructuredLLMClientProto(LLMClientProto, Protocol):
    def complete_json(self, prompt: str, system: Optional[str] = None) -> dict: ...


# ============================================================
# 模板策略（永远可用的兜底）
# ============================================================
class TemplateConclusionWriter:
    name = "template"

    def __init__(self, log=print):
        self.log = log

    def write(self, report: InvestigationReport) -> None:
        news_n = len(report.evidence_by_kind("news"))
        notice_n = len(report.evidence_by_kind("notice"))
        total = len(report.evidences)

        parts = []
        if notice_n:
            parts.append(f"公司在该期间披露了 {notice_n} 条公告")
        if news_n:
            parts.append(f"检索到 {news_n} 条相关新闻")

        if not parts:
            report.conclusion = ("未检索到可支撑成因判断的公告或新闻。"
                                 "该异动可能是市场整体或行业层面的联动，建议扩大检索范围。")
        else:
            report.conclusion = (
                f"{'，'.join(parts)}。上述证据只能说明「期间发生了什么」，"
                f"尚不足以确证「是该事件导致价格变化」。"
                f"建议结合行业指数同步表现与更长窗口进一步验证。")

        report.confidence = min(0.9, 0.15 * min(total, 3)
                                + 0.15 * min(notice_n, 2)
                                + 0.1 * min(news_n, 3))


# ============================================================
# LLM 策略
# ============================================================
_SYSTEM_PROMPT = (
    "你是一名严谨的中文金融分析助手。你的任务是把已有证据归纳成结论。\n"
    "必须遵守以下硬性规则，违反任何一条都视为失败：\n"
    "1. 只能使用【给定证据列表】中的信息，不得引入任何外部知识或常识推断具体事实。\n"
    "2. 每个结论性判断都必须引用证据编号，格式如 [1]、[3]。\n"
    "3. 如果证据不足以判断成因，必须把 insufficient_evidence 设为 true，并在 conclusion 中直说"
    "「现有证据不足以确证成因」。\n"
    "4. 不要把相关性说成因果性。禁止使用「因此必然」「可以确定是」这类表述。\n"
    "5. 只输出 JSON，不要输出任何解释性文字。"
)

_JSON_SCHEMA_HINT = """请严格按以下 JSON 结构输出：
{
  "conclusion": "3~5 句中文结论，每句判断后面用 [编号] 标注依据",
  "confidence": 0.0 到 1.0 之间的数字,
  "cited_evidence_ids": [引用的证据编号整数数组],
  "insufficient_evidence": true 或 false,
  "hypotheses": ["仍然只是推测、但值得进一步验证的说法（可为空数组）"]
}"""


class LLMConclusionWriter:
    """用大模型写结论。

    任何一环不合格（调用失败 / JSON 非法 / 引用编号不存在 / conclusion 为空），
    都会静默降级到 `fallback`，保证报告仍然可用。
    """

    name = "llm"

    def __init__(self, client, fallback: Optional[ConclusionWriter] = None,
                 max_evidence: int = 15, log=print):
        self.client = client
        self.fallback = fallback or TemplateConclusionWriter(log=log)
        self.max_evidence = max_evidence
        self.log = log

    # ---------------- 对外 ----------------
    def write(self, report: InvestigationReport) -> None:
        try:
            payload = self._ask(report)
            self._apply(report, payload)
        except Exception as e:
            reason = f"{type(e).__name__}: {str(e)[:180]}".strip()
            if self.log:
                self.log(f"  [llm] 结论生成失败，降级到模板: {reason}")
            self._mark_degraded(report, reason)
            self.fallback.write(report)

    # ---------------- 内部 ----------------
    def _numbered_evidences(self, report: InvestigationReport) -> list[Evidence]:
        return report.evidences[:self.max_evidence]

    def build_prompt(self, report: InvestigationReport) -> str:
        evs = self._numbered_evidences(report)
        lines = []
        for i, e in enumerate(evs, 1):
            when = e.published_at or "时间未知"
            lines.append(f"[{i}] ({e.kind}/{e.source}, {when}) {e.title}"
                         + (f" —— 节选：{e.excerpt}" if e.excerpt else ""))
        ev_block = "\n".join(lines) if lines else "（无可用证据）"

        event_line = ""
        if report.event is not None and hasattr(report.event, "describe"):
            event_line = report.event.describe()

        facts_block = "\n".join(f"- {f}" for f in report.facts) or "（无）"

        return (f"【事件】\n{event_line}\n\n"
                f"【已确认的事实】\n{facts_block}\n\n"
                f"【证据列表】（只能引用这些编号）\n{ev_block}\n\n"
                f"【问题】{report.question}\n\n"
                f"{_JSON_SCHEMA_HINT}")

    def _ask(self, report: InvestigationReport) -> dict:
        prompt = self.build_prompt(report)
        if hasattr(self.client, "complete_json"):
            return self.client.complete_json(prompt, system=_SYSTEM_PROMPT)
        # 只有纯文本能力的客户端：让它输出 JSON 字符串，再自己解析
        import json
        text = self.client.complete(prompt, system=_SYSTEM_PROMPT)
        lo, hi = text.find("{"), text.rfind("}")
        if lo < 0 or hi <= lo:
            raise ValueError("返回里没有 JSON")
        return json.loads(text[lo:hi + 1])

    def _apply(self, report: InvestigationReport, payload: dict) -> None:
        conclusion = (payload.get("conclusion") or "").strip()
        if not conclusion:
            raise ValueError("conclusion 为空")

        # ---- 引用校验：编造的编号一律不合格 ----
        raw_ids = payload.get("cited_evidence_ids") or []
        try:
            cited = sorted({int(x) for x in raw_ids})
        except (TypeError, ValueError):
            raise ValueError(f"cited_evidence_ids 非法: {raw_ids!r}")

        n = len(self._numbered_evidences(report))
        invalid = [c for c in cited if c < 1 or c > n]
        if invalid:
            raise ValueError(f"模型引用了不存在的证据编号 {invalid}（实际只有 1..{n}），判定为幻觉")

        # 模型自认证据不足时，允许不引用（这正是它该做的）；
        # 反之，有证据却不引用任何编号，属于无据结论。
        insufficient = bool(payload.get("insufficient_evidence"))
        if n > 0 and not cited and not insufficient:
            raise ValueError("有证据但结论未引用任何编号，判定为无据结论")

        # ---- 置信度：不能超过证据能支撑的上限 ----
        try:
            conf = float(payload.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        ceiling = min(0.9, 0.3 + 0.12 * len(cited))
        if payload.get("insufficient_evidence"):
            ceiling = min(ceiling, 0.5)

        report.conclusion = conclusion
        report.confidence = round(min(conf, ceiling), 3)
        report.llm_meta = dict(
            provider=getattr(getattr(self.client, "config", None), "provider", ""),
            model=getattr(getattr(self.client, "config", None), "model", ""),
            cited_evidence_ids=cited,
            insufficient_evidence=bool(payload.get("insufficient_evidence")),
            degraded=False,
        )

        # 模型补充的推测，写进 hypotheses（不污染 facts）
        for h in (payload.get("hypotheses") or [])[:5]:
            if isinstance(h, str) and h.strip():
                report.add_hypothesis(f"[LLM] {h.strip()}")

    def _mark_degraded(self, report: InvestigationReport,
                       reason: str = "llm_fallback") -> None:
        """记录降级原因——生产环境排查问题靠它，不能只写一个笼统标记。"""
        cfg = getattr(self.client, "config", None)
        report.llm_meta = dict(
            degraded=True,
            reason=reason,
            provider=getattr(cfg, "provider", "") or "",
            model=getattr(cfg, "model", "") or "",
        )
