"""Add grounded glossary entries and SM-2 review history."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "13a1_study_flashcards_glossary"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend flashcards and add glossary and review-log tables."""
    with op.batch_alter_table("flashcards") as batch_op:
        batch_op.add_column(sa.Column("document_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_page", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("evidence_sentence", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("fact_key", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "suspended",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_foreign_key(
            "fk_flashcards_document_id_documents",
            "documents",
            ["document_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_flashcards_document_id", "flashcards", ["document_id"])
    op.create_index(
        "uq_flashcards_owner_document_fact",
        "flashcards",
        ["owner_id", "document_id", "fact_key"],
        unique=True,
    )
    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(length=255), nullable=False),
        sa.Column("term_key", sa.String(length=255), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("evidence_sentence", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "owner_id", "document_id", "term_key", name="uq_glossary_owner_doc_term"
        ),
    )
    op.create_index("ix_glossary_terms_owner_id", "glossary_terms", ["owner_id"])
    op.create_index("ix_glossary_terms_document_id", "glossary_terms", ["document_id"])
    op.create_table(
        "review_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "flashcard_id",
            sa.Integer(),
            sa.ForeignKey("flashcards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_review_log_flashcard_id",
        "review_log",
        ["flashcard_id"],
    )
    op.create_index(
        "ix_review_log_owner_id",
        "review_log",
        ["owner_id"],
    )


def downgrade() -> None:
    """Remove glossary/review data and the added flashcard columns."""
    op.drop_index("ix_review_log_owner_id", table_name="review_log")
    op.drop_index("ix_review_log_flashcard_id", table_name="review_log")
    op.drop_table("review_log")
    op.drop_index("ix_glossary_terms_document_id", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_owner_id", table_name="glossary_terms")
    op.drop_table("glossary_terms")
    op.drop_index("uq_flashcards_owner_document_fact", table_name="flashcards")
    op.drop_index("ix_flashcards_document_id", table_name="flashcards")
    with op.batch_alter_table("flashcards") as batch_op:
        batch_op.drop_constraint(
            "fk_flashcards_document_id_documents",
            type_="foreignkey",
        )
        batch_op.drop_column("suspended")
        batch_op.drop_column("fact_key")
        batch_op.drop_column("evidence_sentence")
        batch_op.drop_column("source_page")
        batch_op.drop_column("document_id")
