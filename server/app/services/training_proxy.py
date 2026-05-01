from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def start_training_proxy() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.TRAINING_API_URL,
        timeout=httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=5.0),
    )
    logger.info("Training proxy client started -> %s", settings.TRAINING_API_URL)


async def stop_training_proxy() -> None:
    if _client:
        await _client.aclose()
    logger.info("Training proxy client closed")


async def training_defaults() -> dict[str, Any]:
    return await _request_json("GET", "/training/defaults")


async def training_status() -> dict[str, Any]:
    return await _request_json("GET", "/training/status")


async def training_start(payload: dict[str, Any]) -> dict[str, Any]:
    return await _request_json("POST", "/training/start", json=payload)


async def training_stop() -> dict[str, Any]:
    return await _request_json("POST", "/training/stop")


async def _request_json(method: str, path: str, **kwargs) -> dict[str, Any]:
    if _client is None:
        return {"error": "Training proxy is not initialized"}
    try:
        response = await _client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail")
        except Exception:
            detail = exc.response.text
        return {"error": detail or str(exc)}
    except Exception as exc:
        logger.warning("Training API %s %s failed: %s", method, path, exc)
        return {"error": str(exc)}
