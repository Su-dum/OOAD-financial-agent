/** 自选股事件面板：展示已落库的事件，可直接发起调查；支持增删自选。 */
import { useState, type FormEvent } from "react";
import { MarketEvent } from "../models";
import type { WatchItem } from "../services/MaintenanceService";

interface Props {
  watchlist: WatchItem[];
  events: MarketEvent[];
  onInvestigate?: (e: MarketEvent) => void;
  onPick?: (code: string) => void;
  onRemove?: (code: string) => void;
  onAdd?: (code: string) => void;
  busy?: boolean;
  loading?: boolean;
}

export function WatchlistEvents({
  watchlist, events, onInvestigate, onPick, onRemove, onAdd, busy, loading,
}: Props) {
  const [input, setInput] = useState("");
  const [showAll, setShowAll] = useState(false);
  const COLLAPSED = 8;
  const visible = showAll ? events : events.slice(0, COLLAPSED);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const code = input.trim();
    if (!/^\d{6}$/.test(code)) return;
    onAdd?.(code);
    setInput("");
  };

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

      {onAdd && (
        <form className="search add-watch" onSubmit={submit}>
          <input value={input} onChange={(e) => setInput(e.target.value)}
                 placeholder="输入 6 位代码加入自选（如 601318）" inputMode="numeric"
                 maxLength={6} />
          <button type="submit" disabled={!/^\d{6}$/.test(input.trim())}>加入自选</button>
        </form>
      )}

      {events.length === 0 ? (
        <p className="empty">
          还没有事件。点上方「更新数据」会自动采集公告、检测自选股事件。
        </p>
      ) : (
        <>
          <ul className="events">
            {visible.map((e) => (
              <li key={`${e.dto.code}-${e.dto.rule_name}-${e.dto.event_type}-${e.dto.trade_date}`}
                  className={e.severityClass}>
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
          {events.length > COLLAPSED && (
            <button className="ghost more-btn" onClick={() => setShowAll(!showAll)}>
              {showAll ? "收起" : `显示全部 ${events.length} 条`}
            </button>
          )}
        </>
      )}
    </section>
  );
}
