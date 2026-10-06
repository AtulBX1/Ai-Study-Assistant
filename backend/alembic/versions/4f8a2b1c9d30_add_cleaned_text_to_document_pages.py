"""add normalized text to extracted document pages

Revision ID: 4f8a2b1c9d30
Revises: 2e3f4a5b6c7d
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4f8a2b1c9d30"
down_revision: str | None = "2e3f4a5b6c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("cleaned_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_pages", "cleaned_text")
