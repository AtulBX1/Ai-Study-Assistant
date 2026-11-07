"""Add persistent study plans and scheduled activities."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "13b1_concept_graph_study_plans"
down_revision: str | None = "13a2_document_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create owner-scoped study plan and plan-item tables."""
    op.create_table(
        "study_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("daily_minutes", sa.Integer(), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("omitted_topics", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_study_plans_owner_id", "study_plans", ["owner_id"])
    op.create_table(
        "plan_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("study_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scheduled_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_plan_items_plan_id", "plan_items", ["plan_id"])
    op.create_index("ix_plan_items_document_id", "plan_items", ["document_id"])
    op.create_index(
        "ix_plan_items_plan_date", "plan_items", ["plan_id", "scheduled_date"]
    )


def downgrade() -> None:
    """Drop plan items before their parent plans."""
    op.drop_index("ix_plan_items_plan_date", table_name="plan_items")
    op.drop_index("ix_plan_items_document_id", table_name="plan_items")
    op.drop_index("ix_plan_items_plan_id", table_name="plan_items")
    op.drop_table("plan_items")
    op.drop_index("ix_study_plans_owner_id", table_name="study_plans")
    op.drop_table("study_plans")
