/** 调查报告：事实与推测**分栏展示**，证据可追溯。 */
import { InvestigationReport } from "../models";

/** 证据类别 -> 中文（避免把 notice_text 这种内部标识直接给用户看） */
const KIND_LABEL: Record<string, string> = {
  news: "新闻",
  notice: "公告",
  notice_text: "公告正文",
  indicator: "指标",
  industry: "行业指数",
  cross: "跨资产",
  event: "事件",
};

export function ReportView({ report }: { report: InvestigationReport }) {
  const r = report;
  const meta = r.dto.llm_meta ?? {};
  const auto = meta.auto === true;
  const planner = r.dto.planner ?? "";
  const plannerLabel = planner === "llm" ? "LLM 逐步决策"
    : planner === "heuristic" ? "规则逐步决策" : "";
  return (
    <section className="panel report">
      <header>
        <h2>{r.dto.name || r.dto.code} 事件调查报告</h2>
        {auto && <span className="badge warn">自动调查</span>}
        <span className="badge">置信度 {r.confidenceText}</span>
        {plannerLabel && (
          <span className="badge" title="调查步骤由谁决定下一步（D2 动态多步调查）">
            {plannerLabel}
          </span>
        )}
      </header>

      {r.dto.question && <p className="question">{r.dto.question}</p>}

      <h3>调查步骤（{r.dto.tasks.length}）</h3>
      <ol className="tasks">
        {r.dto.tasks.map((t, idx) => (
          <li key={idx} className={t.status}>
            第 {t.step ?? idx + 1} 步：{t.question}
            <span className="meta">（{t.action || t.tool}，命中 {t.result_count} 条）</span>
            {t.reason && <p className="task-reason">为什么走这步：{t.reason}</p>}
          </li>
        ))}
      </ol>
      {r.dto.stop_reason && (
        <p className="muted">结束原因：{r.dto.stop_reason}</p>
      )}

      <div className="two-col">
        <div>
          <h3>事实（有证据支持）</h3>
          <ul>{r.dto.facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
        </div>
        <div>
          <h3>推测（尚未证实）</h3>
          <ul className="hypo">{r.dto.hypotheses.map((h, i) => <li key={i}>{h}</li>)}</ul>
        </div>
      </div>

      {r.dto.conclusion && (
        <>
          <h3>结论</h3>
          <p className="conclusion">{r.dto.conclusion}</p>
        </>
      )}

      <h3>证据来源（{r.dto.evidences.length}）</h3>
      <ol className="evidences">
        {r.dto.evidences.map((e, i) => (
          <li key={i}>
            <span className="kind">{KIND_LABEL[e.kind] ?? e.kind}</span>
            <span className="src">{e.source}</span>
            {e.url ? (
              <a href={e.url} target="_blank" rel="noreferrer">
                {e.title}
              </a>
            ) : (
              <span>{e.title}</span>
            )}
            <span className="when">{e.published_at ?? ""}</span>
            {e.excerpt && <p className="excerpt">{e.excerpt}</p>}
          </li>
        ))}
      </ol>

      <footer className="provenance">生成于 {r.dto.created_at}</footer>
    </section>
  );
}
