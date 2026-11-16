"""Persist labelled optional web sources on syllabi."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "16_web_sources"
down_revision: str | Sequence[str] | None = "15c_syllabus_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "syllabi",
        sa.Column("web_sources", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("syllabi", "web_sources")
