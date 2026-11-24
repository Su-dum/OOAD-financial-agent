# -*- coding: utf-8 -*-
"""财务数据端点（A1）。

    GET  /api/stocks/{code}/financials          读本地快照（不联网）
    POST /api/stocks/{code}/financials/refresh  显式刷新（打外部财务接口）

为什么读和写分开：用户点开个股就该立刻看到财务数据，不该等一次外部请求；
只有用户明确要求「更新财务」时才打新浪接口。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ...domain.financials import describe_fields
from ..deps import get_services

router = APIRouter(prefix="/api/stocks", tags=["financials"])


@router.get("/{code}/financials", summary="财务快照（最近一期定期报告）")
def get_financials(code: str):
    svc = get_services()
    c = code.split(".")[0]
    if not svc.catalog.name_of(c):
        raise HTTPException(status_code=404, detail=f"{c} 不在股票映射表中")
    body = svc.financial.describe(c)
    body["name"] = svc.catalog.name_of(c)
    body["industry_l1"] = svc.catalog.industry_of(c)
    body["fields"] = describe_fields()
    return body


@router.post("/{code}/financials/refresh", summary="刷新财务快照（外部接口）")
def refresh_financials(code: str, years: int = Query(3, ge=1, le=10)):
    svc = get_services()
    c = code.split(".")[0]
    if not svc.catalog.name_of(c):
        raise HTTPException(status_code=404, detail=f"{c} 不在股票映射表中")
    st = svc.financial.refresh(c, years=years)
    body = st.to_dict()
    body["snapshot"] = svc.financial.get(c)
    body["fields"] = describe_fields()
    return body
