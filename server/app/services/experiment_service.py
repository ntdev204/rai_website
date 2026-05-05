from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, select

from app.core.database import AsyncSessionLocal
from app.models.experiment_trial import ExperimentTrial
from app.schemas.experiment import ExperimentTrialCreate

logger = logging.getLogger(__name__)

# ── Column definitions for CSV exports ────────────────────────────────────────

_OFFLINE_COLS = [
    "id", "scenario", "phase", "trial_index", "result", "observer",
    "detector_latency_avg_ms", "detector_latency_p95_ms",
    "detector_rate", "detector_fp_rate",
    "tracker_id_switch_rate", "tracker_loss_rate",
    "tracker_lifespan_avg", "tracker_fragment_rate",
    "intent_accuracy",
    "intent_f1_stationary", "intent_f1_approaching", "intent_f1_departing",
    "intent_f1_crossing", "intent_f1_erratic",
    "intent_ece", "intent_uncertain_rate",
    "intent_latency_avg_ms", "intent_latency_p95_ms",
    "risk_mean_approaching", "risk_mean_stationary", "risk_auc", "risk_top_features",
    "dataset_total_samples", "dataset_min_class_count",
    "dataset_duplicate_rate", "dataset_corrupt_rate",
    "dataset_pending_review_rate", "dataset_manifest_ready",
    "notes", "started_at", "ended_at", "created_at",
]

_ONLINE_COLS = [
    "id", "scenario", "phase", "trial_index", "result", "observer",
    "ai_fps_avg", "uncertain_count",
    "reaction_latency_ms", "stop_distance_m", "robot_behavior",
    "success_count", "total_count",
    "travel_time_s", "false_stop_count",
    "degrade_detect_ms", "degrade_recovery_ms", "degrade_false_negative_count",
    "notes", "started_at", "ended_at", "created_at",
]

_FULL_COLS = list(dict.fromkeys(_OFFLINE_COLS + _ONLINE_COLS))  # deduplicate, preserve order

_SUMMARY_COLS = [
    "scenario", "phase", "n_trials", "n_pass", "n_fail", "n_partial", "pass_rate",
    "mean_reaction_latency_ms", "std_reaction_latency_ms",
    "mean_stop_distance_m", "std_stop_distance_m",
    "mean_success_rate", "mean_ai_fps_avg",
    "mean_intent_accuracy", "mean_intent_ece",
    "mean_detector_latency_avg_ms", "mean_risk_auc",
]

_OFFLINE_SCENARIOS = {
    "detector_eval", "tracker_eval", "intent_eval", "risk_scorer_eval", "dataset_gate"
}
_ONLINE_SCENARIOS = {
    "corridor_empty", "static_person", "approaching_person",
    "crossing_person", "bad_depth", "perception_degrade",
}


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_trial(data: ExperimentTrialCreate) -> ExperimentTrial:
    trial = ExperimentTrial(**data.model_dump(exclude_none=False))
    if trial.started_at is None:
        trial.started_at = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(trial)
        await db.commit()
        await db.refresh(trial)
    logger.info("Experiment trial created: scenario=%s trial=%d result=%s",
                trial.scenario, trial.trial_index, trial.result)
    return trial


async def list_trials(
    scenario: Optional[str] = None,
    phase: Optional[str] = None,
    result: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[ExperimentTrial]]:
    async with AsyncSessionLocal() as db:
        q = select(ExperimentTrial)
        if scenario:
            q = q.where(ExperimentTrial.scenario == scenario)
        if phase:
            q = q.where(ExperimentTrial.phase == phase)
        if result:
            q = q.where(ExperimentTrial.result == result)
        q = q.order_by(desc(ExperimentTrial.created_at))

        total_q = q.with_only_columns(  # type: ignore[call-arg]
            ExperimentTrial.id
        ).order_by(None)
        total_result = await db.execute(total_q)
        total = len(total_result.all())

        rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
    return total, list(rows)


