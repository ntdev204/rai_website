"""WebSocket router for robot control (teleop).

Flow:
    Client WS → POST json {type, linear, angular}
    → ZMQ Bridge REQ/REP JSON → Pi SCADA → /cmd_vel_keyboard → twist_mux

Only authenticated users can connect. FOLLOW is not accepted because camera-based
person following has been removed from the Jetson pipeline.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.middleware.auth import verify_ws_token
from app.services.zmq_bridge import send_teleop_cmd
from app.services import jetson_proxy

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)
TELEOP_SEND_INTERVAL_S = 0.05


@router.websocket("/control")
async def ws_control(websocket: WebSocket, token: str = Query(default="")):
    await websocket.accept()
    user = await verify_ws_token(token)
    if not user:
        print("[ws_control] AUTH FAILED - closing", flush=True)
        await websocket.close(code=4001, reason="Unauthorized")
        return
    print(f"[ws_control] AUTH OK user={user.get('sub')}", flush=True)
    logger.info("WS /control connected: user=%s", user.get("sub"))

    latest_cmd = {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}
    cmd_event = asyncio.Event()
    sender_running = True

    async def teleop_sender() -> None:
        last_sent = None
        try:
            while sender_running:
                try:
                    await asyncio.wait_for(cmd_event.wait(), timeout=TELEOP_SEND_INTERVAL_S)
                except asyncio.TimeoutError:
                    pass

                cmd_event.clear()
                current = dict(latest_cmd)
                moving = any(abs(current[k]) > 1e-6 for k in ("linear_x", "linear_y", "angular_z"))
                changed = current != last_sent

                if not moving and not changed:
                    continue

                result = await send_teleop_cmd(
                    current["linear_x"],
                    current["linear_y"],
                    current["angular_z"],
                )
                last_sent = current

                if result.get("status") in {"error", "timeout"}:
                    await websocket.send_text(json.dumps(result))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Teleop sender loop error: %s", exc)

    sender_task = asyncio.create_task(teleop_sender())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "cmd_vel_teleop":
                linear = msg.get("linear", {})
                angular = msg.get("angular", {})
                lx = float(linear.get("x", 0))
                ly = float(linear.get("y", 0))
                az = float(angular.get("z", 0))

                lx = max(-1.0, min(1.0, lx))
                ly = max(-1.0, min(1.0, ly))
                az = max(-2.0, min(2.0, az))

                latest_cmd["linear_x"] = lx
                latest_cmd["linear_y"] = ly
                latest_cmd["angular_z"] = az
                cmd_event.set()

            elif msg_type == "set_mode":
                mode = str(msg.get("mode", "")).upper()
                if mode == "FOLLOW":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "error": "FOLLOW mode has been removed"
                            }
                        )
                    )
                    continue
                result = await jetson_proxy.set_mode(mode)
                await websocket.send_text(json.dumps(result))

            elif msg_type == "clear_mode":
                result = await jetson_proxy.clear_mode()
                await websocket.send_text(json.dumps(result))

            elif msg_type == "stop":
                latest_cmd["linear_x"] = 0.0
                latest_cmd["linear_y"] = 0.0
                latest_cmd["angular_z"] = 0.0
                cmd_event.set()
                result = await jetson_proxy.force_stop()
                await websocket.send_text(json.dumps(result))

    except WebSocketDisconnect:
        logger.info("WS /control disconnected: user=%s", user.get("sub"))
        latest_cmd["linear_x"] = 0.0
        latest_cmd["linear_y"] = 0.0
        latest_cmd["angular_z"] = 0.0
        cmd_event.set()
        await send_teleop_cmd(0, 0, 0)
    except Exception as exc:
        logger.error("WS /control error: %s", exc)
        latest_cmd["linear_x"] = 0.0
        latest_cmd["linear_y"] = 0.0
        latest_cmd["angular_z"] = 0.0
        cmd_event.set()
        await send_teleop_cmd(0, 0, 0)
    finally:
        sender_running = False
        cmd_event.set()
        sender_task.cancel()
        with suppress(asyncio.CancelledError):
            await sender_task
