/**
 * 股票服务：封装与股票相关的接口调用。
 * 组件只依赖这个类，不直接拼 URL。
 */
import { HttpClient } from "./HttpClient";
import {
  CrossAsset,
  CrossDTO,
  FinancialDTO,
  Indicator,
  IndicatorDTO,
  PeriodRowDTO,
  Series,
  SeriesDTO,
} from "../models";

export interface RangeOpts {
  start?: string;
  end?: string;
  source?: string;
}

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

  /** 图表数据：收盘价 + 成交量 + 估值（点数已在后端抽样） */
  async series(code: string, opts: RangeOpts = {}): Promise<Series> {
    const qs = new URLSearchParams();
    if (opts.start) qs.set("start", opts.start);
    if (opts.end) qs.set("end", opts.end);
    if (opts.source) qs.set("source", opts.source);
    const dto = await this.http.get<SeriesDTO>(
      `/stocks/${encodeURIComponent(code)}/series?${qs.toString()}`,
    );
    return new Series(dto);
  }

  async compare(codes: string[], start?: string, end?: string): Promise<Indicator[]> {
    const qs = new URLSearchParams({ codes: codes.join(",") });
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    const body = await this.http.get<{ items: IndicatorDTO[] }>(`/stocks/compare?${qs}`);
    return body.items.map((d) => new Indicator(d));
  }

  /** D3：跨资产分析（相对表现 / 相关性 / 基准） */
  async cross(codes: string[], opts: RangeOpts & { benchmark?: string } = {}): Promise<CrossAsset> {
    const qs = new URLSearchParams({ codes: codes.join(",") });
    if (opts.start) qs.set("start", opts.start);
    if (opts.end) qs.set("end", opts.end);
    if (opts.source) qs.set("source", opts.source);
    if (opts.benchmark !== undefined) qs.set("benchmark", opts.benchmark);
    const dto = await this.http.get<CrossDTO>(`/stocks/cross?${qs.toString()}`);
    return new CrossAsset(dto);
  }

  /** A3：同一只票在不同区间的表现 */
  async periods(code: string, windows?: string): Promise<PeriodRowDTO[]> {
    const qs = new URLSearchParams();
    if (windows) qs.set("windows", windows);
    const body = await this.http.get<{ items: PeriodRowDTO[] }>(
      `/stocks/${encodeURIComponent(code)}/periods?${qs.toString()}`,
    );
    return body.items;
  }

  /** A1：财务快照（读本地，不联网） */
  async financials(code: string): Promise<FinancialDTO> {
    return this.http.get<FinancialDTO>(
      `/stocks/${encodeURIComponent(code)}/financials`,
    );
  }

  /** A1：刷新财务快照（打外部接口，用户显式点击才调） */
  async refreshFinancials(code: string, years = 3): Promise<FinancialDTO> {
    return this.http.post<FinancialDTO>(
      `/stocks/${encodeURIComponent(code)}/financials/refresh?years=${years}`,
      {},
    );
  }
}
