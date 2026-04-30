"""ZMQ bridge between the dashboard backend and the Raspberry Pi SCADA node.

Protocol shared with ``wheeltec_scada_bridge``:
    Commands:  REQ/REP JSON on port 5555
    Telemetry: PUB/SUB JSON on port 5556
    Camera/map: PUB raw JPEG or ``MAP:`` PNG frames on port 5557
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import zmq
import zmq.asyncio

from app.core.config import settings

logger = logging.getLogger(__name__)

_latest_telemetry: dict[str, Any] = {"connected": False}
_latest_map_png: bytes | None = None
_latest_map_received_at: float | None = None
_telemetry_lock = asyncio.Lock()
_map_lock = asyncio.Lock()
_cmd_lock = asyncio.Lock()
_bridge_running = False

_ctx: zmq.asyncio.Context | None = None
_cmd_sock: zmq.asyncio.Socket | None = None
_tel_sock: zmq.asyncio.Socket | None = None
_map_sock: zmq.asyncio.Socket | None = None
_telemetry_task: asyncio.Task | None = None
_map_task: asyncio.Task | None = None
_active_scada_host: str | None = None
DEFAULT_COMMAND_TIMEOUT_MS = 1000


async def start_zmq_bridge() -> None:
    global _ctx, _cmd_sock, _tel_sock, _map_sock, _bridge_running
    global _telemetry_task, _map_task, _active_scada_host

    _ctx = zmq.asyncio.Context()
    _active_scada_host = await _select_active_host()
    _cmd_sock = _make_req_socket()

    _tel_sock = _ctx.socket(zmq.SUB)
    _tel_sock.setsockopt(zmq.RCVHWM, 2)
    _tel_sock.setsockopt(zmq.LINGER, 0)
    _tel_sock.setsockopt_string(zmq.SUBSCRIBE, "")
    _tel_sock.connect(f"tcp://{_active_scada_host}:{settings.ZMQ_TELEMETRY_PORT}")

    _map_sock = _ctx.socket(zmq.SUB)
    _map_sock.setsockopt(zmq.RCVHWM, 2)
    _map_sock.setsockopt(zmq.LINGER, 0)
    _map_sock.setsockopt(zmq.SUBSCRIBE, b"MAP:")
    _map_sock.connect(f"tcp://{_active_scada_host}:{settings.ZMQ_CAMERA_PORT}")

    _bridge_running = True
    _telemetry_task = asyncio.create_task(_telemetry_recv_loop())
    _map_task = asyncio.create_task(_map_recv_loop())
    logger.info(
        "ZMQ bridge started: Pi=%s cmd=%d telemetry=%d camera=%d",
        _active_scada_host,
        settings.ZMQ_CMD_PORT,
        settings.ZMQ_TELEMETRY_PORT,
        settings.ZMQ_CAMERA_PORT,
    )


async def stop_zmq_bridge() -> None:
    global _bridge_running
    _bridge_running = False
    tasks = [task for task in (_telemetry_task, _map_task) if task]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    if _cmd_sock:
        _cmd_sock.close()
    if _tel_sock:
        _tel_sock.close()
    if _map_sock:
        _map_sock.close()
    if _ctx:
        _ctx.term()
    logger.info("ZMQ bridge stopped")


async def send_scada_command(
    action: str,
    payload: dict[str, Any] | None = None,
    timeout_ms: int = DEFAULT_COMMAND_TIMEOUT_MS,
) -> dict[str, Any]:
    """Send a JSON command to the ROS2 SCADA bridge and return its reply."""
    global _cmd_sock

    if _ctx is None:
        return {"status": "error", "message": "ZMQ bridge is not started"}

    request = {"action": action, "payload": payload or {}}
    async with _cmd_lock:
        if _cmd_sock is None:
            _cmd_sock = _make_req_socket(timeout_ms=timeout_ms)
        try:
            _cmd_sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
            _cmd_sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
            await _cmd_sock.send_json(request)
            reply = await _cmd_sock.recv_json()
            if isinstance(reply, dict):
                return reply
            return {"status": "error", "message": "Invalid SCADA reply"}
        except zmq.Again:
            logger.warning("SCADA command timeout: %s", action)
            _reset_cmd_socket()
            return {"status": "timeout", "message": "SCADA bridge did not reply"}
        except Exception as exc:
            logger.error("SCADA command failed: %s", exc)
            _reset_cmd_socket()
            return {"status": "error", "message": str(exc)}


async def send_teleop_cmd(linear_x: float, linear_y: float, angular_z: float) -> dict[str, Any]:
    return await send_scada_command(
        "cmd_vel",
        {
            "linear_x": float(linear_x),
            "linear_y": float(linear_y),
            "angular_z": float(angular_z),
        },
    )


async def _telemetry_recv_loop() -> None:
    global _latest_telemetry
    last_received = time.monotonic()

    while _bridge_running:
        try:
            raw_msg = await asyncio.wait_for(_tel_sock.recv(), timeout=0.5)
            raw = _decode_telemetry_message(raw_msg)
            if raw is None:
                continue
            telemetry = _normalize_telemetry(raw)
            async with _telemetry_lock:
                _latest_telemetry = telemetry
            last_received = time.monotonic()
        except asyncio.TimeoutError:
            if time.monotonic() - last_received > 1.5:
                async with _telemetry_lock:
                    _latest_telemetry = {"connected": False}
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Telemetry receive error: %s", exc)
            await asyncio.sleep(0.2)


async def _map_recv_loop() -> None:
    global _latest_map_png, _latest_map_received_at

    while _bridge_running:
        try:
            raw_msg = await asyncio.wait_for(_map_sock.recv(), timeout=1.0)
            if not raw_msg.startswith(b"MAP:"):
                continue

            png = raw_msg[4:]
            if not png:
                continue

            async with _map_lock:
                _latest_map_png = bytes(png)
                _latest_map_received_at = time.time()
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Map frame receive error: %s", exc)
            await asyncio.sleep(0.2)


def _decode_telemetry_message(raw_msg: bytes) -> dict[str, Any] | None:
    if not raw_msg:
        return None

    try:
        text = raw_msg.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if not text:
        return None

    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Dropped non-JSON telemetry frame")
        return None

    if isinstance(decoded, dict):
        return decoded
    return None


def _make_req_socket(timeout_ms: int = DEFAULT_COMMAND_TIMEOUT_MS) -> zmq.asyncio.Socket:
    sock = _ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.SNDHWM, 2)
    sock.setsockopt(zmq.RCVHWM, 2)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    host = _active_scada_host or settings.ZMQ_SCADA_HOST
    sock.connect(f"tcp://{host}:{settings.ZMQ_CMD_PORT}")
    return sock


def _reset_cmd_socket() -> None:
    global _cmd_sock
    if _cmd_sock:
        _cmd_sock.close()
    _cmd_sock = _make_req_socket() if _ctx else None


def _host_candidates() -> list[str]:
    raw = settings.ZMQ_SCADA_HOSTS.strip()
    if raw:
        hosts = [h.strip() for h in raw.split(",") if h.strip()]
        if hosts:
            return hosts
    return [settings.ZMQ_SCADA_HOST]


async def _is_host_reachable(host: str, port: int, timeout_s: float = 0.8) -> bool:
    try:
        fut = asyncio.open_connection(host=host, port=port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout_s)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _select_active_host() -> str:
    for host in _host_candidates():
        ok = await _is_host_reachable(host, settings.ZMQ_TELEMETRY_PORT)
        if ok:
            logger.info("ZMQ host selected: %s", host)
            return host
    fallback = _host_candidates()[0]
    logger.warning("No ZMQ host reachable at startup, fallback to %s", fallback)
    return fallback


def _normalize_telemetry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"connected": False}

    odom = raw.get("odom") if isinstance(raw.get("odom"), dict) else {}
    map_pose = raw.get("map_pose") if isinstance(raw.get("map_pose"), dict) else {}
    voltage = _float_or_none(raw.get("voltage"))
    battery = _battery_percent(voltage)

    return {
        "connected": True,
        "vx": _round(odom.get("v_x")),
        "vy": _round(odom.get("v_y")),
        "vtheta": _round(odom.get("v_z")),
        "pos_x": _round(map_pose.get("x", odom.get("x"))),
        "pos_y": _round(map_pose.get("y", odom.get("y"))),
        "yaw": _round(map_pose.get("yaw", odom.get("yaw"))),
        "battery_percent": battery,
        "voltage": _round(voltage),
        "charging": bool(raw.get("charging", False)),
        "odom": odom,
        "map_pose": map_pose,
        "imu": raw.get("imu") if isinstance(raw.get("imu"), dict) else {},
        "plan": raw.get("plan") if isinstance(raw.get("plan"), list) else [],
        "local_plan": raw.get("local_plan") if isinstance(raw.get("local_plan"), list) else [],
        "patrol": raw.get("patrol") if isinstance(raw.get("patrol"), dict) else {},
        "map_info": raw.get("map_info") if isinstance(raw.get("map_info"), dict) else None,
        "navigation_mode": raw.get("navigation_mode") or raw.get("mode"),
        "timestamp": time.time(),
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 3) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    return round(numeric, digits)


def _battery_percent(voltage: float | None) -> float | None:
    if voltage is None:
        return None
    if voltage > 25.2:
        return 100.0
    if voltage < 21.0:
        return 0.0
    return round((voltage - 21.0) / 4.2 * 100.0, 1)


async def get_latest_telemetry() -> dict[str, Any]:
    async with _telemetry_lock:
        return dict(_latest_telemetry)


async def get_latest_map_png() -> tuple[bytes | None, float | None]:
    async with _map_lock:
        return _latest_map_png, _latest_map_received_at
