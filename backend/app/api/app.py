# -*- coding: utf-8 -*-
"""FastAPI 应用装配。

启动：
    uvicorn backend.app.api.app:app --reload --port 8000
或：
    python scripts/run_api.py
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .deps import get_services
from .routes import events as events_routes
from .routes import stocks as stocks_routes


def create_app() -> FastAPI:
    app = FastAPI(
        title="金融分析与监控智能体（A 股）",
        version="0.1.0",
        description=(
            "面向中国 A 股市场的金融分析、事件监控与基于证据的调查智能体。\n\n"
            "- 指标分析：A1 / A2 / A3\n"
            "- 事件检测：B2\n"
            "- 事件调查：B3 / D2"
        ),
    )

    # 前端本地开发（Vite 默认 5173）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )

    app.include_router(stocks_routes.router)
    app.include_router(events_routes.router)

    @app.get("/api/health", tags=["system"], summary="健康检查")
    def health():
        svc = get_services()
        return {"status": "ok", **svc.info()}

    return app


app = create_app()
