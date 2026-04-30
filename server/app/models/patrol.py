from sqlalchemy import Column, Integer, String, DateTime, JSON, Float, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.core.database import Base

class PatrolRoute(Base):
    __tablename__ = "patrol_routes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    waypoints_json = Column(JSON, nullable=False)
    home_json = Column(JSON, nullable=False)
    waypoint_tolerance = Column(Float, default=0.25)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class PatrolRun(Base):
    __tablename__ = "patrol_runs"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("patrol_routes.id"), nullable=False)
    schedule_id = Column(Integer, nullable=True)
    run_id_zmq = Column(String, nullable=True, index=True)
    status = Column(String, default="pending") # 'pending', 'running', 'completed', 'failed', 'aborted'
    total_loops = Column(Integer, default=1)
    current_loop = Column(Integer, default=0)
    started_by = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    result_message = Column(String, nullable=True)

class PatrolSchedule(Base):
    __tablename__ = "patrol_schedules"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("patrol_routes.id"), nullable=False)
    cron_expression = Column(String, nullable=False)
    is_enabled = Column(Boolean, default=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
