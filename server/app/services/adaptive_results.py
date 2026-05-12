"""Adaptive context-aware result-plane subscriber.

The adaptive runtime publishes protobuf ``PerceptionResultEnvelope`` messages
over ZMQ PUB. The dashboard keeps only the latest decoded snapshot so REST and
WebSocket handlers can expose it without polling the adaptive control API.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

import zmq
import zmq.asyncio
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from app.core.config import settings

logger = logging.getLogger(__name__)

_ctx: zmq.asyncio.Context | None = None
_result_sock: zmq.asyncio.Socket | None = None
_result_task: asyncio.Task | None = None
_running = False
_latest_result: dict[str, Any] = {"connected": False, "entities": [], "persons": [], "obstacles": []}
_result_lock = asyncio.Lock()
_result_classes: dict[str, Any] | None = None


async def start_adaptive_result_subscriber() -> None:
    global _ctx, _result_sock, _result_task, _running

    if not settings.ADAPTIVE_RESULT_ENABLED:
        logger.info("Adaptive result subscriber disabled")
        return
    if _result_task and not _result_task.done():
        return

    host = _adaptive_result_host()
    _ctx = zmq.asyncio.Context()
    _result_sock = _ctx.socket(zmq.SUB)
    _result_sock.setsockopt(zmq.RCVHWM, 2)
    _result_sock.setsockopt(zmq.LINGER, 0)
    _result_sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
    _result_sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)
    _result_sock.setsockopt_string(zmq.SUBSCRIBE, "")
    _result_sock.connect(f"tcp://{host}:{settings.ADAPTIVE_RESULT_PORT}")

    _running = True
    _result_task = asyncio.create_task(_recv_loop(), name="adaptive_result_subscriber")
    logger.info("Adaptive result subscriber connected: tcp://%s:%s", host, settings.ADAPTIVE_RESULT_PORT)


async def stop_adaptive_result_subscriber() -> None:
    global _running

    _running = False
    if _result_task:
        _result_task.cancel()
        await asyncio.gather(_result_task, return_exceptions=True)
    if _result_sock:
        _result_sock.close()
    if _ctx:
        _ctx.term()
    logger.info("Adaptive result subscriber stopped")


async def get_latest_result() -> dict[str, Any]:
    async with _result_lock:
        result = dict(_latest_result)
        result["entities"] = list(_latest_result.get("entities", []))
        result["persons"] = list(_latest_result.get("persons", []))
        result["obstacles"] = list(_latest_result.get("obstacles", []))
        return result


async def _recv_loop() -> None:
    global _latest_result
    last_received = time.monotonic()

    while _running:
        try:
            parts = await asyncio.wait_for(_result_sock.recv_multipart(), timeout=1.0)
            raw = parts[-1] if parts else b""
            if not raw:
                continue
            decoded = _decode_result(raw)
            async with _result_lock:
                _latest_result = decoded
            last_received = time.monotonic()
        except asyncio.TimeoutError:
            if time.monotonic() - last_received > 3.0:
                async with _result_lock:
                    _latest_result = {
                        "connected": False,
                        "entities": [],
                        "persons": [],
                        "obstacles": [],
                        "message": "No adaptive result frames received",
                    }
            continue
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Adaptive result decode failed: %s", exc)
            await asyncio.sleep(0.2)


def _decode_result(raw: bytes) -> dict[str, Any]:
    classes = _result_message_classes()
    envelope = classes["PerceptionResultEnvelope"]()
    envelope.ParseFromString(raw)

    entities = []
    for entity in envelope.entities:
        distance = (
            float(entity.nearest_obstacle_distance_m)
            if entity.HasField("nearest_obstacle_distance_m")
            else None
        )
        position = [float(value) for value in entity.position_xyz_m]
        if distance is None and len(position) >= 2:
            distance = (position[0] ** 2 + position[1] ** 2) ** 0.5
        item = {
            "track_id": int(entity.track_id),
            "class_name": "tracked_entity",
            "confidence": float(entity.confidence),
            "bbox_xywh": [float(value) for value in entity.bbox_xywh],
            "position_xyz_m": position,
            "velocity_xyz_mps": [float(value) for value in entity.velocity_xyz_mps],
            "heading_rad": float(entity.heading_rad),
            "distance": distance,
            "distance_source": "adaptive_fusion" if distance is not None else None,
        }
        entities.append(item)

    metrics = {
        "fps": float(envelope.metrics.fps),
        "inference_ms": float(envelope.metrics.total_latency_ms),
        "total_latency_ms": float(envelope.metrics.total_latency_ms),
        "camera_latency_ms": float(envelope.metrics.camera_latency_ms),
        "detector_latency_ms": float(envelope.metrics.detector_latency_ms),
        "fusion_latency_ms": float(envelope.metrics.fusion_latency_ms),
    }
    timestamp_us = int(envelope.timestamp_us)
    return {
        "connected": True,
        "source_id": str(envelope.source_id),
        "sequence": int(envelope.sequence),
        "frame_id": int(envelope.sequence),
        "timestamp_us": timestamp_us,
        "received_at": time.time(),
        "entities": entities,
        "persons": entities,
        "obstacles": [],
        "metrics": metrics,
        "fps": metrics["fps"],
        "inference_ms": metrics["inference_ms"],
        "persons_count": len(entities),
        "obstacles_count": 0,
    }


def _adaptive_result_host() -> str:
    explicit = settings.ADAPTIVE_RESULT_HOST.strip()
    if explicit:
        return explicit
    parsed = urlparse(settings.adaptive_api_url)
    return parsed.hostname or "127.0.0.1"


def _result_message_classes():
    global _result_classes
    if _result_classes is not None:
        return _result_classes

    file_desc = descriptor_pb2.FileDescriptorProto()
    file_desc.name = "adaptive/context/v1/perception.proto"
    file_desc.package = "adaptive.context.v1"
    _add_tracked_entity(file_desc)
    _add_runtime_metrics(file_desc)
    _add_result_envelope(file_desc)

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_desc)
    _result_classes = {
        name: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"adaptive.context.v1.{name}"))
        for name in ("PerceptionResultEnvelope", "TrackedEntity", "RuntimeMetrics")
    }
    return _result_classes


def _add_tracked_entity(file_desc: descriptor_pb2.FileDescriptorProto) -> None:
    message_desc = file_desc.message_type.add()
    message_desc.name = "TrackedEntity"
    _add_field(message_desc, "track_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
    _add_field(message_desc, "bbox_xywh", 2, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT, repeated=True)
    _add_field(message_desc, "position_xyz_m", 3, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT, repeated=True)
    _add_field(message_desc, "velocity_xyz_mps", 4, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT, repeated=True)
    _add_field(message_desc, "heading_rad", 5, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT)
    _add_field(message_desc, "confidence", 6, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT)
    _add_field(
        message_desc,
        "nearest_obstacle_distance_m",
        7,
        descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT,
        proto3_optional=True,
    )


def _add_runtime_metrics(file_desc: descriptor_pb2.FileDescriptorProto) -> None:
    message_desc = file_desc.message_type.add()
    message_desc.name = "RuntimeMetrics"
    _add_field(message_desc, "total_latency_ms", 1, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT)
    _add_field(message_desc, "camera_latency_ms", 2, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT)
    _add_field(message_desc, "detector_latency_ms", 3, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT)
    _add_field(message_desc, "fusion_latency_ms", 4, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT)
    _add_field(message_desc, "fps", 5, descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT)


def _add_result_envelope(file_desc: descriptor_pb2.FileDescriptorProto) -> None:
    message_desc = file_desc.message_type.add()
    message_desc.name = "PerceptionResultEnvelope"
    _add_field(message_desc, "source_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    _add_field(message_desc, "sequence", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    _add_field(message_desc, "timestamp_us", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    _add_field(
        message_desc,
        "entities",
        10,
        descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
        repeated=True,
        type_name=".adaptive.context.v1.TrackedEntity",
    )
    _add_field(
        message_desc,
        "metrics",
        11,
        descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
        type_name=".adaptive.context.v1.RuntimeMetrics",
    )


def _add_field(
    message_desc: descriptor_pb2.DescriptorProto,
    name: str,
    number: int,
    field_type: int,
    *,
    repeated: bool = False,
    type_name: str | None = None,
    proto3_optional: bool = False,
) -> None:
    field_desc = message_desc.field.add()
    field_desc.name = name
    field_desc.number = number
    field_desc.label = (
        descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
        if repeated
        else descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    )
    field_desc.type = field_type
    if type_name is not None:
        field_desc.type_name = type_name
    if proto3_optional:
        oneof_desc = message_desc.oneof_decl.add()
        oneof_desc.name = f"_{name}"
        field_desc.oneof_index = len(message_desc.oneof_decl) - 1
        field_desc.proto3_optional = True
