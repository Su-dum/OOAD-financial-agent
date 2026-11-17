# -*- coding: utf-8 -*-
"""股票相关端点：指标分析（A1/A2/A3）、事件检测（B2）、事件调查（B3）。

另有两条给前端图表用的端点：
    /series          单标的价格序列（含成交量 / 估值）
    /compare/series  多标的归一化净值序列（跨资产相对表现）
"""
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..deps import get_services

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


def _default_range(days: int = 365) -> tuple[str, str]:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return start, end


def _downsample(records: list, max_points: int = 400) -> list:
    """等距抽样，但保留首尾两点（图表的起止必须真实）。"""
    n = len(records)
    if n <= max_points:
        return records
    step = n / float(max_points)
    idx = sorted({int(i * step) for i in range(max_points)} | {0, n - 1})
    return [records[i] for i in idx if i < n]


# ============================================================
# 指标（A1 / A2 / A3）
# ============================================================
@router.get("/{code}/indicators", summary="单只股票区间指标")
def get_indicators(code: str,
                   start: Optional[str] = Query(None, description="YYYY-MM-DD"),
                   end: Optional[str] = Query(None),
                   adjust: str = Query("qfq", pattern="^(qfq|hfq|none)$"),
                   source: Optional[str] = Query(None, description="优先数据源")):
    s, e = (start, end) if start and end else _default_range()
    svc = get_services()
    ind = svc.analyzer.analyze(code, s, e, adjust=adjust, source=source)
    if ind is None:
        raise HTTPException(status_code=404,
                            detail=f"{code} 在 {s}~{e} 没有可用数据（数据源可能被限流）")
    return ind.to_dict()


@router.get("/compare", summary="跨标的横向比较")
def compare(codes: str = Query(..., description="逗号分隔，如 600519,000001"),
            start: Optional[str] = None, end: Optional[str] = None,
            source: Optional[str] = None):
    s, e = (start, end) if start and end else _default_range()
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        raise HTTPException(status_code=400, detail="codes 不能为空")
    svc = get_services()
    rows = svc.analyzer.compare(code_list, s, e, source=source)
    return {"start": s, "end": e, "count": len(rows),
            "items": [r.to_dict() for r in rows]}


# ============================================================
# 事件（B2）
# ============================================================
@router.get("/{code}/events", summary="检测区间内的事件（行情类 + 公告类）")
def get_events(code: str,
               start: Optional[str] = None, end: Optional[str] = None,
               source: Optional[str] = None,
               include_notices: bool = Query(True, description="是否包含公告类事件"),
               persist: bool = Query(False, description="是否写入数据库")):
    s, e = (start, end) if start and end else _default_range(180)
    svc = get_services()
    events = svc.monitor.scan(code, s, e, source=source,
                              include_notices=include_notices)
    saved = svc.event_repo.save_many(events) if persist else 0
    return {"code": code, "start": s, "end": e,
            "count": len(events),
            "notice_count": sum(1 for ev in events
                                if ev.event_type.startswith("notice_")),
            "saved": saved,
            "items": [ev.to_dict() for ev in events]}


@router.get("/{code}/series", summary="价格序列（前端图表：收盘价 / 成交量 / 估值）")
def get_series(code: str,
               start: Optional[str] = None, end: Optional[str] = None,
               adjust: str = Query("qfq", pattern="^(qfq|hfq|none)$"),
               source: Optional[str] = None,
               max_points: int = Query(400, ge=20, le=2000)):
    s, e = (start, end) if start and end else _default_range(365)
    body = get_services().cross.series_points(code, s, e, adjust=adjust,
                                              source=source, max_points=max_points)
    if body is None:
        raise HTTPException(status_code=404,
                            detail=f"{code} 在 {s}~{e} 没有可用行情（数据源可能被限流）")
    return body


