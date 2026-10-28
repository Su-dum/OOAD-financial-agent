/** 指标面板：展示后端算好的指标。前端不重算，只格式化。 */
import { Indicator } from "../models";

export function IndicatorPanel({ indicator }: { indicator: Indicator }) {
  const i = indicator;
  const rows: [string, string][] = [
    ["区间", `${i.dto.start} ~ ${i.dto.end}`],
    ["累计收益", i.totalReturnText],
    ["年化波动率", i.volatilityText],
    ["最大回撤", i.maxDrawdownText],
    ["回撤区间", `${i.dto.max_drawdown_peak ?? "—"} → ${i.dto.max_drawdown_trough ?? "—"}`],
    ["夏普 / 索提诺", `${i.sharpeText} / ${Indicator.num(i.dto.sortino, 3)}`],
    ["胜率", Indicator.pct(i.dto.win_rate)],
    ["PE(TTM) / 分位", `${i.peText} / ${Indicator.pct(i.dto.pe_ttm_percentile, 0)}`],
    ["PB / 分位", `${Indicator.num(i.dto.pb)} / ${Indicator.pct(i.dto.pb_percentile, 0)}`],
    ["ROE / 净利润增速", `${Indicator.num(i.dto.roe)} / ${Indicator.num(i.dto.profit_growth)}`],
  ];

  return (
    <section className="panel">
      <header>
        <h2>{i.displayName}</h2>
        <span className="badge">{i.dto.industry_l1 || "未分类"}</span>
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
