"""WebSocket router for robot telemetry and Jetson AI metrics.

Pushes merged telemetry (Pi robot state + Jetson AI metrics) to all connected clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.middleware.auth import verify_ws_token
from app.services.zmq_bridge import get_latest_telemetry
from app.services import jetson_proxy

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)

# Connected clients set for broadcast
_telemetry_clients: set[WebSocket] = set()


@router.websocket("/telemetry")
async def ws_telemetry(websocket: WebSocket, token: str = Query(default="")):
    await websocket.accept()
    user = await verify_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    _telemetry_clients.add(websocket)
    logger.info("WS /telemetry connected: user=%s", user.get("sub"))

    try:
        while True:
            # Fetch latest robot state from Pi via ZMQ bridge
            robot_state = await get_latest_telemetry()

            # Fetch AI metrics from Jetson (non-blocking, cached TTL)
            jetson_metrics = await jetson_proxy.get_metrics()

            payload: dict[str, Any] = {
                "robot": robot_state,
                "ai": jetson_metrics,
            }

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.5)  # Push at 2 Hz

    except WebSocketDisconnect:
        logger.info("WS /telemetry disconnected: user=%s", user.get("sub"))
    except Exception as exc:
        logger.error("WS /telemetry error: %s", exc)
    finally:
        _telemetry_clients.discard(websocket)
