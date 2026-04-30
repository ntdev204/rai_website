from sqlalchemy import Column, Integer, String, DateTime, Float, LargeBinary, Boolean
from sqlalchemy.sql import func
from app.core.database import Base

class Map(Base):
    __tablename__ = "maps"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    description = Column(String, nullable=True)
    resolution = Column(Float, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    origin_x = Column(Float, nullable=False)
    origin_y = Column(Float, nullable=False)
    
    png_data = Column(LargeBinary, nullable=True)
    pgm_data = Column(LargeBinary, nullable=True)
    yaml_config = Column(String, nullable=True)
    source = Column(String, nullable=True)
    is_active = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
