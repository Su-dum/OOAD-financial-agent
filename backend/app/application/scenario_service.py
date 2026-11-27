# -*- coding: utf-8 -*-
"""情景分析服务（D4，应用层）。

用户改假设 -> 重算风险指标。输入是**组合**（标的 + 权重），
输出是「基线 vs 压力」的对照 + 每只标的的贡献 + 历史最差窗口。

四类假设：

| 假设 | 参数 | 影响 |
|---|---|---|
| 市场冲击 | `market_shock` = -0.10 | 组合收益 ≈ Σ w_i·β_i·s（一次性） |
| 波动率倍数 | `vol_multiplier` = 1.5 | 协方差矩阵整体乘 k²，VaR/ES 同比放大 |
| 相关性压力 | `correlation_stress` = 0.8 | 相关性向 1 靠拢（危机时一起跌），组合波动上升 |
| 直接回撤 | `drawdown` = -0.15 | 组合直接承受该回撤（压力测试口径） |

为什么「市场冲击」走 β 而不是直接加在每只票上：
    β 来自历史回归，能把「同涨同跌」的暴露量化出来；没有基准时退回 β=1，
    并在 `notes` 里明说，而不是假装算过。
"""
from datetime import datetime, timedelta
from typing import Optional, Sequence

from ..core import indicators as ind
from ..core import scenario as sc


class ScenarioError(ValueError):
    """假设/参数不合法（接口层转 400）。"""


