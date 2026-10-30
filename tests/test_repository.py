"""Verifica integridade real do SQLite e rollback do contexto transacional."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.models import ClockSnapshot, SessionStatus


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


@pytest.mark.parametrize("operation", ["pause", "checkpoint"])
@pytest.mark.parametrize("invalid_part", ["identity", "anchor", "negative", "end", "checkpoint"])
def test_stale_or_inconsistent_snapshot_never_updates_an_interval(
    connection: sqlite3.Connection, invalid_part: str, operation: str
) -> None:
    repository = StudyRepository(connection)
    session, interval = repository.start_session("Snapshot validado", 1000)
    snapshot = ClockSnapshot(interval.id, interval.started_at, 1, interval.started_at + 1)
    if invalid_part == "identity":
        snapshot = replace(snapshot, interval_id=interval.id + 1)
    elif invalid_part == "anchor":
        snapshot = replace(snapshot, started_at=999)
    elif invalid_part == "negative":
        snapshot = replace(snapshot, elapsed_s=-1, valid_until_utc_s=999)
    elif invalid_part == "end":
        snapshot = replace(snapshot, valid_until_utc_s=1005)
    else:
        connection.execute(
            "UPDATE study_intervals SET last_seen_at = ? WHERE id = ?", (1002, interval.id)
        )
    previous = repository.get_open_interval(session.id)
    with pytest.raises(ValueError):
        if operation == "pause":
            repository.pause_session(session.id, snapshot)
        else:
            repository.save_checkpoint(session.id, snapshot)
    assert repository.get_session(session.id) == session
    assert repository.get_open_interval(session.id) == previous
    assert not connection.in_transaction


def test_finish_requires_snapshot_only_for_running_sessions(connection: sqlite3.Connection) -> None:
    repository = StudyRepository(connection)
    session, interval = repository.start_session("Estado e snapshot", 1000)
    snapshot = ClockSnapshot(interval.id, 1000, 0, 1000)
    with pytest.raises(ValueError):
        repository.finish_session(session.id)
    paused = repository.pause_session(session.id, snapshot)
    with pytest.raises(ValueError):
        repository.finish_session(session.id, snapshot)
    assert repository.get_session(session.id) == paused
    finished = repository.finish_session(session.id)
    assert finished.status == SessionStatus.FINISHED
    with pytest.raises(RuntimeError):
        repository.resume_session(session.id, 2000)
    with pytest.raises(RuntimeError):
        repository.finish_session(session.id)


def test_repository_validates_names_when_called_directly(connection: sqlite3.Connection) -> None:
    repository = StudyRepository(connection)
    with pytest.raises(ValueError):
        repository.start_session("x" * 121, 1000)
    assert repository.get_pending_session() is None
    session, _ = repository.start_session(" \x00\n ", 1000)
    assert session.name == "Estudo livre"


def test_checkpoint_is_repeatable_and_only_updates_the_open_interval(
    connection: sqlite3.Connection,
) -> None:
    repository = StudyRepository(connection)
    session, first = repository.start_session("Dois intervalos", 1000)
    repository.pause_session(session.id, ClockSnapshot(first.id, 1000, 3, 1003))
    _, second = repository.resume_session(session.id, 2000)
    snapshot = ClockSnapshot(second.id, 2000, 5, 2005)
    for _ in range(2):
        repository.save_checkpoint(session.id, snapshot)
    intervals = repository.get_session_intervals(session.id)
    assert intervals[0].ended_at == intervals[0].last_seen_at == 1003
    assert intervals[1].last_seen_at == 2005 and intervals[1].ended_at is None
    assert repository.get_session(session.id) == session
    assert not connection.in_transaction


def test_checkpoint_requires_a_running_session(connection: sqlite3.Connection) -> None:
    repository = StudyRepository(connection)
    session, interval = repository.start_session("Estado do checkpoint", 1000)
    snapshot = ClockSnapshot(interval.id, 1000, 0, 1000)
    repository.pause_session(session.id, snapshot)
    with pytest.raises(RuntimeError):
        repository.save_checkpoint(session.id, snapshot)
    repository.finish_session(session.id)
    with pytest.raises(RuntimeError):
        repository.save_checkpoint(session.id, snapshot)
