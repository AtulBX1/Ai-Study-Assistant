"""Exercise the real Alembic history against file-backed SQLite databases."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from alembic import command
from app.core.config import get_settings
from app.core.database import Base
from app.main import _upgrade_local_database


def _upgrade(path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    get_settings.cache_clear()


def test_full_migration_chain_creates_model_schema(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "fresh.sqlite"
    _upgrade(database, monkeypatch)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        inspector = inspect(engine)
        assert set(Base.metadata.tables).issubset(set(inspector.get_table_names()))
        for table_name, model_table in Base.metadata.tables.items():
            actual_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            assert {column.name for column in model_table.columns} <= actual_columns
    finally:
        engine.dispose()


def test_local_startup_upgrade_migrates_an_empty_database(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "startup.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    revision = _upgrade_local_database(f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        assert revision not in {"", "base"}
        assert "alembic_version" in inspect(engine).get_table_names()
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        assert len(command.ScriptDirectory.from_config(config).get_heads()) == 1
    finally:
        engine.dispose()


def test_migration_chain_recovers_when_syllabus_tables_exist(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "partial.sqlite"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        # Build the migration's objects first, as happens after a failed DDL run.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE syllabi (id INTEGER PRIMARY KEY, "
                "owner_id INTEGER NOT NULL, title VARCHAR(255) NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE syllabus_topics (id INTEGER PRIMARY KEY, "
                "syllabus_id INTEGER NOT NULL, parent_id INTEGER, "
                'title VARCHAR(255) NOT NULL, "order" INTEGER NOT NULL DEFAULT 0, '
                "keywords JSON NOT NULL, sub_topics JSON NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE chunk_topics (id INTEGER PRIMARY KEY, "
                "chunk_id INTEGER NOT NULL, topic_id INTEGER NOT NULL, "
                "score FLOAT NOT NULL DEFAULT 0, "
                "source VARCHAR(16) NOT NULL DEFAULT 'auto', "
                "page_start INTEGER, page_end INTEGER)"
            )
    finally:
        engine.dispose()
    _upgrade(database, monkeypatch)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        assert {"syllabi", "syllabus_topics", "chunk_topics"}.issubset(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()
