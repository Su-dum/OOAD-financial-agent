# -*- coding: utf-8 -*-
"""多步调查的「下一步决策」——D2 的核心。

D2 原文拆成两个动词：

    decompose                -> 拆子任务（由 InvestigationAgent 逐步记录，每步一条 InvestigationTask）
    dynamically determine    -> **本文件**：根据「已有的证据」决定下一步查什么、什么时候停

## 为什么单独一层

旧实现是 `for tool in tools: tool.run(...)`——工具集合与顺序在构造时就固定，
无论事件是什么都跑同一套。这不是"多步调查"，是"三连批处理"。

现在把「决策」抽出来，两种实现互为兜底：

    LLMPlanner        让模型从动作菜单里选下一步 + 给出理由（真正的自主决定）
    HeuristicPlanner  纯规则「缺什么补什么」——没有 LLM 时仍然随证据变化，
                      而不是退回到固定三连跑

两条都必须满足：**每一步只跑一次**、**总步数有上限**、**能说出为什么走这一步**。
这样"动态"才是可观察、可验收的，而不是嘴上说。
"""
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence

# ============================================================
# 动作菜单
# ============================================================
# key -> (中文名, 干什么, 这一步要回答的问题)
ACTIONS: dict = {
    "indicator": (
        "区间指标",
        "算区间涨跌幅/波动/回撤，建立价格事实基准",
        "{name} 在 {start} ~ {end} 的价格与风险事实是什么？",
    ),
    "notice_search": (
        "检索公告",
        "查公司近期公告（财报/分红/回购/增减持/监管等）",
        "{name} 在该期间有没有披露可能解释这次异动的公告？",
    ),
    "notice_deep": (
        "公告正文",
        "下载公告 PDF 抽正文，补实质内容（较慢）",
        "已找到的公告正文里到底说了什么实质内容？",
    ),
    "news_search": (
        "个股新闻",
        "按公司名/代码检索新闻",
        "该期间有没有关于 {name} 的新闻报道？",
    ),
    "news_widen": (
        "扩窗检索",
        "个股新闻不足时，换行业关键词并扩大时间窗重试",
        "放宽时间窗、改用行业关键词后，能不能找到相关消息？",
    ),
    "industry": (
        "行业联动",
        "查所属申万行业指数同期表现，判断是否行业性下跌",
        "{industry} 行业同期是否同向异动（即这次异动是行业性还是个股特有）？",
    ),
    "stop": (
        "结束调查",
        "已有证据足以支撑结论",
        "",
    ),
}

# 缺什么补什么的优先级（先拿最便宜、最硬的事实）
PREFERENCE: tuple = ("indicator", "notice_search", "news_search",
                     "news_widen", "industry", "notice_deep")


def label_of(action: str) -> str:
    return ACTIONS.get(action, (action, "", ""))[0]


def describe_of(action: str) -> str:
    return ACTIONS.get(action, (action, "", ""))[1]


def question_of(action: str, **kw) -> str:
    tpl = ACTIONS.get(action, (action, "", ""))[2]
    if not tpl:
        return ""
    try:
        return tpl.format(**kw)
    except (KeyError, IndexError):
        return tpl


# ============================================================
# 决策对象
# ============================================================
@dataclass(frozen=True)
class Decision:
    """下一步做什么。`reason` 会写进任务并展示给用户，不是内部日志。"""
    action: str
    reason: str = ""
    args: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(action=self.action, reason=self.reason, args=dict(self.args))


@dataclass
class PlannerState:
    """决策时能看到的全部信息（只读快照，便于单测）。"""
    event: Any
    menu: Sequence[str]
    tried: Sequence[str]
    evidences: Sequence[Any]
    step: int = 0
    budget: int = 5

    def quality(self) -> dict:
        """按证据类别计数——决策主要依据它。"""
        q: dict = {}
        for e in self.evidences:
            q[e.kind] = q.get(e.kind, 0) + 1
        return q

    def untried(self) -> list[str]:
        return [a for a in self.menu if a not in set(self.tried) and a != "stop"]

    def available(self) -> dict:
        return {a: describe_of(a) for a in self.menu}


class InvestigationPlanner(Protocol):
    name: str

    def decide(self, state: PlannerState) -> Decision:
        ...


# ============================================================
# 规则规划器（无 LLM 时也保持动态）
# ============================================================
class HeuristicPlanner:
    """「缺什么补什么」的确定性策略。

    它不是固定三连跑：每一步都看**当前证据**再决定，因此
      - 新闻查到很多 → 跳过扩窗检索
      - 个股新闻一条都没有 → 主动换关键词 + 扩窗
      - 公司层面信息不足 → 追加行业联动确认
      - 公告只有标题 → 下正文
    事件不同、证据不同，路径就不同。
    """

    name = "heuristic"

    def __init__(self, log=print):
        self.log = log

    def decide(self, state: PlannerState) -> Decision:
        menu = set(state.menu)
        tried = set(state.tried)
        q = state.quality()

        def ok(action: str) -> bool:
            return action in menu and action not in tried

        # 1) 先固定事实：区间指标（便宜、一定有）
        if ok("indicator"):
            return Decision("indicator",
                            "先固定区间事实（涨跌、波动、回撤），作为后续判断的基准")

        # 2) 公司层面的硬信息优先：公告
        if ok("notice_search"):
            return Decision("notice_search",
                            "先查公司公告：披露类信息是事件最直接的成因线索")

        # 3) 消息面：个股新闻
        if ok("news_search"):
            return Decision("news_search", "按公司名检索新闻，补齐消息面")

        # 4) 个股新闻查不到 → **换策略**（这是"动态"最直观的体现）
        if q.get("news", 0) == 0 and ok("news_widen"):
            return Decision("news_widen",
                            "按个股名没查到新闻，改用行业关键词并放宽时间窗重试",
                            dict(widen_days=30))

        # 5) 公司层面信息不足 → 确认是否行业联动
        if ok("industry") and (q.get("news", 0) == 0 or q.get("notice", 0) == 0):
            return Decision("industry",
                            "公司层面证据不足，查所属行业指数确认是否行业性异动")

        # 6) 公告只有标题 → 下正文补实质内容
        if q.get("notice", 0) > 0 and ok("notice_deep"):
            return Decision("notice_deep", "公告只有标题，下载正文补充实质内容")

        # 7) 兜底：**一点证据都没查到**时才把剩余动作试一遍
        #    （对应自定义工具 / 工具全失败的情况；有证据时不该继续凑步数）
        if not state.evidences:
            for action in state.untried():
                return Decision(action, "尚无任何证据，补跑这个尚未执行的动作")

        return Decision("stop", "价格事实、公司公告、新闻与行业对比都已覆盖")


