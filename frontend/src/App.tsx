/**
 * 应用根组件：只负责状态编排，业务逻辑都在 services 里。
 *
 * 页面结构：
 *   1. 「更新数据」按钮 —— 一键刷新新闻 + 公告 + 财务 + 事件 + 自动调查 + 清理
 *   2. 自选股事件面板 —— 已落库的事件，可直接点「调查」
 *   3. 个股分析 —— 区间切换 + 指标（含财务快照）+ 走势图
 *   4. 预警条件 —— 三级配置（默认/全局/个股）
 *   5. 检测到的事件 —— 行情类 + 公告类
 *   6. 分析任务 —— 保存「标的 + 区间 + 对比组」，一键重跑
 *   7. 行业监控 —— 申万一级行业指数 + 行业事件
 *   8. 跨资产对比 —— 相对表现 / 相关性 / 相对基准
 *   9. 情景分析 —— 改假设（冲击/波动/相关性/回撤）看组合影响
 *  10. 追问 —— 自然语言提问与条件修改
 *  11. 调查报告 —— 事实/推测分栏 + 证据编号
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
import { ComparePanel } from "./components/ComparePanel";
import { PeriodPanel } from "./components/PeriodPanel";
import { AlertToast } from "./components/AlertToast";
import { ChatPanel } from "./components/ChatPanel";
import { IndustryPanel } from "./components/IndustryPanel";
import { TaskPanel } from "./components/TaskPanel";
import { ScenarioPanel } from "./components/ScenarioPanel";
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
  const [refreshingFinancials, setRefreshingFinancials] = useState(false);
  /** 每次刷新/巡检完成后自增，让右上角提醒立刻补拉一次 */
  const [feedKey, setFeedKey] = useState(0);
  /** 追问改了预警条件后自增，强制「预警条件」面板重挂载并重拉配置 */
  const [alertKey, setAlertKey] = useState(0);

  // 区间：预设档（按天数）或用户自定义起止日期。custom 一旦设置就覆盖预设。
  const [custom, setCustom] = useState<{ start: string; end: string } | null>(null);
  const [draft, setDraft] = useState({ start: "", end: "" });

  const range = useMemo(() => custom ?? {
    start: iso(new Date(Date.now() - days * 86400000)),
    end: iso(new Date()),
  }, [custom, days]);

  // 日期输入框跟随当前生效区间（含首次挂载）
  useEffect(() => {
    setDraft({ start: range.start, end: range.end });
  }, [range]);

  /** 自定义区间换算成天数，供「分析任务 / 追问」这类按天数保存的功能使用 */
  const effectiveDays = useMemo(() => {
    if (!custom) return days;
    const ms = new Date(custom.end).getTime() - new Date(custom.start).getTime();
    const d = Math.round(ms / 86400000);
    return Math.max(5, Math.min(2000, d || days));
  }, [custom, days]);

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
    setFeedKey((k) => k + 1);      // 刷新/巡检刚跑过，立刻补拉一次提醒
  }, [loadWatchlist]);

  // ---------------- 单只股票分析 ----------------
  /** 真正的取数入口：显式接收 [start, end]，预设档与自定义区间都收敛到这里 */
  const fetchAll = useCallback(async (c: string, start: string, end: string) => {
    setLoading(true);
    setError("");
    setReport(null);
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

  /** 选预设档：清掉自定义区间，按「今天往前 N 天」算 */
  const analyzeByDays = useCallback((c: string, d: number) => {
    setDays(d);
    setCustom(null);
    void fetchAll(
      c,
      iso(new Date(Date.now() - d * 86400000)),
      iso(new Date()),
    );
  }, [fetchAll]);

  const applyRange = useCallback((d: number) => {
    void analyzeByDays(code, d);
  }, [analyzeByDays, code]);

  /** 应用日期选择器里的起止日期 */
  const applyCustom = useCallback(() => {
    const { start, end } = draft;
    if (!start || !end) {
      setError("请先选择开始与结束日期");
      return;
    }
    if (start >= end) {
      setError("开始日期必须早于结束日期");
      return;
    }
    setCustom({ start, end });
    void fetchAll(code, start, end);
  }, [draft, code, fetchAll]);

  /** 换股票但保持当前区间（不管是预设还是自定义） */
  const analyzeCurrentRange = useCallback((c: string) => {
    void fetchAll(c, range.start, range.end);
  }, [fetchAll, range]);

  // 预警条件改了之后，事件要按新阈值重算
  const refreshEvents = useCallback(async () => {
    try {
      const evs = await services.events.detect(code, range);
      setEvents(evs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [code, range]);

  // 单独刷新某只票的财务快照（A1），成功后重算指标
  const refreshFinancials = useCallback(async () => {
    setRefreshingFinancials(true);
    setError("");
    try {
      await services.stocks.refreshFinancials(code);
      const ind = await services.stocks.getIndicator(code, range.start, range.end);
      setIndicator(ind);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshingFinancials(false);
    }
  }, [code, range]);

  // ---------------- 调查 ----------------
  /** 把报告渲染出来并滚到视野内（手动「调查」与右上角提醒点开共用） */
  const openReport = useCallback((r: InvestigationReport) => {
    setReport(r);
    setTimeout(() => {
      document.querySelector(".report")?.scrollIntoView({ behavior: "smooth" });
    }, 60);
  }, []);

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
      openReport(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [openReport]);

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
    void analyzeByDays(p && /^\d{6}$/.test(p) ? p : "600519", 365);
    // 只在首次挂载时执行
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const crossCodes = useMemo(() => {
    const others = ["000001", "300750"].filter((c) => c !== code);
    return [code, ...others];
  }, [code]);

  return (
    <main className="app">
      {/* 右上角重大事件提醒：刷新/巡检发现 high 事件后弹出，点开看 AI 分析 */}
      <AlertToast onOpen={openReport} feedKey={feedKey} />

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
        onPick={analyzeCurrentRange}
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
        <StockSearch code={code} onSearch={analyzeCurrentRange} disabled={loading} />
        <div className="range-bar">
          <span className="muted">区间</span>
          {RANGES.map(([label, d]) => (
            <button key={label}
                    className={!custom && days === d ? "range-btn active" : "range-btn"}
                    onClick={() => applyRange(d)} disabled={loading}>
              {label}
            </button>
          ))}
          <span className="range-sep" />
          <input type="date" className="date-input" value={draft.start}
                 max={draft.end || undefined} disabled={loading}
                 aria-label="开始日期"
                 onChange={(e) => setDraft({ ...draft, start: e.target.value })} />
          <span className="muted">~</span>
          <input type="date" className="date-input" value={draft.end}
                 disabled={loading} aria-label="结束日期"
                 onChange={(e) => setDraft({ ...draft, end: e.target.value })} />
          <button className="range-btn" onClick={applyCustom} disabled={loading}>
            应用日期
          </button>
          {custom && (
            <button className="range-btn" onClick={() => applyRange(days)} disabled={loading}>
              回到预设
            </button>
          )}
          <span className="muted">
            {range.start} ~ {range.end}
            {custom ? "（自定义）" : ""}
          </span>
        </div>
        {error && <p className="error">{error}</p>}
        {loading && <p className="loading">加载中…（首次拉行情可能较慢）</p>}
        {indicator && (
          <IndicatorPanel indicator={indicator}
                          onRefreshFinancials={() => void refreshFinancials()}
                          refreshingFinancials={refreshingFinancials} />
        )}
        {series && <PriceChart series={series} events={events} />}
      </section>

      {/* 跨期对比：依旧是「当前这一只票」，只是换时间段看。
          位置按你的要求放在个股分析（含走势图）与预警条件之间；
          「预警条件 → 检测到事件」那对保持相邻，不被拆开。 */}
      <PeriodPanel code={code} name={indicator?.dto.name ?? ""} />

      {indicator && (
        <AlertConfig key={`${code}-${alertKey}`} code={code}
                     onChanged={() => void refreshEvents()} />
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

      <ComparePanel codes={crossCodes} start={range.start} end={range.end}
                    onPick={analyzeCurrentRange} />

      <TaskPanel code={code} days={effectiveDays} customRange={custom}
                 onLoad={(c, d) => void analyzeByDays(c, d)} />

      <IndustryPanel onError={setError} />

      <CrossPanel codes={crossCodes} start={range.start} end={range.end} />

      <ScenarioPanel codes={crossCodes} start={range.start} end={range.end} />

      <ChatPanel key={code} code={code} start={range.start} end={range.end}
                 onApplyRange={applyRange}
                 onAlertsChanged={() => {
                   // 追问改了预警阈值：既要按新阈值重算事件，
                   // 也要让「预警条件」面板重新拉一次（否则它还显示旧值）
                   setAlertKey((k) => k + 1);
                   void refreshEvents();
                 }} />

      {report && <ReportView report={report} />}
    </main>
  );
}
