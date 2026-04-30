from __future__ import annotations

from fastapi import APIRouter, Depends

from app.middleware.auth import get_current_operator, get_current_user
from app.services import analytics_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary", dependencies=[Depends(get_current_user)])
async def analytics_summary(hours: int = 24):
    return await analytics_service.get_summary(hours=hours)


@router.get("/timeseries", dependencies=[Depends(get_current_user)])
async def analytics_timeseries(hours: int = 6, limit: int = 240):
    return await analytics_service.get_timeseries(hours=hours, limit=limit)


@router.post("/collect-now", dependencies=[Depends(get_current_operator)])
async def collect_now():
    return await analytics_service.collect_snapshot()
