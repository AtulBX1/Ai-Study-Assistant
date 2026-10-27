"""add chat grounding and explanation details

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add structured grounding diagnostics to every persisted message."""
    op.add_column(
        "messages",
        sa.Column(
            "unsupported_sentences", sa.JSON(), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "messages",
        sa.Column("explanation", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    """Remove message grounding explanations."""
    op.drop_column("messages", "explanation")
    op.drop_column("messages", "unsupported_sentences")
