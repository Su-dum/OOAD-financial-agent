/** 自选股事件面板：展示已落库的事件，可直接发起调查。 */
import { MarketEvent } from "../models";
import type { WatchItem } from "../services/MaintenanceService";

interface Props {
  watchlist: WatchItem[];
  events: MarketEvent[];
  onInvestigate?: (e: MarketEvent) => void;
  onPick?: (code: string) => void;
  onRemove?: (code: string) => void;
  busy?: boolean;
  loading?: boolean;
}

export function WatchlistEvents({
  watchlist, events, onInvestigate, onPick, onRemove, busy, loading,
}: Props) {
  return (
    <section className="panel">
      <header>
        <h2>自选股事件</h2>
        <span className="badge">{watchlist.length} 只自选</span>
        {loading && <span className="muted">加载中…</span>}
      </header>

      <div className="chips">
        {watchlist.map((w) => (
          <span key={w.code} className="chip">
            <button className="chip-name" onClick={() => onPick?.(w.code)} title="查看该股指标">
              {w.name || w.code}
            </button>
            <button className="chip-x" onClick={() => onRemove?.(w.code)} title="移出自选">
              ×
            </button>
          </span>
        ))}
        {watchlist.length === 0 && <span className="muted">暂无自选股</span>}
      </div>

      {events.length === 0 ? (
        <p className="empty">
          还没有事件。点上方「更新数据」会自动检测自选股的事件。
        </p>
      ) : (
        <ul className="events">
          {events.map((e) => (
            <li key={`${e.dto.code}-${e.dto.rule_name}-${e.dto.trade_date}`} className={e.severityClass}>
              <div className="ev-main">
                <span className="ev-date">{e.dto.trade_date}</span>
                <button className="ev-stock" onClick={() => onPick?.(e.dto.code)}>
                  {e.dto.name || e.dto.code}
                </button>
                <span className="ev-label">{e.label}</span>
                <span className={`ev-sev ${e.severityClass}`}>{e.dto.severity}</span>
              </div>
              <div className="ev-detail">{e.dto.detail}</div>
              {onInvestigate && (
                <button disabled={busy} onClick={() => onInvestigate(e)}>
                  调查
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
