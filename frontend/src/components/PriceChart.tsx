/**
 * 价格走势图（C3：charts）。
 *
 * 刻意**手写 SVG**，不引图表库：
 *   - 数据量小（后端已抽样到 ≤400 点），引库收益不大
 *   - 不用多一个依赖，构建更快，样式能和现有 CSS 变量体系一致
 *   - 可以精准把「事件」画在发生的那一天（这是本项目的重点，不是通用图表需求）
 *
 * 图分为上下两区：上 72% 画收盘价折线 + 事件标注，下 28% 画成交量柱。
 * 事件点按 severity 着色，鼠标悬停显示事件详情（<title> 原生 tooltip）。
 */
import { MarketEvent, Series } from "../models";

const PAD = { l: 54, r: 16, t: 14, b: 26 };
const W = 780;

const COLORS = {
  line: "#4f8cff",
  areaTop: "rgba(79,140,255,0.28)",
  areaBottom: "rgba(79,140,255,0.02)",
  grid: "#262b36",
  axis: "#8b93a7",
  volume: "#2f3a4d",
  high: "#ff5b5b",
  medium: "#ffa63d",
  low: "#5bd68b",
};

type Pt = { date: string; close: number; volume: number | null };

function scaleX(i: number, n: number, innerW: number): number {
  return PAD.l + (n <= 1 ? 0 : (i / (n - 1)) * innerW);
}

function fmtDate(d: string): string {
  return d.length >= 10 ? d.slice(5) : d;          // MM-DD
}

function niceTicks(min: number, max: number, count: number): number[] {
  if (!isFinite(min) || !isFinite(max) || min === max) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + step * i);
}

/** 成交量单位自适应：指数是「万股/亿股」量级，个股是「万手」量级。 */
function fmtVolume(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(1)} 亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)} 万`;
  return v.toFixed(0);
}

export function PriceChart({
  series,
  events,
  height = 280,
}: {
  series: Series;
  events: MarketEvent[];
  height?: number;
}) {
  const pts: Pt[] = series.points;
  if (pts.length < 2) {
    return <p className="empty">该区间点数太少，无法绘制走势图。</p>;
  }

  const H = height;
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const priceH = innerH * 0.72;
  const volTop = PAD.t + priceH + 10;
  const volH = innerH - priceH - 10;

  const closes = pts.map((p) => p.close);
  const minP = Math.min(...closes);
  const maxP = Math.max(...closes);
  const pad = (maxP - minP) * 0.08 || Math.max(0.5, maxP * 0.01);
  const yMin = minP - pad;
  const yMax = maxP + pad;

  const yPrice = (v: number) =>
    PAD.t + (1 - (v - yMin) / (yMax - yMin || 1)) * priceH;

  const maxVol = Math.max(...pts.map((p) => p.volume ?? 0), 1);

  const linePath = pts
    .map((p, i) => `${i === 0 ? "M" : "L"}${scaleX(i, pts.length, innerW).toFixed(2)},${yPrice(p.close).toFixed(2)}`)
    .join(" ");
  const areaPath =
    `${linePath} L${scaleX(pts.length - 1, pts.length, innerW).toFixed(2)},${(PAD.t + priceH).toFixed(2)}` +
    ` L${PAD.l.toFixed(2)},${(PAD.t + priceH).toFixed(2)} Z`;

  const priceTicks = niceTicks(yMin, yMax, 4);
  const volTicks = [maxVol];

  // 事件定位：找不到精确交易日的，落到最近的交易日
  const nearestIndex = (date: string): number => {
    let lo = 0;
    let hi = pts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (pts[mid].date < date) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  };
  const first = pts[0].date;
  const last = pts[pts.length - 1].date;
  const marks = events
    .filter((e) => e.dto.trade_date >= first && e.dto.trade_date <= last)
    .slice(0, 60)
    .map((e) => {
      const i = nearestIndex(e.dto.trade_date);
      return {
        x: scaleX(i, pts.length, innerW),
        y: yPrice(pts[i].close),
        color: COLORS[e.dto.severity] ?? COLORS.low,
        title: `${e.dto.trade_date} ${e.label}｜${e.dto.detail}`,
        notice: e.isNotice,
      };
    });

  const periodReturn = series.periodReturn;
  const up = (periodReturn ?? 0) >= 0;

  return (
    <figure className="chart">
      <figcaption>
        <span className="chart-title">
          {series.dto.name || series.dto.code} 收盘价
        </span>
        <span className={up ? "delta up" : "delta down"}>
          {periodReturn === null ? "—" : `${(periodReturn * 100).toFixed(2)}%`}
        </span>
        <span className="muted">{series.provenance}</span>
      </figcaption>

      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`${series.dto.code} 收盘价走势`} className="price-chart">
        <defs>
          <linearGradient id="priceArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS.areaTop} />
            <stop offset="100%" stopColor={COLORS.areaBottom} />
          </linearGradient>
        </defs>

        {/* 价格区网格与刻度 */}
        {priceTicks.map((v) => (
          <g key={`pt-${v}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={yPrice(v)} y2={yPrice(v)}
                  stroke={COLORS.grid} strokeWidth="1" />
            <text x={PAD.l - 8} y={yPrice(v) + 4} textAnchor="end"
                  fill={COLORS.axis} fontSize="11">{v.toFixed(1)}</text>
          </g>
        ))}

        <path d={areaPath} fill="url(#priceArea)" />
        <path d={linePath} fill="none" stroke={COLORS.line} strokeWidth="1.8"
              strokeLinejoin="round" strokeLinecap="round" />

        {/* 成交量柱 */}
        <line x1={PAD.l} x2={W - PAD.r} y1={volTop + volH} y2={volTop + volH}
              stroke={COLORS.grid} />
        {pts.map((p, i) => {
          const h = volH * ((p.volume ?? 0) / maxVol);
          const bw = Math.max(1, innerW / pts.length - 0.6);
          return (
            <rect key={`v-${p.date}`}
                  x={scaleX(i, pts.length, innerW) - bw / 2}
                  y={volTop + volH - h} width={bw} height={Math.max(0.5, h)}
                  fill={COLORS.volume} />
          );
        })}
        {volTicks.map((v) => (
          <text key={`vt-${v}`} x={W - PAD.r} y={volTop + 10} textAnchor="end"
                fill={COLORS.axis} fontSize="10">
            成交量上限 {fmtVolume(v)}
          </text>
        ))}

        {/* 事件标注 */}
        {marks.map((m, i) => (
          <g key={`m-${i}`}>
            <circle cx={m.x} cy={m.y} r={m.notice ? 3.6 : 3}
                    fill={m.color} stroke="#0f1115" strokeWidth="1">
              <title>{m.title}</title>
            </circle>
          </g>
        ))}

        {/* X 轴日期（只标 5 个，避免拥挤） */}
        {Array.from({ length: 5 }, (_, k) => {
          const idx = Math.round((k / 4) * (pts.length - 1));
          return (
            <text key={`xt-${k}`} x={scaleX(idx, pts.length, innerW)}
                  y={H - 8} textAnchor="middle" fill={COLORS.axis} fontSize="10">
              {fmtDate(pts[idx].date)}
            </text>
          );
        })}
      </svg>

      <div className="chart-legend">
        <span className="muted">区间 {series.dto.start} ~ {series.dto.end}</span>
        <span className="muted">最低 {minP.toFixed(2)} · 最高 {maxP.toFixed(2)}</span>
        <span className="muted">事件 {marks.length} 个（点悬停可看详情）</span>
      </div>
    </figure>
  );
}
