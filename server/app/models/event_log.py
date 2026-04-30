from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, index=True, nullable=False)
    severity = Column(String, index=True, nullable=False) # 'info', 'warning', 'error', 'critical'
    source = Column(String, nullable=False)
    message = Column(String, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    user_id = Column(Integer, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
