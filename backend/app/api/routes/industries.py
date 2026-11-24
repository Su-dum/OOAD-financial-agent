# -*- coding: utf-8 -*-
"""行业监控端点（B1）。

    GET    /api/industries                31 个申万一级行业 + 是否已监控
    GET    /api/industries/watched        已监控行业
    POST   /api/industries/{code}/watch   加入监控
    DELETE /api/industries/{code}/watch   移出监控
    GET    /api/industries/{code}/series  行业指数走势（图表）
    GET    /api/industries/{code}/events  行业指数事件（同一套行情规则）
    POST   /api/industries/refresh        批量检测已监控行业并落库
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..deps import get_services

router = APIRouter(prefix="/api/industries", tags=["industries"])


@router.get("", summary="申万一级行业清单（含监控状态）")
def list_industries():
    svc = get_services()
    items = svc.industries.list_all()
    return {"count": len(items), "watched": svc.industries.watched(),
            "items": items}


@router.get("/watched", summary="已加入监控的行业")
def watched_industries(limit: int = Query(10, ge=1, le=31)):
    svc = get_services()
    watched = svc.industries.watched()
    out = []
    for w in watched[:limit]:
        try:
            events = svc.industries.scan(w["code"], days=365)
        except Exception:                               # noqa: BLE001
            events = []
        out.append(dict(**w, event_count=len(events),
                        latest_event=(events[0].to_dict() if events else None)))
    return {"count": len(watched), "items": out}


@router.post("/{code}/watch", summary="把行业加入监控")
def watch(code: str):
    svc = get_services()
    try:
        item = svc.industries.watch(code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "item": item, "watched": svc.industries.watched()}


@router.delete("/{code}/watch", summary="移出监控")
def unwatch(code: str):
    svc = get_services()
    if not svc.industries.unwatch(code):
        raise HTTPException(status_code=404, detail="该行业不在监控列表中")
    return {"ok": True, "watched": svc.industries.watched()}


@router.get("/{code}/series", summary="行业指数走势")
def industry_series(code: str, days: int = Query(365, ge=30, le=2000)):
    svc = get_services()
    body = svc.industries.series(code, days=days)
    if body is None:
        raise HTTPException(status_code=404,
                            detail=f"行业 {code} 没有可用行情（可能被限流）")
    return body


@router.get("/{code}/events", summary="行业指数事件（同一套行情规则）")
def industry_events(code: str, days: int = Query(365, ge=30, le=2000),
                    persist: bool = Query(False)):
    svc = get_services()
    try:
        events = svc.industries.scan(code, days=days, persist=persist,
                                     event_repo=svc.event_repo)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": code, "days": days, "count": len(events),
            "items": [e.to_dict() for e in events]}


@router.post("/refresh", summary="批量检测已监控行业并落库")
def refresh_industries(days: int = Query(365, ge=30, le=2000)):
    svc = get_services()
    return svc.industries.refresh(days=days, event_repo=svc.event_repo)
