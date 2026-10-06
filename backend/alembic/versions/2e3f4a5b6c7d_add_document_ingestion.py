"""add page-level document ingestion data

Revision ID: 2e3f4a5b6c7d
Revises: b927c5fb9b31
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2e3f4a5b6c7d"
down_revision: str | None = "b927c5fb9b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))
    op.create_table(
        "document_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("headings", sa.JSON(), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column(
            "ocr_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_needed",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "page_number"),
    )
    op.create_index(
        op.f("ix_document_pages_document_id"),
        "document_pages",
        ["document_id"],
        unique=False,
    )
    op.create_table(
        "document_status_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_status_events_document_id"),
        "document_status_events",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_status_events_document_id"),
        table_name="document_status_events",
    )
    op.drop_table("document_status_events")
    op.drop_index(
        op.f("ix_document_pages_document_id"),
        table_name="document_pages",
    )
    op.drop_table("document_pages")
    op.drop_column("documents", "error_message")
    op.drop_column("documents", "progress")
