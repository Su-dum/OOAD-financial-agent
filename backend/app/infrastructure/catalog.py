# -*- coding: utf-8 -*-
"""静态参考数据适配器：申万行业映射表。

读取两份提交在仓库里的 CSV（由 `scripts/build_industry_map.py` 生成）：

    data/seed/sw_stock_map.csv   个股 -> 申万一级行业 + 估值/成长快照（5229 只）
    data/seed/sw_industry.csv    申万三级行业结构（一级 31 / 二级 131 / 三级 335）

提供股票名称、所属行业、行业清单、ROE/成长等**低频变化**的参考数据。
它是基础设施层的一个适配器：上层不关心数据来自 CSV 还是数据库。
"""
import csv
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]   # backend/app/infrastructure/catalog.py -> 项目根
DEFAULT_CSV = ROOT / "data" / "seed" / "sw_stock_map.csv"
DEFAULT_INDUSTRY_CSV = ROOT / "data" / "seed" / "sw_industry.csv"


class CsvStockCatalog:
    def __init__(self, csv_path: Optional[Path] = None,
                 industry_csv: Optional[Path] = None):
        self.csv_path = Path(csv_path) if csv_path else DEFAULT_CSV
        self.industry_csv = (Path(industry_csv) if industry_csv
                             else DEFAULT_INDUSTRY_CSV)
        self._by_code: dict[str, dict] = {}
        self._industries: dict[str, dict] = {}
        self._loaded = False
        self._industries_loaded = False

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

    def _load_industries(self):
        if self._industries_loaded:
            return
        self._industries_loaded = True
        if not self.industry_csv.exists():
            return
        with open(self.industry_csv, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                code = (r.get("code") or "").strip()
                if not code:
                    continue
                self._industries[code] = r

    def get(self, code: str) -> dict:
        self._load()
        return self._by_code.get(str(code).split(".")[0], {})

    def name_of(self, code: str) -> str:
        return self.get(code).get("name") or ""

    def industry_of(self, code: str) -> str:
        return self.get(code).get("industry_l1_name") or ""

    def by_industry(self, industry: str) -> list[dict]:
        """按申万一级行业名取成份股（用于行业级监控/聚合）。"""
        self._load()
        return [v for v in self._by_code.values()
                if (v.get("industry_l1_name") or "") == industry]

    # ---------------- 行业 ----------------
    def industries(self, level: str = "1") -> list[dict]:
        """申万行业清单（默认一级 31 个）。"""
        self._load_industries()
        out = []
        for r in self._industries.values():
            if str(r.get("level") or "").strip() != str(level):
                continue
            out.append(dict(
                code=(r.get("code") or "").strip(),
                name=(r.get("name") or "").strip(),
                level=str(r.get("level") or ""),
                parent_code=(r.get("parent_code") or "").strip(),
                parent_name=(r.get("parent_name") or "").strip(),
                stock_count=_int(r.get("stock_count")),
                pe_static=_float(r.get("pe_static")),
                pe_ttm=_float(r.get("pe_ttm")),
                pb=_float(r.get("pb")),
                dividend_yield=_float(r.get("dividend_yield")),
            ))
        out.sort(key=lambda x: x["code"])
        return out

    def industry(self, code: str) -> dict:
        """按代码取行业（`801010` 或名字都行）。"""
        self._load_industries()
        key = str(code).strip()
        if key in self._industries:
            return self._row_to_industry(self._industries[key])
        for r in self._industries.values():
            if (r.get("name") or "").strip() == key:
                return self._row_to_industry(r)
        return {}

    @staticmethod
    def _row_to_industry(r: dict) -> dict:
        return dict(code=(r.get("code") or "").strip(),
                    name=(r.get("name") or "").strip(),
                    level=str(r.get("level") or ""),
                    stock_count=_int(r.get("stock_count")))

    def industry_name(self, code: str) -> str:
        return self.industry(code).get("name") or ""

    def __len__(self):
        self._load()
        return len(self._by_code)


def _float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
