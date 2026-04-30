from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    POSTGRES_DB: str | None = None
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: str | None = None
    DATABASE_URL: str
    
    JWT_SECRET: str
    JWT_ACCESS_EXPIRE_MIN: int = 30
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    
    DEFAULT_ADMIN_USER: str = "admin"
    DEFAULT_ADMIN_PASS: str = "admin123"
    
    # Backward-compatible single host (used if ZMQ_SCADA_HOSTS is empty)
    ZMQ_SCADA_HOST: str = "25.12.4.101"
    # Priority list, e.g. "25.12.4.101,100.x.y.z"
    ZMQ_SCADA_HOSTS: str = ""
    ZMQ_CMD_PORT: int = 5555
    ZMQ_TELEMETRY_PORT: int = 5556
    ZMQ_CAMERA_PORT: int = 5557
    
    JETSON_API_URL: str = "http://25.12.4.100:8080"
    ANALYTICS_COLLECT_INTERVAL_SEC: float = 5.0
    ANALYTICS_RETENTION_HOURS: int = 168
    WEBSITE_LOG_BUFFER_SIZE: int = 500
    FACE_MATCH_THRESHOLD: float = 0.78
    FACE_AUTH_SHARED_SECRET: str = ""
    FACE_DATA_DIR: str = "/app/data/faces"
    FACE_MIN_IMAGES: int = 8
    FACE_MAX_IMAGES: int = 20
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
