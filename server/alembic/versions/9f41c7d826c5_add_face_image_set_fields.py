"""Add face image set fields

Revision ID: 9f41c7d826c5
Revises: 6c8a1f4b9d21
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f41c7d826c5"
down_revision: Union[str, Sequence[str], None] = "6c8a1f4b9d21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("face_embeddings_json", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("face_image_paths_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "face_image_paths_json")
    op.drop_column("users", "face_embeddings_json")
