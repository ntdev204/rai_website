from __future__ import annotations

import base64
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class FaceMatch:
    user: User
    score: float


def _decode_image(image_base64: str) -> np.ndarray:
    if "," in image_base64 and image_base64.split(",", 1)[0].startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]
    raw = base64.b64decode(image_base64, validate=False)
    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image payload")
    return image


def _fallback_face_crop(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    x1 = int(w * 0.15)
    x2 = int(w * 0.85)
    y1 = int(h * 0.02)
    y2 = int(h * 0.82)
    crop = image[y1:y2, x1:x2]
    return crop if crop.size else image


def _detect_with_cascade(gray: np.ndarray, cascade_name: str) -> list[tuple[int, int, int, int]]:
    cascade_path = cv2.data.haarcascades + cascade_name
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        return []
    faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=3, minSize=(42, 42))
    return [tuple(int(v) for v in face) for face in faces]


def _largest_face(image: np.ndarray) -> tuple[np.ndarray, bool]:
    if cv2 is None:
        raise RuntimeError("opencv-python-headless is required for face auth")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = _detect_with_cascade(gray, "haarcascade_frontalface_default.xml")

    profile_faces = _detect_with_cascade(gray, "haarcascade_profileface.xml")
    faces.extend(profile_faces)

    flipped = cv2.flip(gray, 1)
    flipped_profiles = _detect_with_cascade(flipped, "haarcascade_profileface.xml")
    img_w = image.shape[1]
    faces.extend((img_w - x - w, y, w, h) for x, y, w, h in flipped_profiles)

    if len(faces) == 0:
        return _fallback_face_crop(image), False

    x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
    pad = int(max(w, h) * 0.18)
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(image.shape[1], x + w + pad)
    y2 = min(image.shape[0], y + h + pad)
    return image[y1:y2, x1:x2], True


def _embedding_from_face(face: np.ndarray) -> list[float]:
    face = cv2.resize(face, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    gray_small = cv2.resize(gray, (24, 24), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0

    hsv = cv2.cvtColor(face, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).flatten()
    hist = hist.astype(np.float32)
    if np.linalg.norm(hist) > 0:
        hist = hist / np.linalg.norm(hist)

    embedding = np.concatenate([gray_small.flatten(), hist])
    norm = float(np.linalg.norm(embedding))
    if norm <= 0:
        raise ValueError("Invalid face embedding")
    embedding = embedding / norm
    return [round(float(v), 6) for v in embedding.tolist()]


def _face_from_base64(
    image_base64: str,
    require_detected_face: bool = False,
) -> tuple[np.ndarray, bool]:
    if cv2 is None:
        raise RuntimeError("opencv-python-headless is required for face auth")

    image = _decode_image(image_base64)
    face, detected = _largest_face(image)
    if require_detected_face and not detected:
        raise ValueError("No face detected")
    if face.size == 0:
        raise ValueError("No usable face crop")
    return face, detected


def compute_face_embedding(image_base64: str, require_detected_face: bool = False) -> list[float]:
    face, _ = _face_from_base64(image_base64, require_detected_face)
    return _embedding_from_face(face)


def _validate_image_count(count: int) -> None:
    if count < settings.FACE_MIN_IMAGES:
        raise ValueError(f"At least {settings.FACE_MIN_IMAGES} face images are required")
    if count > settings.FACE_MAX_IMAGES:
        raise ValueError(f"At most {settings.FACE_MAX_IMAGES} face images are allowed")


def _mean_embedding(embeddings: list[list[float]]) -> list[float]:
    arr = np.asarray(embeddings, dtype=np.float32)
    mean = np.mean(arr, axis=0)
    norm = float(np.linalg.norm(mean))
    if norm <= 0:
        raise ValueError("Invalid face embedding set")
    mean = mean / norm
    return [round(float(v), 6) for v in mean.tolist()]


def _save_face_images(user_id: int, face_id: str, faces: list[np.ndarray]) -> list[str]:
    base_dir = Path(settings.FACE_DATA_DIR)
    user_dir = base_dir / f"user_{user_id}"
    if user_dir.exists():
        shutil.rmtree(user_dir)
    user_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    for idx, face in enumerate(faces, start=1):
        path = user_dir / f"{face_id}_{idx:02d}.jpg"
        ok = cv2.imwrite(str(path), face, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError("Failed to save face image")
        paths.append(str(path))
    return paths


async def register_face(db: AsyncSession, user: User, images_base64: list[str]) -> User:
    _validate_image_count(len(images_base64))

    faces: list[np.ndarray] = []
    embeddings: list[list[float]] = []
    detected_count = 0
    for image_base64 in images_base64:
        face, detected = _face_from_base64(image_base64, require_detected_face=False)
        detected_count += int(detected)
        faces.append(face)
        embeddings.append(_embedding_from_face(face))

    if detected_count == 0:
        raise ValueError("No face detected in captured images")

    mean_embedding = _mean_embedding(embeddings)
    digest_source = "|".join(",".join(f"{v:.6f}" for v in embedding) for embedding in embeddings)
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    user.face_id = f"face_{user.id}_{digest}"
    user.face_embedding_json = mean_embedding
    user.face_embeddings_json = embeddings
    user.face_image_paths_json = _save_face_images(user.id, user.face_id, faces)
    user.face_auth_enabled = True
    user.face_registered_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def clear_face(db: AsyncSession, user: User) -> User:
    user_dir = Path(settings.FACE_DATA_DIR) / f"user_{user.id}"
    if user_dir.exists():
        shutil.rmtree(user_dir)
    user.face_id = None
    user.face_embedding_json = None
    user.face_embeddings_json = None
    user.face_image_paths_json = None
    user.face_auth_enabled = False
    user.face_registered_at = None
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def match_face(db: AsyncSession, image_base64: str) -> FaceMatch | None:
    embedding = np.asarray(compute_face_embedding(image_base64), dtype=np.float32)
    result = await db.execute(
        select(User).where(
            User.is_active.is_(True),
            User.face_auth_enabled.is_(True),
            User.face_id.is_not(None),
            User.face_embedding_json.is_not(None),
        )
    )

    best: FaceMatch | None = None
    for user in result.scalars().all():
        candidates = user.face_embeddings_json or [user.face_embedding_json]
        for candidate_raw in candidates:
            candidate = np.asarray(candidate_raw or [], dtype=np.float32)
            if candidate.shape != embedding.shape:
                continue
            denom = float(np.linalg.norm(embedding) * np.linalg.norm(candidate))
            if denom <= 0:
                continue
            score = float(np.dot(embedding, candidate) / denom)
            if best is None or score > best.score:
                best = FaceMatch(user=user, score=score)

    if best and best.score >= settings.FACE_MATCH_THRESHOLD:
        return best
    return None


def face_status(user: User) -> dict[str, Any]:
    return {
        "face_auth_enabled": bool(user.face_auth_enabled),
        "face_id": user.face_id,
        "face_registered_at": user.face_registered_at,
        "face_image_count": len(user.face_image_paths_json or []),
        "face_image_paths": user.face_image_paths_json or [],
        "min_images": settings.FACE_MIN_IMAGES,
        "max_images": settings.FACE_MAX_IMAGES,
    }
