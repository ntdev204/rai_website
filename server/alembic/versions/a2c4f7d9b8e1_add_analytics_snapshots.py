"""Add analytics snapshots

Revision ID: a2c4f7d9b8e1
Revises: 9f41c7d826c5
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2c4f7d9b8e1"
down_revision: Union[str, Sequence[str], None] = "9f41c7d826c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("navigation_mode", sa.String(), nullable=True),
        sa.Column("voltage", sa.Float(), nullable=True),
        sa.Column("battery_percent", sa.Float(), nullable=True),
        sa.Column("pos_x", sa.Float(), nullable=True),
        sa.Column("pos_y", sa.Float(), nullable=True),
        sa.Column("yaw", sa.Float(), nullable=True),
        sa.Column("vx", sa.Float(), nullable=True),
        sa.Column("vy", sa.Float(), nullable=True),
        sa.Column("vtheta", sa.Float(), nullable=True),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("ai_mode", sa.String(), nullable=True),
        sa.Column("ai_fps", sa.Float(), nullable=True),
        sa.Column("ai_inference_ms", sa.Float(), nullable=True),
        sa.Column("ai_persons", sa.Integer(), nullable=True),
        sa.Column("ai_obstacles", sa.Integer(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analytics_snapshots_id"), "analytics_snapshots", ["id"], unique=False)
    op.create_index(op.f("ix_analytics_snapshots_connected"), "analytics_snapshots", ["connected"], unique=False)
    op.create_index(op.f("ix_analytics_snapshots_navigation_mode"), "analytics_snapshots", ["navigation_mode"], unique=False)
    op.create_index(op.f("ix_analytics_snapshots_ai_mode"), "analytics_snapshots", ["ai_mode"], unique=False)
    op.create_index(op.f("ix_analytics_snapshots_created_at"), "analytics_snapshots", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_analytics_snapshots_created_at"), table_name="analytics_snapshots")
    op.drop_index(op.f("ix_analytics_snapshots_ai_mode"), table_name="analytics_snapshots")
    op.drop_index(op.f("ix_analytics_snapshots_navigation_mode"), table_name="analytics_snapshots")
    op.drop_index(op.f("ix_analytics_snapshots_connected"), table_name="analytics_snapshots")
    op.drop_index(op.f("ix_analytics_snapshots_id"), table_name="analytics_snapshots")
    op.drop_table("analytics_snapshots")
