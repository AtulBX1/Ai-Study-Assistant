"""persist named entities and keyphrases for document glossaries

Revision ID: d4e5f6a7b8c9
Revises: c8d2f1a6b903
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c8d2f1a6b903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create an owner-scoped document key-term table."""
    op.create_table(
        "document_key_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
    )
    op.create_index(
        "ix_document_key_terms_document_id",
        "document_key_terms",
        ["document_id"],
    )


def downgrade() -> None:
    """Drop the generated document key-term table."""
    op.drop_index("ix_document_key_terms_document_id", table_name="document_key_terms")
    op.drop_table("document_key_terms")
