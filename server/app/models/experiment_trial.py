from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base

SCENARIOS = [
    # Offline
    "detector_eval",
    "tracker_eval",
    "intent_eval",
    "risk_scorer_eval",
    "dataset_gate",
    # Online
    "corridor_empty",
    "static_person",
    "approaching_person",
    "crossing_person",
    "bad_depth",
    "perception_degrade",
]

PHASES = ["offline", "online"]
RESULTS = ["PASS", "FAIL", "PARTIAL"]


class ExperimentTrial(Base):
    __tablename__ = "experiment_trials"

    id = Column(Integer, primary_key=True, index=True)
    scenario = Column(String, nullable=False, index=True)
    phase = Column(String, nullable=False, index=True)  # offline | online
    trial_index = Column(Integer, nullable=False, default=1)
    result = Column(String, nullable=False, index=True)  # PASS | FAIL | PARTIAL
    observer = Column(String, nullable=False, default="")
    notes = Column(Text, nullable=True)

    # ── Offline 6.3.1.1 — Detector ──────────────────────────────────────────
    detector_latency_avg_ms = Column(Float, nullable=True)
    detector_latency_p95_ms = Column(Float, nullable=True)
    detector_rate = Column(Float, nullable=True)       # detection rate %
    detector_fp_rate = Column(Float, nullable=True)    # false positive rate %

    # ── Offline 6.3.1.2 — Tracker ───────────────────────────────────────────
    tracker_id_switch_rate = Column(Float, nullable=True)
    tracker_loss_rate = Column(Float, nullable=True)
    tracker_lifespan_avg = Column(Float, nullable=True)  # frames
    tracker_fragment_rate = Column(Float, nullable=True)

    # ── Offline 6.3.1.3 — Intent CNN ────────────────────────────────────────
    intent_accuracy = Column(Float, nullable=True)
    intent_f1_stationary = Column(Float, nullable=True)
    intent_f1_approaching = Column(Float, nullable=True)
    intent_f1_departing = Column(Float, nullable=True)
    intent_f1_crossing = Column(Float, nullable=True)
    intent_f1_erratic = Column(Float, nullable=True)
    intent_ece = Column(Float, nullable=True)
    intent_uncertain_rate = Column(Float, nullable=True)
    intent_latency_avg_ms = Column(Float, nullable=True)
    intent_latency_p95_ms = Column(Float, nullable=True)

    # ── Offline 6.3.1.4 — Risk Scorer ───────────────────────────────────────
    risk_mean_approaching = Column(Float, nullable=True)
    risk_mean_stationary = Column(Float, nullable=True)
    risk_auc = Column(Float, nullable=True)
    risk_top_features = Column(Text, nullable=True)  # JSON string

    # ── Offline 6.3.1.5 — Dataset Gate ──────────────────────────────────────
    dataset_total_samples = Column(Integer, nullable=True)
    dataset_min_class_count = Column(Integer, nullable=True)
    dataset_duplicate_rate = Column(Float, nullable=True)
    dataset_corrupt_rate = Column(Float, nullable=True)
    dataset_pending_review_rate = Column(Float, nullable=True)
    dataset_manifest_ready = Column(Boolean, nullable=True)

    # ── Online common ────────────────────────────────────────────────────────
    ai_fps_avg = Column(Float, nullable=True)
    uncertain_count = Column(Integer, nullable=True)
    reaction_latency_ms = Column(Float, nullable=True)
    stop_distance_m = Column(Float, nullable=True)
    robot_behavior = Column(String, nullable=True)  # STOP/DETOUR/WAIT/SLOW/STEER/HOLD
    success_count = Column(Integer, nullable=True)
    total_count = Column(Integer, nullable=True)

    # ── Online 6.3.2.1 — Corridor Empty ─────────────────────────────────────
    travel_time_s = Column(Float, nullable=True)
    false_stop_count = Column(Integer, nullable=True)

    # ── Online 6.3.2.5/6 — Degrade ──────────────────────────────────────────
    degrade_detect_ms = Column(Float, nullable=True)
    degrade_recovery_ms = Column(Float, nullable=True)
    degrade_false_negative_count = Column(Integer, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
