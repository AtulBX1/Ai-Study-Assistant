"""Add quiz routing, source page, topic, and quality report metadata."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quizzes",
        sa.Column("engine", sa.String(16), nullable=False, server_default="classic"),
    )
    op.add_column(
        "quizzes",
        sa.Column("generation_report", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "questions",
        sa.Column("engine", sa.String(16), nullable=False, server_default="classic"),
    )
    op.add_column(
        "questions",
        sa.Column("topic", sa.String(255), nullable=False, server_default="General"),
    )
    op.add_column(
        "questions", sa.Column("page", sa.Integer(), nullable=False, server_default="1")
    )


def downgrade() -> None:
    op.drop_column("questions", "page")
    op.drop_column("questions", "topic")
    op.drop_column("questions", "engine")
    op.drop_column("quizzes", "generation_report")
    op.drop_column("quizzes", "engine")
