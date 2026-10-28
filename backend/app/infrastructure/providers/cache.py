# -*- coding: utf-8 -*-
"""行情缓存适配器：CSV 落盘。

缓存是必需品而非优化——实测 baostock 单次 3 年查询从 3 秒恶化到 57 秒甚至挂起，
没有缓存整个分析链路不可用。
"""
import csv
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from ...domain.models import PriceRecord, PriceSeries

FIELDS = ["code", "date", "open", "high", "low", "close", "volume", "amount",
          "turnover", "pct_change", "pe_ttm", "pb", "ps_ttm", "pcf_ttm",
          "adjust", "source"]


class CsvPriceCache:
    """满足 domain.ports.PriceCache 协议。

    key 形如 'baostock_600519_qfq_2023-10-29_2026-10-28'。
    """

    def __init__(self, root: Path | str, ttl: int = 12 * 3600):
        self.root = Path(root)
        self.ttl = ttl

    def _path(self, key: str) -> Path:
        return self.root / f"{key.replace(':', '-').replace('/', '-')}.csv"

    def get(self, key: str) -> Optional[PriceSeries]:
        p = self._path(key)
        if not p.exists() or time.time() - p.stat().st_mtime > self.ttl:
            return None
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                return None

            recs = []
            for r in rows:
                def n(k):
                    v = r.get(k)
                    return float(v) if v not in (None, "", "None") else None
                recs.append(PriceRecord(
                    code=r["code"], date=r["date"],
                    open=float(r["open"]), high=float(r["high"]),
                    low=float(r["low"]), close=float(r["close"]),
                    volume=n("volume"), amount=n("amount"),
                    turnover=n("turnover"), pct_change=n("pct_change"),
                    pe_ttm=n("pe_ttm"), pb=n("pb"), ps_ttm=n("ps_ttm"),
                    pcf_ttm=n("pcf_ttm"),
                    adjust=r.get("adjust") or "qfq",
                    source=r.get("source") or "cache"))
            return PriceSeries(code=recs[0].code, records=recs,
                               adjust=recs[0].adjust, source=recs[0].source)
        except Exception:
            return None

    def put(self, key: str, series: PriceSeries) -> None:
        try:
            p = self._path(key)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                for rec in series.records:
                    d = asdict(rec)
                    w.writerow({k: d.get(k) for k in FIELDS})
        except Exception:
            pass   # 缓存失败不影响主流程
