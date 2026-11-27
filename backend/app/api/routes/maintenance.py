# -*- coding: utf-8 -*-
"""运维与刷新端点：一键更新、自选股管理、数据保留。"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..deps import get_services

router = APIRouter(prefix="/api", tags=["maintenance"])


# ============================================================
# 一键更新
# ============================================================
@router.post("/refresh", summary="一键更新：新闻 + 公告 + 财务 + 事件 + 自动调查 + 清理")
def refresh(news_days: float = Query(2, ge=0.5, le=30),
            max_pages: int = Query(12, ge=1, le=60),
            detect_days: int = Query(90, ge=5, le=400),
            include_news: bool = Query(True, description="是否采集新闻（定时巡检的轻量档会关掉）"),
            include_notices: bool = Query(True, description="是否采集公告"),
            notice_days: int = Query(400, ge=30, le=2000),
            max_notice_stocks: int = Query(12, ge=0, le=50),
            include_financials: bool = Query(True, description="是否刷新财务快照"),
            max_financial_codes: int = Query(8, ge=0, le=50),
            include_industries: bool = Query(True, description="是否检测行业指数"),
            auto_investigate: Optional[bool] = Query(
                None, description="是否对高等级事件自动调查（默认按配置开启）"),
            prune: bool = Query(True),
            dry_run_prune: bool = Query(False)):
    svc = get_services()
    res = svc.refresh.run(news_days=news_days, max_pages=max_pages,
                          detect_days=detect_days,
                          include_news=include_news,
                          include_notices=include_notices,
                          notice_days=notice_days,
                          max_notice_stocks=max_notice_stocks,
                          include_financials=include_financials,
                          max_financial_codes=max_financial_codes,
                          include_industries=include_industries,
                          auto_investigate=auto_investigate,
                          prune=prune, dry_run_prune=dry_run_prune)
    return res.to_dict()


# ============================================================
# 自选股
# ============================================================
class WatchRequest(BaseModel):
    code: str
    note: Optional[str] = None


@router.get("/watchlist", summary="自选股列表")
def list_watchlist():
    svc = get_services()
    wl = svc.watchlist_repo.load()
    if len(wl) == 0:
        svc.watchlist_repo.seed_defaults(catalog=svc.catalog)
        wl = svc.watchlist_repo.load()
    return {"count": len(wl), "items": wl.to_dict()}


@router.post("/watchlist", summary="加入自选")
def add_watch(req: WatchRequest):
    svc = get_services()
    code = req.code.split(".")[0]
    name = svc.catalog.name_of(code)
    if not name:
        raise HTTPException(status_code=404, detail=f"{code} 不在股票映射表中")
    from ...domain.watchlist import WatchItem
    from datetime import datetime
    svc.watchlist_repo.save_item(WatchItem(
        code=code, name=name, industry=svc.catalog.industry_of(code),
        added_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        note=req.note or ""))
    return {"ok": True, "code": code, "name": name}


@router.delete("/watchlist/{code}", summary="移出自选")
def remove_watch(code: str):
    svc = get_services()
    ok = svc.watchlist_repo.delete(code)
    if not ok:
        raise HTTPException(status_code=404, detail="不在自选列表中")
    return {"ok": True, "code": code}


# ============================================================
# 数据保留
# ============================================================
@router.get("/maintenance/stats", summary="数据量与保留策略现状")
def maintenance_stats():
    return get_services().maintenance.stats()


@router.post("/maintenance/prune", summary="按保留策略清理旧数据")
def maintenance_prune(dry_run: bool = Query(False)):
    res = get_services().maintenance.prune(dry_run=dry_run)
    return res.to_dict()


# ============================================================
# 自选股事件（前端事件面板直接读这个）
# ============================================================
@router.get("/events/watchlist", summary="自选股的事件（按时间倒序）")
def watchlist_events(limit: int = Query(50, ge=1, le=200)):
    svc = get_services()
    wl = svc.watchlist_repo.load()
    codes = set(wl.codes)
    items = [e for e in svc.event_repo.list_recent(None, limit=limit * 3)
             if e.code in codes]
    return {"count": len(items[:limit]),
            "watchlist": wl.to_dict(),
            "items": [e.to_dict() for e in items[:limit]]}
