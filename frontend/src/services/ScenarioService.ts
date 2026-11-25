/**
 * 情景分析服务（D4）。
 *
 * 注意：情景分析默认走**新浪快源**（source: "sina"）。
 * 情景是交互操作，不能让 baostock 的半挂起把页面卡住；新浪的 qfq 口径同样可信
 * （见 docs/datasource-eval.md §7.5）。
 */
import { HttpClient } from "./HttpClient";
import { ScenarioDTO } from "../models";

export interface ScenarioPayload {
  codes: string[];
  start?: string;
  end?: string;
  weights?: number[];
  market_shock?: number;
  vol_multiplier?: number;
  correlation_stress?: number;
  drawdown?: number | null;
  horizon_days?: number;
  benchmark?: string;
  source?: string | null;
}

export class ScenarioService {
  constructor(private readonly http: HttpClient) {}

  async run(payload: ScenarioPayload): Promise<ScenarioDTO> {
    return this.http.post<ScenarioDTO>("/scenario", {
      source: "sina",
      ...payload,
    });
  }
}
