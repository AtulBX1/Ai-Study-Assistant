"""Initial empty revision for the application scaffold.

Revision ID: 0001_initial_empty
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

revision: str = "0001_initial_empty"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reserve the initial migration point for future application tables."""
    pass


def downgrade() -> None:
    """Revert the initial empty revision."""
    pass
