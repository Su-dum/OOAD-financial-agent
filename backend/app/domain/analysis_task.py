# -*- coding: utf-8 -*-
"""分析任务（C1：analysis tasks）。

评分原文要求界面能配置 **monitoring targets / analysis tasks / alert conditions**。
前两项此前只做到了「监控目标」与预警条件，分析本身是每次临时选参数。
`AnalysisTask` 把「对哪个标的、看多长区间、和谁比、用什么基准」固化成一个
可保存、可复用的任务，点一下就能重跑并拿到一组结果。

它不保存结果本身——结果是随数据变化的，存下来只会过期。
任务只保存**参数**，这也是「配置」与「结果」的自然分界。
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AnalysisTask:
    name: str
    code: str
    days: int = 365
    compare_codes: tuple = ()
    benchmark: Optional[str] = "sh000300"
    id: Optional[int] = None
    created_at: str = ""
    last_run_at: str = ""

    def to_dict(self) -> dict:
        return dict(id=self.id, name=self.name, code=self.code, days=self.days,
                    compare_codes=list(self.compare_codes),
                    benchmark=self.benchmark,
                    created_at=self.created_at, last_run_at=self.last_run_at)


DEFAULT_PERIODS = (("近 1 个月", 30), ("近 3 个月", 90), ("近 6 个月", 180),
                   ("近 1 年", 365), ("近 2 年", 730))


def period_windows(days: int) -> list[tuple]:
    """把任务区间拆成几档，用于跨期对比（不超过任务本身的长度）。"""
    out = []
    for label, d in DEFAULT_PERIODS:
        if d <= max(days, 30):
            out.append((label, d))
    if not out:
        out.append(("任务区间", max(int(days), 5)))
    return out
