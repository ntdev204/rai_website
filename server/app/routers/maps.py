from __future__ import annotations

import asyncio
import base64
import re
from typing import Any, Literal

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from unidecode import unidecode

from app.core.database import get_db
from app.middleware.auth import get_current_operator, get_current_user
from app.models.map import Map
from app.services.zmq_bridge import (
    get_latest_map_png,
    get_latest_telemetry,
    send_scada_command,
)

router = APIRouter(prefix="/api/maps", tags=["maps"])


class MapModeRequest(BaseModel):
    mode: Literal["slam", "nav2"]
    map_id: int | None = None


class Nav2ControlRequest(BaseModel):
    map_id: int | None = None


class SaveMapRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=255)


class NavGoalRequest(BaseModel):
    x: float
    y: float
    theta: float = 0.0


def _map_metadata(row: Map) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "resolution": row.resolution,
        "width": row.width,
        "height": row.height,
        "origin_x": row.origin_x,
        "origin_y": row.origin_y,
        "source": row.source,
        "is_active": row.is_active,
        "created_at": row.created_at,
    }


def _slug_base(name: str) -> str:
    slug = unidecode(name).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "map"


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = _slug_base(name)
    slug = base
    suffix = 2
    while True:
        existing = (await db.execute(select(Map.id).where(Map.slug == slug).limit(1))).scalar_one_or_none()
        if existing is None:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


def _decode_base64_blob(value: Any) -> bytes | None:
    if not value:
        return None
    try:
        return base64.b64decode(str(value), validate=True)
    except Exception:
        return None


def _png_dimensions(png: bytes | None) -> tuple[int, int] | None:
    if not png:
        return None
    try:
        arr = np.frombuffer(png, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if image is None:
            return None
        height, width = image.shape[:2]
        return int(width), int(height)
    except Exception:
        return None


def _map_info_value(info: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(info, dict):
        return default
    return info.get(key, default)


def _origin_from_info(info: dict[str, Any] | None) -> tuple[float, float]:
    origin = _map_info_value(info, "origin", {})
    if not isinstance(origin, dict):
        origin = {}
    return float(origin.get("x", 0.0) or 0.0), float(origin.get("y", 0.0) or 0.0)


def _yaml_from_info(info: dict[str, Any] | None, image_name: str) -> str | None:
    if not isinstance(info, dict):
        return None
    origin_x, origin_y = _origin_from_info(info)
    resolution = float(info.get("resolution", 0.05) or 0.05)
    return "\n".join(
        [
            f"image: {image_name}.pgm",
            f"resolution: {resolution}",
            f"origin: [{origin_x}, {origin_y}, 0.0]",
            "negate: 0",
            "occupied_thresh: 0.65",
            "free_thresh: 0.25",
            "",
        ]
    )


async def _active_map_row(db: AsyncSession) -> Map | None:
    return (
        await db.execute(select(Map).where(Map.is_active.is_(True)).order_by(desc(Map.created_at)).limit(1))
    ).scalars().first()


async def _activate_map(db: AsyncSession, row: Map) -> None:
    await db.execute(update(Map).values(is_active=False))
    row.is_active = True


@router.get("/", dependencies=[Depends(get_current_user)])
async def list_maps(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Map).order_by(desc(Map.created_at)))).scalars().all()
    return [_map_metadata(row) for row in rows]


@router.get("/active", dependencies=[Depends(get_current_user)])
async def get_active_map(db: AsyncSession = Depends(get_db)):
    row = await _active_map_row(db)
    if row is None:
        raise HTTPException(status_code=404, detail="No active map")
    return _map_metadata(row)


@router.get("/live/info", dependencies=[Depends(get_current_user)])
async def get_live_map_info():
    telemetry = await get_latest_telemetry()
    png, received_at = await get_latest_map_png()
    return {
        "map_info": telemetry.get("map_info"),
        "has_image": png is not None,
        "received_at": received_at,
    }


