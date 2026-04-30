from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    role: str = "viewer"
    face_auth_enabled: bool = False
    is_active: bool = True

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    face_auth_enabled: Optional[bool] = None

class UserResponse(UserBase):
    id: int
    face_id: Optional[str] = None
    face_image_paths_json: Optional[list[str]] = None
    avatar_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    face_registered_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
