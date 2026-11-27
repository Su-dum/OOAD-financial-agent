/** 跨期对比（A3）：同一标的在不同时间段的表现。
 *
 * 为什么单独成一块（而不是塞在「分析任务」里）：
 *   分析任务 = 保存「标的 + 区间 + 对比组」再一键重跑；
 *   本面板   = 对**当前标的**用任意手填窗口做跨期对比，不依赖任何保存的任务。
 *   两者没有依赖关系，放在一起会让人以为"要先建任务才能用"。
 *
 * 表头必须写清「这是哪只票 + 用的哪套窗口」：曾经出现过切换标的后
 * 表格仍是上一只票的数字、且没有任何标识的情况，那是会被误读的。
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import { PeriodRowDTO } from "../models";
import { PeriodTable } from "./PeriodTable";

type Mode = "default" | "custom";

interface Loaded {
  code: string;
  name: string;
  mode: Mode;
  windows: string;
  rows: PeriodRowDTO[];
}

const DEFAULT_HINT = "默认五档：近 1 / 3 / 6 / 12 / 24 个月（都以今天为终点）";

export function PeriodPanel({ code, name = "" }: { code: string; name?: string }) {
  const [input, setInput] = useState("");
  const [data, setData] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // 换标的就丢弃旧结果：宁可空着，也不要留一张标着别的股票的表
  useEffect(() => {
    setData(null);
    setError("");
  }, [code]);

  const run = useCallback(async () => {
    setBusy(true);
    setError("");
    const w = input.trim();
    try {
      const rows = await services.stocks.periods(code, w || undefined);
      setData({ code, name, mode: w ? "custom" : "default", windows: w, rows });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setBusy(false);
    }
  }, [code, name, input]);

  const subject = data
    ? `${data.code}${data.name ? ` ${data.name}` : ""} · ${
        data.mode === "custom" ? "自定义窗口" : "默认五档"
      }`
    : "";

  return (
    <section className="panel">
      <header>
        <h2>跨期对比</h2>
        <span className="badge">A3 · 同一标的、不同时间段</span>
        <span className="badge">{code}{name ? ` ${name}` : ""}</span>
      </header>

      <div className="search">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="上半年:2026-01-01:2026-06-30;下半年:2026-07-01:2026-11-26"
        />
        <button onClick={() => void run()} disabled={busy}>
          {busy ? "计算中…" : "计算"}
        </button>
      </div>
      <p className="provenance" style={{ marginTop: 0 }}>
        格式 <code>名称:开始:结束</code>，多段用 <code>;</code> 分隔；
        <b>留空 = {DEFAULT_HINT}</b>。任务的跨期档位只能覆盖"以今天为终点"的窗口，
        想看「上半年 vs 下半年」这类区间就填在这里。
      </p>

      {error && <p className="error">{error}</p>}

      {data && data.rows.length > 0 && (
        <>
          <h3>
            区间指标
            <span className="muted">
              {" "}· <b>{subject}</b>
              {data.mode === "custom" && (
                <> · {data.windows}</>
              )}
            </span>
          </h3>
          <PeriodTable rows={data.rows} />
          <p className="provenance">
            口径：{data.rows[0]?.source || "—"} / {data.rows[0]?.adjust || "—"}。
            「实际区间」是真实取到的首末日（请求区间可能跨节假日或超出上市日）。
            收益 / 波动 / 回撤 / 胜率为小数口径，每行按<b>自己的窗口</b>计算，
            不同长度区间的年化值不可直接横比。
          </p>
        </>
      )}

      {data && data.rows.length === 0 && (
        <p className="empty">{subject} 在这些窗口里没有可用行情数据。</p>
      )}

      {!data && !busy && !error && (
        <p className="empty">
          点「计算」查看 <b>{code}{name ? ` ${name}` : ""}</b> 在{DEFAULT_HINT}的表现；
          也可手填任意窗口（如「上半年 vs 下半年」）。
        </p>
      )}
    </section>
  );
}
