# -*- coding: utf-8 -*-
"""自然语言追问端点（C2 / C1）。

一个端点同时承担两件事：

    问：POST /api/chat {"question": "最近表现怎么样？", "code": "600519"}
    改：POST /api/chat {"question": "把跌幅阈值改成 3%", "code": "600519"}

「改」类请求会解析成结构化动作：能落库的（预警阈值、自选股）**服务端执行**，
需要前端配合的（切时间区间）作为 `actions` 返回给前端执行。
这样自然语言与表单操作走同一套服务，不会出现两套行为。
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...application.conversation_service import ChatContext
from ..deps import get_services

router = APIRouter(prefix="/api", tags=["chat"])


class ChatTurn(BaseModel):
    role: str = "user"
    content: str = ""


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    code: str = "600519"
    start: Optional[str] = None
    end: Optional[str] = None
    # 当前上下文：从事件列表点进来时会把事件带过来，回答更贴合
    event: Optional[dict] = None
    report_id: Optional[int] = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


def _default_range(days: int = 180) -> tuple:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return start, end


@router.post("/chat", summary="自然语言追问 / 交互式修改监控条件（C2 / C1）")
def chat(req: ChatRequest):
    svc = get_services()
    code = req.code.split(".")[0]
    if not svc.catalog.name_of(code):
        raise HTTPException(status_code=404, detail=f"{code} 不在股票映射表中")

    s, e = (req.start, req.end) if req.start and req.end else _default_range()
    ctx = ChatContext(
        code=code, start=s, end=e, event=req.event, report_id=req.report_id,
        history=[dict(role=t.role, content=t.content) for t in req.history])

    body = svc.chat.answer(req.question, ctx)
    body["applied"] = _apply_actions(svc, body.get("actions") or [], code)
    return body


def _apply_actions(svc, actions: list, code: str) -> list:
    """服务端能执行的动作用服务端执行（幂等、可回滚）。"""
    applied = []
    for action in actions:
        kind = action.get("type")
        try:
            if kind == "set_alert":
                item = svc.alerts.update(action["rule_type"], action["params"],
                                         code=code)
                applied.append(dict(action=action, ok=True,
                                    effective=item["params"]))
            elif kind == "add_watchlist":
                target = action.get("code") or code
                name = svc.catalog.name_of(target)
                if name:
                    from datetime import datetime as _dt

                    from ...domain.watchlist import WatchItem
                    svc.watchlist_repo.save_item(WatchItem(
                        code=target, name=name,
                        industry=svc.catalog.industry_of(target),
                        added_at=_dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                        note="通过自然语言加入"))
                    applied.append(dict(action=action, ok=True, name=name))
                else:
                    applied.append(dict(action=action, ok=False,
                                        error=f"{target} 不在股票映射表中"))
            # set_range 由前端执行（后端无状态）
        except Exception as e:                          # noqa: BLE001
            applied.append(dict(action=action, ok=False,
                                error=f"{type(e).__name__}: {e}"))
    return applied


@router.get("/chat/suggestions", summary="追问建议（前端展示成快捷按钮）")
def suggestions(code: Optional[str] = None):
    base = [
        "这只票最近表现怎么样？",
        "为什么最近出现异动？",
        "有哪些财报或回购公告？",
        "把跌幅阈值改成 3%",
        "看近半年",
    ]
    if code:
        base.insert(3, f"和 000001 比较一下")
    return {"items": base}
