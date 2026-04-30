from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth import get_current_user
from app.services import log_service

router = APIRouter(prefix="/api/logs", tags=["logs"])


class ClientLogRequest(BaseModel):
    severity: str = Field(default="info", max_length=20)
    event_type: str = Field(default="client_runtime", max_length=100)
    message: str = Field(..., max_length=4000)
    metadata_json: dict[str, Any] | None = None


@router.get("/", dependencies=[Depends(get_current_user)])
async def list_logs(
    limit: int = 100,
    event_type: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    include_external: bool = True,
    query: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await log_service.list_aggregated_logs(
        db,
        limit=limit,
        event_type=event_type,
        severity=severity,
        source=source,
        include_external=include_external,
        query=query,
    )


@router.post("/client")
async def record_client_log(body: ClientLogRequest):
    await log_service.log_event(
        event_type=body.event_type,
        severity=body.severity,
        source="rai_website.client",
        message=body.message,
        metadata_json=body.metadata_json,
    )
    return {"status": "ok"}
