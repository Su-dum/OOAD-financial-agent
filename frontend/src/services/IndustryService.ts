/**
 * 行业监控服务（B1）。
 *
 * 行业是申万一级的 31 个指数——和个股一样有日线，所以图表组件可以直接复用。
 */
import { HttpClient } from "./HttpClient";
import { EventDTO, IndustryDTO, MarketEvent, Series, SeriesDTO } from "../models";

export class IndustryService {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<IndustryDTO[]> {
    const body = await this.http.get<{ items: IndustryDTO[] }>("/industries");
    return body.items;
  }

  async watched(): Promise<IndustryDTO[]> {
    const body = await this.http.get<{ items: IndustryDTO[] }>("/industries/watched");
    return body.items;
  }

  async watch(code: string): Promise<IndustryDTO[]> {
    const body = await this.http.post<{ watched: IndustryDTO[] }>(
      `/industries/${encodeURIComponent(code)}/watch`, {},
    );
    return body.watched;
  }

  async unwatch(code: string): Promise<IndustryDTO[]> {
    const body = await this.http.delete<{ watched: IndustryDTO[] }>(
      `/industries/${encodeURIComponent(code)}/watch`,
    );
    return body.watched;
  }

  async series(code: string, days = 365): Promise<Series> {
    const dto = await this.http.get<SeriesDTO>(
      `/industries/${encodeURIComponent(code)}/series?days=${days}`,
    );
    return new Series(dto);
  }

  async events(code: string, days = 365): Promise<MarketEvent[]> {
    const body = await this.http.get<{ items: EventDTO[] }>(
      `/industries/${encodeURIComponent(code)}/events?days=${days}`,
    );
    return body.items.map((d) => new MarketEvent(d));
  }

  async refresh(days = 365): Promise<{ scanned: number; events_detected: number; events_saved: number }> {
    return this.http.post(`/industries/refresh?days=${days}`, {});
  }
}
