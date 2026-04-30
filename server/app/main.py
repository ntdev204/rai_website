from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analytics, auth, configs, logs, maps, nodes, patrol, robot, users
from app.routers import ws_control, ws_telemetry, ws_video
from app.services.analytics_service import start_analytics_collector, stop_analytics_collector
from app.services.log_service import log_event
from app.services.runtime_log_buffer import install_runtime_log_handler
from app.services.zmq_bridge import start_zmq_bridge, stop_zmq_bridge
from app.services.jetson_proxy import start_jetson_proxy, stop_jetson_proxy


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    install_runtime_log_handler()
    await start_jetson_proxy()
    await start_zmq_bridge()
    await start_analytics_collector()
    await log_event("server_start", "info", "website.server", "Website backend started")
    yield
    # Shutdown
    await log_event("server_stop", "info", "website.server", "Website backend stopped")
    await stop_analytics_collector()
    await stop_zmq_bridge()
    await stop_jetson_proxy()


app = FastAPI(
    title="Robot Dashboard API",
    description="Backend for Robot Monitoring & Control",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(robot.router)
app.include_router(logs.router)
app.include_router(analytics.router)
app.include_router(nodes.router)
app.include_router(patrol.router)
app.include_router(maps.router)
app.include_router(configs.router)

# WebSocket routers
app.include_router(ws_control.router)
app.include_router(ws_telemetry.router)
app.include_router(ws_video.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "robot_dashboard_api"}
