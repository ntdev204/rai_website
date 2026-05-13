"""REST API router for adaptive laptop runtime and robot node control."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.middleware.auth import get_current_admin, get_current_operator
from app.services import adaptive_proxy
from app.services.zmq_bridge import get_latest_telemetry

router = APIRouter(prefix="/api/robot", tags=["robot"])


class ModeRequest(BaseModel):
    mode: str


class ConfigPatch(BaseModel):
    max_sensor_age_ms: float | None = None
    camera_fps: float | None = None


@router.get("/status")
async def get_robot_status():
    """Get combined Pi telemetry and adaptive runtime health."""
    telemetry = await get_latest_telemetry()
    health = await adaptive_proxy.get_health()
    return {"robot": telemetry, "ai": health}


@router.get("/metrics")
async def get_ai_metrics():
    """Adaptive runtime metrics plus latest ZMQ result-plane stats."""
    return await adaptive_proxy.get_metrics()


@router.get("/detections")
async def get_ai_detections():
    """Latest adaptive perception result snapshot."""
    return await adaptive_proxy.get_detections()


@router.post("/mode")
async def set_robot_mode(body: ModeRequest, current_user = Depends(get_current_admin)):
    """Start or stop the adaptive runtime. Admin only."""
    if body.mode.upper() in {"FOLLOW", "CRUISE", "CAUTIOUS", "AVOID", "YIELD"}:
        raise HTTPException(
            status_code=403,
            detail="Legacy context-aware mode overrides have been removed; use start/stop.",
        )
    result = await adaptive_proxy.set_mode(body.mode)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/mode", dependencies=[Depends(get_current_admin)])
async def clear_robot_mode():
    """Return current adaptive runtime state. Admin only."""
    return await adaptive_proxy.clear_mode()


@router.post("/stop", dependencies=[Depends(get_current_operator)])
async def stop_robot():
    """Stop the adaptive runtime. Operator+Admin."""
    return await adaptive_proxy.force_stop()


@router.get("/config")
async def get_ai_config():
    """Get current adaptive runtime config."""
    return await adaptive_proxy.get_config()


@router.patch("/config", dependencies=[Depends(get_current_admin)])
async def patch_ai_config(body: ConfigPatch):
    """Return a read-only config error for adaptive runtime. Admin only."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    return await adaptive_proxy.patch_config(updates)
