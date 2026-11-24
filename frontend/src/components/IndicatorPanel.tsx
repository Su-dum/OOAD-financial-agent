/** 指标面板：展示后端算好的指标。前端不重算，只格式化。 */
import { Indicator } from "../models";

interface Props {
  indicator: Indicator;
  onRefreshFinancials?: () => void;
  refreshingFinancials?: boolean;
}

export function IndicatorPanel({ indicator, onRefreshFinancials,
                                refreshingFinancials }: Props) {
  const i = indicator;
  const d = i.dto;
  const pct = (v: number | null) =>
    v === null || v === undefined ? "—" : `${v.toFixed(2)}%`;
  const rows: [string, string][] = [
    ["区间", `${d.start} ~ ${d.end}`],
    ["累计收益", i.totalReturnText],
    ["年化波动率", i.volatilityText],
    ["最大回撤", i.maxDrawdownText],
    ["回撤区间", `${d.max_drawdown_peak ?? "—"} → ${d.max_drawdown_trough ?? "—"}`],
    ["夏普 / 索提诺", `${i.sharpeText} / ${Indicator.num(d.sortino, 3)}`],
    ["胜率", Indicator.pct(d.win_rate)],
    ["PE(TTM) / 分位", `${i.peText} / ${Indicator.pct(d.pe_ttm_percentile, 0)}`],
    ["PB / 分位", `${Indicator.num(d.pb)} / ${Indicator.pct(d.pb_percentile, 0)}`],
    ["ROE / 净利润增速", `${Indicator.num(d.roe)} / ${Indicator.num(d.profit_growth)}`],
    ["毛利率 / 净利率", `${pct(d.gross_margin)} / ${pct(d.net_margin)}`],
    ["资产负债率 / EPS", `${pct(d.debt_ratio)} / ${Indicator.num(d.eps)}`],
    ["营收增速", `${Indicator.num(d.revenue_growth)}%`],
  ];

  return (
    <section className="panel">
      <header>
        <h2>{i.displayName}</h2>
        <span className="badge">{d.industry_l1 || "未分类"}</span>
        {d.financial_report_date && (
          <span className="badge">
            财务 {d.financial_report_date}
            {d.financial_source ? ` · ${d.financial_source}` : ""}
          </span>
        )}
        {onRefreshFinancials && (
          <button className="ghost small" disabled={refreshingFinancials}
                  onClick={onRefreshFinancials}
                  title="从新浪财务指标接口重新抓取最近一期定期报告">
            {refreshingFinancials ? "更新中…" : "更新财务"}
          </button>
        )}
      </header>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <footer className="provenance">数据口径：{i.provenance}</footer>
    </section>
  );
}
