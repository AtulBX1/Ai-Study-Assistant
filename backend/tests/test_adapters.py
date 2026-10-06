"""Tests for the interchangeable local service adapters."""

import asyncio
from collections.abc import Callable
from io import StringIO
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.config import Settings, get_settings
from app.core.database import create_database_engine, normalize_database_url
from app.services.file_storage import LocalFileStorage
from app.services.job_queue import LocalJobQueue
from app.services.vector_store import create_vector_store


def test_local_job_queue_runs_registered_task() -> None:
    output: list[str] = []
    background_tasks = BackgroundTasks()
    handlers: dict[str, Callable[[str], None]] = {
        "record": output.append,
    }
    queue = LocalJobQueue(background_tasks, handlers)

    queue.enqueue("record", "completed")
    asyncio.run(background_tasks())

    assert output == ["completed"]


def test_local_job_queue_rejects_unknown_tasks() -> None:
    queue = LocalJobQueue(BackgroundTasks(), {})

    with pytest.raises(ValueError, match="Unknown local background task"):
        queue.enqueue("missing")


def test_local_file_storage_round_trips_nested_file(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "storage")

    storage.put("notes/unit-one.txt", b"study notes")

    assert storage.get("notes/unit-one.txt") == b"study notes"
    storage.delete("notes/unit-one.txt")
    assert not (tmp_path / "storage" / "notes" / "unit-one.txt").exists()


def test_local_file_storage_rejects_path_traversal(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "storage")

    with pytest.raises(ValueError, match="within the storage directory"):
        storage.get("../outside.txt")


def test_local_vector_store_persists_and_searches_vectors(tmp_path: Path) -> None:
    settings = Settings(
        backend="local",
        qdrant_local_path=str(tmp_path / "qdrant"),
    )
    vector_store = create_vector_store(settings)
    vector_store.upsert(
        "test-documents",
        ["00000000-0000-0000-0000-000000000001"],
        [[1.0, 0.0]],
        [{"page": 1}],
    )

    matches = vector_store.search("test-documents", [1.0, 0.0])

    assert matches[0].id == "00000000-0000-0000-0000-000000000001"
    assert matches[0].payload == {"page": 1}


def test_local_database_uses_sqlite_engine(tmp_path: Path) -> None:
    database = tmp_path / "db" / "study.db"
    engine = create_database_engine(
        Settings(database_url=f"sqlite:///{database.as_posix()}")
    )
    try:
        assert engine.dialect.name == "sqlite"
        assert database.parent.is_dir()
    finally:
        engine.dispose()


def test_production_rejects_sqlite_database_url() -> None:
    with pytest.raises(ValueError, match="non-SQLite DATABASE_URL"):
        create_database_engine(Settings(backend="prod"))


def test_standard_postgresql_url_selects_psycopg3_driver() -> None:
    url = normalize_database_url("postgresql://localhost/study_assistant")

    assert url.drivername == "postgresql+psycopg"


def test_alembic_migrates_sqlite_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'nested' / 'migration.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        engine = create_engine(database_url)
        try:
            assert inspect(engine).has_table("alembic_version")
            assert (tmp_path / "nested").is_dir()
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


def test_alembic_generates_postgresql_offline_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/study_assistant",
    )
    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        output = StringIO()
        config.output_buffer = output
        command.upgrade(config, "head", sql=True)

        assert "CREATE TABLE alembic_version" in output.getvalue()
    finally:
        get_settings.cache_clear()
