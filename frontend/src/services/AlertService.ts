/**
 * 预警条件服务（C1）：读 / 改 / 重置。
 *
 * 后端是「默认 -> 全局 -> 个股」两级覆盖，前端只按当前股票读写，
 * 不会在本地合并配置（避免两端规则不一致）。
 */
import { HttpClient } from "./HttpClient";
import { AlertRuleDTO } from "../models";

export interface AlertUpdatePayload {
  rule_type: string;
  params: Record<string, number | string | string[]>;
  code?: string | null;
  enabled?: boolean;
}

export class AlertService {
  constructor(private readonly http: HttpClient) {}

  async list(code?: string): Promise<AlertRuleDTO[]> {
    const qs = code ? `?code=${encodeURIComponent(code)}` : "";
    const body = await this.http.get<{ items: AlertRuleDTO[] }>(`/alerts${qs}`);
    return body.items;
  }

  async update(payload: AlertUpdatePayload): Promise<AlertRuleDTO[]> {
    const body = await this.http.put<{ items: AlertRuleDTO[] }>("/alerts", payload);
    return body.items;
  }

  async reset(ruleType: string, code?: string): Promise<AlertRuleDTO[]> {
    const qs = code ? `?code=${encodeURIComponent(code)}` : "";
    const body = await this.http.delete<{ items: AlertRuleDTO[] }>(
      `/alerts/${encodeURIComponent(ruleType)}${qs}`,
    );
    return body.items;
  }
}
