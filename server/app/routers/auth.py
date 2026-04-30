from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.auth import Token, RefreshRequest
from app.services.auth_service import verify_password, create_access_token, create_refresh_token, decode_token
from app.services.user_service import get_user_by_username, get_user_by_id

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await get_user_by_username(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role,
            "username": user.username,
            "face_auth_enabled": bool(user.face_auth_enabled),
            "face_id": user.face_id,
        }
    )
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    # Optionally store refresh token in db
    
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}

@router.post("/refresh", response_model=Token)
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(request.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
        
    user_id = payload.get("sub")
    user = await get_user_by_id(db, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
        
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role,
            "username": user.username,
            "face_auth_enabled": bool(user.face_auth_enabled),
            "face_id": user.face_id,
        }
    )
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return {"access_token": access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}

@router.post("/logout")
async def logout():
    # In a real implementation with redis/db, revoke the refresh token
    return {"status": "ok"}
