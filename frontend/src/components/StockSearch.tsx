/** 股票搜索：受控输入 + 触发回调。组件不直接调 service，保持无副作用。 */
import { useEffect, useState, type FormEvent } from "react";

interface Props {
  /** 当前正在分析的代码：由外部切换标的后输入框要跟着变 */
  code?: string;
  onSearch: (code: string) => void;
  disabled?: boolean;
}

export function StockSearch({ code = "600519", onSearch, disabled }: Props) {
  const [value, setValue] = useState(code);

  // 主角被外部改掉时（点自选股 / 横向对比某一行 / ?code= 直达 / 载入分析任务）
  // 输入框必须同步，否则会出现「输入框 600519、卡片 000001」的错位。
  useEffect(() => {
    if (/^\d{6}$/.test(code)) setValue(code);
  }, [code]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = value.trim();
    if (/^\d{6}$/.test(v)) onSearch(v);
  };

  return (
    <form className="search" onSubmit={submit}>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="输入 6 位股票代码，如 600519"
        inputMode="numeric"
        maxLength={6}
      />
      <button type="submit" disabled={disabled}>
        分析
      </button>
    </form>
  );
}
