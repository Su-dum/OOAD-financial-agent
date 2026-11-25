/**
 * 跨资产分析面板（D3）。
 *
 * 三块内容：
 *   1. 相对表现图（净值曲线 + 基准）
 *   2. 相关性矩阵（谁和谁同涨同跌）
 *   3. 指标表（区间收益 / 波动 / 回撤 / beta / 相对基准超额）
 *
 * 数据全部来自后端一次 `/api/stocks/cross`，前端不重算——
 * 相关系数、beta、净值都要用同一批对齐后的收益率，前端算会漂移。
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import { CrossAsset } from "../models";
import { NetValueChart } from "./NetValueChart";
import { CorrelationMatrix } from "./CorrelationMatrix";

interface Props {
  /** 默认比较的标的：当前分析的股票 + 两只参照 */
  codes: string[];
  start?: string;
  end?: string;
  onError?: (msg: string) => void;
}

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`;
const num = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toFixed(3);

export function CrossPanel({ codes, start, end, onError }: Props) {
  const [input, setInput] = useState(codes.slice(0, 3).join(","));
  const [data, setData] = useState<CrossAsset | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (raw: string) => {
    const list = raw.split(",").map((s) => s.trim()).filter(Boolean);
    if (list.length < 2) {
      setError("至少输入两个代码（逗号分隔）");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const got = await services.stocks.cross(list, {
        start, end, benchmark: "sh000300", source: "sina",
      });
      setData(got);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onError?.(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [start, end, onError]);

  useEffect(() => {
    setInput(codes.slice(0, 3).join(","));
    if (codes.length >= 2) void load(codes.slice(0, 3).join(","));
  }, [codes, load]);

  return (
    <section className="panel">
      <header>
        <h2>跨资产对比</h2>
        <span className="badge">相对表现 · 相关性 · 相对沪深300</span>
        {loading && <span className="muted">计算中…</span>}
      </header>

      <div className="search">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="逗号分隔的代码，如 600519,000001,300750"
        />
        <button onClick={() => void load(input)} disabled={loading}>对比</button>
      </div>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          {data.dto.note && <p className="muted">{data.dto.note}</p>}
          <NetValueChart cross={data} />

          <h3>区间指标（{data.dto.n_days} 个交易日）</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>标的</th>
                  <th>行业</th>
                  <th>区间收益</th>
                  <th>年化波动</th>
                  <th>最大回撤</th>
                  <th>夏普</th>
                  <th>β</th>
                  <th>与基准相关</th>
                  <th>超额收益</th>
                </tr>
              </thead>
              <tbody>
                {data.dto.assets.map((a) => (
                  <tr key={a.code}>
                    <td>
                      <b>{a.code}</b> {a.name}
                    </td>
                    <td className="muted">{a.industry_l1 || "—"}</td>
                    <td>{pct(a.total_return)}</td>
                    <td>{pct(a.annualized_volatility)}</td>
                    <td>{pct(a.max_drawdown)}</td>
                    <td>{num(a.sharpe)}</td>
                    <td>{num(a.beta)}</td>
                    <td>{num(a.corr_to_benchmark)}</td>
                    <td>{pct(a.excess_return)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.dto.benchmark && (
            <p className="muted">
              基准 {data.dto.benchmark.name}（{data.dto.benchmark.symbol}）
              区间收益 {pct(data.dto.benchmark.total_return)}，
              年化波动 {pct(data.dto.benchmark.annualized_volatility)}；
              β 为日收益率对基准的回归斜率。
            </p>
          )}

          <h3>相关性矩阵</h3>
          <CorrelationMatrix correlation={data.dto.correlation} />
        </>
      )}

      {!data && !loading && !error && (
        <p className="empty">输入两个以上代码，查看相对表现与相关性。</p>
      )}
    </section>
  );
}
