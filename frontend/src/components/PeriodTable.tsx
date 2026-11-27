/** 跨期比较表：任务结果与「跨期对比」面板共用（A3 字段对等）。 */
import { PeriodRowDTO } from "../models";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`;
const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(d);

export function PeriodTable({ rows }: { rows: PeriodRowDTO[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>区间</th>
            <th>实际区间</th>
            <th>交易日</th>
            <th>累计收益</th>
            <th>年化收益</th>
            <th>年化波动</th>
            <th>最大回撤</th>
            <th>夏普</th>
            <th>胜率</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={`${p.period}-${p.start}-${p.end}`}>
              <td>{p.period}</td>
              <td className="muted">{p.start?.slice(2)} ~ {p.end?.slice(2)}</td>
              <td>{p.n_days || "—"}</td>
              <td>{pct(p.total_return)}</td>
              <td>{pct(p.annualized_return)}</td>
              <td>{pct(p.annualized_volatility)}</td>
              <td>{pct(p.max_drawdown)}</td>
              <td>{num(p.sharpe)}</td>
              <td>{pct(p.win_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
