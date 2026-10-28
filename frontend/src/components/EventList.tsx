/** 事件列表：每条事件可发起调查。 */
import { MarketEvent } from "../models";

interface Props {
  events: MarketEvent[];
  onInvestigate?: (e: MarketEvent) => void;
  busy?: boolean;
}

export function EventList({ events, onInvestigate, busy }: Props) {
  if (!events.length) {
    return <p className="empty">该区间内没有检测到事件。</p>;
  }
  return (
    <ul className="events">
      {events.map((e) => (
        <li key={`${e.dto.rule_name}-${e.dto.trade_date}`} className={e.severityClass}>
          <div className="ev-main">
            <span className="ev-date">{e.dto.trade_date}</span>
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
  );
}
