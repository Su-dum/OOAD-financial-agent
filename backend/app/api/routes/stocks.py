# -*- coding: utf-8 -*-
"""股票相关端点：指标分析（A1/A2/A3）、事件检测（B2）、事件调查（B3）。"""
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
@router.get("/{code}/events", summary="检测区间内的事件")
def get_events(code: str,
               start: Optional[str] = None, end: Optional[str] = None,
               source: Optional[str] = None,
               persist: bool = Query(False, description="是否写入数据库")):
    s, e = (start, end) if start and end else _default_range(180)
    svc = get_services()
    events = svc.monitor.scan(code, s, e, source=source)
    saved = svc.event_repo.save_many(events) if persist else 0
    return {"code": code, "start": s, "end": e,
            "count": len(events), "saved": saved,
            "items": [ev.to_dict() for ev in events]}


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


@router.post("/investigate", summary="围绕一个事件做调查并生成报告")
def investigate(req: InvestigateRequest):
    from ...domain.events import MarketEvent

    svc = get_services()
    trade_date = req.trade_date or datetime.now().strftime("%Y-%m-%d")
    ev = MarketEvent(
        code=req.code.split(".")[0], name=svc.market.name_of(req.code),
        event_type=req.event_type, trade_date=trade_date,
        detected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        severity="medium", value=None, threshold=None,
        detail=f"手动发起调查：{req.event_type}", rule_name="manual")
    report = svc.agent.investigate(ev, days=req.days, question=req.question or "")
    rid = svc.report_repo.save(report) if req.persist else 0
    return {"report_id": rid, "report": report.to_dict(),
            "markdown": report.to_markdown()}


@router.get("/{code}/reports", summary="该股票的历史调查报告列表")
def list_reports(code: str, limit: int = 20):
    svc = get_services()
    return {"code": code, "items": svc.report_repo.list_recent(code, limit=limit)}
