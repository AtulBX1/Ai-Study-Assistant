"""persist model-based difficulty labels on document chunks

Revision ID: c8d2f1a6b903
Revises: 6a1c9e2d4f70
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8d2f1a6b903"
down_revision: str | None = "6a1c9e2d4f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable difficulty prediction fields to existing chunks."""
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.add_column(sa.Column("difficulty_label", sa.String(16), nullable=True))
        batch_op.add_column(
            sa.Column("difficulty_confidence", sa.Float(), nullable=True)
        )
        batch_op.add_column(sa.Column("difficulty_model", sa.String(32), nullable=True))


def downgrade() -> None:
    """Remove difficulty predictions while preserving chunk rows."""
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.drop_column("difficulty_model")
        batch_op.drop_column("difficulty_confidence")
        batch_op.drop_column("difficulty_label")
