/**
 * 顶部运维条：「更新数据」按钮 + 自动巡检状态。
 *
 * 两条路径共用后端同一个 RefreshService，区别只在排班：
 *   「更新数据」  手工触发，完整档（新闻 + 公告 + 财务 + 事件 + 自动调查 + 清理）
 *   自动巡检      盘中每 30 分钟轻量档（只检测行情与行业），盘后 16:00 / 21:00 完整档
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import type { MonitorStatus, RefreshResult } from "../services/MaintenanceService";

interface Props {
  /** 刷新/巡检完成后通知上层重拉事件列表（不需要结果对象） */
  onRefreshed?: () => void;
}

const PROFILE_LABEL: Record<string, string> = {
  light: "轻量（行情 + 行业）",
  full: "完整（含新闻 / 公告 / 调查）",
};

export function RefreshBar({ onRefreshed }: Props) {
  const [busy, setBusy] = useState(false);
  const [patrolling, setPatrolling] = useState(false);
  const [result, setResult] = useState<RefreshResult | null>(null);
  const [monitor, setMonitor] = useState<MonitorStatus | null>(null);
  const [error, setError] = useState("");

  const loadMonitor = useCallback(async () => {
    try {
      setMonitor(await services.maintenance.monitorStatus());
    } catch {
      setMonitor(null);          // 巡检状态拿不到不该影响主流程
    }
  }, []);

  // 定期刷一下状态，这样「下次触发」和「上次结果」会自己更新
  useEffect(() => {
    void loadMonitor();
    const t = window.setInterval(() => void loadMonitor(), 60_000);
    return () => window.clearInterval(t);
  }, [loadMonitor]);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await services.maintenance.refresh({ newsDays: 2, maxPages: 12, detectDays: 180 });
      setResult(r);
      onRefreshed?.();
      void loadMonitor();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  /** 手动补跑一次轻量巡检（演示时不用等到下一个排班点） */
  const patrolNow = async () => {
    setPatrolling(true);
    setError("");
    try {
      await services.maintenance.monitorRunNow("light");
      await loadMonitor();
      onRefreshed?.();                        // 让事件列表重新拉一遍
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPatrolling(false);
    }
  };

  const inserted = result?.news.reduce((s, n) => s + n.inserted, 0) ?? 0;
  const pruned =
    result && result.prune && "freed_rows" in result.prune ? result.prune.freed_rows : 0;
  const notices = (result?.notices ?? []).reduce((s, n) => s + (n.inserted ?? 0), 0);
  const financials = (result?.financials ?? []).filter((f) => f?.updated).length;
  const industry = result?.industry_events;
  const auto = result?.auto_reports?.length ?? 0;

  const last = monitor?.last_run ?? null;

  return (
    <div className="refresh-bar">
      <button onClick={run} disabled={busy} className="primary">
        {busy ? "更新中…" : "更新数据"}
      </button>

      <button onClick={patrolNow} disabled={patrolling || busy} className="ghost"
              title="不等排班，立刻跑一次轻量巡检（只检测行情与行业事件）">
        {patrolling ? "巡检中…" : "立即巡检"}
      </button>

      {monitor && (
        <span className="monitor-line">
          <span className={monitor.enabled ? "dot on" : "dot off"} />
          自动巡检
          {monitor.enabled ? (
            <>
              {" "}每 <b>{monitor.interval_minutes}</b> 分钟
              （{monitor.light_window.start}–{monitor.light_window.end}）
              {" "}+ 完整档 <b>{monitor.full_slots.join(" / ")}</b>
              {monitor.skip_weekends ? "（仅工作日）" : ""}
              {monitor.running_profile && (
                <em className="warn"> · {PROFILE_LABEL[monitor.running_profile]} 进行中</em>
              )}
              {monitor.next_run_at && <> · 下次 <b>{monitor.next_run_at.slice(5)}</b></>}
            </>
          ) : (
            <> 已关闭（MONITOR_ENABLED=false）</>
          )}
          {last && (
            <span className="muted">
              {" "}· 上次 {last.finished_at?.slice(5) ?? last.started_at.slice(5)}{" "}
              {last.profile} {last.elapsed_sec}s · 事件 {last.events_detected ?? 0}
              {last.notice_events ? `（公告 ${last.notice_events}）` : ""}
              {last.auto_reports ? ` · 自动报告 ${last.auto_reports}` : ""}
              {last.ok === false ? " · 失败" : ""}
            </span>
          )}
        </span>
      )}

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
