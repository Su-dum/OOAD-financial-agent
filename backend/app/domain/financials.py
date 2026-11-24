# -*- coding: utf-8 -*-
"""财务快照（A1：financial data）。

行情是日频、财务是**季频**，两者时间粒度不同（见 `docs/data-lifecycle.md`）。
财务指标来自交易所披露的定期报告，一只票一年只有 4 个数据点，
所以这里用「快照」而不是「序列」：

    FinancialSnapshot  = 最近一期定期报告的关键指标
    更新频率            = 手动 / 刷新时按 TTL（默认 7 天）补一次

## 单位约定（很重要）

行情类指标（收益、波动、回撤）在项目里一律是**小数**（0.12 = 12%），
而财务指标沿用数据源口径，是**百分数本身**（36.99 表示 36.99%），
与 `IndicatorSet.roe` 的既有语义一致（前端不再乘 100）。
同一个字段只有一种口径，不允许两套。
"""
from dataclasses import dataclass, asdict
from typing import Optional

# 参与计算/展示的字段（顺序即前端展示顺序）
FIELDS = ("roe", "net_profit_growth", "revenue_growth", "net_margin",
          "gross_margin", "debt_ratio", "eps", "bps")

LABELS = {
    "roe": "净资产收益率(%)",
    "net_profit_growth": "净利润增长率(%)",
    "revenue_growth": "营收增长率(%)",
    "net_margin": "销售净利率(%)",
    "gross_margin": "销售毛利率(%)",
    "debt_ratio": "资产负债率(%)",
    "eps": "每股收益(元)",
    "bps": "每股净资产(元)",
    "report_date": "报告期",
}

DESCRIPTIONS = {
    "roe": "最近一期定期报告的净资产收益率，反映股东资金的使用效率",
    "net_profit_growth": "归母净利润同比增速",
    "revenue_growth": "主营业务收入同比增速",
    "net_margin": "销售净利率 = 净利润 / 营业收入",
    "gross_margin": "销售毛利率（部分数据源缺失时为空）",
    "debt_ratio": "资产负债率，衡量财务杠杆",
    "eps": "摊薄每股收益",
    "bps": "每股净资产",
}


@dataclass(frozen=True)
class FinancialSnapshot:
    """最近一期财务快照。数值单位见模块 docstring。"""

    code: str
    report_date: str
    roe: Optional[float] = None
    net_profit_growth: Optional[float] = None
    revenue_growth: Optional[float] = None
    net_margin: Optional[float] = None
    gross_margin: Optional[float] = None
    debt_ratio: Optional[float] = None
    eps: Optional[float] = None
    bps: Optional[float] = None
    source: str = ""
    fetched_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def empty(self) -> bool:
        return all(getattr(self, f) is None for f in FIELDS)

    def value_of(self, field: str):
        return getattr(self, field, None)


def describe_fields() -> list[dict]:
    """给接口 / 前端用的字段说明（名称 + 释义）。"""
    return [dict(field=f, label=LABELS[f], description=DESCRIPTIONS.get(f, ""))
            for f in FIELDS]
