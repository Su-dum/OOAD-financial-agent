/**
 * 应用根组件：只负责状态编排，业务逻辑都在 services 里。
 *
 * 页面结构：
 *   1. 「更新数据」按钮 —— 一键刷新新闻 + 自选股事件 + 清理旧数据
 *   2. 自选股事件面板 —— 已落库的事件，可直接点「调查」
 *   3. 单只股票分析 —— 指标 + 事件 + 调查报告
 */
import { useCallback, useEffect, useState } from "react";
import { StockSearch } from "./components/StockSearch";
import { IndicatorPanel } from "./components/IndicatorPanel";
import { EventList } from "./components/EventList";
import { ReportView } from "./components/ReportView";
import { RefreshBar } from "./components/RefreshBar";
import { WatchlistEvents } from "./components/WatchlistEvents";
import { services } from "./services";
import type { WatchItem } from "./services/MaintenanceService";
import { Indicator, InvestigationReport, MarketEvent } from "./models";

export default function App() {
  const [indicator, setIndicator] = useState<Indicator | null>(null);
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [report, setReport] = useState<InvestigationReport | null>(null);

  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  const [wlEvents, setWlEvents] = useState<MarketEvent[]>([]);
  const [wlLoading, setWlLoading] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ---------------- 自选股 + 已落库事件 ----------------
  const loadWatchlist = useCallback(async () => {
    setWlLoading(true);
    try {
      const r = await services.maintenance.watchlistEvents(50);
      setWatchlist(r.watchlist);
      setWlEvents(r.events);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWlLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWatchlist();
  }, [loadWatchlist]);

  const onRefreshed = useCallback(() => {
    void loadWatchlist();
  }, [loadWatchlist]);

  // ---------------- 单只股票分析 ----------------
  const analyze = useCallback(async (code: string) => {
    setLoading(true);
    setError("");
    setReport(null);
    try {
      const [ind, evs] = await Promise.all([
        services.stocks.getIndicator(code),
        services.events.detect(code),
      ]);
      setIndicator(ind);
      setEvents(evs);
      window.history.replaceState(null, "", `?code=${code}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setIndicator(null);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // ---------------- 调查 ----------------
  const investigate = useCallback(async (ev: MarketEvent) => {
    setLoading(true);
    setError("");
    try {
      const r = await services.reports.investigate({
        code: ev.dto.code,
        trade_date: ev.dto.trade_date,
        event_type: ev.dto.event_type,
        days: 7,
      });
      setReport(r);
      setTimeout(() => {
        document.querySelector(".report")?.scrollIntoView({ behavior: "smooth" });
      }, 60);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const removeWatch = useCallback(
    async (code: string) => {
      try {
        await services.maintenance.removeWatch(code);
        await loadWatchlist();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadWatchlist],
  );

  // 支持 ?code=600519 直接打开（便于分享链接 / 演示）
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("code");
    if (p && /^\d{6}$/.test(p)) void analyze(p);
  }, [analyze]);

  return (
    <main className="app">
      <header className="app-header">
        <h1>金融分析与监控智能体 · A 股</h1>
        <p className="muted">
          指标计算 · 事件监控 · 基于证据的 AI 调查（结论带引用编号，可追溯）
        </p>
      </header>

      <RefreshBar onRefreshed={onRefreshed} />

      <WatchlistEvents
        watchlist={watchlist}
        events={wlEvents}
        onInvestigate={investigate}
        onPick={analyze}
        onRemove={removeWatch}
        busy={loading}
        loading={wlLoading}
      />

      <section className="panel">
        <header>
          <h2>个股分析</h2>
          <span className="badge">输入代码查看指标与事件</span>
        </header>
        <StockSearch onSearch={analyze} disabled={loading} />
        {error && <p className="error">{error}</p>}
        {loading && <p className="loading">加载中…（首次拉行情可能较慢）</p>}
        {indicator && <IndicatorPanel indicator={indicator} />}
        {events.length > 0 && (
          <>
            <h3>该股检测到 {events.length} 个事件</h3>
            <EventList events={events} onInvestigate={investigate} busy={loading} />
          </>
        )}
      </section>

      {report && <ReportView report={report} />}
    </main>
  );
}
