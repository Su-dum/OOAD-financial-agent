# -*- coding: utf-8 -*-
"""领域模型。

对应提案 4.4 的类设计，命名已与 UML 图统一：
  StockAsset       -> StockRef
  PriceRecord      -> PriceRecord
  FinancialIndicator -> IndicatorSet
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class StockRef:
    """一只 A 股的基本标识。"""
    code: str                       # 6 位代码，如 600519
    name: str = ""
    exchange: str = ""              # SH / SZ / BJ
    industry_l1: str = ""           # 申万一级行业

    @staticmethod
    def exchange_of(code: str) -> str:
        c = code.split(".")[0]
        if c.startswith(("60", "68", "90")):
            return "SH"
        if c.startswith(("00", "30", "20")):
            return "SZ"
        if c.startswith(("43", "83", "87", "92")):
            return "BJ"
        return ""

    @property
    def bs_code(self) -> str:
        """baostock 格式：sh.600519"""
        return f"{self.exchange_of(self.code).lower()}.{self.code}"

    @property
    def sina_code(self) -> str:
        """新浪格式：sh600519"""
        return f"{self.exchange_of(self.code).lower()}{self.code}"


@dataclass
class PriceRecord:
    """一根日线。**必须记录复权口径与数据源**，否则指标无法自证。"""
    code: str
    date: str                       # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    amount: Optional[float] = None
    turnover: Optional[float] = None
    pct_change: Optional[float] = None
    # 估值（baostock 日频直接带）
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    pcf_ttm: Optional[float] = None
    adjust: str = "qfq"             # qfq / hfq / none
    source: str = "baostock"


@dataclass
class PriceSeries:
    code: str
    records: List[PriceRecord] = field(default_factory=list)
    adjust: str = "qfq"
    source: str = "baostock"

    def __len__(self):
        return len(self.records)

    @property
    def dates(self):
        return [r.date for r in self.records]

    @property
    def closes(self):
        return [r.close for r in self.records]

    @property
    def start(self):
        return self.records[0].date if self.records else None

    @property
    def end(self):
        return self.records[-1].date if self.records else None

    @property
    def latest(self) -> Optional[PriceRecord]:
        return self.records[-1] if self.records else None


@dataclass
class IndicatorSet:
    """一次分析产出的全部指标。价格类指标全部基于同一条复权序列。"""
    code: str
    name: str = ""
    industry_l1: str = ""
    start: str = ""
    end: str = ""
    n_days: int = 0
    adjust: str = "qfq"
    source: str = "baostock"

    # ---- 收益 ----
    first_close: Optional[float] = None
    last_close: Optional[float] = None
    total_return: Optional[float] = None        # 区间累计收益
    annualized_return: Optional[float] = None   # 年化收益（几何）
    win_rate: Optional[float] = None            # 上涨交易日占比

    # ---- 风险 ----
    annualized_volatility: Optional[float] = None
    downside_deviation: Optional[float] = None
    max_drawdown: Optional[float] = None
    max_drawdown_peak: Optional[str] = None
    max_drawdown_trough: Optional[str] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None

    # ---- 估值 ----
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    pe_ttm_percentile: Optional[float] = None   # 区间内历史分位
    pb_percentile: Optional[float] = None

    # ---- 盈利与成长（来自申万映射表快照）----
    roe: Optional[float] = None
    profit_growth: Optional[float] = None
    revenue_growth: Optional[float] = None
    market_cap: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)
