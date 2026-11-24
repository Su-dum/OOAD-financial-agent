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
  // 财务快照（A1）：单位是百分数本身（23.77 = 23.77%）
  net_margin: number | null;
  gross_margin: number | null;
  debt_ratio: number | null;
  eps: number | null;
  financial_report_date: string | null;
  financial_source: string | null;
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
  /** 后端给的中文事件名（domain/events.py），前端优先用它 */
  label?: string;
  trade_date: string;
  detected_at: string;
  severity: "low" | "medium" | "high";
  value: number | null;
  threshold: number | null;
  detail: string;
  rule_name: string;
  /** 公告类事件带原始公告链接，便于追溯 */
  source_url?: string | null;
}

export class MarketEvent {
  constructor(readonly dto: EventDTO) {}

  static readonly LABELS: Record<string, string> = {
    price_drop: "下跌异动",
    price_surge: "上涨异动",
    volume_spike: "放量异动",
    statistical_anomaly: "统计异常",
    // 公告类（B2：earnings announcements / major corporate events）
    notice_earnings: "财报披露",
    notice_dividend: "分红派息",
    notice_buyback: "股份回购",
    notice_insider_increase: "股东增持",
    notice_insider_decrease: "股东减持",
    notice_major_deal: "重大交易",
    notice_clarification: "异动澄清",
    notice_regulatory: "监管事项",
    notice_equity_change: "股本变动",
    notice_management: "高管变动",
    notice_procedural: "程序性公告",
    generic: "事件",
  };

  get label(): string {
    return this.dto.label ?? MarketEvent.LABELS[this.dto.event_type] ?? this.dto.event_type;
  }
  get severityClass(): string { return `sev-${this.dto.severity}`; }
  get isNotice(): boolean { return this.dto.event_type.startsWith("notice_"); }
}

export interface EvidenceDTO {
  /** event / cross 是追问用的证据类型；报告里只出现 news/notice/indicator */
  kind: string;
  source: string;
  title: string;
  url: string | null;
  published_at: string | null;
  excerpt: string;
  confidence: number;
}

/** 调查报告里的子任务（多步骤调查单元） */
export interface InvestigationTaskDTO {
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
  tasks: InvestigationTaskDTO[];
  evidences: EvidenceDTO[];
  facts: string[];
  hypotheses: string[];
  conclusion: string;
  confidence: number;
  created_at: string;
  /** 结论元信息：degraded / auto / model / cited_evidence_ids ... */
  llm_meta?: Record<string, unknown>;
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

// ============================================================
// 图表（C3）：价格序列与跨资产
// ============================================================
export interface SeriesPointDTO {
  date: string;
  close: number;
  volume: number | null;
  pe_ttm: number | null;
  pb: number | null;
}

export interface SeriesDTO {
  code: string;
  name: string;
  industry_l1: string;
  start: string;
  end: string;
  adjust: string;
  source: string;
  n_days: number;
  points: SeriesPointDTO[];
}

/** 一段价格序列的视图对象：只做取点 / 极值 / 格式化，不重算指标。 */
export class Series {
  constructor(readonly dto: SeriesDTO) {}

  get points(): SeriesPointDTO[] { return this.dto.points; }
  get first(): SeriesPointDTO | undefined { return this.dto.points[0]; }
  get last(): SeriesPointDTO | undefined { return this.dto.points[this.dto.points.length - 1]; }

  get periodReturn(): number | null {
    if (!this.first || !this.last || this.first.close <= 0) return null;
    return this.last.close / this.first.close - 1;
  }

  /** 归一化净值（首日 = 100），用于「相对表现」图 */
  get netValues(): number[] {
    const f = this.first?.close ?? 0;
    if (f <= 0) return [];
    return this.dto.points.map((p) => (p.close / f) * 100);
  }

  get provenance(): string {
    return `${this.dto.source} / ${this.dto.adjust} / ${this.dto.n_days} 个交易日`;
  }
}

export interface CrossAssetDTO {
  code: string;
  name: string;
  industry_l1: string;
  total_return: number | null;
  annualized_return: number | null;
  annualized_volatility: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  beta?: number | null;
  corr_to_benchmark?: number | null;
  tracking_error?: number | null;
  excess_return?: number | null;
}

export interface CorrelationDTO {
  codes: string[];
  matrix: (number | null)[][];
}

export interface NetValueDTO {
  dates: string[];
  series: { code: string; name: string; values: number[] }[];
}

export interface BenchmarkDTO {
  symbol: string;
  name: string;
  total_return: number | null;
  annualized_volatility: number | null;
  source: string;
  net_value: number[];
}

export interface CrossDTO {
  start: string;
  end: string;
  n_days: number;
  adjust?: string;
  source?: string;
  assets: CrossAssetDTO[];
  correlation: CorrelationDTO;
  net_value: NetValueDTO;
  benchmark?: BenchmarkDTO | null;
  note?: string;
}

export class CrossAsset {
  constructor(readonly dto: CrossDTO) {}

