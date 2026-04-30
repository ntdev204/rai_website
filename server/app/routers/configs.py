from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth import get_current_user
from app.models.robot_config import RobotConfig

router = APIRouter(prefix="/api/configs", tags=["configs"])


@router.get("/", dependencies=[Depends(get_current_user)])
async def list_configs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(RobotConfig).order_by(RobotConfig.config_key))).scalars().all()
    return [
        {
            "id": row.id,
            "config_key": row.config_key,
            "config_value": row.config_value,
            "category": row.category,
            "updated_at": row.updated_at,
            "updated_by": row.updated_by,
        }
        for row in rows
    ]
