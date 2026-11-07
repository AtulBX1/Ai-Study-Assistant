"""Add public test snapshots and anonymous handles; remove teacher classes."""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "14b_public_tests_and_handles"
down_revision: str | None = "14a_student_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create public test storage and remove the unused teacher schema."""
    op.drop_index("ix_class_members_student_id", table_name="class_members")
    op.drop_index("ix_class_members_class_id", table_name="class_members")
    op.drop_table("class_members")
    op.drop_index("ix_class_assignments_class_id", table_name="class_assignments")
    op.drop_table("class_assignments")
    op.drop_index("ix_classes_teacher_id", table_name="classes")
    op.drop_table("classes")

    op.add_column(
        "users",
        sa.Column("public_handle", sa.String(length=20), nullable=True),
    )
    if context.is_offline_mode():
        op.execute(
            sa.text(
                "WITH generated_handles AS ("
                "SELECT id, 'learner-' || "
                "lpad(row_number() OVER (ORDER BY id)::text, 12, '0') "
                "AS public_handle FROM users"
                ") UPDATE users AS user_row "
                "SET public_handle = generated_handles.public_handle "
                "FROM generated_handles WHERE user_row.id = generated_handles.id"
            )
        )
    else:
        connection = op.get_bind()
        user_ids = list(connection.execute(sa.text("SELECT id FROM users")).scalars())
        used_handles: set[str] = set()
        for user_id in user_ids:
            handle = f"learner-{secrets.token_hex(4)}"
            while handle.casefold() in used_handles:
                handle = f"learner-{secrets.token_hex(4)}"
            used_handles.add(handle.casefold())
            connection.execute(
                sa.text("UPDATE users SET public_handle = :handle WHERE id = :user_id"),
                {"handle": handle, "user_id": user_id},
            )
    op.add_column(
        "users",
        sa.Column(
            "show_on_leaderboards",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("public_handle_changed_at", sa.DateTime(timezone=True)),
    )
    op.execute("UPDATE users SET role = 'student' WHERE role = 'teacher'")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("user_role", type_="check")
        batch_op.alter_column(
            "public_handle",
            existing_type=sa.String(length=20),
            nullable=False,
        )
        batch_op.alter_column(
            "role",
            existing_type=sa.Enum(
                "student",
                "teacher",
                "admin",
                name="user_role",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.String(length=7),
            existing_nullable=False,
        )
        batch_op.create_check_constraint("user_role", "role IN ('student', 'admin')")
    op.execute(
        "CREATE UNIQUE INDEX uq_users_public_handle_lower "
        "ON users (lower(public_handle))"
    )
    op.add_column(
        "quizzes",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "public_tests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("subject", sa.String(length=120), nullable=False),
        sa.Column("topic_labels", sa.JSON(), nullable=False),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("source_quiz_id", sa.Integer()),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_quiz_id"], ["quizzes.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_public_tests_status", "public_tests", ["status"])
    op.create_index("ix_public_tests_subject", "public_tests", ["subject"])
    op.create_table(
        "public_test_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("shuffled_order", sa.JSON(), nullable=False),
        sa.Column("saved_answers", sa.JSON(), nullable=False),
        sa.Column("graded_answers", sa.JSON(), nullable=False),
        sa.Column("score_percent", sa.Float()),
        sa.Column("correct_count", sa.Integer()),
        sa.Column("elapsed_seconds", sa.Integer()),
        sa.Column("is_first_completed", sa.Boolean(), nullable=False),
        sa.Column("is_suspicious", sa.Boolean(), nullable=False),
        sa.Column("is_late", sa.Boolean(), nullable=False),
        sa.Column("submission_token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["test_id"], ["public_tests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("submission_token_hash"),
    )
    op.create_index(
        "ix_public_test_attempts_test_id", "public_test_attempts", ["test_id"]
    )
    op.create_index(
        "ix_public_test_attempts_user_id", "public_test_attempts", ["user_id"]
    )
    op.create_index(
        "ix_public_test_attempts_pool",
        "public_test_attempts",
        ["test_id", "completed_at"],
    )
    op.create_table(
        "public_test_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["test_id"], ["public_tests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("test_id", "reporter_id"),
    )
    op.create_index(
        "ix_public_test_reports_test_id", "public_test_reports", ["test_id"]
    )
    op.create_index(
        "ix_public_test_reports_reporter_id", "public_test_reports", ["reporter_id"]
    )


def downgrade() -> None:
    """Remove public test data and restore the legacy teacher schema."""
    op.drop_index(
        "ix_public_test_reports_reporter_id", table_name="public_test_reports"
    )
    op.drop_index("ix_public_test_reports_test_id", table_name="public_test_reports")
    op.drop_table("public_test_reports")
    op.drop_index("ix_public_test_attempts_pool", table_name="public_test_attempts")
    op.drop_index("ix_public_test_attempts_user_id", table_name="public_test_attempts")
    op.drop_index("ix_public_test_attempts_test_id", table_name="public_test_attempts")
    op.drop_table("public_test_attempts")
    op.drop_index("ix_public_tests_subject", table_name="public_tests")
    op.drop_index("ix_public_tests_status", table_name="public_tests")
    op.drop_table("public_tests")
    op.drop_column("quizzes", "is_demo")
    op.drop_index("uq_users_public_handle_lower", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("user_role", type_="check")
        batch_op.alter_column(
            "role",
            existing_type=sa.Enum(
                "student",
                "admin",
                name="user_role",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.String(length=7),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "user_role", "role IN ('student', 'teacher', 'admin')"
        )
        batch_op.drop_column("public_handle_changed_at")
        batch_op.drop_column("show_on_leaderboards")
        batch_op.drop_column("public_handle")
        batch_op.drop_column("is_demo")
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_classes_teacher_id", "classes", ["teacher_id"])
    op.create_table(
        "class_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("class_id", "student_id"),
    )
    op.create_index("ix_class_members_class_id", "class_members", ["class_id"])
    op.create_index("ix_class_members_student_id", "class_members", ["student_id"])
    op.create_table(
        "class_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("instructions", sa.Text()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_class_assignments_class_id", "class_assignments", ["class_id"])
