"""Ciclo real de sessões em SQLite temporário com relógios determinísticos."""

import sqlite3
from pathlib import Path

import pytest

from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.models import PauseReason, Session, SessionStatus
from app.services.clock_service import ClockService
from app.services.timer_service import TimerService
from tests.test_clock import SECOND_NS, FakeClock


@pytest.fixture
def source() -> FakeClock:
    return FakeClock()


@pytest.fixture
def clock(source: FakeClock) -> ClockService:
    return ClockService(source)


@pytest.fixture
def repository(connection: sqlite3.Connection) -> StudyRepository:
    return StudyRepository(connection)


@pytest.fixture
def timer(repository: StudyRepository, clock: ClockService) -> TimerService:
    return TimerService(repository, clock)


def advance_study(clock: ClockService, source: FakeClock, duration_ns: int) -> None:
    """Simula callbacks frequentes sem confundir estudo válido com uma lacuna."""
    while duration_ns > 0:
        delta = min(duration_ns, 250_000_000)
        source.advance(delta)
        clock.tick()
        duration_ns -= delta


def completed_seconds(repository: StudyRepository, session_id: int) -> int:
    """Soma apenas intervalos confirmados, sem depender do serviço de relatórios."""
    return sum(
        interval.ended_at - interval.started_at
        for interval in repository.get_session_intervals(session_id)
        if interval.ended_at is not None
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("", "Estudo livre"),
        (" \t\n\x00 ", "Estudo livre"),
        ("  Matemática  ", "Matemática"),
        ("A\x00\nB\u202e", "AB"),
        ("x" * 120, "x" * 120),
        ("Robert'); DROP TABLE sessions;--", "Robert'); DROP TABLE sessions;--"),
    ],
)
def test_start_persists_valid_name_and_matching_interval(
    timer: TimerService, repository: StudyRepository, clock: ClockService, name: str, expected: str
) -> None:
    session = timer.start_session(name)
    assert session.name == expected and session.status == SessionStatus.RUNNING
    assert session.finished_at is None
    assert repository.get_session(session.id) == session
    interval = repository.get_open_interval(session.id)
    snapshot = clock.get_snapshot()
    assert interval is not None and snapshot is not None
    assert snapshot.interval_id == interval.id
    assert snapshot.started_at == interval.started_at == interval.last_seen_at == session.created_at
    assert len(repository.get_session_intervals(session.id)) == 1
    assert clock.is_running


def test_invalid_name_does_not_create_session_or_sample_clock(
    timer: TimerService, repository: StudyRepository, source: FakeClock, clock: ClockService
) -> None:
    with pytest.raises(ValueError, match="120"):
        timer.start_session("x" * 121)
    assert repository.get_pending_session() is None
    assert clock.get_snapshot() is None and source.read_count == 0


def test_complete_cycle_reuses_session_and_excludes_pauses(
    timer: TimerService, repository: StudyRepository, clock: ClockService, source: FakeClock
) -> None:
    original = timer.start_session("Física")
    advance_study(clock, source, 2 * SECOND_NS + 750_000_000)
    paused = timer.pause_session(PauseReason.USER)
    assert paused.status == SessionStatus.PAUSED
    assert repository.get_open_interval(original.id) is None
    source.advance(3600 * SECOND_NS)
    resumed = timer.resume_session()
    assert resumed.id == original.id and resumed.name == original.name
    assert resumed.status == SessionStatus.RUNNING
    advance_study(clock, source, 3 * SECOND_NS + 250_000_000)
    finished = timer.finish_session()
    assert finished.status == SessionStatus.FINISHED
    assert original.status == SessionStatus.RUNNING
    assert repository.get_pending_session() is None
    assert clock.get_snapshot() is None and not clock.is_running
    intervals = repository.get_session_intervals(original.id)
    assert len(intervals) == 2 and intervals[0].id != intervals[1].id
    assert all(interval.ended_at is not None for interval in intervals)
    assert completed_seconds(repository, original.id) == 5
    assert finished.finished_at == intervals[1].ended_at