async def get_trial(trial_id: int) -> Optional[ExperimentTrial]:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(ExperimentTrial).where(ExperimentTrial.id == trial_id))
        ).scalar_one_or_none()


async def delete_trial(trial_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(ExperimentTrial).where(ExperimentTrial.id == trial_id))
        ).scalar_one_or_none()
        if not row:
            return False
        await db.delete(row)
        await db.commit()
    return True


# ── CSV Generation ────────────────────────────────────────────────────────────

def _trial_to_dict(t: ExperimentTrial) -> dict[str, Any]:
    success_rate = None
    if t.success_count is not None and t.total_count and t.total_count > 0:
        success_rate = round(t.success_count / t.total_count, 4)
    return {col: getattr(t, col, None) for col in _FULL_COLS} | {"success_rate": success_rate}


def _write_csv(cols: list[str], rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


async def export_offline_csv() -> str:
    _, trials = await list_trials(phase="offline", limit=10000)
    rows = [_trial_to_dict(t) for t in trials]
    return _write_csv(_OFFLINE_COLS, rows)


async def export_online_csv() -> str:
    _, trials = await list_trials(phase="online", limit=10000)
    rows = [_trial_to_dict(t) for t in trials]
    return _write_csv(_ONLINE_COLS, rows)


async def export_full_csv() -> str:
    _, trials = await list_trials(limit=10000)
    rows = [_trial_to_dict(t) for t in trials]
    return _write_csv(_FULL_COLS, rows)


async def export_summary_csv() -> str:
    import math
    _, trials = await list_trials(limit=10000)

    # Group by scenario
    groups: dict[str, list[ExperimentTrial]] = {}
    for t in trials:
        groups.setdefault(t.scenario, []).append(t)

    def _mean(vals: list[float | None]) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        return round(sum(cleaned) / len(cleaned), 4) if cleaned else None

    def _std(vals: list[float | None]) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        if len(cleaned) < 2:
            return None
        m = sum(cleaned) / len(cleaned)
        variance = sum((x - m) ** 2 for x in cleaned) / (len(cleaned) - 1)
        return round(math.sqrt(variance), 4)

    rows = []
    for scenario in sorted(groups):
        grp = groups[scenario]
        phase = "offline" if scenario in _OFFLINE_SCENARIOS else "online"
        n_pass = sum(1 for t in grp if t.result == "PASS")
        n_fail = sum(1 for t in grp if t.result == "FAIL")
        n_partial = sum(1 for t in grp if t.result == "PARTIAL")
        n = len(grp)

        success_rates = []
        for t in grp:
            if t.success_count is not None and t.total_count and t.total_count > 0:
                success_rates.append(t.success_count / t.total_count)

        rows.append({
            "scenario": scenario,
            "phase": phase,
            "n_trials": n,
            "n_pass": n_pass,
            "n_fail": n_fail,
            "n_partial": n_partial,
            "pass_rate": round(n_pass / n, 4) if n > 0 else None,
            "mean_reaction_latency_ms": _mean([t.reaction_latency_ms for t in grp]),
            "std_reaction_latency_ms": _std([t.reaction_latency_ms for t in grp]),
            "mean_stop_distance_m": _mean([t.stop_distance_m for t in grp]),
            "std_stop_distance_m": _std([t.stop_distance_m for t in grp]),
            "mean_success_rate": _mean(success_rates),
            "mean_ai_fps_avg": _mean([t.ai_fps_avg for t in grp]),
            "mean_intent_accuracy": _mean([t.intent_accuracy for t in grp]),
            "mean_intent_ece": _mean([t.intent_ece for t in grp]),
            "mean_detector_latency_avg_ms": _mean([t.detector_latency_avg_ms for t in grp]),
            "mean_risk_auc": _mean([t.risk_auc for t in grp]),
        })

    return _write_csv(_SUMMARY_COLS, rows)
