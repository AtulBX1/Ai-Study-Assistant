"""add chunk page ranges and stable per-document indices

Revision ID: 6a1c9e2d4f70
Revises: 4f8a2b1c9d30
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6a1c9e2d4f70"
down_revision: str | None = "4f8a2b1c9d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "page_start",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "page_end",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "chunk_index",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.drop_column("chunk_index")
        batch_op.drop_column("page_end")
        batch_op.drop_column("page_start")
