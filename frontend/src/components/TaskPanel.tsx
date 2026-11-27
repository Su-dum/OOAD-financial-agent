/**
 * 分析任务面板（C1）。
 *
 * 把「看哪只票、多长区间、和谁比」存成任务，一键重跑：
 * 指标 + 事件 + 跨期 + 跨资产四块结果一起出来。
 *
 * 任务只保存**参数**，结果每次重算——结果存下来必然过期。
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import { TaskDTO, TaskRunDTO } from "../models";
import { PeriodTable } from "./PeriodTable";

interface Props {
  code: string;
  days: number;
  onLoad?: (code: string, days: number) => void;
  /** 主页面当前是否为「自定义起止日期」；是的话要提示任务只存天数 */
  customRange?: { start: string; end: string } | null;
}

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`;
const num = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toFixed(2);

export function TaskPanel({ code, days, onLoad, customRange }: Props) {
  const [tasks, setTasks] = useState<TaskDTO[]>([]);
  const [name, setName] = useState("");
  const [compare, setCompare] = useState("");
  const [run, setRun] = useState<TaskRunDTO | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setTasks(await services.tasks.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const codes = compare.split(",").map((s) => s.trim()).filter(Boolean);
      const next = await services.tasks.create({
        name: name.trim() || `${code} 分析`, code, days,
        compare_codes: codes,
      });
      setTasks(next);
      setName("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    setBusy(true);
    try {
      setTasks(await services.tasks.remove(id));
      if (run?.task.id === id) setRun(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const execute = async (id: number) => {
    setBusy(true);
    setError("");
    try {
      setRun(await services.tasks.run(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <header>
        <h2>分析任务</h2>
        <span className="badge">保存「标的 + 区间 + 对比组」，一键重跑</span>
      </header>

      <div className="task-create">
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder={`任务名（默认：${code} 分析）`} maxLength={40} />
        <input value={compare} onChange={(e) => setCompare(e.target.value)}
               placeholder="对比标的（可选，逗号分隔）" />
        <button disabled={busy} onClick={() => void create()}>
          保存当前配置（{code} · {days} 天）
        </button>
      </div>

      {customRange && (
        <p className="muted">
          注意：主页面当前是自定义区间 {customRange.start} ~ {customRange.end}。
          分析任务只保存「天数」（这里的 {days} 天），保存后按「最近 {days} 天」重算，
          <b>不会记住具体起止日期</b>。需要固定日期请直接用上面的日期选择器。
        </p>
      )}

      {error && <p className="error">{error}</p>}

      <ul className="task-list">
        {tasks.map((t) => (
          <li key={t.id}>
            <div>
              <b>{t.name}</b>
              <span className="muted">
                {" "}· {t.code} · {t.days} 天
                {t.compare_codes.length ? ` · 对比 ${t.compare_codes.join("/")}` : ""}
                {t.last_run_at ? ` · 上次运行 ${t.last_run_at}` : ""}
              </span>
            </div>
            <div className="task-actions">
              <button disabled={busy} onClick={() => void execute(t.id)}>运行</button>
              {onLoad && (
                <button className="ghost" disabled={busy}
                        onClick={() => onLoad(t.code, t.days)}>载入</button>
              )}
              <button className="ghost danger" disabled={busy}
                      onClick={() => void remove(t.id)}>删除</button>
            </div>
          </li>
        ))}
        {tasks.length === 0 && <li className="empty">还没有任务，保存一个试试。</li>}
      </ul>

      {run && (
        <div className="task-result">
          <h3>
            {run.task.name} 结果
            <span className="muted"> · 任务区间 {run.start} ~ {run.end}</span>
          </h3>

          {run.indicator ? (
            <>
              {/* 下面这块指标是「主力标的」在任务全区间上的表现，
                  必须显式标出来——否则数字对不上任何一行跨期表。 */}
              <h4 className="subject">
                主力标的 {run.indicator.code} {run.indicator.name}
                {run.indicator.industry_l1 && (
                  <span className="muted"> · {run.indicator.industry_l1}</span>
                )}
                <span className="muted">
                  {" "}· 全区间 {run.start} ~ {run.end} ·{" "}
                  {run.indicator.n_days} 个交易日
                </span>
              </h4>
              <div className="kv">
                <div><dt>累计收益</dt><dd>{pct(run.indicator.total_return)}</dd></div>
                <div><dt>年化波动</dt><dd>{pct(run.indicator.annualized_volatility)}</dd></div>
                <div><dt>最大回撤</dt><dd>{pct(run.indicator.max_drawdown)}</dd></div>
                <div><dt>夏普</dt><dd>{num(run.indicator.sharpe)}</dd></div>
                <div><dt>事件</dt><dd>{run.event_count} 个</dd></div>
                <div><dt>ROE</dt><dd>{num(run.indicator.roe)}%</dd></div>
              </div>
            </>
          ) : <p className="empty">区间内没有行情数据。</p>}

          {run.periods.length > 0 && (
            <>
              <h4 className="subject">
                跨期比较
                <span className="muted">
                  {" "}· 同一标的 {run.task.code} 在不同时间段的表现
                  （收益为区间累计，波动 / 回撤 / 夏普为年化口径）
                </span>
              </h4>
              <PeriodTable rows={run.periods} />
            </>
          )}

          {run.cross && (
            <>
              <h3>
                横向对比（{run.cross.n_days} 个共同交易日）
                <span className="muted">
                  {" "}· 含主力标的 {run.task.code} 与任务配置的对比组
                </span>
              </h3>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr><th>标的</th><th>区间收益</th><th>β</th><th>与基准相关</th></tr>
                  </thead>
                  <tbody>
                    {run.cross.assets.map((a) => (
                      <tr key={a.code}>
                        <td>
                          {a.code} {a.name}
                          {a.code === run.task.code && (
                            <span className="badge" style={{ marginLeft: 6 }}>主力</span>
                          )}
                        </td>
                        <td>{pct(a.total_return)}</td>
                        <td>{num(a.beta)}</td>
                        <td>{num(a.corr_to_benchmark)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {run.events.length > 0 && (
            <p className="muted">
              最近事件：
              {run.events.slice(0, 3)
                .map((e) => `${e.trade_date} ${e.label ?? e.event_type}`)
                .join("；")}。
            </p>
          )}
          <p className="muted">生成于 {run.generated_at}</p>
        </div>
      )}

    </section>
  );
}
