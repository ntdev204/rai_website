from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.middleware.auth import verify_ws_token
from app.services.ssh_terminal import SshTerminalSession, get_available_targets

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)


@router.websocket("/ssh")
async def ws_ssh(websocket: WebSocket, token: str = Query(default=""), target: str = Query(default="")):
    await websocket.accept()

    if not settings.SSH_ENABLED:
        await websocket.send_text(json.dumps({"type": "error", "message": "SSH terminal is disabled"}))
        await websocket.close(code=4403, reason="SSH disabled")
        return

    user = await verify_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    if user.get("role") != "admin":
        await websocket.send_text(json.dumps({"type": "error", "message": "Admin role required"}))
        await websocket.close(code=4403, reason="Forbidden")
        return

    available_targets = get_available_targets()
    ssh_target = available_targets.get(target)
    if not ssh_target:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": "Unknown SSH target",
                    "availableTargets": list(available_targets.keys()),
                }
            )
        )
        await websocket.close(code=4404, reason="Unknown target")
        return

    session = SshTerminalSession(ssh_target)

    async def emit(payload: dict) -> None:
        await websocket.send_text(json.dumps(payload))

    try:
        await session.start(emit)
        await emit(
            {
                "type": "status",
                "status": "connected",
                "target": ssh_target.name,
                "label": f"{ssh_target.user}@{ssh_target.host}",
            }
        )

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = message.get("type")
            if msg_type == "input":
                data = message.get("data", "")
                if data:
                    await session.send(str(data))
            elif msg_type == "resize":
                continue
            elif msg_type == "ping":
                await emit({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("WS /ssh disconnected: user=%s target=%s", user.get("sub"), target)
    except Exception as exc:
        logger.exception("WS /ssh error: %s", exc)
        try:
            await emit({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await session.close()
        code = session.process.returncode if session.process else None
        try:
            await emit({"type": "status", "status": "closed", "code": code})
        except Exception:
            pass
