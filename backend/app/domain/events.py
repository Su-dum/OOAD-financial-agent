# -*- coding: utf-8 -*-
"""事件监控领域模型。

对应评分项 **B2（Financial Event Monitoring）**：
检测用户定义的事件或显著变化。

设计要点：
  `AlertRule` 是**策略**（Strategy 模式）。不同检测算法是不同子类，
  `EventMonitor` 只依赖抽象规则列表，新增规则不用改监控器（开闭原则）。

同时这也是 **D1（自动异常检测）** 的落点：
  `ThresholdRule` 是「用户显式定义规则」，`ZScoreRule` 是「不依赖固定规则的统计异常检测」。
"""
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from ..core.indicators import daily_returns
from .models import PriceSeries


@dataclass(frozen=True)
class MarketEvent:
    """一次被检测到的市场事件（值对象：不可变）。"""
    code: str
    name: str
    event_type: str          # price_drop / price_surge / volume_spike / zscore
    trade_date: str          # 事件发生的交易日
    detected_at: str         # 检测时刻
    severity: str            # low / medium / high
    value: Optional[float] = None       # 触发时的实际值（如 -0.085 = 跌 8.5%）
    threshold: Optional[float] = None   # 触发阈值
    detail: str = ""
    rule_name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        v = "—" if self.value is None else f"{self.value:+.4f}"
        return (f"{self.trade_date} {self.code} {self.name} [{self.event_type}] "
                f"severity={self.severity} value={v}  {self.detail}")


def _severity_by(value: float, warn: float, high: float) -> str:
    a = abs(value)
    if a >= high:
        return "high"
    if a >= warn:
        return "medium"
    return "low"


class AlertRule(ABC):
    """预警规则（策略）。子类实现 evaluate()，只依赖一条价格序列。"""

    name: str = "base"
    event_type: str = "generic"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    @abstractmethod
    def evaluate(self, series: PriceSeries, name: str = "") -> list[MarketEvent]:
        ...

    # 便于子类复用
    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name}>"


class ThresholdRule(AlertRule):
    """单日涨跌幅超过阈值。属于「用户显式定义的事件」。"""

    name = "threshold_pct_change"
    event_type = "price_move"

    def __init__(self, drop: float = -0.05, surge: float = 0.05,
                 enabled: bool = True):
        super().__init__(enabled)
        self.drop = drop      # 例如 -0.05 表示跌 5%
        self.surge = surge    # 例如 0.05 表示涨 5%

    def evaluate(self, series: PriceSeries, name: str = "") -> list[MarketEvent]:
        if not self.enabled or len(series) < 2:
            return []
        out = []
        recs = series.records
        for i in range(1, len(recs)):
            prev, cur = recs[i - 1].close, recs[i].close
            if prev <= 0:
                continue
            chg = cur / prev - 1
            if chg <= self.drop:
                out.append(MarketEvent(
                    code=series.code, name=name, event_type="price_drop",
                    trade_date=recs[i].date, detected_at=self._now(),
                    severity=_severity_by(chg, abs(self.drop), abs(self.drop) * 1.6),
                    value=chg, threshold=self.drop,
                    detail=f"单日下跌 {chg*100:.2f}%，超过阈值 {self.drop*100:.2f}%",
                    rule_name=self.name))
            elif chg >= self.surge:
                out.append(MarketEvent(
                    code=series.code, name=name, event_type="price_surge",
                    trade_date=recs[i].date, detected_at=self._now(),
                    severity=_severity_by(chg, self.surge, self.surge * 1.6),
                    value=chg, threshold=self.surge,
                    detail=f"单日上涨 {chg*100:.2f}%，超过阈值 {self.surge*100:.2f}%",
                    rule_name=self.name))
        return out


class VolumeSpikeRule(AlertRule):
    """成交量放大到过去 N 日均量的 k 倍。"""

    name = "volume_spike"
    event_type = "volume"

    def __init__(self, window: int = 20, multiple: float = 2.5,
                 enabled: bool = True):
        super().__init__(enabled)
        self.window = window
        self.multiple = multiple

    def evaluate(self, series: PriceSeries, name: str = "") -> list[MarketEvent]:
        if not self.enabled or len(series) < self.window + 1:
            return []
        out = []
        recs = series.records
        vols = [r.volume or 0.0 for r in recs]
        for i in range(self.window, len(recs)):
            base = statistics.fmean(vols[i - self.window:i])
            if base <= 0:
                continue
            ratio = vols[i] / base
            if ratio >= self.multiple:
                out.append(MarketEvent(
                    code=series.code, name=name, event_type="volume_spike",
                    trade_date=recs[i].date, detected_at=self._now(),
                    severity=_severity_by(ratio, self.multiple, self.multiple * 1.8),
                    value=ratio, threshold=self.multiple,
                    detail=(f"成交量为前 {self.window} 日均量的 {ratio:.1f} 倍"
                            f"（阈值 {self.multiple} 倍）"),
                    rule_name=self.name))
        return out


class ZScoreRule(AlertRule):
    """收益率 z-score 超阈值。

    **不需要用户逐条写规则**——用统计方法自动发现异常，对应 D1。
    """

    name = "zscore_return"
    event_type = "statistical_anomaly"

    def __init__(self, window: int = 60, z: float = 3.0, enabled: bool = True):
        super().__init__(enabled)
        self.window = window
        self.z = z

    def evaluate(self, series: PriceSeries, name: str = "") -> list[MarketEvent]:
        if not self.enabled or len(series) <= self.window + 1:
            return []
        rets = daily_returns(series.closes)
        recs = series.records
        out = []
        for i in range(self.window, len(rets)):
            hist = rets[i - self.window:i]
            if len(hist) < 2:
                continue
            mu = statistics.fmean(hist)
            sd = statistics.stdev(hist)
            if sd <= 0:
                continue
            score = (rets[i] - mu) / sd
            if abs(score) >= self.z:
                out.append(MarketEvent(
                    code=series.code, name=name, event_type="statistical_anomaly",
                    trade_date=recs[i + 1].date, detected_at=self._now(),
                    severity=_severity_by(score, self.z, self.z * 1.5),
                    value=score, threshold=self.z,
                    detail=(f"收益率 {rets[i]*100:+.2f}% 偏离近 {self.window} 日均值 "
                            f"{score:+.1f} 个标准差"),
                    rule_name=self.name))
        return out
