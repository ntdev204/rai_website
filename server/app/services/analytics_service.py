from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, desc, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.analytics_snapshot import AnalyticsSnapshot
from app.models.event_log import EventLog
from app.services import jetson_proxy
from app.services.log_service import log_event
from app.services.zmq_bridge import get_latest_telemetry

logger = logging.getLogger(__name__)

_collector_task: asyncio.Task | None = None
_collector_running = False
_last_connected: bool | None = None
_last_ai_online: bool | None = None
_last_low_battery_log_at = 0.0
_last_cleanup_at = 0.0


async def start_analytics_collector() -> None:
    global _collector_task, _collector_running
    if _collector_task and not _collector_task.done():
        return
    _collector_running = True
    _collector_task = asyncio.create_task(_collector_loop(), name="analytics_collector")
    logger.info("Analytics collector started")
    await log_event(
        event_type="analytics_collector_started",
        severity="info",
        source="website.analytics",
        message="Analytics collection started",
        metadata_json={"interval_sec": settings.ANALYTICS_COLLECT_INTERVAL_SEC},
    )


async def stop_analytics_collector() -> None:
    global _collector_running
    _collector_running = False
    if _collector_task:
        _collector_task.cancel()
        await asyncio.gather(_collector_task, return_exceptions=True)
    logger.info("Analytics collector stopped")


async def collect_snapshot() -> dict[str, Any]:
    telemetry = await get_latest_telemetry()
    ai_metrics = await jetson_proxy.get_metrics()
    snapshot = _build_snapshot(telemetry, ai_metrics)

    async with AsyncSessionLocal() as db:
        db.add(snapshot)
        await db.commit()
        await db.refresh(snapshot)

    await _emit_state_events(snapshot, ai_metrics)
    await _cleanup_old_snapshots()
    return _snapshot_payload(snapshot)


async def get_summary(hours: int = 24) -> dict[str, Any]:
    hours = max(1, min(hours, settings.ANALYTICS_RETENTION_HOURS))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with AsyncSessionLocal() as db:
        current = (
            await db.execute(select(AnalyticsSnapshot).order_by(desc(AnalyticsSnapshot.created_at)).limit(1))
        ).scalar_one_or_none()

        aggregates = (
            await db.execute(
                select(
                    func.count(AnalyticsSnapshot.id).label("samples"),
                    func.avg(AnalyticsSnapshot.voltage).label("avg_voltage"),
                    func.min(AnalyticsSnapshot.voltage).label("min_voltage"),
                    func.avg(AnalyticsSnapshot.battery_percent).label("avg_battery"),
                    func.avg(AnalyticsSnapshot.speed).label("avg_speed"),
                    func.max(AnalyticsSnapshot.speed).label("max_speed"),
                    func.avg(AnalyticsSnapshot.ai_fps).label("avg_ai_fps"),
                    func.sum(AnalyticsSnapshot.ai_persons).label("person_observations"),
                    func.sum(AnalyticsSnapshot.ai_obstacles).label("obstacle_observations"),
                ).where(AnalyticsSnapshot.created_at >= since)
            )
        ).mappings().one()

        mode_rows = (
            await db.execute(
                select(AnalyticsSnapshot.navigation_mode, func.count(AnalyticsSnapshot.id))
                .where(AnalyticsSnapshot.created_at >= since)
                .group_by(AnalyticsSnapshot.navigation_mode)
            )
        ).all()
        severity_rows = (
            await db.execute(
                select(EventLog.severity, func.count(EventLog.id))
                .where(EventLog.created_at >= since)
                .group_by(EventLog.severity)
            )
        ).all()
        source_rows = (
            await db.execute(
                select(EventLog.source, func.count(EventLog.id))
                .where(EventLog.created_at >= since)
                .group_by(EventLog.source)
            )
        ).all()
        alert_rows = (
            await db.execute(
                select(EventLog)
                .where(EventLog.created_at >= since)
                .where(EventLog.severity.in_(("warning", "error", "critical", "WARNING", "ERROR", "CRITICAL")))
                .order_by(desc(EventLog.created_at))
                .limit(10)
            )
        ).scalars().all()

    return {
        "collector": {
            "running": _collector_running,
            "interval_sec": settings.ANALYTICS_COLLECT_INTERVAL_SEC,
            "retention_hours": settings.ANALYTICS_RETENTION_HOURS,
        },
        "current": _snapshot_payload(current) if current else None,
        "window": {
            "hours": hours,
            "samples": int(aggregates["samples"] or 0),
            "avg_voltage": _round(aggregates["avg_voltage"]),
            "min_voltage": _round(aggregates["min_voltage"]),
            "avg_battery_percent": _round(aggregates["avg_battery"]),
            "avg_speed": _round(aggregates["avg_speed"]),
            "max_speed": _round(aggregates["max_speed"]),
            "avg_ai_fps": _round(aggregates["avg_ai_fps"]),
            "person_observations": int(aggregates["person_observations"] or 0),
            "obstacle_observations": int(aggregates["obstacle_observations"] or 0),
            "navigation_modes": {str(mode or "unknown"): int(count) for mode, count in mode_rows},
        },
        "logs": {
            "by_severity": {str(sev or "unknown").upper(): int(count) for sev, count in severity_rows},
            "by_source": {str(src or "unknown"): int(count) for src, count in source_rows},
            "recent_alerts": [_event_payload(row) for row in alert_rows],
        },
    }


