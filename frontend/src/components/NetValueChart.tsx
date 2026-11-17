/**
 * 相对表现图（D3：跨资产）。
 *
 * 多条净值曲线（首日 = 100）+ 基准（沪深300）虚线。
 * 为什么用净值而不是收盘价：不同标的价位差几个数量级（茅台 1200 vs 平安 11），
 * 直接画收盘价等于把低价股压成一条平线，看不出相对强弱。
 */
import { CrossAsset } from "../models";

const PAD = { l: 46, r: 16, t: 14, b: 26 };
const W = 780;
const H = 260;
const PALETTE = ["#4f8cff", "#5bd68b", "#ffa63d", "#c084fc", "#22d3ee", "#f472b6"];
const GRID = "#262b36";
const AXIS = "#8b93a7";

function ticks(min: number, max: number, count: number): number[] {
  if (!isFinite(min) || !isFinite(max) || min === max) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + step * i);
}

export function NetValueChart({ cross }: { cross: CrossAsset }) {
  const dates = cross.dto.net_value?.dates ?? [];
  const series = cross.dto.net_value?.series ?? [];
  const bench = cross.getBenchmarkLine();
  if (dates.length < 2 || series.length === 0) {
    return <p className="empty">没有可比较的净值序列。</p>;
  }

  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const all = series.flatMap((s) => s.values).concat(bench);
  const min = Math.min(...all);
  const max = Math.max(...all);
  const pad = (max - min) * 0.08 || 1;
  const lo = min - pad;
  const hi = max + pad;

  const x = (i: number) => PAD.l + (i / (dates.length - 1)) * innerW;
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo || 1)) * innerH;

  const pathOf = (values: number[]) =>
    values
      .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(v).toFixed(2)}`)
      .join(" ");

  return (
    <figure className="chart">
      <figcaption>
        <span className="chart-title">相对表现（首日 = 100）</span>
        <span className="muted">{cross.dto.start} ~ {cross.dto.end} · {cross.dto.n_days} 个交易日</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="相对表现净值曲线"
           className="net-chart">
        {ticks(lo, hi, 4).map((v) => (
          <g key={`g-${v}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke={GRID} />
            <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end" fill={AXIS}
                  fontSize="11">{v.toFixed(0)}</text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={y(100)} y2={y(100)}
              stroke="#3b4557" strokeDasharray="3 3" />

        {bench.length > 1 && (
          <path d={pathOf(bench)} fill="none" stroke="#8b93a7" strokeWidth="1.4"
                strokeDasharray="5 4" />
        )}
        {series.map((s, k) => (
          <path key={s.code} d={pathOf(s.values)} fill="none"
                stroke={PALETTE[k % PALETTE.length]} strokeWidth="1.8"
                strokeLinejoin="round" />
        ))}

        {Array.from({ length: 5 }, (_, k) => {
          const idx = Math.round((k / 4) * (dates.length - 1));
          return (
            <text key={`x-${k}`} x={x(idx)} y={H - 8} textAnchor="middle"
                  fill={AXIS} fontSize="10">{dates[idx]?.slice(5)}</text>
          );
        })}
      </svg>

      <div className="legend-row">
        {series.map((s, k) => (
          <span key={s.code} className="legend-item">
            <i className="dot" style={{ background: PALETTE[k % PALETTE.length] }} />
            {s.name || s.code}
          </span>
        ))}
        {bench.length > 1 && (
          <span className="legend-item">
            <i className="dot dash" />
            {cross.dto.benchmark?.name ?? "基准"}
          </span>
        )}
      </div>
    </figure>
  );
}
