/**
 * 行业监控面板（B1）。
 *
 * 监控对象是**申万一级行业指数**（31 个），不是成分股聚合——指数口径统一、
 * 历史长且互相可比。行业事件和个股事件走同一套行情规则，只是 `scope=industry`。
 *
 * 交互：从下拉里选行业 → 加入监控 → 点行业看指数走势与事件。
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import { IndustryDTO, MarketEvent, Series } from "../models";
import { PriceChart } from "./PriceChart";
import { EventList } from "./EventList";

interface Props {
  onError?: (msg: string) => void;
}

export function IndustryPanel({ onError }: Props) {
  const [industries, setIndustries] = useState<IndustryDTO[]>([]);
  const [selected, setSelected] = useState("");
  const [series, setSeries] = useState<Series | null>(null);
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);

  const fail = useCallback((e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    onError?.(msg);
  }, [onError]);

  const loadList = useCallback(async () => {
    try {
      setIndustries(await services.industries.list());
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const open = useCallback(async (code: string) => {
    if (!code) return;
    setSelected(code);
    setLoading(true);
    try {
      const [s, evs] = await Promise.all([
        services.industries.series(code),
        services.industries.events(code),
      ]);
      setSeries(s);
      setEvents(evs);
    } catch (e) {
      fail(e);
      setSeries(null);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, [fail]);

  // 首次加载后自动打开第一个已监控行业
  useEffect(() => {
    const first = industries.find((i) => i.watched);
    if (first && !selected) void open(first.code);
  }, [industries, selected, open]);

  const toggle = useCallback(async (item: IndustryDTO) => {
    setBusy(true);
    try {
      const next = item.watched
        ? await services.industries.unwatch(item.code)
        : await services.industries.watch(item.code);
      setIndustries((prev) => prev.map((i) => ({
        ...i,
        watched: next.some((w) => w.code === i.code),
      })));
      if (!item.watched) void open(item.code);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [fail, open]);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      await services.industries.refresh(365);
      if (selected) void open(selected);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [fail, open, selected]);

  const watched = industries.filter((i) => i.watched);
  const current = industries.find((i) => i.code === selected);

  return (
    <section className="panel">
      <header>
        <h2>行业监控</h2>
        <span className="badge">申万一级 · {watched.length} 个在监控</span>
        <button className="ghost small" disabled={busy} onClick={refresh}>
          {busy ? "检测中…" : "刷新行业事件"}
        </button>
      </header>

      <div className="chips">
        {watched.map((w) => (
          <span key={w.code} className="chip">
            <button className="chip-name" onClick={() => void open(w.code)}>
              {w.name}
            </button>
            <button className="chip-x" disabled={busy} onClick={() => void toggle(w)}
                    title="移出监控">×</button>
          </span>
        ))}
        {watched.length === 0 && <span className="muted">还没有监控的行业</span>}
      </div>

      <div className="industry-add">
        <select value={picked} onChange={(e) => setPicked(e.target.value)}>
          <option value="">选择行业（共 {industries.length} 个）</option>
          {industries.map((i) => (
            <option key={i.code} value={i.code} disabled={i.watched}>
              {i.name}（{i.stock_count ?? "—"} 只）{i.watched ? " · 已监控" : ""}
            </option>
          ))}
        </select>
        <button disabled={!picked || busy}
                onClick={() => {
                  const item = industries.find((i) => i.code === picked);
                  if (item) void toggle({ ...item, watched: false });
                }}>
          加入监控
        </button>
      </div>

      {loading && <p className="loading">加载行业指数…</p>}

      {current && series && (
        <>
          <h3>
            {current.name} 指数
            <span className="muted">
              {" "}· {current.stock_count ?? "—"} 只成分股
              {current.pe_ttm !== null ? ` · PE(TTM) ${current.pe_ttm}` : ""}
              {current.pb !== null ? ` · PB ${current.pb}` : ""}
            </span>
          </h3>
          <PriceChart series={series} events={events} height={220} />
          <h3>行业事件（{events.length}）</h3>
          <EventList events={events} />
        </>
      )}

      {!current && !loading && (
        <p className="empty">选择或加入一个行业，查看行业指数走势与事件。</p>
      )}
    </section>
  );
}
