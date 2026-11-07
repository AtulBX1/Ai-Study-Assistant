"""Add document summaries table for Step 13a-2."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "13a2_document_summaries"
down_revision: str | None = "13a1_study_flashcards_glossary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create document_summaries table and associated indices."""
    op.create_table(
        "document_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "summary_type",
            sa.String(length=32),
            nullable=False,
            server_default="short",
        ),
        sa.Column(
            "engine_requested",
            sa.String(length=32),
            nullable=False,
            server_default="extractive",
        ),
        sa.Column(
            "engine_used",
            sa.String(length=32),
            nullable=False,
            server_default="extractive",
        ),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("generation_metadata", sa.JSON(), nullable=False),
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
    op.create_index(
        "ix_document_summaries_document_id",
        "document_summaries",
        ["document_id"],
    )
    op.create_index(
        "ix_document_summaries_owner_id",
        "document_summaries",
        ["owner_id"],
    )
    op.create_index(
        "ix_document_summaries_created_at",
        "document_summaries",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop document_summaries table."""
    op.drop_index("ix_document_summaries_created_at", table_name="document_summaries")
    op.drop_index("ix_document_summaries_owner_id", table_name="document_summaries")
    op.drop_index("ix_document_summaries_document_id", table_name="document_summaries")
    op.drop_table("document_summaries")
