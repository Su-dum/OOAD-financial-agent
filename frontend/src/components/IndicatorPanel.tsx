/** 指标面板：展示后端算好的指标。前端不重算，只格式化。 */
import { Indicator } from "../models";

interface Props {
  indicator: Indicator;
  onRefreshFinancials?: () => void;
  refreshingFinancials?: boolean;
}

/**
 * 金融业（申万一级只有这两个）没有「销售毛利率 / 销售净利率」的商贸口径，
 * 数据源对该行业整列不披露——显示「不适用」比显示「—」更诚实。
 */
const FINANCIAL_INDUSTRIES = new Set(["银行", "非银金融"]);

/** [标签, 值, 可选的原因说明]。有第 3 项时值会带上「?」并可悬浮查看原因。 */
type Row = [label: string, value: string, hint?: string];

export function IndicatorPanel({ indicator, onRefreshFinancials,
                                refreshingFinancials }: Props) {
  const i = indicator;
  const d = i.dto;
  const pct = (v: number | null) =>
    v === null || v === undefined ? "—" : `${v.toFixed(2)}%`;

  const isFinancial = FINANCIAL_INDUSTRIES.has(d.industry_l1 || "");

  // ---- 为什么 PE/PB 会是空的：估值只有 baostock 带 ----
  const valuationMissing = d.pe_ttm == null || d.pb == null;
  const valuationHint = !valuationMissing
    ? undefined
    : d.source === "baostock"
      ? "baostock 在该区间没有返回 PE / PB。"
      : `PE / PB（含历史分位）只有 baostock 源提供；当前行情源是「${d.source}」。`
        + "baostock 不可用时会自动降级到新浪 / 东财，而这两个源不带估值字段。"
        + "冷却 300 秒后链路会自动重试 baostock，恢复后重新分析即可看到。";

  // ---- 为什么毛利率/净利率会是空的：银行不披露 + 新浪不填这一列 ----
  const marginMissing = d.gross_margin == null && d.net_margin == null;
  const marginHint = !marginMissing
    ? undefined
    : isFinancial
      ? "金融业没有「销售毛利率 / 销售净利率」的商贸口径"
        + "（利润表是利息净收入 + 手续费收入 − 减值损失）。"
        + "新浪财务指标对该行业这两个字段整列不披露，属于「不适用」而非数据缺失。"
      : "新浪财务指标在最近一期报告里没给这两个字段：销售毛利率整列不填，"
        + "已顺位回退到「主营业务利润率」仍为空。可点「更新财务」重试。";

  const marginText = isFinancial && marginMissing
    ? "不适用（金融业）"
    : `${pct(d.gross_margin)} / ${pct(d.net_margin)}`;

  const rows: Row[] = [
    ["区间", `${d.start} ~ ${d.end}`],
    ["累计收益", i.totalReturnText],
    ["年化波动率", i.volatilityText],
    ["最大回撤", i.maxDrawdownText],
    ["回撤区间", `${d.max_drawdown_peak ?? "—"} → ${d.max_drawdown_trough ?? "—"}`],
    ["夏普 / 索提诺", `${i.sharpeText} / ${Indicator.num(d.sortino, 3)}`],
    ["胜率", Indicator.pct(d.win_rate)],
    ["PE(TTM) / 分位", `${i.peText} / ${Indicator.pct(d.pe_ttm_percentile, 0)}`, valuationHint],
    ["PB / 分位", `${Indicator.num(d.pb)} / ${Indicator.pct(d.pb_percentile, 0)}`, valuationHint],
    ["ROE / 净利润增速", `${Indicator.num(d.roe)} / ${Indicator.num(d.profit_growth)}`],
    ["毛利率 / 净利率", marginText, marginHint],
    ["资产负债率 / EPS", `${pct(d.debt_ratio)} / ${Indicator.num(d.eps)}`],
    ["每股净资产 BPS", `${Indicator.num(d.bps)} 元`],
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
        {rows.map(([k, v, hint]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className={hint ? "has-hint" : undefined} title={hint}>
              {v}
              {hint && (
                <span className="hint-mark" aria-hidden="true">?</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <footer className="provenance">数据口径：{i.provenance}</footer>
    </section>
  );
}
