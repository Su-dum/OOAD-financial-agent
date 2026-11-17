/**
 * 自然语言追问面板（C2）。
 *
 * 三条设计原则：
 *   1. **答案必须可追溯**：正文里的 [1][3] 是证据编号，点开能看到原公告/新闻。
 *   2. **动作要落地**：追问里说「阈值改成 3%」会真的改配置（后端已执行），
 *      说「看近半年」会把上方区间切过去（前端执行）——而不是只回一句「好的」。
 *   3. **降级要可见**：LLM 不可用时用模板答案，界面上明确标注来源，
 *      不能让用户以为那是模型写的。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { services } from "../services";
import { ChatAnswerDTO, ChatMessage } from "../models";

interface Props {
  code: string;
  start?: string;
  end?: string;
  event?: Record<string, unknown> | null;
  /** 「看近半年」这类动作：把分析区间切过去 */
  onApplyRange?: (days: number) => void;
  /** 预警条件被追问改动后，通知外层刷新配置 */
  onAlertsChanged?: () => void;
}

const INTENT_LABEL: Record<string, string> = {
  performance: "表现",
  reason: "成因",
  notice: "公告",
  events: "事件",
  news: "新闻",
  compare: "对比",
  overview: "概览",
};

export function ChatPanel({ code, start, end, event, onApplyRange, onAlertsChanged }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMessages([]);
    setError("");
    services.chat.suggestions(code).then(setSuggestions).catch(() => setSuggestions([]));
  }, [code]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  const send = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError("");
    setText("");
    const history = messages;
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    try {
      const ans = await services.chat.ask({
        question: q, code, start, end, event: event ?? null, history,
      });
      setMessages((prev) => [...prev, { role: "assistant", content: ans.answer, answer: ans }]);

      // 前端能执行的动作用前端执行（后端无状态）
      for (const act of ans.actions) {
        if (act.type === "set_range" && act.days) onApplyRange?.(act.days);
      }
      if (ans.applied?.some((a) => a.ok && a.action.type === "set_alert")) {
        onAlertsChanged?.();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setMessages((prev) => [...prev, {
        role: "assistant", content: `追问失败：${msg}`,
      }]);
    } finally {
      setBusy(false);
    }
  }, [busy, code, start, end, event, messages, onApplyRange, onAlertsChanged]);

  return (
    <section className="panel chat">
      <header>
        <h2>追问</h2>
        <span className="badge">答案带证据编号，可追溯</span>
        {busy && <span className="muted">思考中…</span>}
      </header>

      <div className="chat-log">
        {messages.length === 0 && (
          <p className="empty">
            可以直接问：为什么异动、有哪些财报公告、和同行业比如何；
            也可以说「把跌幅阈值改成 3%」「看近半年」来改条件。
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "user" ? (
              <div className="bubble">{m.content}</div>
            ) : (
              <AnswerBubble
                answer={m.answer}
                text={m.content}
                openId={openId}
                onToggleEvidence={setOpenId}
              />
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {error && <p className="error">{error}</p>}

      <div className="suggestions">
        {suggestions.map((s) => (
          <button key={s} className="chip-suggest" disabled={busy}
                  onClick={() => void send(s)}>{s}</button>
        ))}
      </div>

      <form className="search" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)}
               placeholder="追问这只票的情况，或说「把跌幅阈值改成 3%」" />
        <button type="submit" disabled={busy || !text.trim()}>发送</button>
      </form>
    </section>
  );
}

function AnswerBubble({
  answer, text, openId, onToggleEvidence,
}: {
  answer?: ChatAnswerDTO;
  text: string;
  openId: string | null;
  onToggleEvidence: (id: string | null) => void;
}) {
  const meta = answer?.llm_meta;
  const cited = answer?.cited_evidence_ids ?? [];
  return (
    <div className="bubble">
      <p className="answer">{text}</p>

      <div className="answer-meta">
        {answer?.intent && (
          <span className="badge">{INTENT_LABEL[answer.intent] ?? answer.intent}</span>
        )}
        {meta && !meta.enabled && <span className="badge">模板答案</span>}
        {meta?.degraded && (
          <span className="badge warn" title={meta.reason ?? ""}>LLM 降级</span>
        )}
        {meta?.enabled && !meta.degraded && <span className="badge">LLM 归纳</span>}
        {cited.length > 0 && (
          <span className="muted">
            依据：
            {cited.map((id) => (
              <button key={id} className="cite" onClick={() => onToggleEvidence(`ev-${id}`)}>
                [{id}]
              </button>
            ))}
          </span>
        )}
      </div>

      {answer?.applied && answer.applied.length > 0 && (
        <ul className="applied">
          {answer.applied.map((a, i) => (
            <li key={i} className={a.ok ? "ok" : "error"}>
              {a.ok ? "已执行" : "未执行"}：{a.action.describe}
              {a.error ? `（${a.error}）` : ""}
            </li>
          ))}
        </ul>
      )}

      {answer?.actions?.some((a) => a.type === "set_range") && (
        <p className="muted">区间参数已切换，上方图表与指标会按新区间重算。</p>
      )}

      {answer && answer.evidences.length > 0 && (
        <details className="evidences-box">
          <summary>证据（{answer.evidences.length}）</summary>
          <ol className="evidences">
            {answer.evidences.map((e) => (
              <li key={e.id} id={`ev-${e.id}`}
                  className={cited.includes(e.id) ? "cited" : openId === `ev-${e.id}` ? "open" : ""}>
                <span className="kind">{e.kind}</span>
                <span className="src">{e.source}</span>
                {e.url ? (
                  <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a>
                ) : <span>{e.title}</span>}
                <span className="when">{e.published_at ?? ""}</span>
                {e.excerpt && <p className="excerpt">{e.excerpt}</p>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
