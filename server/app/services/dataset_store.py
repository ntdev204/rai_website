from __future__ import annotations

import base64
import json
import math
import re
import shutil
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import httpx
import numpy as np

from app.core.config import settings

LABELS = ("STATIONARY", "APPROACHING", "DEPARTING", "CROSSING", "ERRATIC", "UNCERTAIN")
TRAINABLE_LABELS = ("STATIONARY", "APPROACHING", "DEPARTING", "CROSSING", "ERRATIC")
LABEL_DIRS = {label: label.lower() for label in LABELS}

MIN_SEQUENCE_FRAMES = 15
MAX_SEQUENCE_FRAMES = 30
MIN_DEPTH_VALID_RATIO = 0.10


@dataclass
class CandidateSequence:
    session_id: str
    track_id: str
    rows: list[dict[str, Any]]
    source_paths: list[Path]


def status() -> dict[str, Any]:
    state = _read_state()
    dataset_id = state.get("active_dataset_id")
    if not dataset_id:
        return {"status": "empty"}

    raw_dir = _raw_dir(dataset_id)
    manifest = _read_json(raw_dir / "manifest.json")
    if not manifest:
        return {"status": "empty"}

    labeled_dir = _labeled_dir(dataset_id)
    label_manifest = _read_json(labeled_dir / "sequence_manifest.json")
    stage = label_manifest.get("dataset_stage") or manifest.get("dataset_stage") or "raw_sequences"
    payload = {
        "status": "auto_labeled" if label_manifest else "raw_ready",
        "dataset_stage": stage,
        "dataset_id": dataset_id,
        "session_id": manifest.get("session_id"),
        "raw_dir": str(raw_dir),
        "labeled_dir": str(labeled_dir) if labeled_dir.exists() else None,
        "train_dataset_dir": str(labeled_dir / "intent_dataset") if label_manifest else None,
        "sequence_count": int(manifest.get("sequence_count") or 0),
        "frame_count": int(manifest.get("frame_count") or 0),
        "rejected_count": int(manifest.get("rejected_count") or 0),
        "class_counts": label_manifest.get("class_counts", {}),
        "review_pending": label_manifest.get("review_pending", {}),
        "ready_for_training": bool(label_manifest.get("ready_for_training")) if label_manifest else False,
        "created_at": manifest.get("created_at"),
        "updated_at": label_manifest.get("generated_at") or manifest.get("created_at"),
    }
    return payload


def active_labeled_dataset_path() -> str | None:
    state = _read_state()
    dataset_id = state.get("active_dataset_id")
    if not dataset_id:
        return None
    train_dir = _labeled_dir(dataset_id) / "intent_dataset"
    if train_dir.exists():
        return str(train_dir)
    return None


