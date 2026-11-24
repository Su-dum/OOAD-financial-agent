# -*- coding: utf-8 -*-
"""分析任务端点（C1）。

    GET    /api/tasks            已保存的分析任务
    POST   /api/tasks            新建任务（标的 + 区间 + 对比组 + 基准）
    DELETE /api/tasks/{id}       删除
    POST   /api/tasks/{id}/run   重跑：指标 + 事件 + 跨期 + 跨资产
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...application.task_service import TaskValidationError
from ..deps import get_services

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    code: str
    days: int = Field(365, ge=5, le=2000)
    compare_codes: list[str] = Field(default_factory=list, max_length=5)
    benchmark: Optional[str] = "sh000300"


@router.get("", summary="分析任务列表")
def list_tasks(limit: int = Query(50, ge=1, le=200)):
    svc = get_services()
    return {"count": svc.task_repo.count(), "items": svc.tasks.list(limit)}


@router.post("", summary="新建分析任务")
def create_task(req: TaskCreate):
    svc = get_services()
    try:
        task = svc.tasks.create(req.name, req.code, req.days,
                                req.compare_codes, req.benchmark)
    except TaskValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "task": task.to_dict(), "items": svc.tasks.list()}


@router.delete("/{task_id}", summary="删除分析任务")
def delete_task(task_id: int):
    svc = get_services()
    if not svc.tasks.delete(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "items": svc.tasks.list()}


@router.post("/{task_id}/run", summary="运行分析任务（指标 + 事件 + 跨期 + 跨资产）")
def run_task(task_id: int):
    svc = get_services()
    try:
        return svc.tasks.run(task_id)
    except TaskValidationError as e:
        raise HTTPException(status_code=404, detail=str(e))
