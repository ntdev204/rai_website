from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth import get_current_user
from app.models.patrol import PatrolRoute, PatrolRun, PatrolSchedule

router = APIRouter(prefix="/api/patrol", tags=["patrol"])


@router.get("/routes", dependencies=[Depends(get_current_user)])
async def list_routes(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PatrolRoute).order_by(desc(PatrolRoute.created_at)))).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "waypoints_json": row.waypoints_json,
            "home_json": row.home_json,
            "waypoint_tolerance": row.waypoint_tolerance,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get("/runs", dependencies=[Depends(get_current_user)])
async def list_runs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    limit = max(1, min(limit, 200))
    rows = (
        await db.execute(select(PatrolRun).order_by(desc(PatrolRun.started_at)).limit(limit))
    ).scalars().all()
    return [
        {
            "id": row.id,
            "route_id": row.route_id,
            "schedule_id": row.schedule_id,
            "run_id_zmq": row.run_id_zmq,
            "status": row.status,
            "total_loops": row.total_loops,
            "current_loop": row.current_loop,
            "started_by": row.started_by,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "result_message": row.result_message,
        }
        for row in rows
    ]


@router.get("/schedules", dependencies=[Depends(get_current_user)])
async def list_schedules(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(PatrolSchedule).order_by(desc(PatrolSchedule.created_at)))
    ).scalars().all()
    return [
        {
            "id": row.id,
            "route_id": row.route_id,
            "cron_expression": row.cron_expression,
            "is_enabled": row.is_enabled,
            "created_by": row.created_by,
            "created_at": row.created_at,
        }
        for row in rows
    ]
