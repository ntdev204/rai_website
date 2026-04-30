"""REST API router for Jetson AI server proxying and robot node control."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.middleware.auth import get_current_admin, get_current_operator
from app.services import jetson_proxy
from app.services.zmq_bridge import get_latest_telemetry

router = APIRouter(prefix="/api/robot", tags=["robot"])


class ModeRequest(BaseModel):
    mode: str


class ConfigPatch(BaseModel):
    fps_target: float | None = None
    yolo_confidence_threshold: float | None = None
    watchdog_timeout_ms: float | None = None


@router.get("/status")
async def get_robot_status():
    """Get combined Pi telemetry and Jetson health."""
    telemetry = await get_latest_telemetry()
    health = await jetson_proxy.get_health()
    return {"robot": telemetry, "ai": health}


@router.get("/metrics")
async def get_ai_metrics():
    """Full AI inference metrics from Jetson."""
    return await jetson_proxy.get_metrics()


@router.get("/detections")
async def get_ai_detections():
    """Latest Jetson detection snapshot."""
    return await jetson_proxy.get_detections()


@router.post("/mode")
async def set_robot_mode(body: ModeRequest, current_user = Depends(get_current_admin)):
    """Set Jetson AI mode override. Admin only."""
    if body.mode.upper() == "FOLLOW":
        raise HTTPException(
            status_code=403,
            detail="FOLLOW mode has been removed",
        )
    result = await jetson_proxy.set_mode(body.mode)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/mode", dependencies=[Depends(get_current_admin)])
async def clear_robot_mode():
    """Clear mode override, restore the Jetson policy. Admin only."""
    return await jetson_proxy.clear_mode()


@router.post("/stop", dependencies=[Depends(get_current_operator)])
async def stop_robot():
    """Force immediate STOP. Operator+Admin."""
    return await jetson_proxy.force_stop()


@router.get("/config")
async def get_ai_config():
    """Get current Jetson runtime config."""
    return await jetson_proxy.get_config()


@router.patch("/config", dependencies=[Depends(get_current_admin)])
async def patch_ai_config(body: ConfigPatch):
    """Update Jetson runtime config. Admin only."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    return await jetson_proxy.patch_config(updates)
