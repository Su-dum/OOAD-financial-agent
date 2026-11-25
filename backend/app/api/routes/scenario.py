# -*- coding: utf-8 -*-
"""情景分析端点（D4）。

    POST /api/scenario   给定组合与假设，返回基线/压力对照 + 逐标的贡献 + 历史最差窗口

请求示例：

```json
{
  "codes": ["600519", "000001", "300750"],
  "market_shock": -0.10,
  "vol_multiplier": 1.5,
  "correlation_stress": 0.8,
  "drawdown": -0.15,
  "horizon_days": 20
}
```
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...application.scenario_service import ScenarioError
from ..deps import get_services

router = APIRouter(prefix="/api", tags=["scenario"])


class ScenarioRequest(BaseModel):
    codes: list[str] = Field(default_factory=lambda: ["600519", "000001", "300750"])
    weights: Optional[list[float]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    market_shock: float = Field(-0.10, ge=-0.5, le=0.5,
                               description="基准一次性涨跌，如 -0.1 = -10%")
    vol_multiplier: float = Field(1.5, ge=0.2, le=5.0,
                                 description="波动率放大倍数")
    correlation_stress: float = Field(0.5, ge=0.0, le=1.0,
                                     description="相关性向 1 靠拢的程度")
    drawdown: Optional[float] = Field(None, ge=-0.6, le=0.0,
                                     description="直接施加的组合回撤")
    horizon_days: int = Field(20, ge=1, le=250)
    benchmark: Optional[str] = "sh000300"
    source: Optional[str] = Field(
        "sina", description="优先数据源（sina 更快；传 null 走默认降级链）")


@router.post("/scenario", summary="情景分析：改假设看对组合的影响（D4）")
def run_scenario(req: ScenarioRequest):
    svc = get_services()
    try:
        return svc.scenario.run(
            req.codes, weights=req.weights, start=req.start, end=req.end,
            market_shock=req.market_shock, vol_multiplier=req.vol_multiplier,
            correlation_stress=req.correlation_stress, drawdown=req.drawdown,
            horizon_days=req.horizon_days, benchmark=req.benchmark,
            source=req.source)
    except ScenarioError as e:
        raise HTTPException(status_code=400, detail=str(e))
