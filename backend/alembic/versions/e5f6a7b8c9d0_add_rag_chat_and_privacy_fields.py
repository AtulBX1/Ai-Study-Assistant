"""add rag chat and privacy fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_private to documents and provider/latency/feedback_reason to messages."""
    op.add_column(
        "documents",
        sa.Column(
            "is_private",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "messages",
        sa.Column("provider", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("latency_ms", sa.Float(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("feedback_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove rag chat and privacy columns."""
    op.drop_column("messages", "feedback_reason")
    op.drop_column("messages", "latency_ms")
    op.drop_column("messages", "provider")
    op.drop_column("documents", "is_private")
