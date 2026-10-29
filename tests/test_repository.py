"""Verifica integridade real do SQLite e rollback do contexto transacional."""

import sqlite3
from pathlib import Path

import pytest

from app.database.connection import initialize_database
from app.database.repository import StudyRepository


def test_pragmas_and_idempotent_initialization(tmp_path: Path) -> None:
    for _ in range(2):
        database = initialize_database(tmp_path / "estudos.db")
        try:
            assert database.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert database.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert database.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert database.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        finally:
            database.close()


def test_only_one_pending_session(connection: sqlite3.Connection) -> None:
    repository = StudyRepository(connection)
    with repository.transaction() as database:
        database.execute(
            "INSERT INTO sessions (name, created_at, status) VALUES (?, ?, ?)",
            ("Estudo livre", 1000, "paused"),
        )
    with pytest.raises(sqlite3.IntegrityError), repository.transaction() as database:
        database.execute(
            "INSERT INTO sessions (name, created_at, status) VALUES (?, ?, ?)",
            ("Outra sessão", 2000, "paused"),
        )
    assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_invalid_final_state_rolls_back_whole_transaction(connection: sqlite3.Connection) -> None:
    repository = StudyRepository(connection)
    with pytest.raises(sqlite3.IntegrityError), repository.transaction() as database:
        database.execute(
            "INSERT INTO sessions (name, created_at, status) VALUES (?, ?, ?)",
            ("Estudo livre", 1000, "running"),
        )
    assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert not connection.in_transaction


def test_running_to_paused_requires_closing_interval(connection: sqlite3.Connection) -> None:
    repository = StudyRepository(connection)
    with repository.transaction() as database:
        database.execute("INSERT INTO sessions VALUES (1, 'Estudo livre', 1000, NULL, 'paused')")
        database.execute("INSERT INTO study_intervals VALUES (1, 1, 1000, 1000, NULL)")
        database.execute("UPDATE sessions SET status = 'running' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError), repository.transaction() as database:
        database.execute("UPDATE sessions SET status = 'paused' WHERE id = 1")
    assert connection.execute("SELECT status FROM sessions").fetchone()[0] == "running"
    with repository.transaction() as database:
        database.execute("UPDATE study_intervals SET last_seen_at = 1035, ended_at = 1035")
        database.execute("UPDATE sessions SET status = 'paused' WHERE id = 1")


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO study_intervals VALUES (1, 999, 1000, 1000, NULL)",
        "INSERT INTO study_intervals VALUES (1, 1, 1000, 999, NULL)",
        "INSERT INTO study_intervals VALUES (1, 1, 1000, 1001, 1000)",
        "INSERT INTO sessions VALUES (2, ' ', 1000, 1000, 'finished')",
        "INSERT INTO sessions VALUES (2, 'Inválida', 1000, NULL, 'finished')",
    ],
)
def test_invalid_rows_are_rejected(connection: sqlite3.Connection, statement: str) -> None:
    connection.execute("INSERT INTO sessions VALUES (1, 'Estudo livre', 1000, NULL, 'paused')")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(statement)
