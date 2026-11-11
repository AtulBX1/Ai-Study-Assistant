"""Add owner private syllabi and chunk mappings."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "15c_syllabus_mapping"
down_revision: str | Sequence[str] | None = (
    "g7a8b9c0d1e2",
    "14b_public_tests_and_handles",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    if context.is_offline_mode():
        return set()
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    if context.is_offline_mode():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _create_index(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns)


def upgrade() -> None:
    if "syllabi" not in _tables():
        op.create_table(
            "syllabi",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "owner_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index("ix_syllabi_owner_id", "syllabi", ["owner_id"])
    if "syllabus_topics" not in _tables():
        op.create_table(
            "syllabus_topics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "syllabus_id",
                sa.Integer(),
                sa.ForeignKey("syllabi.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "parent_id",
                sa.Integer(),
                sa.ForeignKey("syllabus_topics.id", ondelete="CASCADE"),
            ),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("keywords", sa.JSON(), nullable=False),
            sa.Column("sub_topics", sa.JSON(), nullable=False),
        )
    _create_index("ix_syllabus_topics_syllabus_id", "syllabus_topics", ["syllabus_id"])
    _create_index("ix_syllabus_topics_parent_id", "syllabus_topics", ["parent_id"])
    if "chunk_topics" not in _tables():
        op.create_table(
            "chunk_topics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "chunk_id",
                sa.Integer(),
                sa.ForeignKey("chunks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "topic_id",
                sa.Integer(),
                sa.ForeignKey("syllabus_topics.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("source", sa.String(16), nullable=False, server_default="auto"),
            sa.Column("page_start", sa.Integer()),
            sa.Column("page_end", sa.Integer()),
            sa.UniqueConstraint("chunk_id", "topic_id"),
        )
    _create_index("ix_chunk_topics_chunk_id", "chunk_topics", ["chunk_id"])
    _create_index("ix_chunk_topics_topic_id", "chunk_topics", ["topic_id"])

    columns = (
        set()
        if context.is_offline_mode()
        else {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("questions")
        }
    )
    if "syllabus_topic_id" not in columns:
        with op.batch_alter_table("questions", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("syllabus_topic_id", sa.Integer(), nullable=True)
            )
    foreign_keys = (
        set()
        if context.is_offline_mode()
        else {
            item.get("name")
            for item in sa.inspect(op.get_bind()).get_foreign_keys("questions")
        }
    )
    if "fk_questions_syllabus_topic_id_syllabus_topics" not in foreign_keys:
        with op.batch_alter_table("questions", schema=None) as batch_op:
            batch_op.create_foreign_key(
                "fk_questions_syllabus_topic_id_syllabus_topics",
                "syllabus_topics",
                ["syllabus_topic_id"],
                ["id"],
                ondelete="SET NULL",
            )
    _create_index("ix_questions_syllabus_topic_id", "questions", ["syllabus_topic_id"])


def downgrade() -> None:
    op.drop_index("ix_questions_syllabus_topic_id", table_name="questions")
    with op.batch_alter_table("questions", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_questions_syllabus_topic_id_syllabus_topics", type_="foreignkey"
        )
        batch_op.drop_column("syllabus_topic_id")
    op.drop_table("chunk_topics")
    op.drop_table("syllabus_topics")
    op.drop_table("syllabi")
