from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.middleware.auth import get_current_operator
from app.services import training_proxy

router = APIRouter(
    prefix="/api/training",
    tags=["training"],
    dependencies=[Depends(get_current_operator)],
)


class TrainingStartRequest(BaseModel):
    dataset: str
    output: str
    epochs: int
    batch_size: int
    lr: float
    lambda_dir: float
    val_split: float
    workers: int
    device: str
    temporal_window: int
    freeze_blocks: int
    save_every: int
    replay_buffer: int
    ewc_lambda: float
    confidence_threshold: float
    margin_threshold: float
    resume: str | None = None
    epochs_are_additional: bool = False
    allow_unreviewed_erratic: bool = False
    distill_from: str | None = None


@router.get("/defaults")
async def defaults() -> dict[str, Any]:
    result = await training_proxy.training_defaults()
    _raise_proxy_error(result)
    return result


@router.get("/status")
async def status() -> dict[str, Any]:
    result = await training_proxy.training_status()
    _raise_proxy_error(result)
    return result


@router.post("/start")
async def start(body: TrainingStartRequest) -> dict[str, Any]:
    result = await training_proxy.training_start(body.model_dump())
    _raise_proxy_error(result)
    return result


@router.post("/stop")
async def stop() -> dict[str, Any]:
    result = await training_proxy.training_stop()
    _raise_proxy_error(result)
    return result


def _raise_proxy_error(result: dict[str, Any]) -> None:
    error = result.get("error")
    if error:
        raise HTTPException(status_code=400, detail=error)
