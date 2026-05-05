"""Add experiment_trials table

Revision ID: b3e5a8c12f90
Revises: a2c4f7d9b8e1
Create Date: 2026-05-05 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e5a8c12f90"
down_revision: Union[str, Sequence[str], None] = "a2c4f7d9b8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "experiment_trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("trial_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("observer", sa.String(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=True),
        # Detector
        sa.Column("detector_latency_avg_ms", sa.Float(), nullable=True),
        sa.Column("detector_latency_p95_ms", sa.Float(), nullable=True),
        sa.Column("detector_rate", sa.Float(), nullable=True),
        sa.Column("detector_fp_rate", sa.Float(), nullable=True),
        # Tracker
        sa.Column("tracker_id_switch_rate", sa.Float(), nullable=True),
        sa.Column("tracker_loss_rate", sa.Float(), nullable=True),
        sa.Column("tracker_lifespan_avg", sa.Float(), nullable=True),
        sa.Column("tracker_fragment_rate", sa.Float(), nullable=True),
        # Intent CNN
        sa.Column("intent_accuracy", sa.Float(), nullable=True),
        sa.Column("intent_f1_stationary", sa.Float(), nullable=True),
        sa.Column("intent_f1_approaching", sa.Float(), nullable=True),
        sa.Column("intent_f1_departing", sa.Float(), nullable=True),
        sa.Column("intent_f1_crossing", sa.Float(), nullable=True),
        sa.Column("intent_f1_erratic", sa.Float(), nullable=True),
        sa.Column("intent_ece", sa.Float(), nullable=True),
        sa.Column("intent_uncertain_rate", sa.Float(), nullable=True),
        sa.Column("intent_latency_avg_ms", sa.Float(), nullable=True),
        sa.Column("intent_latency_p95_ms", sa.Float(), nullable=True),
        # Risk Scorer
        sa.Column("risk_mean_approaching", sa.Float(), nullable=True),
        sa.Column("risk_mean_stationary", sa.Float(), nullable=True),
        sa.Column("risk_auc", sa.Float(), nullable=True),
        sa.Column("risk_top_features", sa.Text(), nullable=True),
        # Dataset Gate
        sa.Column("dataset_total_samples", sa.Integer(), nullable=True),
        sa.Column("dataset_min_class_count", sa.Integer(), nullable=True),
        sa.Column("dataset_duplicate_rate", sa.Float(), nullable=True),
        sa.Column("dataset_corrupt_rate", sa.Float(), nullable=True),
        sa.Column("dataset_pending_review_rate", sa.Float(), nullable=True),
        sa.Column("dataset_manifest_ready", sa.Boolean(), nullable=True),
        # Online common
        sa.Column("ai_fps_avg", sa.Float(), nullable=True),
        sa.Column("uncertain_count", sa.Integer(), nullable=True),
        sa.Column("reaction_latency_ms", sa.Float(), nullable=True),
        sa.Column("stop_distance_m", sa.Float(), nullable=True),
        sa.Column("robot_behavior", sa.String(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=True),
        # Online corridor empty
        sa.Column("travel_time_s", sa.Float(), nullable=True),
        sa.Column("false_stop_count", sa.Integer(), nullable=True),
        # Online degrade
        sa.Column("degrade_detect_ms", sa.Float(), nullable=True),
        sa.Column("degrade_recovery_ms", sa.Float(), nullable=True),
        sa.Column("degrade_false_negative_count", sa.Integer(), nullable=True),
        # Timestamps
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiment_trials_id", "experiment_trials", ["id"], unique=False)
    op.create_index("ix_experiment_trials_scenario", "experiment_trials", ["scenario"], unique=False)
    op.create_index("ix_experiment_trials_phase", "experiment_trials", ["phase"], unique=False)
    op.create_index("ix_experiment_trials_result", "experiment_trials", ["result"], unique=False)
    op.create_index("ix_experiment_trials_created_at", "experiment_trials", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_experiment_trials_created_at", table_name="experiment_trials")
    op.drop_index("ix_experiment_trials_result", table_name="experiment_trials")
    op.drop_index("ix_experiment_trials_phase", table_name="experiment_trials")
    op.drop_index("ix_experiment_trials_scenario", table_name="experiment_trials")
    op.drop_index("ix_experiment_trials_id", table_name="experiment_trials")
    op.drop_table("experiment_trials")
