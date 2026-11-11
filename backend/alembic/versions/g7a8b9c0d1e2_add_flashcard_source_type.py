"""add flashcard source type

Revision ID: g7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "g7a8b9c0d1e2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the document source that produced each flashcard."""
    columns = (
        set()
        if context.is_offline_mode()
        else {
            item["name"] for item in sa.inspect(op.get_bind()).get_columns("flashcards")
        }
    )
    if "source_type" not in columns:
        with op.batch_alter_table("flashcards", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "source_type",
                    sa.String(length=32),
                    nullable=False,
                    server_default="glossary",
                )
            )


def downgrade() -> None:
    """Remove flashcard source metadata."""
    op.drop_column("flashcards", "source_type")
