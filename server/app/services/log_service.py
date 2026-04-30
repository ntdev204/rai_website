from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.event_log import EventLog
from app.services import jetson_proxy
from app.services.runtime_log_buffer import get_runtime_logs
from app.services.zmq_bridge import send_scada_command

logger = logging.getLogger(__name__)

_SEVERITY_MAP = {
    "debug": "DEBUG",
    "info": "INFO",
    "warn": "WARNING",
    "warning": "WARNING",
    "error": "ERROR",
    "fatal": "CRITICAL",
    "critical": "CRITICAL",
}


async def log_event(
    event_type: str,
    severity: str,
    source: str,
    message: str,
    metadata_json: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> EventLog | None:
    try:
        async with AsyncSessionLocal() as db:
            row = EventLog(
                event_type=event_type,
                severity=_normalize_severity(severity).lower(),
                source=source,
                message=message,
                metadata_json=metadata_json,
                user_id=user_id,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row
    except Exception as exc:
        logger.warning("Could not persist event log: %s", exc)
        return None


async def list_aggregated_logs(
    db: AsyncSession,
    limit: int = 100,
    event_type: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    include_external: bool = True,
    query: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    normalized_severity = _normalize_severity(severity) if severity else None

    logs = await _database_logs(
        db,
        limit=limit,
        event_type=event_type,
        severity=normalized_severity,
        source=source,
        query=query,
    )
    logs.extend(_filter_logs(get_runtime_logs(limit), normalized_severity, source, event_type, query))

    if include_external:
        context_task = asyncio.create_task(_context_aware_logs(limit))
        scada_task = asyncio.create_task(_wheeltec_logs(limit))
        external_results = await asyncio.gather(context_task, scada_task, return_exceptions=True)
        for result in external_results:
            if isinstance(result, Exception):
                logger.debug("External log source failed: %s", result)
                continue
            logs.extend(_filter_logs(result, normalized_severity, source, event_type, query))

    logs.sort(key=_log_sort_key, reverse=True)
    return logs[:limit]


async def _database_logs(
    db: AsyncSession,
    limit: int,
    event_type: str | None,
    severity: str | None,
    source: str | None,
    query: str | None,
) -> list[dict[str, Any]]:
    stmt = select(EventLog)
    if event_type:
        stmt = stmt.where(EventLog.event_type == event_type)
    if severity:
        stmt = stmt.where(EventLog.severity.in_([severity.lower(), severity.upper(), severity]))
    database_source_requested = bool(source and "database" in source.lower())
    if source and not database_source_requested:
        stmt = stmt.where(EventLog.source.ilike(f"%{source}%"))
    if query:
        stmt = stmt.where(EventLog.message.ilike(f"%{query}%"))
    stmt = stmt.order_by(desc(EventLog.created_at)).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    entries = [
        {
            "id": row.id,
            "event_type": row.event_type,
            "severity": _normalize_severity(row.severity),
            "source": row.source,
            "message": row.message,
            "metadata_json": row.metadata_json,
            "user_id": row.user_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    if database_source_requested:
        entries.append(_diagnostic_log("website.database", "INFO", f"EventLog database reachable; {len(rows)} rows matched"))
    return entries


async def _context_aware_logs(limit: int) -> list[dict[str, Any]]:
    result = await jetson_proxy.get_logs(limit=limit)
    if not isinstance(result, dict):
        return []
    if "error" in result:
        return [_diagnostic_log("context-aware", "WARNING", result["error"])]
    raw_logs = result.get("logs")
    if not isinstance(raw_logs, list):
        return []
    return [_normalize_external_log(item, "context-aware") for item in raw_logs if isinstance(item, dict)]


async def _wheeltec_logs(limit: int) -> list[dict[str, Any]]:
    result = await send_scada_command("get_logs", {"limit": limit}, timeout_ms=3000)
    if not isinstance(result, dict):
        return []
    if result.get("status") not in {"ok", "success"}:
        message = str(result.get("message") or result.get("status") or "SCADA log source unavailable")
        return [_diagnostic_log("wheeltec_ros2", "WARNING", message)]
    raw_logs = result.get("logs")
    if not isinstance(raw_logs, list):
        return []
    return [_normalize_external_log(item, "wheeltec_ros2") for item in raw_logs if isinstance(item, dict)]


def _normalize_external_log(item: dict[str, Any], default_source: str) -> dict[str, Any]:
    source = str(item.get("source") or default_source)
    timestamp = item.get("created_at") or item.get("timestamp") or datetime.now(timezone.utc).isoformat()
    return {
        "id": item.get("id") or f"{source}:{hash((timestamp, item.get('message')))}",
        "event_type": item.get("event_type") or item.get("logger") or "runtime",
        "severity": _normalize_severity(item.get("severity") or item.get("level") or "INFO"),
        "source": source,
        "message": str(item.get("message") or ""),
        "metadata_json": item.get("metadata_json") or item.get("metadata") or {},
        "user_id": item.get("user_id"),
        "created_at": timestamp,
    }


def _diagnostic_log(source: str, severity: str, message: str) -> dict[str, Any]:
    return {
        "id": f"diagnostic:{source}",
        "event_type": "log_source",
        "severity": _normalize_severity(severity),
        "source": source,
        "message": message,
        "metadata_json": {},
        "user_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _filter_logs(
    logs: list[dict[str, Any]],
    severity: str | None,
    source: str | None,
    event_type: str | None,
    query: str | None,
) -> list[dict[str, Any]]:
    filtered = []
    for log in logs:
        normalized = _normalize_external_log(log, str(log.get("source") or "unknown"))
        if severity and normalized["severity"] != severity:
            continue
        if source and source.lower() not in normalized["source"].lower():
            continue
        if event_type and normalized["event_type"] != event_type:
            continue
        if query and query.lower() not in normalized["message"].lower():
            continue
        filtered.append(normalized)
    return filtered


def _normalize_severity(value: Any) -> str:
    key = str(value or "INFO").strip().lower()
    return _SEVERITY_MAP.get(key, key.upper() if key else "INFO")


def _log_sort_key(log: dict[str, Any]) -> float:
    created_at = log.get("created_at")
    if isinstance(created_at, datetime):
        return created_at.timestamp()
    if isinstance(created_at, (int, float)):
        return float(created_at)
    if isinstance(created_at, str):
        text = created_at.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return 0.0
    return 0.0
