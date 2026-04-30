from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="viewer", nullable=False) # 'admin', 'operator', 'viewer'
    is_active = Column(Boolean, default=True)
    face_auth_enabled = Column(Boolean, default=False)
    face_id = Column(String, unique=True, index=True, nullable=True)
    face_embedding_json = Column(JSON, nullable=True)
    face_embeddings_json = Column(JSON, nullable=True)
    face_image_paths_json = Column(JSON, nullable=True)
    face_registered_at = Column(DateTime(timezone=True), nullable=True)
    avatar_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    token_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
