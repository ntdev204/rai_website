"""WebSocket router for proxying ROS2 camera frames from Wheeltec SCADA."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.middleware.auth import verify_ws_token
from app.services.zmq_bridge import get_latest_camera_jpeg

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)


@router.websocket("/video")
async def ws_video(websocket: WebSocket, token: str = Query(default="")):
    await websocket.accept()
    user = await verify_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    logger.info("WS /video connected: user=%s", user.get("sub"))

    try:
        last_received_at: float | None = None
        while True:
            frame, received_at = await get_latest_camera_jpeg()
            if frame and received_at and received_at != last_received_at:
                await websocket.send_bytes(frame)
                last_received_at = received_at
            elif not frame:
                await websocket.send_text('{"status":"stream_offline","source":"wheeltec_scada_bridge"}')
                await asyncio.sleep(1.0)
                continue
            await asyncio.sleep(0.03)
    except WebSocketDisconnect:
        logger.info("WS /video disconnected: user=%s", user.get("sub"))
    except Exception as exc:
        logger.error("WS /video error: %s", exc)
