from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ExperimentTrialCreate(BaseModel):
    scenario: str = Field(..., description="One of 11 defined scenarios")
    phase: str = Field(..., pattern="^(offline|online)$")
    trial_index: int = Field(default=1, ge=1)
    result: str = Field(..., pattern="^(PASS|FAIL|PARTIAL)$")
    observer: str = Field(default="")
    notes: Optional[str] = None

    # Offline 6.3.1.1 — Detector
    detector_latency_avg_ms: Optional[float] = None
    detector_latency_p95_ms: Optional[float] = None
    detector_rate: Optional[float] = None
    detector_fp_rate: Optional[float] = None

    # Offline 6.3.1.2 — Tracker
    tracker_id_switch_rate: Optional[float] = None
    tracker_loss_rate: Optional[float] = None
    tracker_lifespan_avg: Optional[float] = None
    tracker_fragment_rate: Optional[float] = None

    # Offline 6.3.1.3 — Intent CNN
    intent_accuracy: Optional[float] = None
    intent_f1_stationary: Optional[float] = None
    intent_f1_approaching: Optional[float] = None
    intent_f1_departing: Optional[float] = None
    intent_f1_crossing: Optional[float] = None
    intent_f1_erratic: Optional[float] = None
    intent_ece: Optional[float] = None
    intent_uncertain_rate: Optional[float] = None
    intent_latency_avg_ms: Optional[float] = None
    intent_latency_p95_ms: Optional[float] = None

    # Offline 6.3.1.4 — Risk Scorer
    risk_mean_approaching: Optional[float] = None
    risk_mean_stationary: Optional[float] = None
    risk_auc: Optional[float] = None
    risk_top_features: Optional[str] = None

    # Offline 6.3.1.5 — Dataset Gate
    dataset_total_samples: Optional[int] = None
    dataset_min_class_count: Optional[int] = None
    dataset_duplicate_rate: Optional[float] = None
    dataset_corrupt_rate: Optional[float] = None
    dataset_pending_review_rate: Optional[float] = None
    dataset_manifest_ready: Optional[bool] = None

    # Online common
    ai_fps_avg: Optional[float] = None
    uncertain_count: Optional[int] = None
    reaction_latency_ms: Optional[float] = None
    stop_distance_m: Optional[float] = None
    robot_behavior: Optional[str] = None
    success_count: Optional[int] = None
    total_count: Optional[int] = None

    # Online 6.3.2.1 — Corridor Empty
    travel_time_s: Optional[float] = None
    false_stop_count: Optional[int] = None

    # Online 6.3.2.5/6 — Degrade
    degrade_detect_ms: Optional[float] = None
    degrade_recovery_ms: Optional[float] = None
    degrade_false_negative_count: Optional[int] = None

    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_scenario(self) -> "ExperimentTrialCreate":
        valid = {
            "detector_eval", "tracker_eval", "intent_eval",
            "risk_scorer_eval", "dataset_gate",
            "corridor_empty", "static_person", "approaching_person",
            "crossing_person", "bad_depth", "perception_degrade",
        }
        if self.scenario not in valid:
            raise ValueError(f"scenario must be one of: {sorted(valid)}")
        return self


class ExperimentTrialRead(ExperimentTrialCreate):
    id: int
    created_at: datetime

    # Computed
    success_rate: Optional[float] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_success_rate(self) -> "ExperimentTrialRead":
        if self.success_count is not None and self.total_count and self.total_count > 0:
            self.success_rate = round(self.success_count / self.total_count, 4)
        return self


class ExperimentTrialList(BaseModel):
    total: int
    items: list[ExperimentTrialRead]
