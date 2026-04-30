from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String
from sqlalchemy.sql import func

from app.core.database import Base


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    connected = Column(Boolean, nullable=False, default=False, index=True)
    navigation_mode = Column(String, nullable=True, index=True)
    voltage = Column(Float, nullable=True)
    battery_percent = Column(Float, nullable=True)
    pos_x = Column(Float, nullable=True)
    pos_y = Column(Float, nullable=True)
    yaw = Column(Float, nullable=True)
    vx = Column(Float, nullable=True)
    vy = Column(Float, nullable=True)
    vtheta = Column(Float, nullable=True)
    speed = Column(Float, nullable=True)
    ai_mode = Column(String, nullable=True, index=True)
    ai_fps = Column(Float, nullable=True)
    ai_inference_ms = Column(Float, nullable=True)
    ai_persons = Column(Integer, nullable=True)
    ai_obstacles = Column(Integer, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
