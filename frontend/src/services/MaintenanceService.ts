/**
 * 运维服务：数据更新、自选股、保留策略。
 */
import { HttpClient } from "./HttpClient";
import { EventDTO, MarketEvent } from "../models";

export interface IngestStat {
  source: string;
  fetched: number;
  inserted: number;
  skipped: number;
  linked: number;
  pages: number;
  stopped_by: string;
}

export interface PruneResult {
  news_deleted: number;
  events_deleted: number;
  vacuumed: boolean;
  news_before: number;
  news_after: number;
  freed_rows: number;
}

export interface NoticeIngestStat {
  code: string;
  source: string;
  fetched: number;
  inserted: number;
  classified: number;
  stopped_by: string;
}

export interface FinancialIngestStat {
  code: string;
  source: string;
  report_date: string;
  updated: boolean;
  stopped_by: string;
}

export interface RefreshResult {
  started_at: string;
  elapsed_sec: number;
  news: IngestStat[];
  notices?: NoticeIngestStat[];
  financials?: FinancialIngestStat[];
  events_detected: number;
  events_saved: number;
  notice_events?: number;
  stocks_scanned: number;
  failed_stocks: string[];
  industry_events?: { scanned: number; events_detected: number; events_saved: number };
  auto_reports?: { report_id: number; code: string; trade_date: string; event_type: string }[];
  auto_failed?: { code: string; trade_date: string; error: string }[];
  prune: PruneResult | { error: string };
  news_total_before: number;
  news_total_after: number;
  note: string;
}

export interface WatchItem {
  code: string;
  name: string;
  industry: string;
  added_at: string;
  note: string;
}

export interface RetentionPolicy {
  news_days: number;
  event_days: number;
  news_cutoff: string;
  event_cutoff: string;
}

/** 一次巡检的结果摘要（定时与手动共用同一形状） */
export interface MonitorRun {
  profile: "light" | "full";
  slot: string | null;
  started_at: string;
  ok: boolean;
  elapsed_sec: number;
  events_detected?: number;
  notice_events?: number;
  industry_events?: number;
  auto_reports?: number;
  stocks_scanned?: number;
  note?: string;
  error?: string;
  finished_at?: string;
}

export interface MonitorStatus {
  enabled: boolean;
  interval_minutes: number;
  light_window: { start: string; end: string };
  full_slots: string[];
  detect_days: number;
  skip_weekends: boolean;
  tick_seconds: number;
  running_profile: "light" | "full" | null;
  last_run: MonitorRun | null;
  next_run_at: string | null;
  history: MonitorRun[];
}

/** 右上角提醒的一条重大事件（B3 的通知面） */
export interface AlertItem {
  code: string;
  name: string;
  event_type: string;
  label: string;
  trade_date: string;
  detected_at: string;
  severity: "low" | "medium" | "high";
  detail: string;
  source_url: string | null;
  /** 有现成 AI 分析时非空，点开直接看；为空则点开现场跑一次 */
  report_id: number | null;
  report_ready: boolean;
  confidence: number | null;
  headline: string;
  llm_model: string;
  degraded: boolean;
}

export interface AlertFeed {
  count: number;
  since: string;
  since_clamped: boolean;
  min_severity: string;
  now: string;
  items: AlertItem[];
}

export class MaintenanceService {
  constructor(private readonly http: HttpClient) {}

  /** 一键更新：新闻增量 + 快照 + 自选股事件落库 + 清理 */
  async refresh(opts?: {
    newsDays?: number;
    maxPages?: number;
    detectDays?: number;
    prune?: boolean;
  }): Promise<RefreshResult> {
    const qs = new URLSearchParams();
    if (opts?.newsDays !== undefined) qs.set("news_days", String(opts.newsDays));
    if (opts?.maxPages !== undefined) qs.set("max_pages", String(opts.maxPages));
    if (opts?.detectDays !== undefined) qs.set("detect_days", String(opts.detectDays));
    if (opts?.prune !== undefined) qs.set("prune", String(opts.prune));
    return this.http.post<RefreshResult>(`/refresh?${qs}`);
  }

  async watchlist(): Promise<WatchItem[]> {
    const body = await this.http.get<{ items: WatchItem[] }>("/watchlist");
    return body.items;
  }

  async addWatch(code: string): Promise<void> {
    await this.http.post("/watchlist", { code });
  }

  async removeWatch(code: string): Promise<void> {
    await this.http.delete<void>(`/watchlist/${code}`);
  }

  /** 定时巡检状态（排班 / 上次结果 / 下次触发） */
  async monitorStatus(): Promise<MonitorStatus> {
    return this.http.get<MonitorStatus>("/monitor/status");
  }

  /** 立刻巡检一次（手动补救 / 演示，不等排班） */
  async monitorRunNow(profile: "light" | "full" = "light"): Promise<MonitorRun> {
    return this.http.post<MonitorRun>(`/monitor/run-now?profile=${profile}`, {});
  }

  /**
   * 重大事件提醒。`since` 传「上次看到提醒的时间」，
   * 后端只返回此后**新检测到**的事件（不是按事件发生日，否则会弹一堆历史）。
   */
  async alerts(since?: string, opts?: {
    limit?: number;
    minSeverity?: "low" | "medium" | "high";
  }): Promise<AlertFeed> {
    const qs = new URLSearchParams();
    if (since) qs.set("since", since);
    if (opts?.limit !== undefined) qs.set("limit", String(opts.limit));
    if (opts?.minSeverity) qs.set("min_severity", opts.minSeverity);
    return this.http.get<AlertFeed>(`/monitor/alerts?${qs}`);
  }

  /** 自选股的事件（已落库的） */
  async watchlistEvents(limit = 50): Promise<{ watchlist: WatchItem[]; events: MarketEvent[] }> {
    const body = await this.http.get<{ watchlist: WatchItem[]; items: EventDTO[] }>(
      `/events/watchlist?limit=${limit}`,
    );
    return { watchlist: body.watchlist, events: body.items.map((d) => new MarketEvent(d)) };
  }

  async retention(): Promise<RetentionPolicy> {
    const s = await this.http.get<{ policy: RetentionPolicy }>("/maintenance/stats");
    return s.policy;
  }

  async prune(dryRun = true): Promise<PruneResult> {
    return this.http.post<PruneResult>(
      `/maintenance/prune?dry_run=${dryRun}`,
      {},
    );
  }
}
