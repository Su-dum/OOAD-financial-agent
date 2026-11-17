# -*- coding: utf-8 -*-
"""公告端点（B2 的数据底料）。

分两个方向：
    读：本地公告库（不联网，秒回）—— 事件列表 / 报告证据都用它
    写：显式刷新某只票的公告（打外部接口，只在用户点按钮时发生）

刷新后顺手重算该股事件，这样前端一点就能看到新的公告事件，
不用再点一次「更新数据」。
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ...domain.notices import describe_categories
from ..deps import get_services

router = APIRouter(prefix="/api/notices", tags=["notices"])


def _range(days: int) -> tuple:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return start, end


@router.get("/categories", summary="公告事件类别清单（公告类型 -> 事件类别的映射）")
def categories():
    items = describe_categories()
    return {"count": len(items),
            "material": sum(1 for c in items if c["material"]),
            "items": items}


@router.get("", summary="本地公告列表（按公告日倒序）")
def list_notices(code: str = Query(..., description="6 位股票代码"),
                 start: Optional[str] = None, end: Optional[str] = None,
                 limit: int = Query(50, ge=1, le=500)):
    svc = get_services()
    c = code.split(".")[0]
    items = svc.notice_repo.find_by_stock(c, start=start, end=end, limit=limit)
    return {"code": c, "count": len(items), "items": items}


@router.post("/{code}/refresh", summary="刷新该股票的公告（外部接口）并重算事件")
def refresh_notices(code: str, days: int = Query(400, ge=30, le=2000),
                    limit: int = Query(500, ge=10, le=2000),
                    persist: bool = Query(True, description="事件是否落库")):
    svc = get_services()
    c = code.split(".")[0]
    if not svc.catalog.name_of(c):
        raise HTTPException(status_code=404, detail=f"{c} 不在股票映射表中")

    st = svc.notice_ingest.fetch(c, days=days, limit=limit)
    body = st.to_dict()
    body["total_in_db"] = svc.notice_repo.count(c)

    start, end = _range(days)
    events = svc.monitor.scan(c, start, end)
    body["events"] = len(events)
    body["notice_events"] = sum(1 for e in events
                                if e.event_type.startswith("notice_"))
    if persist and events:
        body["saved"] = svc.event_repo.save_many(events)
    return body