def import_archive(fileobj: BinaryIO, filename: str | None) -> dict[str, Any]:
    _ensure_dirs()
    dataset_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    upload_name = _safe_name(filename or "dataset.zip")
    upload_path = _uploads_dir() / f"{dataset_id}_{upload_name}"
    tmp_dir = _tmp_dir() / dataset_id
    raw_dir = _raw_dir(dataset_id)

    with upload_path.open("wb") as handle:
        shutil.copyfileobj(fileobj, handle)

    tmp_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        _safe_extract_zip(upload_path, tmp_dir)
        sequences, rejected = _canonicalize_extracted(tmp_dir, raw_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    frame_count = sum(seq["frame_count"] for seq in sequences)
    manifest = {
        "dataset_id": dataset_id,
        "session_id": dataset_id,
        "source_filename": filename,
        "dataset_stage": "raw_sequences",
        "schema": "track_sequence_v1",
        "created_at": int(time.time()),
        "sequence_count": len(sequences),
        "frame_count": frame_count,
        "rejected_count": len(rejected),
        "rejected": rejected[:500],
    }
    _write_json(raw_dir / "manifest.json", manifest)
    _write_state({"active_dataset_id": dataset_id})
    return {**status(), "imported": len(sequences), "rejected": len(rejected)}


def list_sequences() -> dict[str, Any]:
    current = status()
    dataset_id = current.get("dataset_id")
    if not dataset_id:
        return {"status": "empty", "count": 0, "sequences": []}

    raw_dir = _raw_dir(str(dataset_id))
    sequences = []
    for seq_dir in _iter_sequence_dirs(raw_dir):
        meta = _read_json(seq_dir / "meta.json")
        label = _read_json(seq_dir / "label.json")
        frame_count = int(meta.get("frame_count") or len(_frame_paths(seq_dir)))
        key = _sequence_key(seq_dir)
        sequences.append(
            {
                "sequence_id": key,
                "session_id": meta.get("session_id") or seq_dir.parent.name,
                "track_id": meta.get("track_id") or seq_dir.name,
                "frame_count": frame_count,
                "depth_valid_ratio": meta.get("depth_valid_ratio", 0),
                "preview_index": 0,
                "label": label or None,
                "metadata": _sequence_summary(meta),
            }
        )
    return {**current, "count": len(sequences), "sequences": sequences}


def preview_frame(sequence_id: str, frame_index: int) -> tuple[bytes, str]:
    current = status()
    dataset_id = current.get("dataset_id")
    if not dataset_id:
        raise FileNotFoundError("No uploaded dataset")
    seq_dir = _sequence_dir_from_key(_raw_dir(str(dataset_id)), sequence_id)
    frames = _frame_paths(seq_dir)
    if not frames:
        raise FileNotFoundError("Sequence has no frames")
    index = max(0, min(frame_index, len(frames) - 1))
    frame = frames[index]
    media_type = "image/png" if frame.suffix.lower() == ".png" else "image/jpeg"
    return frame.read_bytes(), media_type


def build_archive(kind: str = "labeled") -> tuple[Path, str]:
    current = status()
    dataset_id = current.get("dataset_id")
    if not dataset_id:
        raise FileNotFoundError("No uploaded dataset")

    source = _labeled_dir(str(dataset_id)) if kind == "labeled" else _raw_dir(str(dataset_id))
    if kind == "labeled" and not source.exists():
        source = _raw_dir(str(dataset_id))
        kind = "raw"
    if not source.exists():
        raise FileNotFoundError("Dataset directory not found")

    exports = _exports_dir()
    exports.mkdir(parents=True, exist_ok=True)
    zip_path = exports / f"{dataset_id}_{kind}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, Path(dataset_id) / path.relative_to(source))
    return zip_path, f"context_aware_{dataset_id}_{kind}.zip"


def auto_label_active() -> dict[str, Any]:
    current = status()
    dataset_id = current.get("dataset_id")
    if not dataset_id:
        raise ValueError("Upload a raw sequence dataset before auto-labeling")

    raw_dir = _raw_dir(str(dataset_id))
    seq_dirs = list(_iter_sequence_dirs(raw_dir))
    if not seq_dirs:
        raise ValueError("Uploaded dataset contains no valid sequences")

    labeled_dir = _labeled_dir(str(dataset_id))
    if labeled_dir.exists():
        shutil.rmtree(labeled_dir)
    sequence_out = labeled_dir / "sequences"
    train_out = labeled_dir / "intent_dataset"
    sequence_out.mkdir(parents=True, exist_ok=True)
    train_out.mkdir(parents=True, exist_ok=True)
    for label in LABELS:
        (train_out / LABEL_DIRS[label]).mkdir(parents=True, exist_ok=True)

    sequence_rows: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    review_pending: Counter[str] = Counter()
    train_metadata: list[dict[str, Any]] = []

    for seq_dir in seq_dirs:
        meta = _read_json(seq_dir / "meta.json")
        heuristic = _heuristic_label(meta)
        vlm = _maybe_vlm_label(seq_dir, meta, heuristic)
        label = _reconcile_label(meta, heuristic, vlm)
        _write_json(seq_dir / "label.json", label)

        dest_seq_dir = sequence_out / seq_dir.parent.name / seq_dir.name
        dest_seq_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(seq_dir, dest_seq_dir)

        class_counts[label["primary_label"]] += 1
        if label["review_status"] == "needs_review":
            review_pending[label["primary_label"]] += 1

        frame_rows = _export_training_frames(seq_dir, train_out, label)
        train_metadata.extend(frame_rows)
        sequence_rows.append(
            {
                "sequence_id": _sequence_key(seq_dir),
                "path": str(dest_seq_dir.relative_to(labeled_dir)),
                "raw_path": str(seq_dir),
                "frame_count": int(meta.get("frame_count") or 0),
                "label": label,
                "depth_valid_ratio": meta.get("depth_valid_ratio", 0),
            }
        )

    _write_jsonl(train_out / "metadata.jsonl", train_metadata)
    train_manifest = _build_train_manifest(train_out, sequence_rows, class_counts, review_pending)
    _write_json(train_out / "manifest.json", train_manifest)

    sequence_manifest = {
        "dataset_id": dataset_id,
        "dataset_stage": "auto_labeled",
        "schema": "track_sequence_labeled_v1",
        "generated_at": int(time.time()),
        "raw_dataset_dir": str(raw_dir),
        "train_dataset_dir": str(train_out),
        "sequence_count": len(sequence_rows),
        "class_counts": dict(class_counts),
        "review_pending": dict(review_pending),
        "ready_for_training": train_manifest["ready_for_phase2_training"],
        "sequences": sequence_rows,
    }
    _write_json(labeled_dir / "sequence_manifest.json", sequence_manifest)
    _write_state({"active_dataset_id": str(dataset_id)})
    return {
        "status": "ok",
        "dataset_id": dataset_id,
        "labeled_dir": str(labeled_dir),
        "train_dataset_dir": str(train_out),
        "sequence_count": len(sequence_rows),
        "class_counts": dict(class_counts),
        "review_pending": dict(review_pending),
        "ready_for_training": train_manifest["ready_for_phase2_training"],
        "message": "Sequence-level auto-label completed",
    }


def _canonicalize_extracted(extracted: Path, raw_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rejected: list[dict[str, Any]] = []
    candidates = _existing_sequence_candidates(extracted)
    if not candidates:
        candidates = _legacy_metadata_candidates(extracted)

    by_session: dict[str, str] = {}
    per_session_count: Counter[str] = Counter()
    imported: list[dict[str, Any]] = []

    for candidate in candidates:
        session_name = by_session.setdefault(
            str(candidate.session_id),
            f"session_{len(by_session) + 1:03d}",
        )
        segments = _split_track_rows(candidate.rows, candidate.source_paths)
        for rows, paths in segments:
            per_session_count[session_name] += 1
            track_name = f"track_{per_session_count[session_name]:04d}"
            result = _write_sequence(raw_dir, session_name, track_name, rows, paths, candidate)
            if result.get("rejected"):
                rejected.append(result)
            else:
                imported.append(result)

    return imported, rejected


def _existing_sequence_candidates(extracted: Path) -> list[CandidateSequence]:
    candidates: list[CandidateSequence] = []
    for frames_dir in sorted(extracted.rglob("frames")):
        if not frames_dir.is_dir():
            continue
        seq_dir = frames_dir.parent
        meta_path = seq_dir / "meta.json"
        if not meta_path.exists():
            continue
        frames = _frame_paths(seq_dir)
        if not frames:
            continue
        meta = _read_json(meta_path)
        rows = []
        for idx, frame_path in enumerate(frames):
            rows.append(_row_from_sequence_meta(meta, idx, frame_path))
        candidates.append(
            CandidateSequence(
                session_id=str(meta.get("session_id") or seq_dir.parent.name),
                track_id=str(meta.get("track_id") or seq_dir.name),
                rows=rows,
                source_paths=frames,
            )
        )
    return candidates


def _legacy_metadata_candidates(extracted: Path) -> list[CandidateSequence]:
    grouped: dict[tuple[str, str], list[tuple[dict[str, Any], Path]]] = defaultdict(list)
    for metadata_path in sorted(extracted.rglob("metadata.jsonl")):
        if any(part in {"intent_dataset", "review_queue", "reports"} for part in metadata_path.parts):
            continue
        parent = metadata_path.parent
        for row in _read_jsonl(metadata_path):
            file_value = str(row.get("file") or "")
            if not file_value:
                continue
            source_path = parent / file_value
            if not source_path.exists():
                source_path = extracted / file_value
            if not source_path.exists() or not source_path.is_file():
                continue
            session_id = str(row.get("session_id") or row.get("_session_id") or parent.name)
            track_id = str(row.get("track_id") or row.get("track_uid") or row.get("tid") or "track")
            normalized = _normalize_legacy_row(row, source_path)
            grouped[(session_id, track_id)].append((normalized, source_path))

    candidates = []
    for (session_id, track_id), items in grouped.items():
        items.sort(key=lambda item: (float(item[0].get("ts") or 0), int(item[0].get("frame_id") or 0)))
        candidates.append(
            CandidateSequence(
                session_id=session_id,
                track_id=track_id,
                rows=[item[0] for item in items],
                source_paths=[item[1] for item in items],
            )
        )
    return candidates


def _split_track_rows(
    rows: list[dict[str, Any]],
    paths: list[Path],
) -> list[tuple[list[dict[str, Any]], list[Path]]]:
    if len(rows) < MIN_SEQUENCE_FRAMES:
        return [(rows, paths)]

    states = [_rough_motion_state(rows, i) for i in range(len(rows))]
    segments: list[tuple[int, int]] = []
    start = 0
    active = states[0]
    for i, state_name in enumerate(states[1:], start=1):
        if state_name != active and i - start >= MIN_SEQUENCE_FRAMES:
            segments.append((start, i))
            start = i
            active = state_name
    segments.append((start, len(rows)))

    normalized: list[tuple[list[dict[str, Any]], list[Path]]] = []
    for start, end in segments:
        while end - start > MAX_SEQUENCE_FRAMES:
            normalized.append((rows[start : start + MAX_SEQUENCE_FRAMES], paths[start : start + MAX_SEQUENCE_FRAMES]))
            start += MAX_SEQUENCE_FRAMES
        if end - start >= MIN_SEQUENCE_FRAMES:
            normalized.append((rows[start:end], paths[start:end]))
        elif normalized:
            prev_rows, prev_paths = normalized[-1]
            if len(prev_rows) + (end - start) <= MAX_SEQUENCE_FRAMES:
                normalized[-1] = (prev_rows + rows[start:end], prev_paths + paths[start:end])
    return normalized or [(rows, paths)]


def _write_sequence(
    raw_dir: Path,
    session_name: str,
    track_name: str,
    rows: list[dict[str, Any]],
    source_paths: list[Path],
    candidate: CandidateSequence,
) -> dict[str, Any]:
    quality = _quality_check(rows, source_paths)
    sequence_id = f"{session_name}/{track_name}"
    if quality["reject"]:
        return {
            "rejected": True,
            "sequence_id": sequence_id,
            "source_session_id": candidate.session_id,
            "source_track_id": candidate.track_id,
            "frame_count": len(rows),
            "quality_flags": quality["flags"],
        }

    seq_dir = raw_dir / session_name / track_name
    frames_dir = seq_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    copied_names: list[str] = []
    for index, source_path in enumerate(source_paths, start=1):
        dest_name = f"{index:04d}.jpg"
        dest_path = frames_dir / dest_name
        _copy_as_jpeg(source_path, dest_path)
        copied_names.append(f"frames/{dest_name}")

    meta = _build_sequence_meta(
        session_name=session_name,
        track_name=track_name,
        candidate=candidate,
        rows=rows,
        copied_names=copied_names,
        quality_flags=quality["flags"],
    )
    _write_json(seq_dir / "meta.json", meta)
    return {
        "sequence_id": sequence_id,
        "frame_count": int(meta["frame_count"]),
        "depth_valid_ratio": meta["depth_valid_ratio"],
        "quality_flags": quality["flags"],
    }


def _build_sequence_meta(
    session_name: str,
    track_name: str,
    candidate: CandidateSequence,
    rows: list[dict[str, Any]],
    copied_names: list[str],
    quality_flags: list[str],
) -> dict[str, Any]:
    dist = [_num(row.get("dist_mm")) for row in rows]
    valid_depth = [value > 0 for value in dist]
    depth_valid_ratio = sum(valid_depth) / len(valid_depth) if valid_depth else 0.0
    return {
        "track_id": track_name,
        "source_track_id": candidate.track_id,
        "session_id": session_name,
        "source_session_id": candidate.session_id,
        "timestamps": [_num(row.get("ts")) for row in rows],
        "frame_ids": [int(_num(row.get("frame_id"))) for row in rows],
        "frames": copied_names,
        "dist_mm": dist,
        "cx": [_num(row.get("cx")) for row in rows],
        "cy": [_num(row.get("cy")) for row in rows],
        "bw": [_num(row.get("bw")) for row in rows],
        "bh": [_num(row.get("bh")) for row in rows],
        "vx": [_num(row.get("vx")) for row in rows],
        "vy": [_num(row.get("vy")) for row in rows],
        "vtheta": [_num(row.get("vtheta")) for row in rows],
        "frame_w": int(_first_number(rows, "frame_w", 640)),
        "frame_h": int(_first_number(rows, "frame_h", 480)),
        "depth_valid_ratio": round(depth_valid_ratio, 4),
        "frame_count": len(rows),
        "quality_flags": quality_flags,
        "bbox_center_trajectory": [
            {"cx": _num(row.get("cx")), "cy": _num(row.get("cy"))}
            for row in rows
        ],
    }


def _quality_check(rows: list[dict[str, Any]], source_paths: list[Path]) -> dict[str, Any]:
    flags: list[str] = []
    if len(rows) < MIN_SEQUENCE_FRAMES:
        flags.append("too_short")
    missing_files = [path for path in source_paths if not path.exists() or path.stat().st_size <= 0]
    if missing_files:
        flags.append("missing_or_empty_frame")

    dist = np.asarray([_num(row.get("dist_mm")) for row in rows], dtype=float)
    depth_valid_ratio = float(np.mean(dist > 0)) if len(dist) else 0.0
    if depth_valid_ratio < MIN_DEPTH_VALID_RATIO:
        flags.append("depth_missing_mostly")

    frame_w = max(_first_number(rows, "frame_w", 640), 1)
    frame_h = max(_first_number(rows, "frame_h", 480), 1)
    cx = np.asarray([_num(row.get("cx")) for row in rows], dtype=float)
    cy = np.asarray([_num(row.get("cy")) for row in rows], dtype=float)
    if len(cx) > 2:
        jump = np.abs(np.diff(cx)) / frame_w + np.abs(np.diff(cy)) / frame_h
        if float(np.quantile(jump, 0.95)) > 0.60:
            flags.append("bbox_jitter_high")

    bw = np.asarray([_num(row.get("bw")) for row in rows], dtype=float)
    bh = np.asarray([_num(row.get("bh")) for row in rows], dtype=float)
    bad_bbox = np.mean((bw < 8) | (bh < 12)) if len(bw) else 1.0
    if bad_bbox > 0.20:
        flags.append("bbox_crop_invalid")

    reject = bool({"too_short", "missing_or_empty_frame", "bbox_jitter_high", "bbox_crop_invalid"} & set(flags))
    return {"reject": reject, "flags": flags or ["ok"]}


def _heuristic_label(meta: dict[str, Any]) -> dict[str, Any]:
    frame_count = int(meta.get("frame_count") or 0)
    if frame_count < MIN_SEQUENCE_FRAMES:
        return _label_payload("UNCERTAIN", None, "heuristic", 0.2, "needs_review", "sequence too short", {})

    features = _motion_features(meta)
    depth_ratio = float(meta.get("depth_valid_ratio") or 0.0)
    if depth_ratio < 0.30 and abs(features["cx_slope_px_s"]) < 55:
        return _label_payload("UNCERTAIN", None, "heuristic", 0.35, "needs_review", "depth signal is sparse", features)

    if features["erratic_score"] > 0.55:
        return _label_payload("ERRATIC", None, "heuristic", min(0.9, features["erratic_score"]), "needs_review", "trajectory changes sign repeatedly", features)

    if (
        features["depth_slope_mm_s"] < -120
        and features["depth_negative_ratio"] >= 0.65
        and depth_ratio >= 0.30
    ):
        confidence = min(0.95, 0.55 + abs(features["depth_slope_mm_s"]) / 700)
        return _label_payload("APPROACHING", None, "heuristic", confidence, "auto_accepted", "depth decreases consistently", features)

    if (
        features["depth_slope_mm_s"] > 120
        and features["depth_positive_ratio"] >= 0.65
        and depth_ratio >= 0.30
    ):
        confidence = min(0.95, 0.55 + abs(features["depth_slope_mm_s"]) / 700)
        return _label_payload("DEPARTING", None, "heuristic", confidence, "auto_accepted", "depth increases consistently", features)

    if (
        abs(features["cx_slope_px_s"]) > 45
        and features["cx_sign_consistency"] >= 0.65
        and abs(features["depth_slope_mm_s"]) < 220
    ):
        secondary = "crossing_right" if features["cx_slope_px_s"] > 0 else "crossing_left"
        confidence = min(0.92, 0.52 + abs(features["cx_slope_px_s"]) / 300)
        return _label_payload("CROSSING", secondary, "heuristic", confidence, "auto_accepted", "lateral motion is consistent while depth is not dominant", features)

    if (
        abs(features["depth_slope_mm_s"]) < 80
        and abs(features["cx_slope_px_s"]) < 25
        and features["depth_std_mm"] < 140
        and features["cx_std_px"] < 35
    ):
        return _label_payload("STATIONARY", None, "heuristic", 0.82, "auto_accepted", "depth and bbox center stay stable", features)

    return _label_payload("UNCERTAIN", None, "heuristic", 0.45, "needs_review", "motion consistency is weak", features)


def _maybe_vlm_label(seq_dir: Path, meta: dict[str, Any], heuristic: dict[str, Any]) -> dict[str, Any] | None:
    if not settings.OLLAMA_URL or not settings.OLLAMA_VLM_MODEL:
        return None
    if heuristic["primary_label"] not in {"UNCERTAIN", "ERRATIC"} and float(heuristic["confidence"]) >= 0.72:
        return None

    frames = _sample_frames(_frame_paths(seq_dir), limit=12)
    images = []
    for frame in frames:
        try:
            images.append(base64.b64encode(frame.read_bytes()).decode("ascii"))
        except OSError:
            continue
    if not images:
        return None

    features = heuristic.get("features", {})
    prompt = (
        "You label a short sequence of person ROI frames for robot navigation. "
        "Use the image sequence plus numeric motion summary. Return strict JSON only with keys: "
        "primary_label, secondary_label, confidence, notes. Valid primary labels are "
        "STATIONARY, APPROACHING, DEPARTING, CROSSING, ERRATIC, UNCERTAIN. "
        "Use secondary_label crossing_left or crossing_right only for CROSSING.\n"
        f"Motion summary: {json.dumps(features, ensure_ascii=True)}"
    )
    response = _ollama_generate(settings.OLLAMA_VLM_MODEL, prompt, images=images)
    if not response:
        return None
    parsed = _parse_json_object(response)
    if not parsed:
        return None
    return _normalize_model_label(parsed, "vlm")


def _reconcile_label(
    meta: dict[str, Any],
    heuristic: dict[str, Any],
    vlm: dict[str, Any] | None,
) -> dict[str, Any]:
    if not vlm:
        return heuristic
    if vlm["primary_label"] == heuristic["primary_label"]:
        confidence = max(float(heuristic["confidence"]), float(vlm["confidence"]))
        result = {**heuristic, "confidence": round(min(0.97, confidence), 3)}
        result["label_source"] = "heuristic+vlm"
        result["notes"] = f"{heuristic.get('notes', '')}; VLM agrees"
        return _with_review_policy(result, disagreement=False)

    if settings.OLLAMA_LLM_MODEL:
        prompt = (
            "Resolve a sequence-level motion label disagreement for robot navigation. "
            "Return strict JSON only with keys primary_label, secondary_label, confidence, notes. "
            f"Valid primary labels: {', '.join(LABELS)}.\n"
            f"Heuristic: {json.dumps(heuristic, ensure_ascii=True)}\n"
            f"VLM: {json.dumps(vlm, ensure_ascii=True)}\n"
            f"Meta summary: {json.dumps(_sequence_summary(meta), ensure_ascii=True)}"
        )
        response = _ollama_generate(settings.OLLAMA_LLM_MODEL, prompt)
        parsed = _parse_json_object(response) if response else None
        if parsed:
            resolved = _normalize_model_label(parsed, "llm")
            resolved["heuristic"] = heuristic
            resolved["vlm"] = vlm
            return _with_review_policy(resolved, disagreement=True)

    if float(heuristic["confidence"]) < 0.65 and float(vlm["confidence"]) >= 0.70:
        result = {**vlm, "heuristic": heuristic, "vlm": vlm}
        return _with_review_policy(result, disagreement=True)
    result = _label_payload(
        "UNCERTAIN",
        None,
        "heuristic+vlm",
        0.45,
        "needs_review",
        "heuristic and VLM disagree",
        heuristic.get("features", {}),
    )
    result["heuristic"] = heuristic
    result["vlm"] = vlm
    return result


def _export_training_frames(seq_dir: Path, train_out: Path, label: dict[str, Any]) -> list[dict[str, Any]]:
    primary = label["primary_label"]
    label_dir = LABEL_DIRS[primary]
    dest_dir = train_out / label_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    meta = _read_json(seq_dir / "meta.json")
    rows = []
    for index, frame in enumerate(_frame_paths(seq_dir), start=1):
        dest_name = f"{seq_dir.parent.name}_{seq_dir.name}_f{index:04d}.jpg"
        dest_path = dest_dir / dest_name
        shutil.copy2(frame, dest_path)
        row = {
            "file": f"{label_dir}/{dest_name}",
            "source_sequence": _sequence_key(seq_dir),
            "label": primary,
            "secondary_label": label.get("secondary_label"),
            "label_source": label.get("label_source"),
            "confidence": label.get("confidence"),
            "review_status": label.get("review_status"),
            "review_required": label.get("review_status") == "needs_review",
            "track_uid": _sequence_key(seq_dir),
            "session_id": meta.get("session_id"),
            "track_id": meta.get("track_id"),
            "frame_id": _array_get(meta.get("frame_ids"), index - 1, index),
            "sequence_frame_index": index,
            "cx": _array_get(meta.get("cx"), index - 1, None),
            "cy": _array_get(meta.get("cy"), index - 1, None),
            "bw": _array_get(meta.get("bw"), index - 1, None),
            "bh": _array_get(meta.get("bh"), index - 1, None),
            "dist_mm": _array_get(meta.get("dist_mm"), index - 1, None),
            "vx": _array_get(meta.get("vx"), index - 1, 0.0),
            "vy": _array_get(meta.get("vy"), index - 1, 0.0),
            "vtheta": _array_get(meta.get("vtheta"), index - 1, 0.0),
        }
        rows.append(row)
    if label.get("review_status") == "needs_review":
        review_dir = train_out / "review_queue" / label_dir
        review_dir.mkdir(parents=True, exist_ok=True)
        first_frame = _frame_paths(seq_dir)[0]
        shutil.copy2(first_frame, review_dir / f"{seq_dir.parent.name}_{seq_dir.name}.jpg")
    return rows


def _build_train_manifest(
    train_out: Path,
    sequence_rows: list[dict[str, Any]],
    class_counts: Counter[str],
    review_pending: Counter[str],
) -> dict[str, Any]:
    frame_counts = Counter()
    for row in _read_jsonl(train_out / "metadata.jsonl"):
        frame_counts[str(row.get("label") or "UNCERTAIN")] += 1
    trainable_frames = sum(frame_counts[label] for label in TRAINABLE_LABELS)
    ready = (
        trainable_frames >= 1
        and review_pending.get("ERRATIC", 0) == 0
        and any(frame_counts[label] for label in TRAINABLE_LABELS)
    )
    return {
        "generated_at": int(time.time()),
        "dataset": str(train_out),
        "schema": "intent_sequence_frame_export_v1",
        "ontology": {
            "runtime_intents": list(LABELS),
            "trainable_intents": list(TRAINABLE_LABELS),
        },
        "sequence_count": len(sequence_rows),
        "class_counts": dict(class_counts),
        "frame_counts": dict(frame_counts),
        "review_pending": dict(review_pending),
        "ready_for_phase2_training": ready,
        "gates": {
            "has_trainable_frames": trainable_frames >= 1,
            "erratic_review_done": review_pending.get("ERRATIC", 0) == 0,
        },
    }


def _motion_features(meta: dict[str, Any]) -> dict[str, float]:
    dist = np.asarray(meta.get("dist_mm") or [], dtype=float)
    cx = np.asarray(meta.get("cx") or [], dtype=float)
    times = _time_axis(meta, len(cx))
    valid = dist > 0
    depth_slope = _slope(times[valid], dist[valid]) if np.count_nonzero(valid) >= 3 else 0.0
    cx_slope = _slope(times, cx) if len(cx) >= 3 else 0.0

    valid_dist = dist[valid]
    depth_diffs = np.diff(valid_dist) if len(valid_dist) >= 2 else np.asarray([])
    cx_diffs = np.diff(cx) if len(cx) >= 2 else np.asarray([])
    depth_negative = _sign_ratio(depth_diffs, negative=True, threshold=15)
    depth_positive = _sign_ratio(depth_diffs, negative=False, threshold=15)
    cx_consistency = max(_sign_ratio(cx_diffs, negative=True, threshold=2), _sign_ratio(cx_diffs, negative=False, threshold=2))
    depth_flips = _sign_flip_ratio(depth_diffs, threshold=20)
    cx_flips = _sign_flip_ratio(cx_diffs, threshold=3)
    erratic_score = max(depth_flips, cx_flips)
    return {
        "depth_slope_mm_s": round(float(depth_slope), 3),
        "cx_slope_px_s": round(float(cx_slope), 3),
        "depth_negative_ratio": round(depth_negative, 3),
        "depth_positive_ratio": round(depth_positive, 3),
        "cx_sign_consistency": round(cx_consistency, 3),
        "depth_std_mm": round(float(np.std(valid_dist)) if len(valid_dist) else 0.0, 3),
        "cx_std_px": round(float(np.std(cx)) if len(cx) else 0.0, 3),
        "erratic_score": round(float(erratic_score), 3),
        "depth_valid_ratio": round(float(meta.get("depth_valid_ratio") or 0.0), 3),
    }


def _rough_motion_state(rows: list[dict[str, Any]], index: int) -> str:
    start = max(0, index - 7)
    end = min(len(rows), index + 8)
    if end - start < 5:
        return "unknown"
    meta = {
        "frame_count": end - start,
        "dist_mm": [_num(row.get("dist_mm")) for row in rows[start:end]],
        "cx": [_num(row.get("cx")) for row in rows[start:end]],
        "timestamps": [_num(row.get("ts")) for row in rows[start:end]],
        "depth_valid_ratio": 1.0,
    }
    features = _motion_features(meta)
    if features["depth_slope_mm_s"] < -120:
        return "approaching"
    if features["depth_slope_mm_s"] > 120:
        return "departing"
    if abs(features["cx_slope_px_s"]) > 45:
        return "crossing"
    if features["erratic_score"] > 0.55:
        return "erratic"
    return "stationary"


def _label_payload(
    primary: str,
    secondary: str | None,
    source: str,
    confidence: float,
    review_status: str,
    notes: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    return {
        "primary_label": primary,
        "secondary_label": secondary,
        "label_source": source,
        "confidence": round(float(confidence), 3),
        "review_status": review_status,
        "notes": notes,
        "features": features,
    }


def _with_review_policy(label: dict[str, Any], disagreement: bool) -> dict[str, Any]:
    primary = label["primary_label"]
    confidence = float(label.get("confidence") or 0.0)
    if primary in {"ERRATIC", "UNCERTAIN"} or confidence < 0.65 or disagreement:
        label["review_status"] = "needs_review"
    else:
        label["review_status"] = "auto_accepted"
    return label


def _normalize_model_label(payload: dict[str, Any], source: str) -> dict[str, Any]:
    primary = str(payload.get("primary_label") or payload.get("label") or "UNCERTAIN").strip().upper()
    if primary in {"CROSSING_LEFT", "CROSSING_RIGHT"}:
        secondary = primary.lower()
        primary = "CROSSING"
    else:
        secondary = payload.get("secondary_label")
    if primary not in LABELS:
        primary = "UNCERTAIN"
    confidence = _num(payload.get("confidence"), 0.5)
    result = _label_payload(
        primary,
        str(secondary) if secondary else None,
        source,
        max(0.0, min(1.0, confidence)),
        "needs_review",
        str(payload.get("notes") or ""),
        {},
    )
    return _with_review_policy(result, disagreement=False)


def _ollama_generate(model: str, prompt: str, images: list[str] | None = None) -> str | None:
    url = settings.OLLAMA_URL.rstrip("/") + "/api/generate"
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    if images:
        body["images"] = images
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=3.0, read=120.0, write=30.0, pool=5.0)) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
            data = response.json()
            return str(data.get("response") or "")
    except Exception:
        return None


def _parse_json_object(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _row_from_sequence_meta(meta: dict[str, Any], idx: int, frame_path: Path) -> dict[str, Any]:
    return {
        "file": frame_path.name,
        "frame_id": _array_get(meta.get("frame_ids"), idx, idx + 1),
        "session_id": meta.get("session_id"),
        "track_id": meta.get("track_id"),
        "tid": meta.get("source_track_id") or meta.get("track_id"),
        "ts": _array_get(meta.get("timestamps"), idx, idx),
        "cx": _array_get(meta.get("cx"), idx, 0),
        "cy": _array_get(meta.get("cy"), idx, 0),
        "bw": _array_get(meta.get("bw"), idx, 0),
        "bh": _array_get(meta.get("bh"), idx, 0),
        "frame_w": meta.get("frame_w", 640),
        "frame_h": meta.get("frame_h", 480),
        "dist_mm": _array_get(meta.get("dist_mm"), idx, 0),
        "vx": _array_get(meta.get("vx"), idx, 0),
        "vy": _array_get(meta.get("vy"), idx, 0),
        "vtheta": _array_get(meta.get("vtheta"), idx, 0),
    }


def _normalize_legacy_row(row: dict[str, Any], source_path: Path) -> dict[str, Any]:
    return {
        **row,
        "frame_id": int(_num(row.get("frame_id"))),
        "tid": row.get("tid") or row.get("track_id") or row.get("track_uid"),
        "ts": _num(row.get("ts") or row.get("timestamp") or row.get("timestamp_ms")),
        "cx": _num(row.get("cx")),
        "cy": _num(row.get("cy")),
        "bw": _num(row.get("bw")),
        "bh": _num(row.get("bh")),
        "frame_w": int(_num(row.get("frame_w"), 640)),
        "frame_h": int(_num(row.get("frame_h"), 480)),
        "dist_mm": _num(row.get("dist_mm")),
        "vx": _num(row.get("vx")),
        "vy": _num(row.get("vy")),
        "vtheta": _num(row.get("vtheta")),
        "_source_path": str(source_path),
    }


def _copy_as_jpeg(source: Path, dest: Path) -> None:
    if source.suffix.lower() in {".jpg", ".jpeg"}:
        shutil.copy2(source, dest)
        return
    try:
        import cv2

        image = cv2.imread(str(source))
        if image is not None and cv2.imwrite(str(dest), image, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            return
    except Exception:
        pass
    shutil.copy2(source, dest)


def _safe_extract_zip(archive_path: Path, output_dir: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or re.match(r"^[a-zA-Z]:", name) or ".." in parts:
                raise ValueError(f"Unsafe archive member path: {member.filename}")
        archive.extractall(output_dir)


def _frame_paths(seq_dir: Path) -> list[Path]:
    frames_dir = seq_dir / "frames"
    if not frames_dir.exists():
        return []
    return sorted(
        [
            p
            for p in frames_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]
    )


def _iter_sequence_dirs(raw_dir: Path):
    for session_dir in sorted(raw_dir.glob("session_*")):
        if not session_dir.is_dir():
            continue
        for track_dir in sorted(session_dir.glob("track_*")):
            if (track_dir / "frames").is_dir() and (track_dir / "meta.json").exists():
                yield track_dir


def _sequence_key(seq_dir: Path) -> str:
    return f"{seq_dir.parent.name}__{seq_dir.name}"


def _sequence_dir_from_key(raw_dir: Path, key: str) -> Path:
    parts = key.split("__", 1)
    if len(parts) != 2:
        raise FileNotFoundError("Invalid sequence id")
    seq_dir = raw_dir / parts[0] / parts[1]
    if not seq_dir.exists():
        raise FileNotFoundError("Sequence not found")
    return seq_dir


def _sequence_summary(meta: dict[str, Any]) -> dict[str, Any]:
    features = _motion_features(meta) if meta else {}
    return {
        "track_id": meta.get("track_id"),
        "session_id": meta.get("session_id"),
        "frame_count": meta.get("frame_count"),
        "depth_valid_ratio": meta.get("depth_valid_ratio"),
        "quality_flags": meta.get("quality_flags", []),
        "motion": features,
    }


def _time_axis(meta: dict[str, Any], count: int) -> np.ndarray:
    timestamps = np.asarray(meta.get("timestamps") or [], dtype=float)
    if len(timestamps) == count and count > 1:
        diffs = np.diff(timestamps)
        positive_diffs = diffs[diffs > 0]
        median_step = float(np.median(positive_diffs)) if len(positive_diffs) else 0.0
        if np.nanmax(timestamps) > 1_000_000 or median_step > 10.0:
            timestamps = timestamps / 1000.0
        timestamps = timestamps - timestamps[0]
        if float(np.nanmax(timestamps)) > 0:
            return timestamps
    return np.arange(count, dtype=float) / 30.0


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or len(y) < 2:
        return 0.0
    if float(np.max(x) - np.min(x)) <= 1e-6:
        x = np.arange(len(y), dtype=float)
    try:
        return float(np.polyfit(x, y, 1)[0])
    except Exception:
        return 0.0


def _sign_ratio(values: np.ndarray, negative: bool, threshold: float) -> float:
    valid = values[np.abs(values) >= threshold]
    if len(valid) == 0:
        return 0.0
    return float(np.mean(valid < 0 if negative else valid > 0))


def _sign_flip_ratio(values: np.ndarray, threshold: float) -> float:
    valid = values[np.abs(values) >= threshold]
    if len(valid) < 3:
        return 0.0
    signs = np.sign(valid)
    return float(np.mean(signs[1:] != signs[:-1]))


def _sample_frames(frames: list[Path], limit: int) -> list[Path]:
    if len(frames) <= limit:
        return frames
    indexes = np.linspace(0, len(frames) - 1, limit).round().astype(int)
    return [frames[int(i)] for i in indexes]


def _array_get(values: Any, index: int, default: Any) -> Any:
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return default


def _first_number(rows: list[dict[str, Any]], key: str, default: float) -> float:
    for row in rows:
        value = _num(row.get(key), math.nan)
        if math.isfinite(value) and value > 0:
            return value
    return default


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", Path(name).name)[:120] or "dataset.zip"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_state() -> dict[str, Any]:
    return _read_json(_state_path())


def _write_state(payload: dict[str, Any]) -> None:
    _write_json(_state_path(), payload)


def _root_dir() -> Path:
    return Path(settings.DATASET_DATA_DIR)


def _raw_dir(dataset_id: str) -> Path:
    return _root_dir() / "raw" / dataset_id


def _labeled_dir(dataset_id: str) -> Path:
    return _root_dir() / "labeled" / dataset_id


def _uploads_dir() -> Path:
    return _root_dir() / "uploads"


def _tmp_dir() -> Path:
    return _root_dir() / "_tmp"


def _exports_dir() -> Path:
    return _root_dir() / "exports"


def _state_path() -> Path:
    return _root_dir() / "state.json"


def _ensure_dirs() -> None:
    for path in (_root_dir(), _uploads_dir(), _tmp_dir(), _exports_dir()):
        path.mkdir(parents=True, exist_ok=True)
