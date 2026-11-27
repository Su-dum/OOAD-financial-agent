/**
 * 重大事件提醒（右上角弹窗）。
 *
 * 对应 B3 的「通知面」：刷新/巡检发现重大事件后，后端已经自动用 LLM 生成过报告，
 * 但报告只是躺在库里——用户根本不知道。这个组件负责把「刚刚发生了什么」推到眼前。
 *
 * 行为：
 *   - 轮询 `/api/monitor/alerts?since=<上次看到的时间>`，只取**此后新检测到**的事件
 *   - 每条显示：标的 + 事件类型 + 日期 + 一句话结论（有 AI 分析时）
 *   - 点卡片：有 `report_id` 就直接打开后端已存的分析；没有就现场跑一次 LLM 调查
 *   - 不点：12 秒后自动消失（底部进度条可见），鼠标悬停暂停计时
 *   - 「上次看到的时间」存在 localStorage，刷新页面不会重复弹同一条
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { services } from "../services";
import { InvestigationReport } from "../models";
import type { AlertItem } from "../services/MaintenanceService";

interface Props {
  /** 点开某条提醒后，把报告交给上层渲染 */
  onOpen: (r: InvestigationReport) => void;
  /** 变化时立刻拉一次（例如刚点完「更新数据」） */
  feedKey?: number;
}

const SEEN_KEY = "finance.alertSince";
const DISMISS_MS = 12_000;
const POLL_MS = 45_000;
const MAX_VISIBLE = 3;

const pad = (n: number) => String(n).padStart(2, "0");
const nowStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
         `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

export function AlertToast({ onOpen, feedKey = 0 }: Props) {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const seenRef = useRef<string>("");

  // 首次进入：以「现在」为起点，避免把库里 180 天的历史事件一次性弹出来
  if (!seenRef.current) {
    const stored = localStorage.getItem(SEEN_KEY);
    seenRef.current = stored || nowStr();
    if (!stored) localStorage.setItem(SEEN_KEY, seenRef.current);
  }

  const dismiss = useCallback((key: string) => {
    setItems((prev) => prev.filter((x) => `${x.code}-${x.event_type}-${x.trade_date}` !== key));
  }, []);

  const poll = useCallback(async () => {
    try {
      const feed = await services.maintenance.alerts(seenRef.current, {
        limit: MAX_VISIBLE, minSeverity: "high",
      });
      // 把游标推进到服务端时间：这样同一条不会被反复推
      if (feed.now) {
        seenRef.current = feed.now;
        localStorage.setItem(SEEN_KEY, feed.now);
      }
      if (feed.items.length) {
        setItems((prev) => {
          const seen = new Set(prev.map((x) => `${x.code}-${x.event_type}-${x.trade_date}`));
          const fresh = feed.items.filter(
            (x) => !seen.has(`${x.code}-${x.event_type}-${x.trade_date}`));
          return [...fresh, ...prev].slice(0, MAX_VISIBLE);
        });
      }
      setError("");
    } catch {
      /* 提醒拉不到不该打扰用户 */
    }
  }, []);

  useEffect(() => {
    void poll();
    const t = window.setInterval(() => void poll(), POLL_MS);
    return () => window.clearInterval(t);
  }, [poll]);

  // 「更新数据」完成后立刻补拉一次
  useEffect(() => {
    if (feedKey > 0) void poll();
  }, [feedKey, poll]);

  const open = async (item: AlertItem) => {
    const key = `${item.code}-${item.event_type}-${item.trade_date}`;
    setBusy(key);
    setError("");
    try {
      const report = item.report_ready && item.report_id
        ? await services.reports.get(item.report_id)          // 后端已分析好，直接看
        : await services.reports.investigate({                // 没分析过 -> 现场跑 LLM
            code: item.code,
            trade_date: item.trade_date,
            event_type: item.event_type,
            days: 7,
            severity: item.severity,
            detail: item.detail,
            question: `${item.name || item.code} 在 ${item.trade_date} 发生「${item.label}」` +
                      `（${item.detail}），可能原因与影响是什么？`,
          });
      dismiss(key);
      onOpen(report);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  if (items.length === 0 && !error) return null;

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {error && <p className="toast-error">{error}</p>}
      {items.map((item) => (
        <ToastCard key={`${item.code}-${item.event_type}-${item.trade_date}`}
                   item={item}
                   busy={busy === `${item.code}-${item.event_type}-${item.trade_date}`}
                   onOpen={() => void open(item)}
                   onClose={() => dismiss(`${item.code}-${item.event_type}-${item.trade_date}`)} />
      ))}
    </div>
  );
}

function ToastCard({ item, busy, onOpen, onClose }: {
  item: AlertItem;
  busy: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const [paused, setPaused] = useState(false);

  // 12 秒自动消失；悬停暂停（重新计时）
  useEffect(() => {
    if (paused || busy) return;
    const t = window.setTimeout(onClose, DISMISS_MS);
    return () => window.clearTimeout(t);
  }, [paused, busy, onClose]);

  const conf = item.confidence === null || item.confidence === undefined
    ? null : `${Math.round(item.confidence * 100)}%`;

  return (
    <div className={`toast toast-${item.severity}`}
         onMouseEnter={() => setPaused(true)}
         onMouseLeave={() => setPaused(false)}>
      <button className="toast-close" onClick={onClose} title="关闭" aria-label="关闭">×</button>

      {/* 用 div+role 而不是 button：里面要放多行文本，button 只允许行内内容 */}
      <div className="toast-body" role="button" tabIndex={0}
           aria-disabled={busy}
           onClick={() => { if (!busy) onOpen(); }}
           onKeyDown={(e) => { if (!busy && (e.key === "Enter" || e.key === " ")) onOpen(); }}
           title="点击查看该事件的 AI 分析">
        <div className="toast-head">
          <span className={`toast-sev toast-sev-${item.severity}`}>{item.severity}</span>
          <b>{item.name || item.code}</b>
          <span className="toast-label">{item.label}</span>
          <span className="toast-date">{item.trade_date}</span>
        </div>

        <p className="toast-detail">{item.detail}</p>

        {busy ? (
          <p className="toast-meta busy">正在用 AI 分析…（可能需要十几秒）</p>
        ) : item.report_ready ? (
          <>
            {item.headline && <p className="toast-headline">{item.headline}</p>}
            <p className="toast-meta">
              AI 已分析
              {item.llm_model ? ` · ${item.llm_model}` : ""}
              {conf ? ` · 置信度 ${conf}` : ""}
              {item.degraded ? " · 已降级模板" : ""}
              {" "}· 点击查看
            </p>
          </>
        ) : (
          <p className="toast-meta">
            尚无分析 · 点击让 AI 调查成因与影响
          </p>
        )}
      </div>

      <span className={`toast-timer ${paused ? "paused" : ""}`} aria-hidden="true" />
    </div>
  );
}
