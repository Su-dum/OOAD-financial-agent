# -*- coding: utf-8 -*-
"""预警规则配置服务（应用层）。

把「规则是什么」与「规则参数是多少」分开：

    领域层  ThresholdRule(drop, surge) / VolumeSpikeRule(window, multiple) / ...
    本服务    从配置读出参数，**构造**出这些规则对象

这样 C1 的「用户可配置预警条件」只是「让本服务读配置」，
`EventMonitor` / 规则类一行都不用改。

## 两级配置

    alert_rule(code='')       全局默认
    alert_rule(code='600519') 个股覆盖

读取时按「默认 -> 全局 -> 个股」逐层覆盖。用户改一只票的阈值，
不会影响其它票；想改全体就把 code 传空。

## 为什么要做参数校验

阈值是可以把系统搞坏的东西：`drop=0` 会让「任何下跌」都成事件，
`z=0` 会让每天的波动都成异常。所以每个参数都有**上下界**，
越界直接拒绝（而不是静默钳制），让用户知道配置没生效。
"""
from typing import Optional, Sequence

from ..domain.events import (AlertRule, NoticeEventRule, NoticeRule,
                             ThresholdRule, VolumeSpikeRule, ZScoreRule)

# 规则类型的默认参数（与 EventMonitor.default 的出厂值一致）
DEFAULT_RULES: dict = {
    "threshold_pct_change": dict(drop=-0.05, surge=0.05),
    "volume_spike": dict(window=20, multiple=2.5),
    "zscore": dict(window=60, z=3.0),
    "notice_event": dict(min_severity="low"),
}

LABELS: dict = {
    "threshold_pct_change": "单日涨跌幅阈值",
    "volume_spike": "成交量放大倍数",
    "zscore": "收益率统计异常 z 值",
    "notice_event": "公告事件最小级别",
}

# 参数上下界（含端点）。数值型一律给 (min, max)。
BOUNDS: dict = {
    "threshold_pct_change": {"drop": (-0.30, -0.005), "surge": (0.005, 0.30)},
    "volume_spike": {"window": (5, 120), "multiple": (1.2, 10.0)},
    "zscore": {"window": (20, 250), "z": (1.5, 6.0)},
}
NOTICE_SEVERITIES = ("low", "medium", "high")


def _validate(rule_type: str, params: dict) -> dict:
    """校验并归一化参数；不合法抛 ValueError（不静默钳制）。"""
    if rule_type not in DEFAULT_RULES:
        raise ValueError(f"未知规则类型 {rule_type}，可选：{list(DEFAULT_RULES)}")
    allowed = set(DEFAULT_RULES[rule_type]) | {"include", "exclude", "enabled"}
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"规则 {rule_type} 不认识的参数 {sorted(unknown)}")

    out = dict(params)
    if rule_type == "notice_event":
        sev = out.get("min_severity", DEFAULT_RULES[rule_type]["min_severity"])
        if sev not in NOTICE_SEVERITIES:
            raise ValueError(f"min_severity 只能是 {NOTICE_SEVERITIES}")
        out["min_severity"] = sev
        for key in ("include", "exclude"):
            if key in out:
                vals = out[key]
                if not isinstance(vals, (list, tuple)):
                    raise ValueError(f"{key} 必须是字符串数组")
                out[key] = [str(v) for v in vals]
        return out

    for key, (lo, hi) in BOUNDS[rule_type].items():
        if key not in out:
            continue
        v = out[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"{rule_type}.{key} 必须是数字，收到 {v!r}")
        if not (lo <= v <= hi):
            raise ValueError(f"{rule_type}.{key} 必须在 [{lo}, {hi}] 之间，收到 {v}")
    return out


class AlertConfigService:
    def __init__(self, repo=None, defaults: Optional[dict] = None, log=print):
        self.repo = repo
        self.defaults = dict(defaults or DEFAULT_RULES)
        self.log = log

    # ---------------- 读 ----------------
    def _overrides(self, code: Optional[str]) -> dict:
        """{(code, rule_type): row}，code='' 为全局。"""
        if self.repo is None:
            return {}
        out = {}
        for row in self.repo.load(code):
            out[(row["code"], row["rule_type"])] = row
        return out

    def describe(self, code: Optional[str] = None) -> list[dict]:
        """给接口/前端：每个规则类型的生效值 + 来源（default/global/code）。"""
        c = str(code).split(".")[0] if code else ""
        overrides = self._overrides(c)
        items = []
        for rule_type, default_params in self.defaults.items():
            params = dict(default_params)
            source = "default"
            enabled = True
            g = overrides.get(("", rule_type))
            if g is not None:
                params.update(g["params"])
                enabled = g["enabled"]
                source = "global"
            if c:
                o = overrides.get((c, rule_type))
                if o is not None:
                    params.update(o["params"])
                    enabled = o["enabled"]
                    source = "code"
            items.append(dict(rule_type=rule_type,
                              label=LABELS.get(rule_type, rule_type),
                              params=params,
                              defaults=dict(default_params),
                              enabled=enabled,
                              source=source,
                              bounds=BOUNDS.get(rule_type, {}),
                              is_percent=rule_type == "threshold_pct_change"))
        return items

    def effective(self, code: Optional[str] = None) -> dict:
        return {it["rule_type"]: it for it in self.describe(code)}

    # ---------------- 写 ----------------
    def update(self, rule_type: str, params: dict, code: Optional[str] = None,
               enabled: Optional[bool] = None) -> dict:
        if self.repo is None:
            raise ValueError("没有配置仓储，无法保存预警规则")
        current = self.effective(code).get(rule_type)
        if current is None:
            raise ValueError(f"未知规则类型 {rule_type}")
        merged = dict(current["params"])
        merged.update(_validate(rule_type, dict(params)))
        self.repo.upsert(rule_type, merged,
                         code=code,
                         enabled=current["enabled"] if enabled is None else enabled)
        return self.effective(code)[rule_type]

    def reset(self, rule_type: Optional[str] = None,
              code: Optional[str] = None) -> int:
        """删除个股覆盖值（或全局值），让其退回默认。"""
        if self.repo is None:
            return 0
        if rule_type:
            return 1 if self.repo.delete(rule_type, code=code) else 0
        return self.repo.reset(code=code)

    # ---------------- 构造规则对象 ----------------
    def build_price_rules(self, code: Optional[str] = None) -> list:
        cfg = self.effective(code)
        rules: list[AlertRule] = []
        t = cfg["threshold_pct_change"]
        if t["enabled"]:
            rules.append(ThresholdRule(drop=float(t["params"]["drop"]),
                                       surge=float(t["params"]["surge"])))
        v = cfg["volume_spike"]
        if v["enabled"]:
            rules.append(VolumeSpikeRule(window=int(v["params"]["window"]),
                                         multiple=float(v["params"]["multiple"])))
        z = cfg["zscore"]
        if z["enabled"]:
            rules.append(ZScoreRule(window=int(z["params"]["window"]),
                                    z=float(z["params"]["z"])))
        return rules

    def build_notice_rules(self, code: Optional[str] = None) -> list:
        cfg = self.effective(code)["notice_event"]
        if not cfg["enabled"]:
            return []
        p = cfg["params"]
        return [NoticeEventRule(min_severity=p.get("min_severity", "low"),
                                include=p.get("include"),
                                exclude=p.get("exclude"))]

    def for_code(self, code: Optional[str] = None):
        """`EventMonitor` 的规则来源：返回 (价格规则, 公告规则)。"""
        return (self.build_price_rules(code), self.build_notice_rules(code))
