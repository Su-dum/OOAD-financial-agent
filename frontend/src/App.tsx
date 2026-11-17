/**
 * 应用根组件：只负责状态编排，业务逻辑都在 services 里。
 *
 * 页面结构：
 *   1. 「更新数据」按钮 —— 一键刷新新闻 + 公告 + 自选股事件 + 清理
 *   2. 自选股事件面板 —— 已落库的事件，可直接点「调查」
 *   3. 个股分析 —— 区间切换 + 指标 + 走势图 + 预警条件 + 事件
 *   4. 跨资产对比 —— 相对表现 / 相关性 / 相对基准
 *   5. 追问 —— 自然语言提问与条件修改
 *   6. 调查报告 —— 事实/推测分栏 + 证据编号
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { StockSearch } from "./components/StockSearch";
import { IndicatorPanel } from "./components/IndicatorPanel";
import { PriceChart } from "./components/PriceChart";
import { AlertConfig } from "./components/AlertConfig";
import { EventList } from "./components/EventList";
import { ReportView } from "./components/ReportView";
import { RefreshBar } from "./components/RefreshBar";
import { WatchlistEvents } from "./components/WatchlistEvents";
import { CrossPanel } from "./components/CrossPanel";
import { ChatPanel } from "./components/ChatPanel";
import { services } from "./services";
import type { WatchItem } from "./services/MaintenanceService";
import { Indicator, InvestigationReport, MarketEvent, Series } from "./models";

const RANGES: [string, number][] = [
  ["1个月", 30], ["3个月", 90], ["6个月", 180], ["1年", 365], ["2年", 730],
];

const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function App() {
  const [code, setCode] = useState("600519");
  const [days, setDays] = useState(365);

  const [indicator, setIndicator] = useState<Indicator | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [report, setReport] = useState<InvestigationReport | null>(null);

  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  const [wlEvents, setWlEvents] = useState<MarketEvent[]>([]);
  const [wlLoading, setWlLoading] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const range = useMemo(() => ({
    start: iso(new Date(Date.now() - days * 86400000)),
    end: iso(new Date()),
  }), [days]);

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
  const analyze = useCallback(async (c: string, d: number) => {
    setLoading(true);
    setError("");
    setReport(null);
    const start = iso(new Date(Date.now() - d * 86400000));
    const end = iso(new Date());
    try {
      const [ind, ser, evs] = await Promise.all([
        services.stocks.getIndicator(c, start, end),
        services.stocks.series(c, { start, end }),
        services.events.detect(c, { start, end }),
      ]);
      setIndicator(ind);
      setSeries(ser);
      setEvents(evs);
      setCode(c);
      window.history.replaceState(null, "", `?code=${c}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setIndicator(null);
      setSeries(null);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const applyRange = useCallback((d: number) => {
    setDays(d);
    void analyze(code, d);
  }, [analyze, code]);

  // 预警条件改了之后，事件要按新阈值重算
  const refreshEvents = useCallback(async () => {
    try {
      const evs = await services.events.detect(code, range);
      setEvents(evs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [code, range]);

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
        question: ev.isNotice
          ? `${ev.dto.name || ev.dto.code} 在 ${ev.dto.trade_date} 披露了「${ev.dto.detail}」，这对公司意味着什么？`
          : undefined,
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

  const addWatch = useCallback(async (c: string) => {
    try {
      await services.maintenance.addWatch(c);
      await loadWatchlist();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [loadWatchlist]);

  const removeWatch = useCallback(async (c: string) => {
    try {
      await services.maintenance.removeWatch(c);
      await loadWatchlist();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [loadWatchlist]);

  // 支持 ?code=600519 直接打开（便于分享链接 / 演示）
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("code");
    void analyze(p && /^\d{6}$/.test(p) ? p : "600519", 365);
    // 只在首次挂载时执行
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const crossCodes = useMemo(() => {
    const others = ["000001", "300750"].filter((c) => c !== code);
    return [code, ...others];
  }, [code]);

  return (
    <main className="app">
      <header className="app-header">
        <h1>金融分析与监控智能体 · A 股</h1>
        <p className="muted">
          指标计算 · 事件监控 · 跨资产对比 · 基于证据的 AI 调查与追问（结论带引用编号，可追溯）
        </p>
      </header>

      <RefreshBar onRefreshed={onRefreshed} />

      <WatchlistEvents
        watchlist={watchlist}
        events={wlEvents}
        onInvestigate={investigate}
        onPick={(c) => void analyze(c, days)}
        onRemove={removeWatch}
        onAdd={addWatch}
        busy={loading}
        loading={wlLoading}
      />

      <section className="panel">
        <header>
          <h2>个股分析</h2>
          <span className="badge">输入代码查看指标、走势与事件</span>
        </header>
        <StockSearch onSearch={(c) => void analyze(c, days)} disabled={loading} />
        <div className="range-bar">
          <span className="muted">区间</span>
          {RANGES.map(([label, d]) => (
            <button key={label}
                    className={days === d ? "range-btn active" : "range-btn"}
                    onClick={() => applyRange(d)} disabled={loading}>
              {label}
            </button>
          ))}
          <span className="muted">{range.start} ~ {range.end}</span>
        </div>
        {error && <p className="error">{error}</p>}
        {loading && <p className="loading">加载中…（首次拉行情可能较慢）</p>}
        {indicator && <IndicatorPanel indicator={indicator} />}
        {series && <PriceChart series={series} events={events} />}
      </section>

      {indicator && (
        <AlertConfig key={code} code={code} onChanged={() => void refreshEvents()} />
      )}

      {events.length > 0 && (
        <section className="panel">
          <header>
            <h2>检测到 {events.length} 个事件</h2>
            <span className="badge">
              行情类 {events.filter((e) => !e.isNotice).length} · 公告类{" "}
              {events.filter((e) => e.isNotice).length}
            </span>
          </header>
          <EventList events={events} onInvestigate={investigate} busy={loading} />
        </section>
      )}

      <CrossPanel codes={crossCodes} start={range.start} end={range.end} />

      <ChatPanel key={code} code={code} start={range.start} end={range.end}
                 onApplyRange={applyRange} onAlertsChanged={() => void refreshEvents()} />

      {report && <ReportView report={report} />}
    </main>
  );
}
