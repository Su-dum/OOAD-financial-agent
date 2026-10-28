/** 股票搜索：受控输入 + 触发回调。组件不直接调 service，保持无副作用。 */
import { useState } from "react";

interface Props {
  initialCode?: string;
  onSearch: (code: string) => void;
  disabled?: boolean;
}

export function StockSearch({ initialCode = "600519", onSearch, disabled }: Props) {
  const [code, setCode] = useState(initialCode);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = code.trim();
    if (/^\d{6}$/.test(v)) onSearch(v);
  };

  return (
    <form className="search" onSubmit={submit}>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value)}
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