@router.get("/cross", summary="跨资产分析：相对表现 / 相关性 / 相对基准（D3）")
def cross_assets(codes: str = Query(..., description="逗号分隔，如 600519,000001,300750"),
                 start: Optional[str] = None, end: Optional[str] = None,
                 source: Optional[str] = None,
                 benchmark: Optional[str] = Query(
                     "sh000300", description="基准指数，传空字符串则不算 beta"),
                 max_points: int = Query(400, ge=20, le=2000)):
    s, e = (start, end) if start and end else _default_range(365)
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if len(code_list) < 2:
        raise HTTPException(status_code=400, detail="跨资产分析至少需要 2 个代码")
    body = get_services().cross.compare(code_list, s, e, source=source,
                                        benchmark=benchmark or None,
                                        max_points=max_points)
    if not body.get("assets"):
        raise HTTPException(status_code=404,
                            detail=body.get("note") or "所选标的没有可用数据")
    return body


@router.get("/{code}/periods", summary="跨期比较：同一只票在不同区间的表现（A3）")
def compare_periods(code: str,
                    windows: Optional[str] = Query(
                        None, description="label:start:end，用 ; 分隔；不传则用默认五档"),
                    adjust: str = Query("qfq", pattern="^(qfq|hfq|none)$"),
                    source: Optional[str] = None):
    svc = get_services()
    periods = _parse_windows(windows) or _auto_periods()
    rows = svc.analyzer.compare_periods(code, periods, adjust=adjust, source=source)
    return {"code": code, "periods": [p[0] for p in periods], "items": rows}


def _parse_windows(windows: Optional[str]):
    """`近3月:2026-08-01:2026-11-01;近1年:...` -> [(label, start, end), ...]"""
    if not windows:
        return []
    out = []
    for chunk in windows.split(";"):
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) == 3 and parts[1] and parts[2]:
            out.append((parts[0], parts[1], parts[2]))
    return out


def _auto_periods():
    """默认五档：近 1 / 3 / 6 / 12 / 24 个月（都以今天为终点）。"""
    end = datetime.now()
    return [(label, (end - timedelta(days=days)).strftime("%Y-%m-%d"),
             end.strftime("%Y-%m-%d"))
            for label, days in (("近 1 个月", 30), ("近 3 个月", 90),
                                ("近 6 个月", 180), ("近 1 年", 365),
                                ("近 2 年", 730))]


# ============================================================
# 调查（B3 / D2）
# ============================================================
class InvestigateRequest(BaseModel):
    code: str
    trade_date: Optional[str] = None
    event_type: str = "price_move"
    days: int = 7
    question: Optional[str] = None
    persist: bool = True
    # 前端从事件列表拿到的真实字段，传进来报告会更贴合事实
    severity: str = "medium"
    value: Optional[float] = None
    threshold: Optional[float] = None
    detail: Optional[str] = None


@router.post("/investigate", summary="围绕一个事件做调查并生成报告")
def investigate(req: InvestigateRequest):
    from ...domain.events import MarketEvent

    svc = get_services()
    trade_date = req.trade_date or datetime.now().strftime("%Y-%m-%d")
    name = svc.market.name_of(req.code)
    ev = MarketEvent(
        code=req.code.split(".")[0], name=name,
        event_type=req.event_type, trade_date=trade_date,
        detected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        severity=req.severity, value=req.value, threshold=req.threshold,
        detail=req.detail or f"{name or req.code} 在 {trade_date} 发生 {req.event_type}",
        rule_name="manual")
    report = svc.agent.investigate(ev, days=req.days, question=req.question or "")
    rid = svc.report_repo.save(report) if req.persist else 0
    return {"report_id": rid, "report": report.to_dict(),
            "markdown": report.to_markdown()}


@router.get("/{code}/reports", summary="该股票的历史调查报告列表")
def list_reports(code: str, limit: int = 20):
    svc = get_services()
    return {"code": code, "items": svc.report_repo.list_recent(code, limit=limit)}