# ============================================================
# LLM 规划器（模型自主选下一步）
# ============================================================
_JSON_HINT = """只输出 JSON：
{
  "action": "从菜单里选一个动作名，或 stop",
  "reason": "一句话说明为什么这步必要（会展示给用户）",
  "args": {}
}"""

_SYSTEM = (
    "你是一名严谨的金融事件调查员，正在**分步**调查一次股价异动。\n"
    "每一步只能选一个动作。请根据已有证据判断「还缺什么」，不要重复已执行的动作。\n"
    "规则：\n"
    "1. 只能从给定菜单里选，不得编造动作名。\n"
    "2. 如果个股新闻一条都没有，应改用 news_widen（换关键词+扩窗），而不是重复 news_search。\n"
    "3. 如果公司层面证据不足，应追加 industry 判断是否行业联动。\n"
    "4. 证据已足够回答「成因与影响」时选 stop，不要为了凑步数继续查。\n"
    "5. 只输出 JSON。"
)


class LLMPlanner:
    """让模型决定下一步；任何异常/非法输出都退回规则规划器，绝不让调查挂掉。"""

    name = "llm"

    def __init__(self, llm, fallback: Optional[InvestigationPlanner] = None,
                 log=print):
        self.llm = llm
        self.fallback = fallback or HeuristicPlanner(log=log)
        self.log = log

    # ---------------- 对外 ----------------
    def decide(self, state: PlannerState) -> Decision:
        try:
            payload = self._ask(state)
        except Exception as e:                            # noqa: BLE001
            if self.log:
                self.log(f"  [agent] 规划调用失败，退回规则: {type(e).__name__}")
            return self._fallback(state, "LLM 规划不可用")

        action = str(payload.get("action") or "").strip()
        reason = str(payload.get("reason") or "").strip()

        if action == "stop":
            return Decision("stop", reason or "模型判断已有证据足以支撑结论")
        if action not in state.menu:
            if self.log:
                self.log(f"  [agent] 模型选了菜单外的动作 {action!r}，退回规则")
            return self._fallback(state, f"模型给出无效动作 {action!r}")
        if action in set(state.tried):
            if self.log:
                self.log(f"  [agent] 模型重复选择已执行动作 {action!r}，退回规则")
            return self._fallback(state, f"模型重复选择 {action}")
        args = payload.get("args")
        return Decision(action, reason or describe_of(action),
                        args if isinstance(args, dict) else {})

    # ---------------- 内部 ----------------
    def _fallback(self, state: PlannerState, why: str) -> Decision:
        d = self.fallback.decide(state)
        reason = f"[规则兜底·{why}] {d.reason}" if d.reason else f"[规则兜底·{why}]"
        return Decision(d.action, reason, d.args)

    def build_prompt(self, state: PlannerState) -> str:
        ev = state.event
        q = state.quality()
        lines = []
        for i, e in enumerate(list(state.evidences)[-12:], 1):
            when = e.published_at or "时间未知"
            lines.append(f"[{i}] ({e.kind}/{e.source}, {when}) {e.title}"
                         + (f" —— {e.excerpt[:110]}" if e.excerpt else ""))
        menu = "\n".join(f"- {a}: {d}" for a, d in state.available().items())
        tried = "、".join(state.tried) or "（还没执行任何步骤）"
        return (
            f"【事件】{ev.trade_date} {ev.code} {ev.name} "
            f"[{ev.label}] severity={ev.severity}　{ev.detail}\n\n"
            f"【进度】第 {state.step + 1} / {state.budget} 步\n"
            f"【已执行】{tried}\n"
            f"【证据计数】{q or '（尚无证据）'}\n"
            f"【已有证据】\n{chr(10).join(lines) if lines else '（无）'}\n\n"
            f"【可选动作】\n{menu}\n\n"
            f"{_JSON_HINT}"
        )

    def _ask(self, state: PlannerState) -> dict:
        prompt = self.build_prompt(state)
        if hasattr(self.llm, "complete_json"):
            return self.llm.complete_json(prompt, system=_SYSTEM) or {}
        import json
        text = self.llm.complete(prompt, system=_SYSTEM) or ""
        lo, hi = text.find("{"), text.rfind("}")
        if lo < 0 or hi <= lo:
            raise ValueError("返回里没有 JSON")
        return json.loads(text[lo:hi + 1])
