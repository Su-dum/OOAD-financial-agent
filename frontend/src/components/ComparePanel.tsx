/**
 * 横向对比面板（A3）。
 *
 * 比较 2~6 只标的在**同一区间**的指标，回答「同一段时间里，
 * 谁涨得多、谁波动大、谁更便宜、谁更赚钱」。
 *
 * 与「跨资产对比」面板的分工：
 *   ComparePanel  基本面视角：收益 / 波动 / 回撤 / 夏普 / PE / PB / ROE / 增速
 *   CrossPanel    相关性视角：净值曲线 / 相关矩阵 / β / 跟踪误差
 * 两者都只渲染后端算好的数，前端不重算（避免两端算法漂移）。
 *
 * 字段是后端 20 个指标里挑出来的 10 个；要看全字段请直接查
 * `GET /api/stocks/compare`。
 *
 * 注意：区间与数据**绑在一起**存。否则用户改日期后、请求还在飞的时候，
 * 小标题已经显示新区间、表格还是旧数字，会自相矛盾。
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import { Indicator } from "../models";

interface Props {
  /** 默认对比的标的：当前分析的主角 + 两只参照 */
  codes: string[];
  start: string;
  end: string;
  /** 点某一行把主页面的主角切过去 */
  onPick?: (code: string) => void;
}

/** 一次成功取数的结果：区间与行必须一起存，不能分开 */
interface Loaded {
  start: string;
  end: string;
  rows: Indicator[];
}

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`;
const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(d);

export function ComparePanel({ codes, start, end, onPick }: Props) {
  const [input, setInput] = useState(codes.slice(0, 3).join(","));
  const [data, setData] = useState<Loaded | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (raw: string, s: string, e: string) => {
    const list = raw.split(",").map((x) => x.trim()).filter(Boolean);
    if (list.length < 2) {
      setError("至少输入两个代码（逗号分隔）");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const rows = await services.stocks.compare(list, s, e);
      setData({ start: s, end: e, rows });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // 主角或区间变了就重算
  useEffect(() => {
    const next = codes.slice(0, 3).join(",");
    setInput(next);
    if (codes.length >= 2) void load(next, start, end);
  }, [codes, start, end, load]);

  const rows = data?.rows ?? [];
  const best = rows.length > 0 ? rows[0] : null;

  return (
    <section className="panel">
      <header>
        <h2>横向对比</h2>
        <span className="badge">同一区间 · 多标的指标对比（A3）</span>
        {loading && <span className="muted">计算中…</span>}
      </header>

      <div className="search">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="逗号分隔的代码，如 600519,000001,300750"
        />
        <button onClick={() => void load(input, start, end)} disabled={loading}>
          对比
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {data && rows.length > 0 && (() => {
        // 窗口一致性：各行的实际交易日/区间可能不同（停牌、上市晚）。
        // 不一致时收益/波动**不可直接横比**，必须显式提示，否则这张表就是个误导。
        const days = rows.map((r) => r.dto.n_days);
        const maxDays = Math.max(...days);
        const minDays = Math.min(...days);
        const spans = new Set(rows.map((r) => `${r.dto.start}~${r.dto.end}`));
        const uniformDays = minDays === maxDays;
        const uniformSpan = spans.size === 1;
        const aligned = uniformDays && uniformSpan;
        return (
        <>
          <h3>
            区间指标
            <span className="muted">
              {" "}· {data.start} ~ {data.end} · {rows.length} 只标的 · 按区间收益降序
            </span>
          </h3>

          {!aligned && (
            <p className="warn-box">
              ⚠ 各标的<b>实际交易日不一致</b>（{minDays}~{maxDays} 天
              {uniformSpan ? "" : `，区间 ${[...spans].slice(0, 3).join(" / ")}${spans.size > 3 ? " …" : ""}`}
              ）：收益、波动、回撤是各自在<b>自己的窗口</b>上算的，
              不能直接横比。要看同窗口对比请用下方「跨资产对比」
              （会自动对齐到共同交易日）。
            </p>
          )}

          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>标的</th>
                  <th>行业</th>
                  <th>交易日</th>
                  <th>区间收益</th>
                  <th>年化波动</th>
                  <th>最大回撤</th>
                  <th>夏普</th>
                  <th>PE(TTM)</th>
                  <th>PB</th>
                  <th>ROE</th>
                  <th>净利增速</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const d = r.dto;
                  const isBest = best !== null && d.code === best.code;
                  const short = !aligned && d.n_days < maxDays;
                  return (
                    <tr key={d.code}
                        onClick={onPick ? () => onPick(d.code) : undefined}
                        style={onPick ? { cursor: "pointer" } : undefined}
                        title={onPick ? `点击把主标的切到 ${d.code}` : undefined}>
                      <td>
                        <b>{d.code}</b> {d.name}
                        {isBest && (
                          <span className="badge" style={{ marginLeft: 6 }}>最佳</span>
                        )}
                      </td>
                      <td className="muted">{d.industry_l1 || "—"}</td>
                      <td title={`${d.start} ~ ${d.end}`}>
                        {d.n_days}
                        {short && <span className="badge warn" style={{ marginLeft: 6 }}>短窗</span>}
                      </td>
                      <td>{pct(d.total_return)}</td>
                      <td>{pct(d.annualized_volatility)}</td>
                      <td>{pct(d.max_drawdown)}</td>
                      <td>{num(d.sharpe, 3)}</td>
                      <td>{num(d.pe_ttm)}</td>
                      <td>{num(d.pb)}</td>
                      <td>{num(d.roe)}%</td>
                      <td>{num(d.profit_growth)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="provenance">
            口径：{rows[0].dto.source} / {rows[0].dto.adjust}。
            ROE 与净利增速为最近一期定期报告（百分数本身），收益与波动为小数。
            PE / PB 仅 baostock 源提供，降级到新浪或东财时显示「—」。
            鼠标悬停「交易日」可看该行实际区间。
          </p>
        </>
        );
      })()}

      {data && rows.length === 0 && (
        <p className="empty">所选标的在该区间没有可用数据。</p>
      )}

      {!data && !loading && !error && (
        <p className="empty">输入两个以上代码，对比同一区间的收益、风险和估值。</p>
      )}
    </section>
  );
}
