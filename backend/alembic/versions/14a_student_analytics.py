"""Persist topic accuracy and the learner's timezone."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "14a_student_analytics"
down_revision: str | None = "13b1_concept_graph_study_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add analytics fields while preserving existing topic statistics."""
    op.execute(
        "UPDATE quiz_attempts SET completed_at = started_at "
        "WHERE score IS NOT NULL AND completed_at IS NULL"
    )
    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="UTC",
        ),
    )
    op.add_column(
        "topic_stats",
        sa.Column("accuracy", sa.Float(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE topic_stats "
        "SET accuracy = CASE WHEN attempts > 0 "
        "THEN CAST(correct AS FLOAT) / attempts ELSE 0 END"
    )
    op.add_column(
        "topic_stats",
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE topic_stats SET last_seen = updated_at")
    with op.batch_alter_table("topic_stats") as batch_op:
        batch_op.alter_column(
            "last_seen",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )


def downgrade() -> None:
    """Remove fields introduced for student analytics."""
    with op.batch_alter_table("topic_stats") as batch_op:
        batch_op.drop_column("last_seen")
        batch_op.drop_column("accuracy")
    op.drop_column("users", "timezone")
