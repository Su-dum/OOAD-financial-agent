/**
 * 预警条件配置（C1：用户可以配置 alert conditions）。
 *
 * 展示的是**当前生效值**（后端已把「默认 -> 全局 -> 个股」合并好），
 * 保存时写的是**个股覆盖值**，所以改一只票不会影响其它票。
 *
 * 百分比规则在界面上用「5」表示 5%，提交时换算成 0.05 —— 换算只发生在这一层，
 * 后端与领域模型里始终是小数，避免两套口径。
 */
import { useCallback, useEffect, useState } from "react";
import { services } from "../services";
import { AlertRuleDTO } from "../models";

interface Props {
  code: string;
  onChanged?: () => void;
}

const SOURCE_LABEL: Record<string, string> = {
  default: "出厂默认",
  global: "全局配置",
  code: "个股覆盖",
};

function fieldValue(rule: AlertRuleDTO, key: string): string {
  const v = rule.params[key];
  if (v === undefined || v === null) return "";
  if (typeof v === "number") {
    return rule.is_percent ? (v * 100).toFixed(2) : String(v);
  }
  return String(v);
}

export function AlertConfig({ code, onChanged }: Props) {
  const [rules, setRules] = useState<AlertRuleDTO[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const items = await services.alerts.list(code);
      setRules(items);
      const next: Record<string, string> = {};
      for (const r of items) {
        for (const k of Object.keys(r.params)) {
          if (typeof r.params[k] === "number") {
            next[`${r.rule_type}.${k}`] = fieldValue(r, k);
          }
        }
      }
      setDraft(next);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [code]);

  useEffect(() => { void refresh(); }, [refresh]);

  const save = async (rule: AlertRuleDTO) => {
    setBusy(true);
    setMsg("");
    setError("");
    try {
      const params: Record<string, number | string> = {};
      for (const k of Object.keys(rule.bounds)) {
        const raw = draft[`${rule.rule_type}.${k}`];
        if (raw === undefined || raw.trim() === "") continue;
        const n = Number(raw);
        if (Number.isNaN(n)) throw new Error(`${rule.label}.${k} 不是数字`);
        params[k] = rule.is_percent ? n / 100 : n;
      }
      if (rule.rule_type === "notice_event") {
        const sev = draft[`${rule.rule_type}.min_severity`];
        if (sev) params.min_severity = sev;
      }
      const items = await services.alerts.update({
        rule_type: rule.rule_type, params, code,
      });
      setRules(items);
      setMsg(`${rule.label} 已保存（个股覆盖）`);
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const reset = async (rule: AlertRuleDTO) => {
    setBusy(true);
    setError("");
    try {
      const items = await services.alerts.reset(rule.rule_type, code);
      setRules(items);
      await refresh();
      setMsg(`${rule.label} 已恢复默认`);
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <header>
        <h2>预警条件</h2>
        <span className="badge">个股 {code}</span>
        {busy && <span className="muted">保存中…</span>}
      </header>

      {error && <p className="error">{error}</p>}
      {msg && <p className="ok">{msg}</p>}

      <div className="alert-grid">
        {rules.map((rule) => (
          <div key={rule.rule_type} className="alert-card">
            <div className="alert-head">
              <b>{rule.label}</b>
              <span className={`badge src-${rule.source}`}>
                {SOURCE_LABEL[rule.source] ?? rule.source}
              </span>
            </div>

            {rule.rule_type === "notice_event" ? (
              <label className="field">
                <span>最小级别</span>
                <select
                  value={String(draft[`${rule.rule_type}.min_severity`] ??
                    (rule.params.min_severity as string) ?? "low")}
                  onChange={(e) => setDraft({
                    ...draft, [`${rule.rule_type}.min_severity`]: e.target.value,
                  })}
                >
                  <option value="low">全部（low 及以上）</option>
                  <option value="medium">只看中/高</option>
                  <option value="high">只看高</option>
                </select>
              </label>
            ) : (
              Object.keys(rule.bounds).map((k) => (
                <label key={k} className="field">
                  <span>
                    {k === "drop" ? "跌幅" : k === "surge" ? "涨幅"
                      : k === "window" ? "窗口（天）"
                      : k === "multiple" ? "倍数" : k === "z" ? "z 值" : k}
                    {rule.is_percent ? "（%）" : ""}
                  </span>
                  <input
                    type="number"
                    step="any"
                    value={draft[`${rule.rule_type}.${k}`] ?? ""}
                    onChange={(e) => setDraft({
                      ...draft, [`${rule.rule_type}.${k}`]: e.target.value,
                    })}
                  />
                </label>
              ))
            )}

            <div className="alert-actions">
              <button disabled={busy} onClick={() => void save(rule)}>保存</button>
              <button className="ghost" disabled={busy} onClick={() => void reset(rule)}>
                恢复默认
              </button>
            </div>
          </div>
        ))}
        {rules.length === 0 && !error && <p className="empty">加载中…</p>}
      </div>
      <p className="muted">
        涨跌幅阈值为「单日」口径；窗口越大 z-score 越稳。改完点「分析」或「检测事件」即可按新阈值重算。
      </p>
    </section>
  );
}
