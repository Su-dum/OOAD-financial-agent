# -*- coding: utf-8 -*-
"""预警规则配置端点（C1：用户可配置预警条件）。

    GET    /api/alerts?code=600519    生效配置（默认 -> 全局 -> 个股 合并后的结果）
    PUT    /api/alerts                改参数（code 传空 = 改全局）
    DELETE /api/alerts/{rule_type}    删除覆盖值，退回默认
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..deps import get_services

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertUpdate(BaseModel):
    rule_type: str = Field(..., description="threshold_pct_change / volume_spike / "
                                            "zscore / notice_event")
    params: dict = Field(default_factory=dict)
    code: Optional[str] = Field(None, description="传空表示改全局默认")
    enabled: Optional[bool] = None


@router.get("", summary="当前生效的预警规则配置")
def get_alerts(code: Optional[str] = None):
    svc = get_services()
    items = svc.alerts.describe(code)
    return {"code": (code or "").split(".")[0], "count": len(items), "items": items}


@router.put("", summary="修改预警参数（两级配置：全局 / 个股）")
def update_alert(req: AlertUpdate):
    svc = get_services()
    try:
        item = svc.alerts.update(req.rule_type, req.params, code=req.code,
                                 enabled=req.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "item": item, "items": svc.alerts.describe(req.code)}


@router.delete("/{rule_type}", summary="删除覆盖值，退回默认")
def reset_alert(rule_type: str, code: Optional[str] = Query(None)):
    svc = get_services()
    removed = svc.alerts.reset(rule_type, code=code)
    return {"ok": True, "removed": removed, "items": svc.alerts.describe(code)}
