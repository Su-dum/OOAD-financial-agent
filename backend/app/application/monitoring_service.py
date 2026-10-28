# -*- coding: utf-8 -*-
"""事件监控服务（应用层）。

职责：把一条价格序列喂给若干 `AlertRule` 策略，汇总出事件列表。

这里体现了开闭原则：`EventMonitor` 只依赖 `AlertRule` 抽象，
新增一种检测算法（比如换手率异常、龙虎榜异动）不用改本文件。
"""
from typing import Optional, Sequence

from ..domain.events import (AlertRule, MarketEvent, ThresholdRule,
                             VolumeSpikeRule, ZScoreRule)
from .market_service import MarketDataService


class EventMonitor:
    def __init__(self, market: MarketDataService,
                 rules: Sequence[AlertRule], log=print):
        self.market = market
        self.rules = list(rules)
        self.log = log

    @classmethod
    def default(cls, market: MarketDataService, log=print) -> "EventMonitor":
        return cls(market, [
            ThresholdRule(drop=-0.05, surge=0.05),   # 用户显式阈值（B2）
            VolumeSpikeRule(window=20, multiple=2.5),
            ZScoreRule(window=60, z=3.0),            # 不依赖固定规则的统计检测（D1）
        ], log=log)

    def add_rule(self, rule: AlertRule) -> None:
        self.rules.append(rule)

    def scan(self, code: str, start: str, end: str,
             source: Optional[str] = None) -> list[MarketEvent]:
        series = self.market.get_series(code, start, end, source=source,
                                       require_returns=True)
        if series is None or len(series) < 2:
            if self.log:
                self.log(f"  [monitor] {code} 无可用序列")
            return []
        name = self.market.name_of(code)
        events: list[MarketEvent] = []
        for rule in self.rules:
            try:
                events.extend(rule.evaluate(series, name=name))
            except Exception as e:                     # 单条规则出错不影响其它规则
                if self.log:
                    self.log(f"  [monitor] 规则 {rule.name} 失败: {type(e).__name__}")
        events.sort(key=lambda e: e.trade_date, reverse=True)
        return events

    def scan_many(self, codes: Sequence[str], start: str, end: str,
                  source: Optional[str] = None) -> list[MarketEvent]:
        out: list[MarketEvent] = []
        for c in codes:
            out.extend(self.scan(c, start, end, source=source))
        out.sort(key=lambda e: (e.trade_date, e.severity), reverse=True)
        return out
