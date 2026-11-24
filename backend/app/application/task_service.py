# -*- coding: utf-8 -*-
"""分析任务服务（C1）。

一个任务 = 一组**参数**（标的 / 区间 / 对比组 / 基准）。
`run()` 把这些参数翻译成一次完整分析：指标 + 事件 + 跨期 + 跨资产。

为什么不在任务里存结果：结果是随数据变化的快照，存下来必然过期；
任务只存参数，每次运行重新计算——这也是「配置」与「结果」的自然分界。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from ..domain.analysis_task import AnalysisTask, period_windows


class TaskValidationError(ValueError):
    """任务参数不合法（接口层转成 HTTP 400）。"""


def _range_of(days: int) -> tuple:
    end = datetime.now()
    start = end - timedelta(days=int(days))
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


class AnalysisTaskService:
    def __init__(self, repo, analyzer, monitor=None, cross=None, catalog=None,
                 log=print):
        self.repo = repo
        self.analyzer = analyzer
        self.monitor = monitor
        self.cross = cross
        self.catalog = catalog
        self.log = log

    # ---------------- 校验 ----------------
    def _validate(self, name: str, code: str, days: int,
                  compare_codes: Sequence[str]) -> tuple:
        name = (name or "").strip()
        if not name:
            raise TaskValidationError("任务名不能为空")
        if len(name) > 40:
            raise TaskValidationError("任务名太长（最多 40 字）")
        c = str(code or "").split(".")[0]
        if not c.isdigit() or len(c) != 6:
            raise TaskValidationError(f"股票代码不合法：{code!r}")
        if self.catalog is not None and not self.catalog.name_of(c):
            raise TaskValidationError(f"{c} 不在股票映射表中")
        if not 5 <= int(days) <= 2000:
            raise TaskValidationError("区间天数必须在 5~2000 之间")
        codes = []
        for x in compare_codes or ():
            x = str(x).strip().split(".")[0]
            if x and x != c and x not in codes:
                codes.append(x)
        if len(codes) > 5:
            raise TaskValidationError("对比标的最多 5 个")
        return name, c, int(days), tuple(codes)

    # ---------------- 写 ----------------
    def create(self, name: str, code: str, days: int = 365,
               compare_codes: Sequence[str] = (), benchmark: Optional[str] = None
               ) -> AnalysisTask:
        name, c, days, codes = self._validate(name, code, days, compare_codes)
        task = AnalysisTask(name=name, code=c, days=days, compare_codes=codes,
                            benchmark=benchmark or "sh000300")
        tid = self.repo.create(task)
        return AnalysisTask(**{**task.__dict__, "id": tid,
                               "created_at": datetime.now().strftime(
                                   "%Y-%m-%d %H:%M:%S")})

    def delete(self, task_id: int) -> bool:
        return self.repo.delete(task_id)

    def list(self, limit: int = 50) -> list[dict]:
        return [t.to_dict() for t in self.repo.list(limit)]

    # ---------------- 运行 ----------------
    def run(self, task_id: int) -> dict:
        task = self.repo.get(task_id)
        if task is None:
            raise TaskValidationError(f"任务 {task_id} 不存在")
        start, end = _range_of(task.days)
        body = dict(task=task.to_dict(), start=start, end=end,
                    generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        indicator = self.analyzer.analyze(task.code, start, end)
        body["indicator"] = indicator.to_dict() if indicator is not None else None

        if self.monitor is not None:
            try:
                events = self.monitor.scan(task.code, start, end)
            except Exception as e:                      # noqa: BLE001
                if self.log:
                    self.log(f"  [task] {task.code} 事件检测失败: {type(e).__name__}")
                events = []
            body["events"] = [e.to_dict() for e in events[:10]]
            body["event_count"] = len(events)
        else:
            body["events"] = []
            body["event_count"] = 0

        periods = []
        for label, days in period_windows(task.days):
            s, e = _range_of(days)
            try:
                r = self.analyzer.analyze(task.code, s, e)
            except Exception:                           # noqa: BLE001
                r = None
            periods.append(dict(
                period=label, start=s, end=e,
                total_return=None if r is None else r.total_return,
                annualized_volatility=None if r is None else r.annualized_volatility,
                max_drawdown=None if r is None else r.max_drawdown,
                sharpe=None if r is None else r.sharpe,
                n_days=0 if r is None else r.n_days))
        body["periods"] = periods

        body["cross"] = None
        if self.cross is not None and task.compare_codes:
            try:
                x = self.cross.compare([task.code] + list(task.compare_codes),
                                       start, end, benchmark=task.benchmark)
                body["cross"] = dict(
                    n_days=x.get("n_days"), assets=x.get("assets"),
                    correlation=x.get("correlation"),
                    benchmark=x.get("benchmark"), note=x.get("note"))
            except Exception as e:                      # noqa: BLE001
                if self.log:
                    self.log(f"  [task] 跨资产失败: {type(e).__name__}")

        self.repo.touch(task_id)
        return body
