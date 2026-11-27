/**
 * 事件列表：每条事件可发起调查；公告类事件带原始公告链接。
 *
 * 默认**折叠**：只显示最近 N 条，多余的点「显示全部」展开。
 * 原因：一次季度区间常能检出 8~10 个事件（公告类尤其多），
 * 全部铺开会把整页撑得很长，把下面的分析任务/行业监控挤到很远处。
 * 列表本身已按「事件日倒序」，所以折叠后看到的就是最近的几条。
 */
import { useEffect, useState } from "react";
import { MarketEvent } from "../models";

interface Props {
  events: MarketEvent[];
  onInvestigate?: (e: MarketEvent) => void;
  busy?: boolean;
  /** 折叠时显示多少条。传 0 或负数表示不折叠。 */
  collapsed?: number;
}

export function EventList({ events, onInvestigate, busy, collapsed = 5 }: Props) {
  const [showAll, setShowAll] = useState(false);

  // 换标的 / 换区间后收回折叠态，避免上一只票的展开状态延续过来
  useEffect(() => {
    setShowAll(false);
  }, [events]);

  if (!events.length) {
    return <p className="empty">该区间内没有检测到事件。</p>;
  }

  const folding = collapsed > 0 && events.length > collapsed;
  // 直接 slice，而不是用 CSS 隐藏：多余的卡片不该留在 DOM 里占高度
  const visible = folding && !showAll ? events.slice(0, collapsed) : events;

  return (
    <>
      <ul className="events">
        {visible.map((e) => (
          <li key={`${e.dto.rule_name}-${e.dto.event_type}-${e.dto.trade_date}`}
              className={e.severityClass}>
            <div className="ev-main">
              <span className="ev-date">{e.dto.trade_date}</span>
              <span className="ev-label">{e.label}</span>
              {e.isNotice && <span className="ev-kind">公告</span>}
              <span className={`ev-sev ${e.severityClass}`}>{e.dto.severity}</span>
            </div>
            <div className="ev-detail">
              {e.dto.detail}
              {e.dto.source_url && (
                <a className="ev-link" href={e.dto.source_url} target="_blank" rel="noreferrer">
                  公告原文
                </a>
              )}
            </div>
            {onInvestigate && (
              <button disabled={busy} onClick={() => onInvestigate(e)}>
                调查
              </button>
            )}
          </li>
        ))}
      </ul>

      {folding && (
        <button className="ghost more-btn" onClick={() => setShowAll(!showAll)}>
          {showAll
            ? "收起"
            : `显示全部 ${events.length} 条（还有 ${events.length - collapsed} 条）`}
        </button>
      )}
    </>
  );
}
