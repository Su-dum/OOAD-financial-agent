# -*- coding: utf-8 -*-
"""新浪财务指标适配器（满足 domain.ports.FinancialProvider）。

数据来源：`stock_financial_analysis_indicator`（akshare 封装的新浪财务指标，
实测 86 列）。探针 `scripts/probes/01_core_coverage.py` 早已验证可用，
这里把它封装成 8 个真正用得到的字段——**不是把 86 列原样扔给上层**：

    净资产收益率 / 净利润增长率 / 营收增长率 / 销售净利率 /
    销售毛利率 / 资产负债率 / 每股收益 / 每股净资产

## 列名是中文，且不同报告期可能缺列

所以用「候选列名 + 缺列跳过」的方式读取（见 `_COLUMNS`），
任何一个字段缺了只影响它自己，不影响整条快照。
"""
import math
from datetime import datetime
from typing import Optional

from .akshare_compat import call as akcall
from ...domain.financials import FinancialSnapshot

# 字段 -> 候选列名（按优先级）
_COLUMNS = {
    "roe": ("净资产收益率(%)", "加权净资产收益率(%)", "总资产净利润率(%)"),
    "net_profit_growth": ("净利润增长率(%)", "扣除非经常性损益后的净利润增长率(%)"),
    "revenue_growth": ("主营业务收入增长率(%)",),
    "net_margin": ("销售净利率(%)",),
    "gross_margin": ("销售毛利率(%)", "主营业务利润率(%)"),
    "debt_ratio": ("资产负债率(%)",),
    "eps": ("摊薄每股收益(元)", "加权每股收益(元)", "每股收益_调整后(元)"),
    "bps": ("每股净资产_调整前(元)", "每股净资产_调整后(元)"),
}


def _num(v) -> Optional[float]:
    """把单元格转成 float；nan / inf / '-' / None 一律当作缺失。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def parse_financial_frame(df, code: str,
                          source: str = "sina_financial") -> Optional[FinancialSnapshot]:
    """DataFrame -> FinancialSnapshot（取最近一期报告）。

    独立成纯函数是为了能离线单测：只要给一个带正确列名的 DataFrame 即可，
    不需要联网、也不需要真的装 akshare。
    """
    if df is None or len(df) == 0:
        return None
    date_col = "日期" if "日期" in df.columns else df.columns[0]
    ordered = df.copy()
    ordered["_date"] = ordered[date_col].astype(str).str[:10]
    ordered = ordered.sort_values("_date")
    last = ordered.iloc[-1]
    report_date = str(last["_date"])[:10]
    if not report_date or report_date.lower() in ("nan", "none"):
        return None

    values = {}
    for field, candidates in _COLUMNS.items():
        for col in candidates:
            if col in df.columns:
                v = _num(last[col])
                if v is not None:
                    values[field] = v
                    break

    return FinancialSnapshot(code=str(code).split(".")[0],
                             report_date=report_date,
                             source=source,
                             fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             **values)


class SinaFinancialProvider:
    name = "sina_financial"

    def __init__(self, log=print, years: int = 3):
        self.log = log
        self.years = years

    def fetch(self, code: str, years: Optional[int] = None) -> Optional[FinancialSnapshot]:
        c = str(code).split(".")[0]
        span = years or self.years
        start_year = str(max(1990, datetime.now().year - span))
        try:
            df = akcall("stock_financial_analysis_indicator",
                        symbol=c, start_year=start_year)
        except Exception as e:                          # noqa: BLE001
            if self.log:
                self.log(f"  [financial] {c} 取数失败: {type(e).__name__} {str(e)[:80]}")
            return None
        snap = parse_financial_frame(df, c, source=self.name)
        if snap is None or snap.empty:
            if self.log:
                self.log(f"  [financial] {c} 无可用财务数据（start_year={start_year}）")
            return None
        if self.log:
            self.log(f"  [financial] {c} 报告期 {snap.report_date} "
                     f"ROE={snap.roe} 净利增速={snap.net_profit_growth}")
        return snap
