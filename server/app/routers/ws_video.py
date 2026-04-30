"""WebSocket router for proxying Jetson MJPEG stream as binary WebSocket frames.

Implements ring buffer (size=2) to ensure latest frame always sent.
Target: 30 FPS / <20ms latency per plan specification.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.middleware.auth import verify_ws_token
from app.services import jetson_proxy

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)

# Ring buffer: only keep 2 latest frames
_frame_buffer: deque[bytes] = deque(maxlen=2)
_frame_event: asyncio.Event | None = None  # lazy-init inside running loop
_stream_task: asyncio.Task | None = None
_stream_clients: set[WebSocket] = set()


def _get_frame_event() -> asyncio.Event:
    """Lazy-init frame event inside the running event loop."""
    global _frame_event
    if _frame_event is None:
        _frame_event = asyncio.Event()
    return _frame_event



async def _start_frame_producer() -> None:
    """Pull frames from Jetson MJPEG stream and push into ring buffer."""
    global _stream_task

    async def _produce():
        while True:
            try:
                async for frame in jetson_proxy.stream_mjpeg_frames():
                    if not frame:
                        continue
                    _frame_buffer.append(frame)
                    ev = _get_frame_event()
                    ev.set()
                    ev.clear()
                    if not _stream_clients:
                        # No clients — pause polling
                        await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning("MJPEG producer error: %s — retrying in 2s", exc)
                await asyncio.sleep(2.0)

    _stream_task = asyncio.create_task(_produce())


@router.websocket("/video")
async def ws_video(websocket: WebSocket, token: str = Query(default="")):
    await websocket.accept()
    user = await verify_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    _stream_clients.add(websocket)

    # Start producer if not running
    global _stream_task
    if _stream_task is None or _stream_task.done():
        await _start_frame_producer()

    logger.info("WS /video connected: user=%s", user.get("sub"))

    try:
        last_frame: bytes | None = None
        while True:
            try:
                await asyncio.wait_for(_get_frame_event().wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Jetson stream offline — keep connection open, keep waiting
                await websocket.send_text('{"status":"stream_offline"}')
                continue

            if _frame_buffer:
                frame = _frame_buffer[-1]
                if frame != last_frame:
                    await websocket.send_bytes(frame)
                    last_frame = frame

    except WebSocketDisconnect:
        logger.info("WS /video disconnected: user=%s", user.get("sub"))
    except Exception as exc:
        logger.error("WS /video error: %s", exc)
    finally:
        _stream_clients.discard(websocket)

