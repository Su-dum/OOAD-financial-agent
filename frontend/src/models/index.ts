/**
 * 领域模型（前端侧）。
 *
 * 与后端 `backend/app/domain/models.py` 一一对应。
 * 前端不重复业务计算，指标一律由后端算好返回，这里只负责
 * 「结构化 + 展示格式化」，避免两端算法漂移。
 */

export interface IndicatorDTO {
  code: string;
  name: string;
  industry_l1: string;
  start: string;
  end: string;
  n_days: number;
  adjust: string;
  source: string;
  first_close: number | null;
  last_close: number | null;
  total_return: number | null;
  annualized_return: number | null;
  win_rate: number | null;
  annualized_volatility: number | null;
  downside_deviation: number | null;
  max_drawdown: number | null;
  max_drawdown_peak: string | null;
  max_drawdown_trough: string | null;
  sharpe: number | null;
  sortino: number | null;
  pe_ttm: number | null;
  pb: number | null;
  pe_ttm_percentile: number | null;
  pb_percentile: number | null;
  roe: number | null;
  profit_growth: number | null;
  revenue_growth: number | null;
  market_cap: number | null;
}

/** 指标是一组只读事实的视图对象。 */
export class Indicator {
  constructor(readonly dto: IndicatorDTO) {}

  get code(): string { return this.dto.code; }
  get displayName(): string { return `${this.dto.code} ${this.dto.name}`.trim(); }

  static pct(v: number | null, digits = 2): string {
    return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
  }
  static pctSigned(v: number | null, digits = 2): string {
    return v === null || v === undefined
      ? "—"
      : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
  }
  static num(v: number | null, digits = 2): string {
    return v === null || v === undefined ? "—" : v.toFixed(digits);
  }

  get totalReturnText(): string { return Indicator.pctSigned(this.dto.total_return); }
  get volatilityText(): string { return Indicator.pct(this.dto.annualized_volatility); }
  get maxDrawdownText(): string { return Indicator.pct(this.dto.max_drawdown); }
  get sharpeText(): string { return Indicator.num(this.dto.sharpe, 3); }
  get peText(): string { return Indicator.num(this.dto.pe_ttm); }

  /** 数据口径提示：报告里必须能说清来源与复权方式 */
  get provenance(): string {
    return `${this.dto.source} / ${this.dto.adjust} / ${this.dto.n_days} 个交易日`;
  }
}

export interface EventDTO {
  code: string;
  name: string;
  event_type: string;
  trade_date: string;
  detected_at: string;
  severity: "low" | "medium" | "high";
  value: number | null;
  threshold: number | null;
  detail: string;
  rule_name: string;
}

export class MarketEvent {
  constructor(readonly dto: EventDTO) {}

  static readonly LABELS: Record<string, string> = {
    price_drop: "下跌异动",
    price_surge: "上涨异动",
    volume_spike: "放量异动",
    statistical_anomaly: "统计异常",
    generic: "事件",
  };

  get label(): string { return MarketEvent.LABELS[this.dto.event_type] ?? this.dto.event_type; }
  get severityClass(): string { return `sev-${this.dto.severity}`; }
}

export interface EvidenceDTO {
  kind: "news" | "notice" | "indicator";
  source: string;
  title: string;
  url: string | null;
  published_at: string | null;
  excerpt: string;
  confidence: number;
}

export interface TaskDTO {
  question: string;
  tool: string;
  status: string;
  result_count: number;
  note: string;
}

export interface ReportDTO {
  code: string;
  name: string;
  event: EventDTO | null;
  question: string;
  tasks: TaskDTO[];
  evidences: EvidenceDTO[];
  facts: string[];
  hypotheses: string[];
  conclusion: string;
  confidence: number;
  created_at: string;
}

export class InvestigationReport {
  constructor(readonly dto: ReportDTO) {}

  get evidencesByKind(): Record<string, EvidenceDTO[]> {
    return this.dto.evidences.reduce<Record<string, EvidenceDTO[]>>((acc, e) => {
      (acc[e.kind] ??= []).push(e);
      return acc;
    }, {});
  }

  get hasBothSides(): boolean {
    return this.dto.facts.length > 0 || this.dto.hypotheses.length > 0;
  }

  get confidenceText(): string {
    return `${Math.round(this.dto.confidence * 100)}%`;
  }
}
