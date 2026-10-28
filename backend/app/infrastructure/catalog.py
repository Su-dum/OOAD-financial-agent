# -*- coding: utf-8 -*-
"""静态参考数据适配器：申万行业映射表。

读取 `data/seed/sw_stock_map.csv`（由 scripts/build_industry_map.py 生成），
提供股票名称、所属申万一级行业、ROE、成长率等**低频变化**的参考数据。

它是基础设施层的一个适配器：上层不关心数据来自 CSV 还是数据库。
"""
import csv
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]   # backend/app/infrastructure/catalog.py -> 项目根
DEFAULT_CSV = ROOT / "data" / "seed" / "sw_stock_map.csv"


class CsvStockCatalog:
    def __init__(self, csv_path: Optional[Path] = None):
        self.csv_path = Path(csv_path) if csv_path else DEFAULT_CSV
        self._by_code: dict[str, dict] = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if not self.csv_path.exists():
            return
        with open(self.csv_path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                code = (r.get("code") or "").strip()
                if code:
                    self._by_code[code] = r

    def get(self, code: str) -> dict:
        self._load()
        return self._by_code.get(str(code).split(".")[0], {})

    def name_of(self, code: str) -> str:
        return self.get(code).get("name") or ""

    def industry_of(self, code: str) -> str:
        return self.get(code).get("industry_l1_name") or ""

    def by_industry(self, industry: str) -> list[dict]:
        self._load()
        return [v for v in self._by_code.values()
                if (v.get("industry_l1_name") or "") == industry]

    def __len__(self):
        self._load()
        return len(self._by_code)