@pytest.mark.parametrize("paused", [False, True])
def test_only_one_session_can_be_pending(
    timer: TimerService, repository: StudyRepository, source: FakeClock, paused: bool
) -> None:
    session = timer.start_session("Primeira")
    if paused:
        timer.pause_session(PauseReason.USER)
    count = source.read_count
    with pytest.raises(RuntimeError):
        timer.start_session("Segunda")
    pending = repository.get_pending_session()
    assert pending is not None and pending.id == session.id and pending.name == "Primeira"
    assert len(repository.get_session_intervals(session.id)) == 1
    assert source.read_count == count


def test_finishing_allows_another_session_without_erasing_history(
    timer: TimerService, repository: StudyRepository
) -> None:
    original = timer.start_session("Primeira")
    finished = timer.finish_session()
    current = timer.start_session("Segunda")
    assert current.id != original.id
    assert repository.get_session(original.id) == finished
    assert len(repository.get_session_intervals(original.id)) == 1


@pytest.mark.parametrize("resume_zero", [False, True])
def test_zero_second_sessions_remain_recorded_with_creation_as_finish(
    timer: TimerService, repository: StudyRepository, source: FakeClock, resume_zero: bool
) -> None:
    session = timer.start_session("")
    if resume_zero:
        timer.pause_session(PauseReason.USER)
        source.advance(3600 * SECOND_NS)
        timer.resume_session()
    source.advance(750_000_000)
    finished = timer.finish_session()
    assert finished.finished_at == session.created_at
    assert repository.get_session(session.id) == finished
    assert completed_seconds(repository, session.id) == 0
    assert len(repository.get_session_intervals(session.id)) == (2 if resume_zero else 1)


def test_finish_running_confirms_the_last_partial_callback(
    timer: TimerService, source: FakeClock, repository: StudyRepository
) -> None:
    session = timer.start_session("Sem callback ainda")
    source.advance(2 * SECOND_NS + 750_000_000)
    finished = timer.finish_session()
    assert completed_seconds(repository, session.id) == 2
    assert finished.finished_at == session.created_at + 2


def test_finish_paused_never_reads_the_clock_or_counts_waiting_time(
    timer: TimerService, source: FakeClock, clock: ClockService, repository: StudyRepository
) -> None:
    session = timer.start_session("Pausa")
    advance_study(clock, source, 3 * SECOND_NS)
    timer.pause_session(PauseReason.USER)
    count = source.read_count
    source.advance(3600 * SECOND_NS)
    source.failure = OSError("A fonte não deve ser consultada")
    finished = timer.finish_session()
    assert source.read_count == count
    assert finished.finished_at == session.created_at + 3
    assert completed_seconds(repository, session.id) == 3


@pytest.mark.parametrize("first_duration_s", [0, 3])
def test_finish_keeps_greatest_end_after_civil_clock_moves_back_between_intervals(
    timer: TimerService,
    repository: StudyRepository,
    clock: ClockService,
    source: FakeClock,
    first_duration_s: int,
) -> None:
    session = timer.start_session("Relógio corrigido durante a pausa")
    advance_study(clock, source, first_duration_s * SECOND_NS)
    timer.pause_session(PauseReason.USER)
    source.wall_time_s = session.created_at - 60.0
    timer.resume_session()
    advance_study(clock, source, 2 * SECOND_NS)
    finished = timer.finish_session()
    assert finished.finished_at == session.created_at + first_duration_s
    assert completed_seconds(repository, session.id) == first_duration_s + 2


@pytest.mark.parametrize(
    "reason", [PauseReason.SUSPEND, PauseReason.SHUTDOWN, PauseReason.WRITE_FAILURE]
)
def test_conservative_pause_does_not_sample_unconfirmed_time(
    timer: TimerService,
    repository: StudyRepository,
    clock: ClockService,
    source: FakeClock,
    reason: PauseReason,
) -> None:
    session = timer.start_session("Congelamento seguro")
    advance_study(clock, source, SECOND_NS)
    source.advance(3 * SECOND_NS)
    count = source.read_count
    timer.pause_session(reason)
    assert source.read_count == count
    assert completed_seconds(repository, session.id) == 1
    assert clock.pause_reason == reason


