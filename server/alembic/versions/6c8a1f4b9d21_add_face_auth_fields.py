"""Add face auth fields

Revision ID: 6c8a1f4b9d21
Revises: f0fa067cf666
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6c8a1f4b9d21"
down_revision: Union[str, Sequence[str], None] = "f0fa067cf666"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("face_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("face_embedding_json", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("face_registered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_users_face_id"), "users", ["face_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_face_id"), table_name="users")
    op.drop_column("users", "face_registered_at")
    op.drop_column("users", "face_embedding_json")
    op.drop_column("users", "face_id")
