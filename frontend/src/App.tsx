/**
 * 应用根组件：只负责状态编排，业务逻辑都在 services 里。
 */
import { useCallback, useState } from "react";
import { StockSearch } from "./components/StockSearch";
import { IndicatorPanel } from "./components/IndicatorPanel";
import { EventList } from "./components/EventList";
import { ReportView } from "./components/ReportView";
import { services } from "./services";
import { Indicator, InvestigationReport, MarketEvent } from "./models";

export default function App() {
  const [indicator, setIndicator] = useState<Indicator | null>(null);
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [report, setReport] = useState<InvestigationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const analyze = useCallback(async (code: string) => {
    setLoading(true);
    setError("");
    setReport(null);
    try {
      const [ind, evs] = await Promise.all([
        services.stocks.getIndicator(code),
        services.events.detect(code, { start: undefined, end: undefined }),
      ]);
      setIndicator(ind);
      setEvents(evs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setIndicator(null);
      setEvents([]);
    } finally {
      setLoading(false);
    }
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
      });
      setReport(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <main className="app">
      <h1>金融分析与监控智能体 · A 股</h1>
      <StockSearch onSearch={analyze} disabled={loading} />
      {error && <p className="error">{error}</p>}
      {loading && <p className="loading">加载中…</p>}

      {indicator && <IndicatorPanel indicator={indicator} />}
      {events.length > 0 && (
        <section className="panel">
          <h2>检测到 {events.length} 个事件</h2>
          <EventList events={events} onInvestigate={investigate} busy={loading} />
        </section>
      )}
      {report && <ReportView report={report} />}
    </main>
  );
}
