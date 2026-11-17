# -*- coding: utf-8 -*-
"""事件监控领域模型。

对应评分项 **B2（Financial Event Monitoring）**：
检测用户定义的事件或显著变化。

设计要点：
  `AlertRule` 是**策略**（Strategy 模式）。不同检测算法是不同子类，
  `EventMonitor` 只依赖抽象规则列表，新增规则不用改监控器（开闭原则）。

  规则有**两个并列的策略族**，因为输入根本不同：
      AlertRule    吃价格序列（涨跌幅 / 放量 / z-score）
      NoticeRule   吃公告流（财报 / 分红 / 增减持 / 回购 / 重大交易 / 澄清 / 监管）
  两者产出同一种 `MarketEvent`，所以下游（落库、调查、前端）完全不用区分。

同时这也是 **D1（自动异常检测）** 的落点：
  `ThresholdRule` 是「用户显式定义规则」，`ZScoreRule` 是「不依赖固定规则的统计异常检测」。
"""
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Sequence

from ..core.indicators import daily_returns
from .models import PriceSeries
from .notices import classify_notice, clean_title


_EVENT_LABELS = {
    "price_drop": "下跌异动",
    "price_surge": "上涨异动",
    "volume_spike": "放量异动",
    "statistical_anomaly": "统计异常",
    "notice_earnings": "财报披露",
    "notice_dividend": "分红派息",
    "notice_buyback": "股份回购",
    "notice_insider_increase": "股东增持",
    "notice_insider_decrease": "股东减持",
    "notice_major_deal": "重大交易",
    "notice_clarification": "异动澄清",
    "notice_regulatory": "监管事项",
    "notice_equity_change": "股本变动",
    "notice_management": "高管变动",
    "notice_procedural": "程序性公告",
}


@dataclass(frozen=True)
class MarketEvent:
    """一次被检测到的市场事件（值对象：不可变）。"""
    code: str
    name: str
    event_type: str          # price_drop / price_surge / volume_spike / notice_earnings ...
    trade_date: str          # 事件发生的交易日
    detected_at: str         # 检测时刻
    severity: str            # low / medium / high
    value: Optional[float] = None       # 触发时的实际值（如 -0.085 = 跌 8.5%）
    threshold: Optional[float] = None   # 触发阈值
    detail: str = ""
    rule_name: str = ""
    # 公告类事件带上原始公告链接，配合 C4「证据可追溯」
    source_url: Optional[str] = None

    @property
    def label(self) -> str:
        """中文事件名。报告/追问里直接用它，避免把 notice_earnings 这种内部标识给用户看。"""
        return _EVENT_LABELS.get(self.event_type, self.event_type)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d

    def describe(self) -> str:
        v = "—" if self.value is None else f"{self.value:+.4f}"
        return (f"{self.trade_date} {self.code} {self.name} [{self.label}] "
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


# ============================================================
# 公告类规则（B2 的 earnings announcements / major corporate events）
# ============================================================
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


class NoticeRule(ABC):
    """公告类事件规则。

    与 `AlertRule` 并列而不是继承它——因为**输入不同**：
    价格规则吃一条 `PriceSeries`，公告规则吃公告流（list[dict]）。
    把两者硬塞进同一个 `evaluate()` 签名会破坏里氏替换（参数含义完全不同）。

    子类只要把公告映射成 `MarketEvent` 即可，监控器不关心它怎么映射。
    """

    name: str = "notice_base"
    event_type: str = "notice_generic"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    @abstractmethod
    def evaluate(self, notices: Sequence[dict], code: str = "",
                 name: str = "") -> list[MarketEvent]:
        ...

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name}>"


class NoticeEventRule(NoticeRule):
    """把「重大公司事件」类公告变成事件。

    输出粒度是 **（类别, 公告日）**：同一天同类的多条公告合并成一条事件，
    数量写进 `value`，标题拼进 `detail`。这样做有两个好处：

      - 事件表不刷屏（一次年报会附 10+ 条相关公告）
      - 与 event 表的唯一键 `(code, event_type, trade_date, rule_name)` 天然一致

    类别表在 `domain/notices.py`，87 种公告类型 -> 11 个类别（8 类构成事件）；
    程序性公告（法律意见书、议事规则…）显式排除，不产生事件。
    """

    name = "notice_event"

    def __init__(self, min_severity: str = "low",
                 include: Optional[Sequence[str]] = None,
                 exclude: Optional[Sequence[str]] = None,
                 max_titles: int = 3, enabled: bool = True):
        super().__init__(enabled)
        self.min_severity = min_severity if min_severity in _SEVERITY_ORDER else "low"
        self.include = set(include) if include else None
        self.exclude = set(exclude or ())
        self.max_titles = max_titles

    def evaluate(self, notices: Sequence[dict], code: str = "",
                 name: str = "") -> list[MarketEvent]:
        if not self.enabled or not notices:
            return []

        floor = _SEVERITY_ORDER[self.min_severity]
        grouped: dict = {}
        for n in notices:
            cat = classify_notice(n.get("notice_type") or "", n.get("title") or "")
            if cat is None or not cat.material:
                continue                                  # 程序性公告不构成事件
            if self.include is not None and cat.key not in self.include:
                continue
            if cat.key in self.exclude:
                continue
            if _SEVERITY_ORDER.get(cat.severity, 0) < floor:
                continue
            day = (n.get("published_at") or "")[:10]
            if not day:
                continue
            grouped.setdefault((cat.event_type, day, cat), []).append(n)

        out = []
        for (event_type, day, cat), items in grouped.items():
            titles = [clean_title(str(i.get("title") or ""), str(i.get("name") or ""))
                      for i in items]
            titles = [t for t in titles if t]
            head = titles[0] if titles else cat.label
            detail = f"{cat.label}：{head}"
            if len(items) > 1:
                more = "；".join(t for t in titles[1:self.max_titles] if t)
                detail += f"（同日同类共 {len(items)} 条" + (f"：{more}" if more else "") + "）"
            url = next((i.get("url") for i in items if i.get("url")), None)
            out.append(MarketEvent(
                code=code, name=name, event_type=event_type, trade_date=day,
                detected_at=self._now(), severity=cat.severity,
                value=float(len(items)), threshold=None,
                detail=detail, rule_name=self.name, source_url=url))
        out.sort(key=lambda e: e.trade_date, reverse=True)
        return out
