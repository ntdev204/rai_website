"""Jetson adaptive-context-aware control-plane proxy.

The new adaptive runtime exposes a small FastAPI control API:
``/health``, ``/ready``, ``/metrics``, ``/config``, ``/control/start`` and
``/control/stop``. High-rate camera and perception data now flow through the
ROS2 SCADA bridge and adaptive ZMQ result plane instead of HTTP MJPEG or
legacy context-aware endpoints.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings
from app.services import adaptive_results

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def start_jetson_proxy() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.JETSON_API_URL,
        timeout=httpx.Timeout(connect=2.0, read=5.0, write=2.0, pool=5.0),
    )
    logger.info("Adaptive Jetson proxy client started: %s", settings.JETSON_API_URL)


async def stop_jetson_proxy() -> None:
    if _client:
        await _client.aclose()
    logger.info("Adaptive Jetson proxy client closed")


async def get_health() -> dict[str, Any]:
    health = await _request_json("GET", "/health", fallback={"status": "unreachable"})
    if health.get("status") == "unreachable":
        return health

    ready = await _request_json("GET", "/ready", fallback={})
    metrics = await get_metrics()
    return {
        "status": health.get("status", "ok"),
        "runtime": ready,
        "state": ready.get("state") or metrics.get("state"),
        "ready": bool(ready.get("ready", metrics.get("ready", False))),
        "reason": ready.get("reason") or metrics.get("reason"),
        "mode": ready.get("state") or metrics.get("state"),
        "service": "adaptive-context-aware",
    }


async def get_metrics() -> dict[str, Any]:
    raw = await _request_json("GET", "/metrics", fallback={})
    if not raw:
        return {}

    result = await adaptive_results.get_latest_result()
    result_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}

    total_latency_ms = _first_number(
        raw.get("inference_ms"),
        raw.get("total_latency_ms"),
        result_metrics.get("total_latency_ms"),
        result_metrics.get("inference_ms"),
    )
    fps = _first_number(raw.get("fps"), result_metrics.get("fps"))

    return {
        **raw,
        "mode": raw.get("state"),
        "fps": fps,
        "inference_ms": total_latency_ms,
        "persons": int(result.get("persons_count") or len(result.get("persons", []))),
        "obstacles": int(result.get("obstacles_count") or len(result.get("obstacles", []))),
        "result_connected": bool(result.get("connected")),
        "result_sequence": result.get("sequence"),
        "result_source_id": result.get("source_id"),
        "adaptive_metrics": result_metrics,
    }


async def get_detections() -> dict[str, Any]:
    result = await adaptive_results.get_latest_result()
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    return {
        "connected": bool(result.get("connected")),
        "frame_id": result.get("frame_id") or result.get("sequence"),
        "sequence": result.get("sequence"),
        "source_id": result.get("source_id"),
        "timestamp_us": result.get("timestamp_us"),
        "mode": "adaptive-context-aware",
        "inference_ms": metrics.get("total_latency_ms") or metrics.get("inference_ms"),
        "persons": result.get("persons", []),
        "obstacles": result.get("obstacles", []),
        "entities": result.get("entities", []),
    }


async def get_logs(limit: int = 200) -> dict[str, Any]:
    health = await get_health()
    metrics = await get_metrics()
    config = await get_config()
    logs = [
        {
            "severity": "INFO" if health.get("status") == "ok" else "WARNING",
            "source": "adaptive-context-aware",
            "event_type": "runtime_health",
            "message": (
                f"state={health.get('state') or '-'} ready={health.get('ready')} "
                f"reason={health.get('reason') or '-'}"
            ),
            "metadata": health,
        },
        {
            "severity": "INFO" if metrics.get("result_connected") else "WARNING",
            "source": "adaptive-context-aware",
            "event_type": "result_plane",
            "message": (
                f"result_connected={metrics.get('result_connected')} "
                f"sequence={metrics.get('result_sequence') or '-'}"
            ),
            "metadata": metrics,
        },
    ]
    if config:
        logs.append(
            {
                "severity": "INFO",
                "source": "adaptive-context-aware",
                "event_type": "runtime_config",
                "message": (
                    f"sensor_ingest={config.get('sensor_ingest_endpoint') or '-'} "
                    f"result_publish={config.get('result_publish_endpoint') or '-'}"
                ),
                "metadata": config,
            }
        )
    return {"logs": logs[: max(1, min(limit, 500))]}


async def set_mode(mode: str) -> dict[str, Any]:
    mode = mode.lower()
    if mode in {"run", "running", "start", "adaptive"}:
        return await start_runtime()
    if mode in {"stop", "stopped", "hold"}:
        return await stop_runtime()
    return {
        "error": "Adaptive runtime only supports start/stop control through the dashboard",
        "valid_modes": ["start", "stop"],
    }


async def clear_mode() -> dict[str, Any]:
    return await get_health()


async def force_stop() -> dict[str, Any]:
    return await stop_runtime()


async def start_runtime() -> dict[str, Any]:
    return await _request_json("POST", "/control/start", fallback={"error": "Adaptive runtime start failed"})


async def stop_runtime() -> dict[str, Any]:
    return await _request_json("POST", "/control/stop", fallback={"error": "Adaptive runtime stop failed"})


async def get_config() -> dict[str, Any]:
    return await _request_json("GET", "/config", fallback={})


async def patch_config(updates: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": "Adaptive runtime config is read-only from rai_website; update adaptive-context-aware env/config and restart.",
        "updates": updates,
    }


async def dataset_status() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "message": "On-robot collection endpoints were removed with adaptive-context-aware. Use server dataset upload/import.",
    }


async def dataset_start(mode: str) -> dict[str, Any]:
    return {"error": f"On-robot collection is unavailable for adaptive-context-aware mode '{mode}'."}


async def dataset_stop() -> dict[str, Any]:
    return {"error": "On-robot collection is unavailable for adaptive-context-aware."}


async def dataset_discard() -> dict[str, Any]:
    return {"error": "On-robot collection is unavailable for adaptive-context-aware."}


async def dataset_save() -> dict[str, Any]:
    return {"error": "On-robot collection is unavailable for adaptive-context-aware."}


async def dataset_images() -> dict[str, Any]:
    return {"images": [], "message": "On-robot image collection is unavailable for adaptive-context-aware."}


async def dataset_delete_image(index: int) -> dict[str, Any]:
    return {"error": f"On-robot image collection is unavailable; cannot delete image {index}."}


async def dataset_autolabel() -> dict[str, Any]:
    return {"error": "Jetson auto-label is unavailable. Use server auto-label."}


async def dataset_preview(index: int) -> tuple[bytes, str]:
    raise RuntimeError(f"On-robot collection preview is unavailable for image {index}")


async def dataset_download() -> tuple[AsyncIterator[bytes], dict[str, str]]:
    async def _empty() -> AsyncIterator[bytes]:
        if False:
            yield b""

    raise RuntimeError("On-robot collection download is unavailable for adaptive-context-aware")


async def stream_mjpeg_frames():
    if False:
        yield b""
    return


async def _request_json(method: str, path: str, *, fallback: dict[str, Any]) -> dict[str, Any]:
    if _client is None:
        return {**fallback, "error": "Jetson proxy client is not started"}
    try:
        response = await _client.request(method, path)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else fallback
    except Exception as exc:
        logger.warning("Adaptive Jetson %s %s failed: %s", method, path, exc)
        return {**fallback, "error": str(exc)}


def _first_number(*values: Any) -> float | None:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        return number
    return None
