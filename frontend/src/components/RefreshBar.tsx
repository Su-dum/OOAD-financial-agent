/** 「更新数据」按钮：一键刷新新闻 + 公告 + 财务 + 事件 + 自动调查 + 清理。 */
import { useState } from "react";
import { services } from "../services";
import type { RefreshResult } from "../services/MaintenanceService";

interface Props {
  onRefreshed?: (r: RefreshResult) => void;
}

export function RefreshBar({ onRefreshed }: Props) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RefreshResult | null>(null);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await services.maintenance.refresh({ newsDays: 2, maxPages: 12, detectDays: 180 });
      setResult(r);
      onRefreshed?.(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const inserted = result?.news.reduce((s, n) => s + n.inserted, 0) ?? 0;
  const pruned =
    result && result.prune && "freed_rows" in result.prune ? result.prune.freed_rows : 0;
  const notices = (result?.notices ?? []).reduce((s, n) => s + (n.inserted ?? 0), 0);
  const financials = (result?.financials ?? []).filter((f) => f?.updated).length;
  const industry = result?.industry_events;
  const auto = result?.auto_reports?.length ?? 0;

  return (
    <div className="refresh-bar">
      <button onClick={run} disabled={busy} className="primary">
        {busy ? "更新中…" : "更新数据"}
      </button>

      {result && !busy && (
        <span className="refresh-summary">
          新闻 <b>{inserted}</b> · 公告 <b>{notices}</b> · 财务 <b>{financials}</b> ·
          自选股 <b>{result.stocks_scanned}</b> · 事件 <b>{result.events_detected}</b>
          {industry ? ` · 行业事件 ${industry.events_detected ?? 0}` : ""}
          {auto > 0 && <> · 自动报告 <b>{auto}</b></>}
          {" "}· 清理 <b>{pruned}</b> · 耗时 <b>{result.elapsed_sec}s</b>
          {result.failed_stocks.length > 0 && (
            <em className="warn"> （{result.failed_stocks.join(", ")} 行情获取失败）</em>
          )}
          <br />
          <span className="muted">
            更新于 {result.started_at} · 新闻库 {result.news_total_before.toLocaleString()} →{" "}
            {result.news_total_after.toLocaleString()} 条
            {result.note ? ` · ${result.note}` : ""}
          </span>
        </span>
      )}

      {error && <span className="error">{error}</span>}
    </div>
  );
}
