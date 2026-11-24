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