@pytest.mark.parametrize("gap", [False, True])
def test_unsafe_final_tick_is_excluded_when_pausing(
    timer: TimerService,
    repository: StudyRepository,
    clock: ClockService,
    source: FakeClock,
    gap: bool,
) -> None:
    session = timer.start_session("Interrupção")
    advance_study(clock, source, SECOND_NS)
    source.advance(20 * SECOND_NS if gap else SECOND_NS, wall_delta_s=3600.0)
    paused = timer.pause_session(PauseReason.USER)
    assert paused.status == SessionStatus.PAUSED
    assert completed_seconds(repository, session.id) == 1
    assert clock.pause_reason == (PauseReason.TICK_GAP if gap else PauseReason.CLOCK_CHANGE)


@pytest.mark.parametrize("operation", ["pause", "resume", "finish"])
def test_commands_require_a_pending_session(
    timer: TimerService, source: FakeClock, operation: str
) -> None:
    with pytest.raises(RuntimeError):
        if operation == "pause":
            timer.pause_session(PauseReason.USER)
        elif operation == "resume":
            timer.resume_session()
        else:
            timer.finish_session()
    assert source.read_count == 0


def test_invalid_transitions_do_not_change_the_persisted_state(timer: TimerService) -> None:
    session = timer.start_session("Transições")
    with pytest.raises(RuntimeError):
        timer.resume_session()
    paused = timer.pause_session(PauseReason.USER)
    with pytest.raises(RuntimeError):
        timer.pause_session(PauseReason.USER)
    assert timer.get_active_session() == paused
    timer.finish_session()
    with pytest.raises(RuntimeError):
        timer.finish_session()
    assert session.id == paused.id


@pytest.mark.parametrize("operation", ["pause", "finish"])
def test_running_session_without_corresponding_clock_requires_recovery(
    timer: TimerService, repository: StudyRepository, source: FakeClock, operation: str
) -> None:
    session = timer.start_session("Processo anterior")
    restarted = TimerService(repository, ClockService(source))
    with pytest.raises(RuntimeError, match="recuperação"):
        if operation == "pause":
            restarted.pause_session(PauseReason.USER)
        else:
            restarted.finish_session()
    assert repository.get_session(session.id) == session
    assert repository.get_open_interval(session.id) is not None


def test_source_failure_on_resume_leaves_the_paused_session_untouched(
    timer: TimerService, repository: StudyRepository, source: FakeClock, clock: ClockService
) -> None:
    session = timer.start_session("Sem âncora válida")
    paused = timer.pause_session(PauseReason.USER)
    intervals = repository.get_session_intervals(session.id)
    snapshot = clock.get_snapshot()
    source.failure = OSError("Falha simulada na fonte")
    with pytest.raises(OSError):
        timer.resume_session()
    assert repository.get_session(session.id) == paused
    assert repository.get_session_intervals(session.id) == intervals
    assert clock.get_snapshot() is snapshot and not clock.is_running


