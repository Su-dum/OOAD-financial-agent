/** 报告服务：发起调查与查询报告。 */
import { HttpClient } from "./HttpClient";
import { InvestigationReport, ReportDTO } from "../models";

export interface InvestigatePayload {
  code: string;
  trade_date?: string;
  event_type?: string;
  days?: number;
  question?: string;
  persist?: boolean;
  /** 从事件列表/提醒带过来的真实字段，让报告更贴合事实 */
  severity?: "low" | "medium" | "high";
  value?: number | null;
  threshold?: number | null;
  detail?: string;
}

export class ReportService {
  constructor(private readonly http: HttpClient) {}

  async investigate(payload: InvestigatePayload): Promise<InvestigationReport> {
    const body = await this.http.post<{ report: ReportDTO; report_id: number }>(
      "/stocks/investigate",
      payload,
    );
    return new InvestigationReport(body.report);
  }

  /** 按 id 取整份报告（右上角提醒点开时用，拿的是后端已存好的分析） */
  async get(id: number): Promise<InvestigationReport> {
    const body = await this.http.get<{ payload: ReportDTO }>(`/reports/${id}`);
    return new InvestigationReport(body.payload);
  }

  async list(code: string, limit = 20) {
    return this.http.get<{ items: { id: number; created_at: string; question: string }[] }>(
      `/stocks/${encodeURIComponent(code)}/reports?limit=${limit}`,
    );
  }
}
