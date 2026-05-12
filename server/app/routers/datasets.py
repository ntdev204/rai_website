"""Dataset APIs.

Adaptive-context-aware removed the old on-runtime collection HTTP endpoints.
Server endpoints own the upload -> sequence ingest -> auto-label -> train-ready
dataset flow.
"""

from __future__ import annotations

import re
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from app.middleware.auth import get_current_operator
from app.services import adaptive_proxy, dataset_store

router = APIRouter(
    prefix="/api/datasets",
    tags=["datasets"],
    dependencies=[Depends(get_current_operator)],
)


class DatasetStartRequest(BaseModel):
    mode: str = "intent_cnn"


class SequenceLabelRequest(BaseModel):
    primary_label: str
    secondary_label: str | None = None


@router.get("/collection")
async def collection_status():
    return await adaptive_proxy.dataset_status()


@router.post("/collection/start")
async def start_collection(body: DatasetStartRequest):
    result = await adaptive_proxy.dataset_start(body.mode)
    _raise_proxy_error(result)
    return result


@router.post("/collection/stop")
async def stop_collection():
    result = await adaptive_proxy.dataset_stop()
    _raise_proxy_error(result)
    return result


@router.delete("/collection")
async def discard_collection():
    result = await adaptive_proxy.dataset_discard()
    _raise_proxy_error(result)
    return result


@router.post("/collection/save")
async def save_collection():
    result = await adaptive_proxy.dataset_save()
    _raise_proxy_error(result)
    return result


@router.get("/collection/images")
async def collection_images():
    result = await adaptive_proxy.dataset_images()
    _raise_proxy_error(result)
    return result


@router.delete("/collection/images/{index}")
async def delete_collection_image(index: int):
    result = await adaptive_proxy.dataset_delete_image(index)
    _raise_proxy_error(result)
    return result


@router.post("/collection/autolabel")
async def autolabel_collection():
    raise HTTPException(
        status_code=410,
        detail="Runtime auto-label is disabled. Download the raw collection, upload it here, then run server auto-label.",
    )


@router.get("/collection/preview/{index}")
async def preview_frame(index: int):
    try:
        content, media_type = await adaptive_proxy.dataset_preview(index)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=content, media_type=media_type)


@router.get("/collection/download")
async def download_collection():
    try:
        stream, headers = await adaptive_proxy.dataset_download()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StreamingResponse(
        stream,
        media_type=headers.get("content-type", "application/zip"),
        headers={
            "Content-Disposition": headers.get(
                "content-disposition",
                'attachment; filename="adaptive_context_aware_dataset.zip"',
            )
        },
    )


async def _close_stream(stream) -> None:
    aclose = getattr(stream, "aclose", None)
    if callable(aclose):
        await aclose()
        return
    async for _chunk in stream:
        pass


@router.post("/collection/import-latest")
async def import_latest_collection():
    try:
        stream, headers = await adaptive_proxy.dataset_download()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    filename = _filename_from_disposition(headers.get("content-disposition", ""))
    try:
        with tempfile.SpooledTemporaryFile(max_size=128 * 1024 * 1024, mode="w+b") as tmp:
            async for chunk in stream:
                tmp.write(chunk)
            tmp.seek(0)
            return dataset_store.import_archive(tmp, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await _close_stream(stream)


@router.get("")
async def server_dataset_status():
    return dataset_store.status()


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip raw sequence dataset")
    try:
        return dataset_store.import_archive(file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sequences")
async def server_sequences():
    return dataset_store.list_sequences()


@router.get("/sequences/{sequence_id}/preview/{frame_index}")
async def server_sequence_preview(sequence_id: str, frame_index: int):
    try:
        content, media_type = dataset_store.preview_frame(sequence_id, frame_index)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=content, media_type=media_type)


@router.post("/sequences/{sequence_id}/label")
async def server_sequence_label(sequence_id: str, body: SequenceLabelRequest):
    try:
        return dataset_store.update_sequence_label(
            sequence_id,
            body.primary_label,
            body.secondary_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/autolabel")
async def server_autolabel():
    try:
        return dataset_store.auto_label_active()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/download")
async def server_download(kind: str = "labeled"):
    if kind not in {"raw", "labeled"}:
        raise HTTPException(status_code=400, detail="kind must be raw or labeled")
    try:
        path, filename = dataset_store.build_archive(kind)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/zip", filename=filename)


def _raise_proxy_error(result: dict):
    error = result.get("error")
    if error:
        raise HTTPException(status_code=400, detail=error)


def _filename_from_disposition(disposition: str) -> str:
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition or "")
    return match.group(1) if match else "adaptive_context_aware_robot_collection.zip"