def test_failed_interval_insertion_rolls_back_the_new_session(
    timer: TimerService,
    repository: StudyRepository,
    connection: sqlite3.Connection,
    clock: ClockService,
) -> None:
    connection.execute(
        "CREATE TRIGGER fail_new_interval BEFORE INSERT ON study_intervals "
        "BEGIN SELECT RAISE(ABORT, 'forced_failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        timer.start_session("Deve reverter")
    assert repository.get_pending_session() is None
    assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM study_intervals").fetchone()[0] == 0
    assert clock.get_snapshot() is None and not clock.is_running
    assert not connection.in_transaction


def test_failed_resume_transition_rolls_back_the_inserted_interval(
    timer: TimerService,
    repository: StudyRepository,
    connection: sqlite3.Connection,
    clock: ClockService,
) -> None:
    session = timer.start_session("Retomada atômica")
    paused = timer.pause_session(PauseReason.USER)
    intervals = repository.get_session_intervals(session.id)
    snapshot = clock.get_snapshot()
    connection.execute(
        "CREATE TRIGGER fail_resume BEFORE UPDATE OF status ON sessions "
        "WHEN NEW.status = 'running' BEGIN SELECT RAISE(ABORT, 'forced_failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        timer.resume_session()
    assert repository.get_session(session.id) == paused
    assert repository.get_session_intervals(session.id) == intervals
    assert clock.get_snapshot() is snapshot and not clock.is_running


@pytest.mark.parametrize("operation", ["start", "pause", "resume", "finish"])
def test_real_commit_failure_rolls_back_all_rows_and_preserves_safe_clock_for_retry(
    timer: TimerService,
    repository: StudyRepository,
    connection: sqlite3.Connection,
    clock: ClockService,
    source: FakeClock,
    operation: str,
) -> None:
    session = None
    if operation != "start":
        session = timer.start_session("Commit atômico")
        advance_study(clock, source, 3 * SECOND_NS)
        if operation == "resume":
            timer.pause_session(PauseReason.USER)
    before_sessions = [tuple(row) for row in connection.execute("SELECT * FROM sessions")]
    before_intervals = [tuple(row) for row in connection.execute("SELECT * FROM study_intervals")]

    def deny_commit(
        action: int,
        arg1: str | None,
        arg2: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        return (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT"
            else sqlite3.SQLITE_OK
        )

    def command() -> Session:
        if operation == "start":
            return timer.start_session("Commit atômico")
        if operation == "pause":
            return timer.pause_session(PauseReason.USER)
        if operation == "resume":
            return timer.resume_session()
        return timer.finish_session()

    connection.set_authorizer(deny_commit)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            command()
    finally:
        connection.set_authorizer(None)
    assert [tuple(row) for row in connection.execute("SELECT * FROM sessions")] == before_sessions
    assert [
        tuple(row) for row in connection.execute("SELECT * FROM study_intervals")
    ] == before_intervals
    assert not connection.in_transaction and not clock.is_running
    assert timer.persistence_failed
    if operation in ("pause", "finish"):
        snapshot = clock.get_snapshot()
        assert snapshot is not None and snapshot.elapsed_s == 3
        source.advance(3600 * SECOND_NS)
    result = command()
    assert not timer.persistence_failed
    if operation in ("pause", "finish"):
        assert session is not None
        assert completed_seconds(repository, session.id) == 3
    assert result == repository.get_session(result.id)


def test_two_connections_cannot_create_two_pending_sessions(tmp_path: Path) -> None:
    first = initialize_database(tmp_path / "estudos.db")
    second = initialize_database(tmp_path / "estudos.db")
    try:
        original, _ = StudyRepository(first).start_session("Primeira conexão", 1000)
        with pytest.raises(RuntimeError):
            StudyRepository(second).start_session("Segunda conexão", 2000)
        assert StudyRepository(second).get_pending_session() == original
    finally:
        second.close()
        first.close()


def test_paused_session_can_resume_with_fresh_services_after_reopening_database(
    tmp_path: Path,
) -> None:
    path = tmp_path / "estudos.db"
    source = FakeClock()
    connection = initialize_database(path)
    try:
        repository = StudyRepository(connection)
        clock = ClockService(source)
        timer = TimerService(repository, clock)
        session = timer.start_session("Persistência sem cache de sessão")
        advance_study(clock, source, 2 * SECOND_NS)
        timer.pause_session(PauseReason.USER)
    finally:
        connection.close()
    source.advance(3600 * SECOND_NS)
    reopened = initialize_database(path)
    try:
        repository = StudyRepository(reopened)
        clock = ClockService(source)
        timer = TimerService(repository, clock)
        assert timer.resume_session().id == session.id
        advance_study(clock, source, 3 * SECOND_NS)
        timer.finish_session()
        assert completed_seconds(repository, session.id) == 5
        assert len(repository.get_session_intervals(session.id)) == 2
    finally:
        reopened.close()