  get hasCorrelation(): boolean {
    return (this.dto.correlation?.matrix?.length ?? 0) > 1;
  }

  get leader(): CrossAssetDTO | undefined {
    return this.dto.assets[0];
  }

  getBenchmarkLine(): number[] {
    return this.dto.benchmark?.net_value ?? [];
  }

  /** 相关系数 -> 语义标签（前端只做展示映射，不做统计） */
  static corrLabel(v: number | null): string {
    if (v === null || v === undefined) return "—";
    const a = Math.abs(v);
    const dir = v > 0 ? "正" : "负";
    if (a >= 0.7) return `强${dir}相关`;
    if (a >= 0.4) return `中等${dir}相关`;
    if (a >= 0.2) return `弱${dir}相关`;
    return "几乎无关";
  }
}

// ============================================================
// 自然语言追问（C2）
// ============================================================
export interface ChatEvidenceDTO {
  id: number;
  kind: string;
  source: string;
  title: string;
  url: string | null;
  published_at: string | null;
  excerpt: string;
  confidence: number;
}

export interface ChatAction {
  type: "set_alert" | "set_range" | "add_watchlist" | string;
  describe: string;
  rule_type?: string;
  params?: Record<string, number>;
  days?: number;
  code?: string;
}

export interface ChatApplied {
  action: ChatAction;
  ok: boolean;
  effective?: Record<string, number | string>;
  error?: string;
  name?: string;
}

export interface ChatAnswerDTO {
  question: string;
  code: string;
  start: string;
  end: string;
  intent: string;
  answer: string;
  cited_evidence_ids: number[];
  evidences: ChatEvidenceDTO[];
  actions: ChatAction[];
  applied: ChatApplied[];
  llm_meta: {
    enabled: boolean;
    degraded: boolean;
    reason?: string;
    insufficient_evidence?: boolean;
    confidence?: number;
  };
}

/** 一条对话消息（前端本地状态，不入库） */
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  answer?: ChatAnswerDTO;
}

// ============================================================
// 预警条件（C1）
// ============================================================
export interface AlertRuleDTO {
  rule_type: string;
  label: string;
  params: Record<string, number | string | string[]>;
  defaults: Record<string, number | string | string[]>;
  enabled: boolean;
  source: "default" | "global" | "code";
  bounds: Record<string, [number, number]>;
  is_percent: boolean;
}

// ============================================================
// 跨期比较（A3）
// ============================================================
export interface PeriodRowDTO {
  period: string;
  start: string;
  end: string;
  total_return: number | null;
  annualized_volatility: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  n_days: number;
}

// ============================================================
// 财务快照（A1）
// ============================================================
export interface FinancialFieldDTO {
  field: string;
  label: string;
  description: string;
}

export interface FinancialDTO {
  code: string;
  name: string;
  industry_l1: string;
  snapshot: Record<string, number | string | null> | null;
  fields: FinancialFieldDTO[];
  stale: boolean;
  ttl_days: number;
  fetched_at: string | null;
}

// ============================================================
// 行业监控（B1）
// ============================================================
export interface IndustryDTO {
  code: string;
  name: string;
  level: string;
  stock_count: number | null;
  pe_static: number | null;
  pe_ttm: number | null;
  pb: number | null;
  dividend_yield: number | null;
  watched: boolean;
  added_at?: string | null;
  event_count?: number;
  latest_event?: EventDTO | null;
}

// ============================================================
// 分析任务（C1）
// ============================================================
export interface TaskDTO {
  id: number;
  name: string;
  code: string;
  days: number;
  compare_codes: string[];
  benchmark: string | null;
  created_at: string;
  last_run_at: string;
}

export interface TaskRunDTO {
  task: TaskDTO;
  start: string;
  end: string;
  generated_at: string;
  indicator: IndicatorDTO | null;
  events: EventDTO[];
  event_count: number;
  periods: PeriodRowDTO[];
  cross: {
    n_days: number;
    assets: CrossAssetDTO[];
    correlation: CorrelationDTO;
    benchmark: BenchmarkDTO | null;
    note?: string;
  } | null;
}
