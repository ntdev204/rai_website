from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.services import face_service

router = APIRouter(prefix="/api/faces", tags=["faces"])


class FaceImageRequest(BaseModel):
    image_base64: str


class FaceRegisterRequest(BaseModel):
    images_base64: list[str]


class FaceVerifyRequest(FaceImageRequest):
    track_id: int | None = None
    gesture: str | None = None


@router.get("/me")
async def get_my_face(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return face_service.face_status(current_user)


@router.post("/me/register")
async def register_my_face(
    body: FaceRegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        user = await face_service.register_face(db, current_user, body.images_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", **face_service.face_status(user)}


@router.delete("/me")
async def clear_my_face(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user = await face_service.clear_face(db, current_user)
    return {"status": "ok", **face_service.face_status(user)}


@router.post("/verify")
async def verify_face_crop(
    body: FaceVerifyRequest,
    db: AsyncSession = Depends(get_db),
    x_face_auth_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if settings.FACE_AUTH_SHARED_SECRET and x_face_auth_token != settings.FACE_AUTH_SHARED_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid face auth token")

    try:
        match = await face_service.match_face(db, body.image_base64)
    except ValueError:
        return {"matched": False, "track_id": body.track_id, "reason": "invalid_face_crop"}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if match is None:
        return {"matched": False, "track_id": body.track_id}

    return {
        "matched": True,
        "track_id": body.track_id,
        "score": round(match.score, 4),
        "user_id": match.user.id,
        "username": match.user.username,
        "face_id": match.user.face_id,
    }
