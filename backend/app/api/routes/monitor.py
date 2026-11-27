# -*- coding: utf-8 -*-
"""定时巡检端点（B1）。

    GET  /api/monitor/status     当前排班、上次巡检结果、下次触发时间
    POST /api/monitor/run-now    立刻跑一次（不看排班），便于演示与手动补救

为什么单独开一个路由而不是塞进 maintenance：
    maintenance 管的是「数据保留 + 手工刷新」这类运维动作；
    monitor 管的是「自动巡检的排班与状态」。两者生命周期不同（一个随请求，一个随进程），
    分开更好读。
"""
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

from ..deps import get_services

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/status", summary="定时巡检状态（排班 / 上次结果 / 下次触发）")
def status():
    svc = get_services()
    return svc.scheduler.status()


@router.get("/alerts", summary="重大事件提醒（自 since 之后新检测到的 + AI 分析状态）")
def alerts(since: Optional[str] = Query(
               None, description="上次看到提醒的时间（YYYY-MM-DD HH:MM:SS）"),
           limit: int = Query(5, ge=1, le=20),
           min_severity: Optional[str] = Query(
               "high", pattern="^(low|medium|high)$"),
           include_notice: bool = Query(True, description="是否包含公告类事件")):
    """前端右上角提醒的数据源。

    只返回 `detected_at > since` 的事件——即「刚刚发现了什么」，
    不用 `trade_date`（否则一次刷新会把 180 天内的历史事件全弹出来）。
    每条附带「有没有现成 AI 分析」（`report_id` / `headline` / `confidence`）。
    """
    svc = get_services()
    return svc.alert_feed.recent(since=since, limit=limit,
                                 min_severity=min_severity,
                                 include_notice=include_notice)


@router.post("/run-now", summary="立刻执行一次巡检（light / full）")
def run_now(profile: str = Query("light", pattern="^(light|full)$",
                                 description="light=只检测行情与行业；full=含新闻/公告/财务/调查")):
    svc = get_services()
    res = svc.scheduler.run_now(profile)
    if not res.get("ok", True):
        raise HTTPException(status_code=409, detail=res.get("error") or "巡检未执行")
    return res


@router.post("/start", summary="启动后台巡检线程")
def start():
    svc = get_services()
    started = svc.scheduler.start()
    return {"started": started, "status": svc.scheduler.status()}


@router.post("/stop", summary="停止后台巡检线程")
def stop():
    svc = get_services()
    svc.scheduler.stop()
    return {"stopped": True, "status": svc.scheduler.status()}
