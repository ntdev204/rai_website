"""Jetson AI Server Proxy.

Wraps the context-aware Edge API (running on Jetson Orin Nano Super at JETSON_API_URL).

Jetson API endpoints:
    GET  /health               → liveness + current mode/fps
    GET  /metrics              → full inference metrics
    GET  /stream               → MJPEG stream (for proxy to WS)
    WS   /ws/metrics           → live metrics push @ 1 Hz
    WS   /ws/detections        → per-frame detection JSON @ ~30 Hz
    POST /control/stop         → force STOP mode
    POST /control/mode/{mode}  → set mode override (STOP|CRUISE|CAUTIOUS|AVOID)
    DELETE /control/mode       → clear override, restore policy
    GET  /config               → current runtime config
    PATCH /config              → update fps_target, yolo_confidence_threshold, etc.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
VALID_MODES = frozenset({"STOP", "CRUISE", "CAUTIOUS", "AVOID", "YIELD"})


async def start_jetson_proxy() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.JETSON_API_URL,
        timeout=httpx.Timeout(connect=2.0, read=5.0, write=2.0, pool=5.0),
    )
    logger.info("Jetson proxy client started → %s", settings.JETSON_API_URL)


async def stop_jetson_proxy() -> None:
    if _client:
        await _client.aclose()
    logger.info("Jetson proxy client closed")


async def get_health() -> dict[str, Any]:
    try:
        r = await _client.get("/health")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Jetson /health failed: %s", exc)
        return {"status": "unreachable", "error": str(exc)}


async def get_metrics() -> dict[str, Any]:
    try:
        r = await _client.get("/metrics")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Jetson /metrics failed: %s", exc)
        return {}


async def get_detections() -> dict[str, Any]:
    try:
        r = await _client.get("/detections")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Jetson /detections failed: %s", exc)
        return {}


async def get_logs(limit: int = 200) -> dict[str, Any]:
    try:
        r = await _client.get("/logs", params={"limit": max(1, min(limit, 500))})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Jetson /logs failed: %s", exc)
        return {"error": str(exc)}


async def set_mode(mode: str) -> dict[str, Any]:
    mode = mode.upper()
    if mode not in VALID_MODES:
        return {"error": f"Invalid mode '{mode}'. Valid: {sorted(VALID_MODES)}"}
    try:
        r = await _client.post(f"/control/mode/{mode}")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson set_mode failed: %s", exc)
        return {"error": str(exc)}


async def clear_mode() -> dict[str, Any]:
    try:
        r = await _client.delete("/control/mode")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson clear_mode failed: %s", exc)
        return {"error": str(exc)}


async def force_stop() -> dict[str, Any]:
    try:
        r = await _client.post("/control/stop")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson force_stop failed: %s", exc)
        return {"error": str(exc)}


async def get_config() -> dict[str, Any]:
    try:
        r = await _client.get("/config")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Jetson /config GET failed: %s", exc)
        return {}


async def patch_config(updates: dict[str, Any]) -> dict[str, Any]:
    try:
        r = await _client.patch("/config", json=updates)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson /config PATCH failed: %s", exc)
        return {"error": str(exc)}


async def dataset_status() -> dict[str, Any]:
    try:
        r = await _client.get("/dataset/status")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Jetson /dataset/status failed: %s", exc)
        return {"status": "unreachable", "error": str(exc)}


async def dataset_start(mode: str) -> dict[str, Any]:
    try:
        r = await _client.post("/dataset/start", json={"mode": mode})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson /dataset/start failed: %s", exc)
        return {"error": str(exc)}


async def dataset_stop() -> dict[str, Any]:
    try:
        r = await _client.post("/dataset/stop")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson /dataset/stop failed: %s", exc)
        return {"error": str(exc)}


async def dataset_discard() -> dict[str, Any]:
    try:
        r = await _client.delete("/dataset")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson DELETE /dataset failed: %s", exc)
        return {"error": str(exc)}


async def dataset_save() -> dict[str, Any]:
    try:
        r = await _client.post("/dataset/save")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson /dataset/save failed: %s", exc)
        return {"error": str(exc)}


async def dataset_images() -> dict[str, Any]:
    try:
        r = await _client.get("/dataset/images")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson /dataset/images failed: %s", exc)
        return {"error": str(exc)}


async def dataset_delete_image(index: int) -> dict[str, Any]:
    try:
        r = await _client.delete(f"/dataset/images/{index}")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson DELETE /dataset/images/%s failed: %s", index, exc)
        return {"error": str(exc)}


async def dataset_autolabel() -> dict[str, Any]:
    try:
        r = await _client.post("/dataset/autolabel", timeout=120.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("Jetson /dataset/autolabel failed: %s", exc)
        return {"error": str(exc)}


async def dataset_preview(index: int) -> tuple[bytes, str]:
    try:
        r = await _client.get(f"/dataset/preview/{index}")
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/jpeg")
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise RuntimeError(f"Jetson preview failed with status {status}") from exc
    except Exception as exc:
        raise RuntimeError(f"Jetson preview failed: {exc}") from exc


async def dataset_download() -> tuple[AsyncIterator[bytes], dict[str, str]]:
    try:
        request = _client.build_request("GET", "/dataset/download")
        response = await _client.send(request, stream=True)
        response.raise_for_status()
    except Exception as exc:
        logger.error("Jetson /dataset/download failed: %s", exc)
        raise RuntimeError(str(exc)) from exc

    headers = {
        "content-type": response.headers.get("content-type", "application/zip"),
        "content-disposition": response.headers.get("content-disposition", ""),
    }

    async def _iter() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return _iter(), headers


async def stream_mjpeg_frames():
    """Async generator yielding raw JPEG bytes from Jetson MJPEG stream."""
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    try:
        async with _client.stream("GET", "/stream") as response:
            buffer = b""
            async for chunk in response.aiter_bytes(chunk_size=65536):
                buffer += chunk
                # Parse MJPEG boundary
                while True:
                    start = buffer.find(boundary)
                    if start == -1:
                        break
                    end = buffer.find(b"\r\n--frame", start + len(boundary))
                    if end == -1:
                        break
                    frame_bytes = buffer[start + len(boundary):end]
                    if frame_bytes:
                        yield frame_bytes
                    buffer = buffer[end:]
    except Exception as exc:
        logger.error("MJPEG stream error: %s", exc)
