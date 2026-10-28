/** 调查报告：事实与推测**分栏展示**，证据可追溯。 */
import { InvestigationReport } from "../models";

export function ReportView({ report }: { report: InvestigationReport }) {
  const r = report;
  return (
    <section className="panel report">
      <header>
        <h2>{r.dto.name || r.dto.code} 事件调查报告</h2>
        <span className="badge">置信度 {r.confidenceText}</span>
      </header>

      {r.dto.question && <p className="question">{r.dto.question}</p>}

      <h3>调查步骤（{r.dto.tasks.length}）</h3>
      <ol className="tasks">
        {r.dto.tasks.map((t, idx) => (
          <li key={idx} className={t.status}>
            {t.question}
            <span className="meta">（{t.tool}，命中 {t.result_count} 条）</span>
          </li>
        ))}
      </ol>

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
            <span className="kind">{e.kind}</span>
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