async def get_timeseries(hours: int = 6, limit: int = 240) -> list[dict[str, Any]]:
    hours = max(1, min(hours, settings.ANALYTICS_RETENTION_HOURS))
    limit = max(1, min(limit, 1000))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AnalyticsSnapshot)
                .where(AnalyticsSnapshot.created_at >= since)
                .order_by(desc(AnalyticsSnapshot.created_at))
                .limit(limit)
            )
        ).scalars().all()

    return [_snapshot_payload(row) for row in reversed(rows)]


async def _collector_loop() -> None:
    while _collector_running:
        started = time.monotonic()
        try:
            await collect_snapshot()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Analytics collection failed: %s", exc)
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1.0, settings.ANALYTICS_COLLECT_INTERVAL_SEC - elapsed))


def _build_snapshot(telemetry: dict[str, Any], ai_metrics: dict[str, Any]) -> AnalyticsSnapshot:
    vx = _float_or_none(telemetry.get("vx"))
    vy = _float_or_none(telemetry.get("vy"))
    vtheta = _float_or_none(telemetry.get("vtheta"))
    ai_velocity = ai_metrics.get("robot_velocity") if isinstance(ai_metrics.get("robot_velocity"), dict) else {}
    vx = vx if vx is not None else _float_or_none(ai_velocity.get("vx"))
    vy = vy if vy is not None else _float_or_none(ai_velocity.get("vy"))
    vtheta = vtheta if vtheta is not None else _float_or_none(ai_velocity.get("vtheta"))
    speed = math.sqrt((vx or 0.0) ** 2 + (vy or 0.0) ** 2)

    return AnalyticsSnapshot(
        connected=bool(telemetry.get("connected")),
        navigation_mode=telemetry.get("navigation_mode"),
        voltage=_float_or_none(telemetry.get("voltage")),
        battery_percent=_float_or_none(telemetry.get("battery_percent")),
        pos_x=_float_or_none(telemetry.get("pos_x")),
        pos_y=_float_or_none(telemetry.get("pos_y")),
        yaw=_float_or_none(telemetry.get("yaw")),
        vx=vx,
        vy=vy,
        vtheta=vtheta,
        speed=round(speed, 4),
        ai_mode=ai_metrics.get("mode"),
        ai_fps=_float_or_none(ai_metrics.get("fps")),
        ai_inference_ms=_float_or_none(ai_metrics.get("inference_ms")),
        ai_persons=_int_or_none(ai_metrics.get("persons")),
        ai_obstacles=_int_or_none(ai_metrics.get("obstacles")),
        metrics_json={"robot": telemetry, "ai": ai_metrics},
    )


async def _emit_state_events(snapshot: AnalyticsSnapshot, ai_metrics: dict[str, Any]) -> None:
    global _last_connected, _last_ai_online, _last_low_battery_log_at

    if _last_connected is None or _last_connected != snapshot.connected:
        severity = "info" if snapshot.connected else "warning"
        message = "Raspberry Pi ROS2 telemetry connected" if snapshot.connected else "Raspberry Pi ROS2 telemetry disconnected"
        await log_event("robot_connection", severity, "website.analytics", message)
        _last_connected = snapshot.connected

    ai_online = bool(ai_metrics) and "error" not in ai_metrics
    if _last_ai_online is None or _last_ai_online != ai_online:
        severity = "info" if ai_online else "warning"
        message = "Context-aware AI metrics connected" if ai_online else "Context-aware AI metrics unavailable"
        await log_event("context_aware_connection", severity, "website.analytics", message)
        _last_ai_online = ai_online

    if snapshot.battery_percent is not None and snapshot.battery_percent <= 20:
        now = time.monotonic()
        if now - _last_low_battery_log_at > 300:
            await log_event(
                "battery_low",
                "warning",
                "website.analytics",
                f"Battery low: {snapshot.battery_percent:.1f}%",
                metadata_json={"voltage": snapshot.voltage},
            )
            _last_low_battery_log_at = now


async def _cleanup_old_snapshots() -> None:
    global _last_cleanup_at
    now = time.monotonic()
    if now - _last_cleanup_at < 3600:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.ANALYTICS_RETENTION_HOURS)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AnalyticsSnapshot).where(AnalyticsSnapshot.created_at < cutoff))
        await db.commit()
    _last_cleanup_at = now


def _snapshot_payload(row: AnalyticsSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "connected": row.connected,
        "navigation_mode": row.navigation_mode,
        "voltage": _round(row.voltage),
        "battery_percent": _round(row.battery_percent),
        "pos_x": _round(row.pos_x),
        "pos_y": _round(row.pos_y),
        "yaw": _round(row.yaw),
        "vx": _round(row.vx),
        "vy": _round(row.vy),
        "vtheta": _round(row.vtheta),
        "speed": _round(row.speed),
        "ai_mode": row.ai_mode,
        "ai_fps": _round(row.ai_fps),
        "ai_inference_ms": _round(row.ai_inference_ms),
        "ai_persons": row.ai_persons,
        "ai_obstacles": row.ai_obstacles,
        "created_at": row.created_at,
    }


def _event_payload(row: EventLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "severity": str(row.severity).upper(),
        "source": row.source,
        "message": row.message,
        "created_at": row.created_at,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 3) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    return round(numeric, digits)
