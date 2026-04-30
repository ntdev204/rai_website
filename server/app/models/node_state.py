from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class NodeState(Base):
    __tablename__ = "node_states"

    id = Column(Integer, primary_key=True, index=True)
    node_name = Column(String, unique=True, index=True, nullable=False)
    package_name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="unknown")
    last_changed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    changed_by_user_id = Column(Integer, nullable=True)