@router.get("/live/image", dependencies=[Depends(get_current_user)])
async def get_live_map_image():
    png, _ = await get_latest_map_png()
    if png is None:
        await send_scada_command("resend_map", {})
        await asyncio.sleep(0.2)
        png, _ = await get_latest_map_png()
    if png is None:
        raise HTTPException(status_code=404, detail="No live map image available")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/live/trigger", dependencies=[Depends(get_current_operator)])
async def trigger_live_map_resend():
    return await send_scada_command("resend_map", {})


@router.post("/slam/{action}", dependencies=[Depends(get_current_operator)])
async def control_slam(action: Literal["start", "reset", "stop"]):
    reply = await send_scada_command(
        "slam_control",
        {"action": action},
        timeout_ms=60000 if action == "reset" else 10000,
    )
    status = str(reply.get("status", "")).lower()
    if status in {"error", "timeout", "unknown_action", "pending_implementation"}:
        raise HTTPException(status_code=502, detail=reply.get("message") or reply.get("status"))
    return {"status": "ok", "action": action, "scada": reply}


@router.post("/nav2/{action}", dependencies=[Depends(get_current_operator)])
async def control_nav2(
    action: Literal["start", "stop"],
    body: Nav2ControlRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload: dict[str, Any] = {"action": action}
    active_row: Map | None = None

    if action == "start":
        map_id = body.map_id if body else None
        if map_id is not None:
            active_row = await db.get(Map, map_id)
            if active_row is None:
                raise HTTPException(status_code=404, detail="Map not found")
            await _activate_map(db, active_row)
            await db.commit()
            await db.refresh(active_row)
        else:
            active_row = await _active_map_row(db)
            if active_row is None:
                raise HTTPException(status_code=400, detail="Nav2 requires a saved map")

        payload.update(
            {
                "map_id": active_row.id,
                "map_name": active_row.name,
                "map_path": active_row.source,
                "resolution": active_row.resolution,
                "width": active_row.width,
                "height": active_row.height,
                "origin": {"x": active_row.origin_x, "y": active_row.origin_y},
            }
        )

    reply = await send_scada_command("nav2_control", payload, timeout_ms=10000)
    status = str(reply.get("status", "")).lower()
    if status in {"error", "timeout", "unknown_action", "pending_implementation"}:
        raise HTTPException(status_code=502, detail=reply.get("message") or reply.get("status"))
    return {"status": "ok", "action": action, "map": _map_metadata(active_row) if active_row else None, "scada": reply}


@router.get("/{map_id}/image", dependencies=[Depends(get_current_user)])
async def get_saved_map_image(map_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(Map, map_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Map not found")
    if not row.png_data:
        raise HTTPException(status_code=404, detail="Map image not stored")
    return Response(content=row.png_data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/{map_id}/activate", dependencies=[Depends(get_current_operator)])
async def activate_saved_map(map_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(Map, map_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Map not found")
    await _activate_map(db, row)
    await db.commit()
    await db.refresh(row)
    return _map_metadata(row)


@router.delete("/{map_id}", dependencies=[Depends(get_current_operator)])
async def delete_saved_map(map_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(Map, map_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Map not found")

    deleted_map = _map_metadata(row)
    was_active = bool(row.is_active)
    next_active = None
    if was_active:
        next_active = (
            await db.execute(
                select(Map)
                .where(Map.id != map_id)
                .order_by(desc(Map.created_at))
                .limit(1)
            )
        ).scalars().first()
        if next_active is not None:
            next_active.is_active = True

    await db.delete(row)
    await db.commit()
    if next_active is not None:
        await db.refresh(next_active)

    return {
        "status": "deleted",
        "deleted_map": deleted_map,
        "active_map": _map_metadata(next_active) if next_active else None,
    }


@router.post("/mode", dependencies=[Depends(get_current_operator)])
async def set_navigation_mode(body: MapModeRequest, db: AsyncSession = Depends(get_db)):
    payload: dict[str, Any] = {"mode": body.mode}
    active_row: Map | None = None

    if body.mode == "nav2":
        if body.map_id is not None:
            active_row = await db.get(Map, body.map_id)
            if active_row is None:
                raise HTTPException(status_code=404, detail="Map not found")
            await _activate_map(db, active_row)
            await db.commit()
            await db.refresh(active_row)
        else:
            active_row = await _active_map_row(db)
            if active_row is None:
                raise HTTPException(status_code=400, detail="Nav2 requires a saved map")

        payload.update(
            {
                "map_id": active_row.id,
                "map_name": active_row.name,
                "map_path": active_row.source,
                "resolution": active_row.resolution,
                "width": active_row.width,
                "height": active_row.height,
                "origin": {"x": active_row.origin_x, "y": active_row.origin_y},
            }
        )

    reply = await send_scada_command("navigation_mode", payload, timeout_ms=10000)
    status = str(reply.get("status", "")).lower()
    if status in {"error", "timeout", "unknown_action", "pending_implementation"}:
        raise HTTPException(status_code=502, detail=reply.get("message") or reply.get("status"))
    return {"status": "ok", "mode": body.mode, "map": _map_metadata(active_row) if active_row else None, "scada": reply}


@router.post("/save", dependencies=[Depends(get_current_operator)])
async def save_live_map(body: SaveMapRequest, db: AsyncSession = Depends(get_db)):
    reply = await send_scada_command(
        "slam_control",
        {"action": "save", "name": body.name},
        timeout_ms=60000,
    )
    status = str(reply.get("status", "")).lower()
    if status in {"error", "timeout", "unknown_action", "pending_implementation"}:
        raise HTTPException(status_code=502, detail=reply.get("message") or reply.get("status"))

    telemetry = await get_latest_telemetry()
    live_png, _ = await get_latest_map_png()

    png_data = _decode_base64_blob(reply.get("png_base64")) or live_png
    if png_data is None:
        await send_scada_command("resend_map", {})
        await asyncio.sleep(0.2)
        png_data, _ = await get_latest_map_png()
    if png_data is None:
        raise HTTPException(status_code=409, detail="No map image available to store")

    pgm_data = _decode_base64_blob(reply.get("pgm_base64"))
    map_info = reply.get("map_info") if isinstance(reply.get("map_info"), dict) else telemetry.get("map_info")
    dimensions = _png_dimensions(png_data)

    width = int(_map_info_value(map_info, "width", dimensions[0] if dimensions else 0) or 0)
    height = int(_map_info_value(map_info, "height", dimensions[1] if dimensions else 0) or 0)
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=409, detail="No valid map dimensions available")

    origin_x, origin_y = _origin_from_info(map_info)
    resolution = float(_map_info_value(map_info, "resolution", 0.05) or 0.05)
    slug = await _unique_slug(db, body.name)
    yaml_config = str(reply.get("yaml") or "") or _yaml_from_info(map_info, slug)

    row = Map(
        name=body.name.strip(),
        slug=slug,
        description=body.description,
        resolution=resolution,
        width=width,
        height=height,
        origin_x=origin_x,
        origin_y=origin_y,
        png_data=png_data,
        pgm_data=pgm_data,
        yaml_config=yaml_config,
        source=reply.get("source") or reply.get("yaml_path") or f"db:{slug}",
        is_active=True,
    )
    await db.execute(update(Map).values(is_active=False))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"status": "saved", "map": _map_metadata(row), "scada": reply}


@router.post("/goal", dependencies=[Depends(get_current_operator)])
async def send_nav_goal(body: NavGoalRequest):
    reply = await send_scada_command("nav_goal", {"x": body.x, "y": body.y, "theta": body.theta})
    status = str(reply.get("status", "")).lower()
    if status in {"error", "timeout", "unknown_action"}:
        raise HTTPException(status_code=502, detail=reply.get("message") or reply.get("status"))
    return {"status": "goal_sent", "goal": body.model_dump(), "scada": reply}
