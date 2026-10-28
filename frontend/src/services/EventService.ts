/** 事件服务：检测与查询。 */
import { HttpClient } from "./HttpClient";
import { EventDTO, MarketEvent } from "../models";

export class EventService {
  constructor(private readonly http: HttpClient) {}

  async detect(code: string, opts?: { start?: string; end?: string; persist?: boolean }) {
    const qs = new URLSearchParams();
    if (opts?.start) qs.set("start", opts.start);
    if (opts?.end) qs.set("end", opts.end);
    if (opts?.persist) qs.set("persist", "true");
    const body = await this.http.get<{ items: EventDTO[]; count: number }>(
      `/stocks/${encodeURIComponent(code)}/events?${qs}`,
    );
    return body.items.map((d) => new MarketEvent(d));
  }

  async recent(code?: string, limit = 50): Promise<MarketEvent[]> {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (code) qs.set("code", code);
    const body = await this.http.get<{ items: EventDTO[] }>(`/events?${qs}`);
    return body.items.map((d) => new MarketEvent(d));
  }
}
