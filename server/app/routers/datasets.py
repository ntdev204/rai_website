"""Dataset API proxy for the Context-Aware Jetson server."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.middleware.auth import get_current_operator
from app.services import jetson_proxy

router = APIRouter(
    prefix="/api/datasets",
    tags=["datasets"],
    dependencies=[Depends(get_current_operator)],
)


class DatasetStartRequest(BaseModel):
    mode: str = "intent_cnn"


@router.get("/collection")
async def collection_status():
    return await jetson_proxy.dataset_status()


@router.post("/collection/start")
async def start_collection(body: DatasetStartRequest):
    result = await jetson_proxy.dataset_start(body.mode)
    _raise_proxy_error(result)
    return result


@router.post("/collection/stop")
async def stop_collection():
    result = await jetson_proxy.dataset_stop()
    _raise_proxy_error(result)
    return result


@router.delete("/collection")
async def discard_collection():
    result = await jetson_proxy.dataset_discard()
    _raise_proxy_error(result)
    return result


@router.post("/collection/save")
async def save_collection():
    result = await jetson_proxy.dataset_save()
    _raise_proxy_error(result)
    return result


@router.get("/collection/images")
async def collection_images():
    result = await jetson_proxy.dataset_images()
    _raise_proxy_error(result)
    return result


@router.delete("/collection/images/{index}")
async def delete_collection_image(index: int):
    result = await jetson_proxy.dataset_delete_image(index)
    _raise_proxy_error(result)
    return result


@router.post("/collection/autolabel")
async def autolabel_collection():
    result = await jetson_proxy.dataset_autolabel()
    _raise_proxy_error(result)
    return result


@router.get("/collection/preview/{index}")
async def preview_frame(index: int):
    try:
        content, media_type = await jetson_proxy.dataset_preview(index)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=content, media_type=media_type)


@router.get("/collection/download")
async def download_collection():
    try:
        stream, headers = await jetson_proxy.dataset_download()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StreamingResponse(
        stream,
        media_type=headers.get("content-type", "application/zip"),
        headers={
            "Content-Disposition": headers.get(
                "content-disposition",
                'attachment; filename="context_aware_dataset.zip"',
            )
        },
    )


def _raise_proxy_error(result: dict):
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
