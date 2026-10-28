# -*- coding: utf-8 -*-
"""事件与报告端点（读库）。"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..deps import get_services

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events", summary="已入库的事件列表")
def list_events(code: Optional[str] = None, limit: int = Query(50, le=500)):
    svc = get_services()
    items = svc.event_repo.list_recent(code, limit=limit)
    return {"count": len(items), "items": [e.to_dict() for e in items]}


@router.get("/reports/{report_id}", summary="按 id 取调查报告")
def get_report(report_id: int):
    svc = get_services()
    r = svc.report_repo.get(report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return r


@router.get("/reports", summary="最近的调查报告")
def list_reports(limit: int = Query(20, le=200)):
    svc = get_services()
    return {"items": svc.report_repo.list_recent(None, limit=limit)}


@router.get("/meta/stocks/{code}", summary="股票基础信息（申万行业等）")
def stock_meta(code: str):
    svc = get_services()
    meta = svc.market.meta(code)
    if not meta:
        raise HTTPException(status_code=404, detail="股票不在映射表中")
    return dict(meta)