class ScenarioService:
    def __init__(self, cross, catalog=None, benchmark_symbol: str = "sh000300",
                 log=print):
        self.cross = cross              # CrossAssetAnalyzer（复用取数/对齐/基准）
        self.catalog = catalog
        self.benchmark_symbol = benchmark_symbol
        self.log = log

    # ---------------- 入口 ----------------
    def run(self, codes: Sequence[str], weights: Optional[Sequence[float]] = None,
            start: Optional[str] = None, end: Optional[str] = None,
            market_shock: float = -0.10, vol_multiplier: float = 1.5,
            correlation_stress: float = 0.5,
            drawdown: Optional[float] = None, horizon_days: int = 20,
            benchmark: Optional[str] = None,
            source: Optional[str] = None) -> dict:
        """source：优先数据源（"sina" 更快；None 走默认降级链）。"""
        codes = self._clean_codes(codes)
        self._validate(market_shock, vol_multiplier, correlation_stress,
                       drawdown, horizon_days)
        start, end = self._range(start, end)
        symbol = self.benchmark_symbol if benchmark is None else benchmark
        weights_in = list(weights) if weights else None
        if weights_in is not None and len(weights_in) != len(codes):
            raise ScenarioError("weights 数量必须与 codes 一致")

        series = self.cross.fetch(codes, start, end, source=source)
        if len(series) < 1:
            raise ScenarioError("所选标的没有可用行情（可能被限流或区间太短）")
        dates, aligned = self.cross.align(series)
        if len(dates) < 5:
            raise ScenarioError(f"共同交易日太少（{len(dates)} 天），无法做情景分析")

        found = list(aligned.keys())
        weights = sc.normalize_weights(weights_in, n=len(found))
        returns = {c: ind.daily_returns(aligned[c]) for c in found}

        bench = (self.cross.benchmark_aligned(symbol, dates, start, end)
                 if symbol else None)
        bench_rets = ind.daily_returns(bench["closes"]) if bench else None

        # ---- 逐标的统计 ----
        asset_rows = []
        betas = []
        for i, code in enumerate(found):
            rets = returns[code]
            beta = (ind.beta(rets, bench_rets)
                    if bench_rets is not None else None)
            betas.append(beta)
            asset_rows.append(dict(
                code=code,
                name=self._name_of(code),
                is_industry=(self.cross.is_industry_code(code)
                             if hasattr(self.cross, "is_industry_code") else False),
                weight=round(weights[i], 6),
                beta=None if beta is None else round(beta, 4),
                annualized_volatility=_round(sc.annualized_volatility(rets)),
                impact=None,
                contribution=None,
                stressed_volatility=None,
            ))

        # ---- 基线组合 ----
        port_rets = sc.portfolio_series(weights, [returns[c] for c in found])
        cov = sc.covariance_matrix([returns[c] for c in found])
        mu_p = sc.mean(port_rets) or 0.0
        vol_p = sc.portfolio_volatility(weights, cov)
        beta_p = (ind.beta(port_rets, bench_rets)
                  if bench_rets is not None else None)
        baseline = dict(
            annualized_return=_round(sc.annualized_return(port_rets)),
            annualized_volatility=_round(sc.annualized_volatility(port_rets)),
            beta=None if beta_p is None else round(beta_p, 4),
            max_drawdown=_round(sc.max_drawdown_from_returns(port_rets)),
            var_1d_95=_round(sc.parametric_var(mu_p, vol_p or 0.0, 0.95)),
            var_1d_99=_round(sc.parametric_var(mu_p, vol_p or 0.0, 0.99)),
            es_1d_95=_round(sc.expected_shortfall(mu_p, vol_p or 0.0, 0.95)),
        )
        baseline["var_horizon_95"] = _round(sc.parametric_var(
            mu_p * horizon_days, (vol_p or 0.0) * (horizon_days ** 0.5), 0.95))

        # ---- 压力后组合 ----
        cov_s = sc.stress_covariance(cov, vol_multiplier=vol_multiplier,
                                     corr_stress=correlation_stress)
        vol_s = sc.portfolio_volatility(weights, cov_s)
        stressed = dict(
            annualized_volatility=_round((vol_s or 0.0) * (sc.TRADING_DAYS ** 0.5)),
            var_1d_95=_round(sc.parametric_var(mu_p, vol_s or 0.0, 0.95)),
            var_1d_99=_round(sc.parametric_var(mu_p, vol_s or 0.0, 0.99)),
            es_1d_95=_round(sc.expected_shortfall(mu_p, vol_s or 0.0, 0.95)),
        )
        stressed["var_horizon_95"] = _round(sc.parametric_var(
            mu_p * horizon_days, (vol_s or 0.0) * (horizon_days ** 0.5), 0.95))

        # ---- 市场冲击：按 β 传导 ----
        fallback_beta = bench_rets is None
        for i, row in enumerate(asset_rows):
            b = betas[i] if betas[i] is not None else 1.0
            impact = b * market_shock
            row["impact"] = _round(impact)
            row["contribution"] = _round(weights[i] * impact)
            row["stressed_volatility"] = _round(
                (sc.volatilities(cov_s)[i] if cov_s else 0.0) * (sc.TRADING_DAYS ** 0.5))
        portfolio_impact = sum(r["contribution"] or 0.0 for r in asset_rows)
        stressed["portfolio_impact"] = _round(portfolio_impact)
        stressed["drawdown_impact"] = _round(drawdown) if drawdown is not None else None

        # ---- 情景点估计：冲击与回撤**叠成一条** ----
        # 这两个是"某一种情形的具体数"，与上面 VaR/波动（分布法）性质不同，
        # 并列展示但不互相替代：分布法回答"通常能亏多少"，点估计回答"这种情形亏多少"。
        total_impact = sc.combine_impacts(portfolio_impact, drawdown)
        stressed["total_impact"] = _round(total_impact)
        # 回本需涨幅：亏 20% 要涨 25%，亏 50% 要涨 100%
        stressed["recovery_gain"] = _round(sc.recovery_gain(total_impact))
        stressed["recovery_gain_drawdown"] = _round(sc.recovery_gain(drawdown))

        # ---- 历史重放（最差窗口） ----
        replay = sc.worst_rolling_window(
            [returns[c] for c in found], weights, horizon_days, dates=dates[1:])
        replay_out = None
        if replay is not None:
            replay_out = dict(
                window_start=replay.get("window_start"),
                window_end=replay.get("window_end"),
                portfolio_return=_round(replay["portfolio_return"]),
                assets=[{"code": found[i], "name": asset_rows[i]["name"],
                         "return": _round(replay["asset_returns"][i])}
                        for i in range(len(found))],
            )

        notes = []
        if fallback_beta:
            notes.append("基准指数不可用，市场冲击按 β=1 直接传导到每只标的")
        if weights_in is not None and any(w < 0 for w in weights_in):
            notes.append("负权重（做空）已按 0 处理")
        if drawdown is not None:
            notes.append(
                "「情景合计影响」= (1+冲击传导)×(1+直接回撤)−1，按「先冲击后回撤」"
                "复利叠加（不是相加）；若你的回撤已包含冲击，请取消勾选避免重复计算")
            notes.append(
                "「回本需涨幅」= |损失| / (1−|损失|)：亏 20% 需涨 25%，亏 50% 需涨 100%")
        if total_impact <= -0.99 + 1e-9:
            notes.append("情景跌幅触及 100% 下限，已按 −99% 处理")
        notes.append("冲击与回撤是情景点估计，与 VaR/波动（分布法）并列、不互相替代："
                     "前者答「这种情形亏多少」，后者答「通常能亏多少」")
        notes.append("市场冲击为一次性事件，按 β 线性传导；不构成投资建议")
        notes.append("VaR/ES 为参数法（正态假设），尾部极端行情会比估计更差")

        return dict(
            start=dates[0], end=dates[-1], n_days=len(dates),
            horizon_days=horizon_days,
            benchmark=dict(symbol=symbol,
                           name=(bench or {}).get("name") or symbol,
                           available=bench is not None),
            assumptions=dict(market_shock=market_shock,
                            vol_multiplier=vol_multiplier,
                            correlation_stress=correlation_stress,
                            drawdown=drawdown,
                            horizon_days=horizon_days),
            weights={c: round(weights[i], 6) for i, c in enumerate(found)},
            baseline=baseline, stressed=stressed,
            assets=asset_rows,
            historical_replay=replay_out,
            notes=notes,
        )

    # ---------------- 校验 ----------------
    def _name_of(self, code: str) -> str:
        """标的名称：优先走 cross 的元信息（它认行业代码），再退回目录。"""
        if hasattr(self.cross, "meta_of"):
            try:
                name = (self.cross.meta_of(code) or {}).get("name") or ""
                if name:
                    return name
            except Exception:                         # noqa: BLE001
                pass
        return self.catalog.name_of(code) if self.catalog else ""

    @staticmethod
    def _clean_codes(codes: Sequence[str]) -> list[str]:
        out = []
        for c in codes or ():
            c = str(c).strip().split(".")[0]
            if c and c not in out:
                out.append(c)
        if len(out) < 2:
            raise ScenarioError("至少需要 2 个标的（单标的请用 β=1 直接冲击）")
        if len(out) > 8:
            raise ScenarioError("标的数量最多 8 个")
        return out

    @staticmethod
    def _validate(market_shock, vol_multiplier, correlation_stress,
                  drawdown, horizon_days) -> None:
        if not -0.5 <= market_shock <= 0.5:
            raise ScenarioError("market_shock 必须在 [-0.5, 0.5] 之间")
        if not 0.2 <= vol_multiplier <= 5.0:
            raise ScenarioError("vol_multiplier 必须在 [0.2, 5] 之间")
        if not 0.0 <= correlation_stress <= 1.0:
            raise ScenarioError("correlation_stress 必须在 [0, 1] 之间")
        if drawdown is not None and not -0.6 <= drawdown <= 0.0:
            raise ScenarioError("drawdown 必须在 [-0.6, 0] 之间")
        if not 1 <= int(horizon_days) <= 250:
            raise ScenarioError("horizon_days 必须在 [1, 250] 之间")

    @staticmethod
    def _range(start: Optional[str], end: Optional[str]) -> tuple:
        end_d = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
        start_d = (datetime.strptime(start, "%Y-%m-%d") if start
                   else end_d - timedelta(days=365))
        if start_d >= end_d:
            raise ScenarioError("start 必须早于 end")
        return start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")


def _round(v, digits: int = 6):
    if v is None:
        return None
    return round(float(v), digits)
