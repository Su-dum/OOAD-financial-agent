# -*- coding: utf-8 -*-
"""事件监控服务（应用层）。

职责：把**行情序列**喂给 `AlertRule` 策略、把**公告流**喂给 `NoticeRule` 策略，
汇总成同一份事件列表。

这里体现了开闭原则：`EventMonitor` 只依赖 `AlertRule` / `NoticeRule` 两个抽象，
新增一种检测算法（比如换手率异常、龙虎榜异动、某类新公告）不用改本文件。

两类规则的输入不同，所以是**并列**的两条链，而不是硬塞进一个签名：

    价格链：MarketDataService -> PriceSeries -> AlertRule.evaluate(series)
    公告链：NoticeRepository  -> list[dict]  -> NoticeRule.evaluate(notices)

任一条链失败都不影响另一条（行情源挂了，公告事件照样能出）。
"""
from typing import Optional, Sequence

from ..domain.events import (AlertRule, MarketEvent, NoticeEventRule, NoticeRule,
                             ThresholdRule, VolumeSpikeRule, ZScoreRule)
from .market_service import MarketDataService

_SEV_ORDER = {"low": 0, "medium": 1, "high": 2}


class EventMonitor:
    def __init__(self, market: MarketDataService,
                 rules: Sequence[AlertRule],
                 notice_rules: Sequence[NoticeRule] = (),
                 notices=None, rulebook=None, log=print):
        self.market = market
        self.rules = list(rules)
        self.notice_rules = list(notice_rules)
        self.notices = notices          # 满足 domain.ports.NoticeRepository 的仓储
        # rulebook：可选的「按标的取规则」来源（C1 用户可配置预警条件）。
        # 给了它就用它，没给就用构造时传入的固定规则列表（单测/脚本方便）。
        self.rulebook = rulebook
        self.log = log

    @classmethod
    def default(cls, market: MarketDataService, notices=None,
                notice_rules: Optional[Sequence[NoticeRule]] = None,
                rulebook=None, log=print) -> "EventMonitor":
        return cls(market, [
            ThresholdRule(drop=-0.05, surge=0.05),   # 出厂阈值（可被 rulebook 覆盖）
            VolumeSpikeRule(window=20, multiple=2.5),
            ZScoreRule(window=60, z=3.0),            # 不依赖固定规则的统计检测（D1）
        ],
            notice_rules=(notice_rules if notice_rules is not None
                          else [NoticeEventRule()]),
            notices=notices,
            rulebook=rulebook,
            log=log)

    def add_rule(self, rule: AlertRule) -> None:
        self.rules.append(rule)

    def add_notice_rule(self, rule: NoticeRule) -> None:
        self.notice_rules.append(rule)

    def rules_for(self, code: str):
        """该标的当前生效的 (价格规则, 公告规则)。"""
        if self.rulebook is None:
            return self.rules, self.notice_rules
        try:
            price_rules, notice_rules = self.rulebook.for_code(code)
            return list(price_rules), list(notice_rules)
        except Exception as e:                     # noqa: BLE001
            if self.log:
                self.log(f"  [monitor] {code} 规则配置读取失败，退回出厂规则: "
                         f"{type(e).__name__}")
            return self.rules, self.notice_rules

    # ---------------- 扫描 ----------------
    def scan(self, code: str, start: str, end: str,
             source: Optional[str] = None,
             include_notices: bool = True) -> list[MarketEvent]:
        name = self.market.name_of(code) if self.market else ""
        rules, notice_rules = self.rules_for(code)
        events: list[MarketEvent] = []
        events.extend(self._scan_price(code, start, end, source, name, rules))
        if include_notices:
            events.extend(self._scan_notices(code, start, end, name, notice_rules))
        events.sort(key=lambda e: (e.trade_date,
                                   _SEV_ORDER.get(e.severity, 0)), reverse=True)
        return events

    def scan_many(self, codes: Sequence[str], start: str, end: str,
                  source: Optional[str] = None,
                  include_notices: bool = True) -> list[MarketEvent]:
        out: list[MarketEvent] = []
        for c in codes:
            out.extend(self.scan(c, start, end, source=source,
                                 include_notices=include_notices))
        out.sort(key=lambda e: (e.trade_date, e.severity), reverse=True)
        return out

    # ---------------- 内部：两条链 ----------------
    def _scan_price(self, code, start, end, source, name,
                    rules=None) -> list[MarketEvent]:
        rules = self.rules if rules is None else rules
        if not rules:
            return []
        series = self.market.get_series(code, start, end, source=source,
                                       require_returns=True) if self.market else None
        if series is None or len(series) < 2:
            if self.log:
                self.log(f"  [monitor] {code} 无可用行情序列，跳过价格规则")
            return []
        events: list[MarketEvent] = []
        for rule in rules:
            try:
                events.extend(rule.evaluate(series, name=name))
            except Exception as e:                     # 单条规则出错不影响其它规则
                if self.log:
                    self.log(f"  [monitor] 规则 {rule.name} 失败: {type(e).__name__}")
        return events

    def _scan_notices(self, code, start, end, name,
                      notice_rules=None) -> list[MarketEvent]:
        notice_rules = self.notice_rules if notice_rules is None else notice_rules
        if not notice_rules or self.notices is None:
            return []
        try:
            rows = self.notices.find_by_stock(code, start=start, end=end, limit=200)
        except Exception as e:                         # noqa: BLE001
            if self.log:
                self.log(f"  [monitor] {code} 公告读取失败: {type(e).__name__}")
            return []
        if not rows:
            return []
        events: list[MarketEvent] = []
        for rule in notice_rules:
            try:
                events.extend(rule.evaluate(rows, code=code, name=name))
            except Exception as e:                     # noqa: BLE001
                if self.log:
                    self.log(f"  [monitor] 公告规则 {rule.name} 失败: {type(e).__name__}")
        return events
