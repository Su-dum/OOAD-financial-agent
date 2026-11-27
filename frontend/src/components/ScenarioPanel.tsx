/**
 * 情景分析面板（D4）。
 *
 * 用户改「假设」→ 后端重算基线与压力下的风险指标：
 *   市场冲击（基准一次性涨跌，按 β 传导）
 *   波动率倍数（恐慌/平静）
 *   相关性压力（危机时资产一起跌）
 *   直接回撤（压力测试口径，可选）
 * 同时给出**历史最差窗口**作为对照，避免只看参数法数字。
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import { ScenarioDTO } from "../models";

interface Props {
  codes: string[];
  start?: string;
  end?: string;
}

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
const pctSigned = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined
    ? "—"
    : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
const num = (v: number | null | undefined, digits = 3) =>
  v === null || v === undefined ? "—" : v.toFixed(digits);

function Slider({
  label, value, min, max, step, onChange, format, hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format: (v: number) => string;
  hint?: string;
}) {
  return (
    <label className="scenario-control">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))} />
      <b>{format(value)}</b>
      {hint && <em className="muted">{hint}</em>}
    </label>
  );
}

export function ScenarioPanel({ codes, start, end }: Props) {
  const [shock, setShock] = useState(-0.10);
  const [volMult, setVolMult] = useState(1.5);
  const [corr, setCorr] = useState(0.6);
  const [horizon, setHorizon] = useState(20);
  const [useDrawdown, setUseDrawdown] = useState(true);
  const [drawdown, setDrawdown] = useState(-0.15);

  const [data, setData] = useState<ScenarioDTO | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const key = codes.join(",");

  const run = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const got = await services.scenario.run({
        codes,
        start,
        end,
        market_shock: shock,
        vol_multiplier: volMult,
        correlation_stress: corr,
        horizon_days: horizon,
        drawdown: useDrawdown ? drawdown : null,
      });
      setData(got);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setBusy(false);
    }
  }, [codes, start, end, shock, volMult, corr, horizon, useDrawdown, drawdown]);

  // 只在标的/区间变化时自动算一次；拖滑杆后点「重算」，避免每次拖动都发请求
  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, start, end]);

  const reset = () => {
    setShock(-0.10);
    setVolMult(1.5);
    setCorr(0.6);
    setHorizon(20);
    setUseDrawdown(true);
    setDrawdown(-0.15);
  };

  return (
    <section className="panel">
      <header>
        <h2>情景分析</h2>
        <span className="badge">改假设看影响 · 组合口径</span>
        {busy && <span className="muted">计算中…</span>}
      </header>

      <div className="scenario-controls">
        <Slider label="市场冲击（一次性）" value={shock} min={-0.3} max={0.3}
                step={0.01} onChange={setShock} format={(v) => pctSigned(v, 0)}
                hint="基准涨跌按 β 传导到各标的" />
        <Slider label="波动率倍数" value={volMult} min={0.5} max={3} step={0.1}
                onChange={setVolMult} format={(v) => `×${v.toFixed(1)}`}
                hint="放大/缩小所有标的波动率" />
        <Slider label="相关性压力" value={corr} min={0} max={1} step={0.05}
                onChange={setCorr} format={(v) => v.toFixed(2)}
                hint="1 = 完全同涨同跌（危机）" />
        <Slider label="持有期" value={horizon} min={5} max={120} step={5}
                onChange={setHorizon} format={(v) => `${v} 天`}
                hint="用于持有期 VaR 与历史窗口" />
        <label className="scenario-check">
          <input type="checkbox" checked={useDrawdown}
                 onChange={(e) => setUseDrawdown(e.target.checked)} />
          施加直接回撤
        </label>
        {useDrawdown && (
          <Slider label="直接回撤" value={drawdown} min={-0.4} max={0} step={0.01}
                  onChange={setDrawdown} format={(v) => pctSigned(v, 0)}
                  hint="压力测试口径，直接作用于组合" />
        )}
      </div>

      <div className="scenario-actions">
        <button disabled={busy} onClick={() => void run()}>重算</button>
        <button className="ghost" disabled={busy} onClick={reset}>恢复默认假设</button>
        {data && (
          <span className="muted">
            组合：{data.assets.map((a) => `${a.name || a.code} ${(a.weight * 100).toFixed(0)}%`).join(" / ")}
            {" "}· {data.start} ~ {data.end}（{data.n_days} 个交易日）
          </span>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <p className="provenance" style={{ marginTop: 0 }}>
            两类指标性质不同，<b>并列但不互相替代</b>：
            「市场冲击传导 / 情景合计影响 / 回本需涨幅」是<b>特定情形的点估计</b>（这种情形亏多少）；
            「年化波动 / VaR / ES」是<b>分布法</b>，由波动率与相关性假设推出（通常能亏多少）。
          </p>
          <div className="scenario-cards">
            <div className="scenario-card">
              <span className="k">市场冲击传导</span>
              <span className={"v " + onTrack(data.stressed.portfolio_impact)}>
                {pctSigned(data.stressed.portfolio_impact)}
              </span>
              <span className="muted">
                组合 β {num(data.baseline.beta)} × 冲击 {pctSigned(data.assumptions.market_shock, 0)}
              </span>
            </div>
            <div className="scenario-card">
              <span className="k">年化波动</span>
              <span className="v">
                {pct(data.baseline.annualized_volatility)} → {pct(data.stressed.annualized_volatility)}
              </span>
              <span className="muted">基线 → 压力</span>
            </div>
            <div className="scenario-card">
              <span className="k">1 日 VaR 95%</span>
              <span className="v">{pct(data.stressed.var_1d_95)}</span>
              <span className="muted">基线 {pct(data.baseline.var_1d_95)}</span>
            </div>
            <div className="scenario-card">
              <span className="k">1 日 VaR 99%</span>
              <span className="v">{pct(data.stressed.var_1d_99)}</span>
              <span className="muted">基线 {pct(data.baseline.var_1d_99)}</span>
            </div>
            <div className="scenario-card">
              <span className="k">{data.horizon_days} 日 VaR 95%</span>
              <span className="v">{pct(data.stressed.var_horizon_95)}</span>
              <span className="muted">基线 {pct(data.baseline.var_horizon_95)}</span>
            </div>
            {useDrawdown && (
              <div className="scenario-card">
                <span className="k">情景合计影响</span>
                {/* 不着色：这是"某种情形的损失幅度"，不是行情涨跌，红绿会被误读 */}
                <span className="v">
                  {pctSigned(data.stressed.total_impact)}
                </span>
                <span className="muted">
                  冲击 {pctSigned(data.stressed.portfolio_impact)}
                  {" ⊕ "}回撤 {pctSigned(data.stressed.drawdown_impact)}
                  {" （复利，非相加）"}
                </span>
              </div>
            )}
            <div className="scenario-card">
              <span className="k">回本需涨幅</span>
              <span className="v">
                {pctSigned(data.stressed.recovery_gain)}
              </span>
              <span className="muted">
                {useDrawdown
                  ? `从 ${pctSigned(data.stressed.total_impact)} 回到原点`
                  : "仅市场冲击（未施加回撤）"}
              </span>
            </div>
          </div>

          <h3>逐标的贡献</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>标的</th><th>权重</th><th>β</th>
                  <th>单标的冲击</th><th>对组合贡献</th><th>压力后波动</th>
                </tr>
              </thead>
              <tbody>
                {data.assets.map((a) => (
                  <tr key={a.code}>
                    <td><b>{a.code}</b> {a.name}</td>
                    <td>{pct(a.weight, 1)}</td>
                    <td>{num(a.beta)}</td>
                    <td className={onTrack(a.impact)}>{pctSigned(a.impact)}</td>
                    <td className={onTrack(a.contribution)}>{pctSigned(a.contribution)}</td>
                    <td>{pct(a.stressed_volatility)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.historical_replay && (
            <>
              <h3>历史最差窗口（{data.horizon_days} 个交易日，买入持有）</h3>
              <p>
                {data.historical_replay.window_start} ~ {data.historical_replay.window_end}
                ：组合 <b className={onTrack(data.historical_replay.portfolio_return)}>
                  {pctSigned(data.historical_replay.portfolio_return)}
                </b>
                {" "}（{data.historical_replay.assets.map((a) =>
                  `${a.name || a.code} ${pctSigned(a.return)}`).join("，")}）
              </p>
            </>
          )}

          <ul className="scenario-notes">
            {data.notes.map((n, i) => <li key={i} className="muted">{n}</li>)}
          </ul>
        </>
      )}

      {!data && !busy && !error && (
        <p className="empty">选择标的与假设，点「重算」查看对组合的影响。</p>
      )}
    </section>
  );
}

function onTrack(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  return v >= 0 ? "up" : "down";
}
