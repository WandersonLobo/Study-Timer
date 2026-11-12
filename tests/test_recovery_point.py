"""Regressões de recuperação pelo arquivo externo ao SQLite."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.database.recovery_point import RecoveryPoint
from app.database.repository import StudyRepository
from app.models import ClockSnapshot, SessionStatus


def test_recovery_point_is_applied_once(connection: sqlite3.Connection, tmp_path: Path) -> None:
    repository = StudyRepository(connection)
    session, interval = repository.start_session("Estudo", 1000)
    snapshot = ClockSnapshot(interval.id, 1000, 7, 1007)
    with ThreadPoolExecutor(max_workers=1) as worker:
        point = RecoveryPoint(tmp_path / "recovery-point.pending", worker)
        point.submit(snapshot)

    assert repository.get_open_interval(session.id) == interval
    assert point.read() == snapshot
    recovered = repository.recover_pending(point.read())
    assert recovered is not None and recovered.status == SessionStatus.PAUSED
    assert repository.recover_pending(point.read()) == recovered
    closed = repository.get_session_intervals(session.id)
    assert len(closed) == 1 and closed[0].ended_at == closed[0].last_seen_at == 1007

    _, resumed = repository.resume_session(session.id, 1020)
    repository.recover_pending(point.read())
    assert repository.get_session_intervals(session.id)[-1].ended_at == resumed.started_at


def test_incomplete_file_preserves_sqlite_checkpoint(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    repository = StudyRepository(connection)
    session, interval = repository.start_session("Estudo", 1000)
    repository.save_checkpoint(session.id, ClockSnapshot(interval.id, 1000, 3, 1003))
    path = tmp_path / "recovery-point.pending"
    path.write_text("[1, 1000,", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=1) as worker:
        point = RecoveryPoint(path, worker)
        assert point.read() is None
        repository.recover_pending(point.read())
    assert repository.get_session_intervals(session.id)[0].ended_at == 1003
