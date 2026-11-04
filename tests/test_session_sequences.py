"""Sequências determinísticas verificadas contra um modelo independente."""

import random
import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.database.repository import StudyRepository
from app.models import HistorySelection, PauseReason, ReportPeriod, SessionStatus, StudyColor
from app.services.clock_service import ClockService
from app.services.report_service import ReportService
from app.services.timer_service import TimerService
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_recovery import deny_commit


@pytest.mark.parametrize("seed", [7, 41, 997])
def test_generated_session_sequences_preserve_model_totals(
    connection: sqlite3.Connection,
    seed: int,
) -> None:
    rng = random.Random(seed)
    repository = StudyRepository(connection)
    kind = repository.create_study_type("Tipo sintético", StudyColor.BLUE)
    source = FakeClock(wall_time_s=datetime(2024, 5, 10, 12, tzinfo=UTC).timestamp())
    timer = TimerService(repository, ClockService(source))
    reports = ReportService(repository, lambda: UTC)
    finished: dict[int, int] = {}
    state = "idle"
    pending_id: int | None = None
    closed_s = 0
    active_ns = 0

    def check_model() -> None:
        repository.validate_invariants()
        stored_sessions = [
            (row[0], row[1])
            for row in connection.execute("SELECT id,status FROM sessions ORDER BY id")
        ]
        expected_sessions = [(session_id, "finished") for session_id in finished]
        if pending_id is not None:
            expected_sessions.append((pending_id, state))
        assert stored_sessions == sorted(expected_sessions)
        open_sessions = [
            row[0]
            for row in connection.execute(
                "SELECT session_id FROM study_intervals WHERE ended_at IS NULL ORDER BY id"
            )
        ]
        assert open_sessions == ([pending_id] if state == "running" else [])
        pending = timer.get_active_session()
        if state == "idle":
            assert pending is None and timer.get_elapsed_seconds() == 0
        else:
            assert pending is not None and pending.id == pending_id
            assert pending.study_type_id == kind.id
            expected_status = SessionStatus.RUNNING if state == "running" else SessionStatus.PAUSED
            assert pending.status == expected_status
            assert timer.is_running == (state == "running")
            assert timer.get_elapsed_seconds() == closed_s + active_ns // SECOND_NS
        for session_id, total in finished.items():
            persisted = connection.execute(
                "SELECT SUM(ended_at-started_at) FROM study_intervals WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            assert persisted == total
        report = reports.get_period_report(
            HistorySelection(ReportPeriod.MONTH, date(2024, 5, 10)), timer.get_snapshot()
        )
        assert report.total_s == sum(finished.values()) + closed_s + active_ns // SECOND_NS
        assert sum(bucket.duration_s for bucket in report.buckets) == report.total_s

    for _ in range(80):
        choices = {
            "idle": ["start", "invalid", "query"],
            "running": ["study", "study", "pause", "finish", "heartbeat", "invalid", "query"],
            "paused": ["wait", "resume", "finish", "invalid", "query"],
        }
        action = rng.choice(choices[state])
        if action == "start":
            session = timer.start_session("Sessão sintética", kind.id)
            pending_id = session.id
            state = "running"
        elif action == "study":
            duration = rng.choice([249_999_999, 250_000_001, 750_000_000, 1_250_000_000])
            source.advance(duration)
            timer.tick()
            active_ns += duration
        elif action == "pause":
            timer.pause_session(PauseReason.USER)
            closed_s += active_ns // SECOND_NS
            active_ns = 0
            state = "paused"
        elif action == "resume":
            timer.resume_session()
            state = "running"
        elif action == "finish":
            assert pending_id is not None
            timer.finish_session()
            finished[pending_id] = closed_s + active_ns // SECOND_NS
            pending_id, closed_s, active_ns, state = None, 0, 0, "idle"
        elif action == "wait":
            source.advance(3600 * SECOND_NS)
        elif action == "heartbeat":
            timer.heartbeat()
        elif action == "invalid":
            before = connection.total_changes
            with pytest.raises(RuntimeError):
                if state == "idle":
                    timer.finish_session()
                else:
                    timer.start_session("Sobreposição inválida", kind.id)
            assert connection.total_changes == before
        check_model()
    if state != "idle":
        assert pending_id is not None
        timer.finish_session()
        finished[pending_id] = closed_s + active_ns // SECOND_NS
        pending_id, closed_s, active_ns, state = None, 0, 0, "idle"
    check_model()


@pytest.mark.parametrize("operation", ["pause", "finish", "heartbeat"])
def test_failed_commit_retry_keeps_the_frozen_model_cut(
    connection: sqlite3.Connection,
    operation: str,
) -> None:
    repository = StudyRepository(connection)
    kind = repository.create_study_type("Falha sintética", StudyColor.TEAL)
    source = FakeClock()
    clock = ClockService(source)
    timer = TimerService(repository, clock)
    session = timer.start_session("Repetição segura", kind.id)
    for _ in range(11):
        source.advance(250_000_000)
        timer.tick()
    cut = 2  # Onze quartos de segundo são 2,75 s; o intervalo trunca uma vez.

    def command() -> None:
        if operation == "pause":
            timer.pause_session(PauseReason.USER)
        elif operation == "finish":
            timer.finish_session()
        else:
            timer.heartbeat()

    connection.set_authorizer(deny_commit)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            command()
    finally:
        connection.set_authorizer(None)
    assert timer.persistence_failed and not timer.is_running
    source.advance(3600 * SECOND_NS)
    reads = source.read_count
    for _ in range(3):
        assert timer.get_elapsed_seconds() == cut
        assert timer.persistence_failed
    command()
    assert source.read_count == reads and not timer.persistence_failed
    repository.validate_invariants()
    total = connection.execute(
        "SELECT SUM(ended_at-started_at) FROM study_intervals WHERE session_id=?",
        (session.id,),
    ).fetchone()[0]
    assert total == cut
    saved = repository.get_session(session.id)
    assert saved is not None and saved.study_type_id == kind.id
    assert saved.status == (
        SessionStatus.FINISHED if operation == "finish" else SessionStatus.PAUSED
    )
