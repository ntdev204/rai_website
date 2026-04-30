from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, status
logger = logging.getLogger(__name__)

from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.auth_service import decode_token
from app.services.user_service import get_user_by_id
from app.schemas.user import UserResponse

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> UserResponse:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = await get_user_by_id(db, int(user_id))
    if user is None or not user.is_active:
        raise credentials_exception

    return user


async def get_current_admin(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")
    return current_user


async def get_current_operator(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    if current_user.role not in ["admin", "operator"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")
    return current_user


# Aliases used by REST routers
require_admin = Depends(get_current_admin)
require_operator = Depends(get_current_operator)


async def verify_ws_token(token: str) -> dict[str, Any] | None:
    """Verify a JWT token passed as query param for WebSocket connections."""
    if not token:
        logger.warning("WS auth: no token provided")
        return None
    payload = decode_token(token)
    if not payload:
        logger.warning("WS auth: token decode failed (wrong secret or malformed)")
        return None
    return payload
