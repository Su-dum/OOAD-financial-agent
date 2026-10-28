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

  async list(code: string, limit = 20) {
    return this.http.get<{ items: { id: number; created_at: string; question: string }[] }>(
      `/stocks/${encodeURIComponent(code)}/reports?limit=${limit}`,
    );
  }
}
