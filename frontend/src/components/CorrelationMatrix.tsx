/**
 * 相关系数矩阵（D3）。
 *
 * 只做「数值 -> 颜色/文案」的展示映射，不在这里算相关系数
 * （后端 `CrossAssetAnalyzer.correlation_matrix` 算，前端重算会两端漂移）。
 *
 * 配色：正相关偏蓝、负相关偏红，透明度表示强度；
 * 对角线固定 1.00，不参与着色，避免整张表一半格子是纯色。
 */
import type { CSSProperties } from "react";
import { CrossAsset, CorrelationDTO } from "../models";

function cellStyle(v: number | null): CSSProperties {
  if (v === null || v === undefined) return {};
  const a = Math.min(Math.abs(v), 1) * 0.55;
  return {
    background: v >= 0 ? `rgba(79,140,255,${a})` : `rgba(255,91,91,${a})`,
  };
}

/** 代码 -> 显示标签（有名称就带上，行业加「行业」前缀）。 */
export type NameMap = Record<string, { name?: string; is_industry?: boolean }>;

function labelOf(code: string, names?: NameMap): string {
  const m = names?.[code];
  if (!m || (!m.name && !m.is_industry)) return code;
  return `${m.is_industry ? "行业 " : ""}${m.name || code}`;
}

export function CorrelationMatrix({ correlation, names }: {
  correlation: CorrelationDTO;
  names?: NameMap;
}) {
  const { codes, matrix } = correlation;
  if (!codes?.length || !matrix?.length) {
    return <p className="empty">所选标的共同交易日不足，无法计算相关性。</p>;
  }

  return (
    <div className="corr-wrap">
      <table className="corr">
        <thead>
          <tr>
            <th />
            {codes.map((c) => (
              <th key={c} title={c}>{labelOf(c, names)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {codes.map((rowCode, i) => (
            <tr key={rowCode}>
              <th scope="row" title={rowCode}>{labelOf(rowCode, names)}</th>
              {codes.map((colCode, j) => {
                const v = matrix[i][j];
                const same = i === j;
                return (
                  <td key={colCode} style={same ? undefined : cellStyle(v)}
                      title={same ? "自身" : CrossAsset.corrLabel(v)}>
                    {v === null || v === undefined ? "—" : v.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        日收益率皮尔逊相关系数；蓝为正相关、红为负相关，颜色越深越强。
        行业指数以「行业」开头标注。
      </p>
    </div>
  );
}
