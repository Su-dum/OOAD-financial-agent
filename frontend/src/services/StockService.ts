/**
 * 股票服务：封装与股票相关的接口调用。
 * 组件只依赖这个类，不直接拼 URL。
 */
import { HttpClient } from "./HttpClient";
import { Indicator, IndicatorDTO } from "../models";

export class StockService {
  constructor(private readonly http: HttpClient) {}

  async getIndicator(code: string, start?: string, end?: string): Promise<Indicator> {
    const qs = new URLSearchParams();
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    const dto = await this.http.get<IndicatorDTO>(
      `/stocks/${encodeURIComponent(code)}/indicators?${qs.toString()}`,
    );
    return new Indicator(dto);
  }

  async compare(codes: string[], start?: string, end?: string): Promise<Indicator[]> {
    const qs = new URLSearchParams({ codes: codes.join(",") });
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    const body = await this.http.get<{ items: IndicatorDTO[] }>(`/stocks/compare?${qs}`);
    return body.items.map((d) => new Indicator(d));
  }
}
