"""Checkpoints, falhas reais de SQLite e recuperação sem tempo fantasma."""

import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.models import ClockSnapshot, PauseReason, SessionStatus
from app.services.clock_service import ClockService
from app.services.timer_service import TimerService
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_timer import advance_study, completed_seconds


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


def test_heartbeat_uses_only_the_last_accepted_tick(
    timer: TimerService, repository: StudyRepository, clock: ClockService, source: FakeClock
) -> None:
    session = timer.start_session("Checkpoint confiável")
    advance_study(clock, source, 5 * SECOND_NS + 750_000_000)
    snapshot = clock.get_snapshot()
    source.advance(3600 * SECOND_NS)
    count = source.read_count
    source.failure = OSError("O heartbeat não deve ler a fonte")
    timer.heartbeat()
    timer.heartbeat()
    interval = repository.get_open_interval(session.id)
    assert interval is not None and interval.last_seen_at == session.created_at + 5
    assert interval.ended_at is None
    assert source.read_count == count and clock.get_snapshot() is snapshot
    assert clock.is_running and not timer.persistence_failed


@pytest.mark.parametrize("state", ["idle", "paused", "finished"])
def test_heartbeat_without_a_running_session_does_not_write_or_sample(
    timer: TimerService, connection: sqlite3.Connection, source: FakeClock, state: str
) -> None:
    if state != "idle":
        timer.start_session("Sem checkpoint")
        timer.pause_session(PauseReason.USER)
        if state == "finished":
            timer.finish_session()
    count = source.read_count
    connection.execute("PRAGMA query_only = ON")
    timer.heartbeat()
    assert source.read_count == count and not timer.persistence_failed


@pytest.mark.parametrize("reason", [PauseReason.TICK_GAP, PauseReason.CLOCK_CHANGE])
def test_heartbeat_persists_a_clock_pause_without_crediting_the_rejected_tick(
    timer: TimerService,
    repository: StudyRepository,
    clock: ClockService,
    source: FakeClock,
    reason: PauseReason,
) -> None:
    session = timer.start_session("Pausa automática")
    advance_study(clock, source, 3 * SECOND_NS)
    source.advance(20 * SECOND_NS if reason == PauseReason.TICK_GAP else SECOND_NS, 3600)
    clock.tick()
    count = source.read_count
    timer.heartbeat()
    assert source.read_count == count and clock.pause_reason == reason
    assert repository.get_open_interval(session.id) is None
    assert completed_seconds(repository, session.id) == 3
    active = timer.get_active_session()
    assert active is not None and active.status == SessionStatus.PAUSED


@pytest.mark.parametrize("failure", ["commit", "readonly", "locked", "full"])
def test_failed_checkpoint_freezes_and_only_reports_saved_after_a_successful_retry(
    timer: TimerService,
    repository: StudyRepository,
    connection: sqlite3.Connection,
    clock: ClockService,
    source: FakeClock,
    tmp_path: Path,
    failure: str,
) -> None:
    session = timer.start_session("Falha de escrita")
    advance_study(clock, source, 5 * SECOND_NS)
    timer.heartbeat()
    advance_study(clock, source, 3 * SECOND_NS)
    snapshot = clock.get_snapshot()
    previous = repository.get_open_interval(session.id)
    other = None
    if failure == "commit":
        connection.set_authorizer(deny_commit)
    elif failure == "readonly":
        connection.execute("PRAGMA query_only = ON")
    elif failure == "locked":
        other = initialize_database(tmp_path / "estudos.db")
        connection.execute("PRAGMA busy_timeout = 0")
        other.execute("BEGIN IMMEDIATE")
    else:
        connection.execute("CREATE TABLE fill_storage (payload BLOB)")
        connection.execute(
            "CREATE TRIGGER fill_disk BEFORE UPDATE ON study_intervals "
            "BEGIN INSERT INTO fill_storage VALUES (zeroblob(65536)); END"
        )
        connection.execute("PRAGMA max_page_count = 1")
    try:
        with pytest.raises(sqlite3.Error) as raised:
            timer.heartbeat()
        if failure == "full":
            assert raised.value.sqlite_errorcode == sqlite3.SQLITE_FULL
        assert timer.persistence_failed and not clock.is_running
        assert clock.pause_reason == PauseReason.WRITE_FAILURE
        assert clock.get_snapshot() is snapshot
        assert repository.get_open_interval(session.id) == previous
        assert timer.get_active_session() == session
        assert timer.persistence_failed and not connection.in_transaction
        with pytest.raises(sqlite3.Error):
            timer.heartbeat()
        assert timer.persistence_failed and clock.get_snapshot() is snapshot
    finally:
        connection.set_authorizer(None)
        connection.execute("PRAGMA query_only = OFF")
        if other is not None:
            other.rollback()
            other.close()
        if failure == "full":
            connection.execute("DROP TRIGGER fill_disk")
    source.advance(3600 * SECOND_NS)
    count = source.read_count
    timer.heartbeat()
    assert not timer.persistence_failed and not clock.is_running
    assert source.read_count == count
    assert repository.get_open_interval(session.id) is None
    active = timer.get_active_session()
    assert active is not None and active.status == SessionStatus.PAUSED
    assert completed_seconds(repository, session.id) == 8
    timer.resume_session()
    advance_study(clock, source, 2 * SECOND_NS)
    timer.finish_session()
    assert completed_seconds(repository, session.id) == 10


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


def test_failed_pause_retains_its_first_reason_until_heartbeat_retry(
    timer: TimerService,
    repository: StudyRepository,
    connection: sqlite3.Connection,
    clock: ClockService,
    source: FakeClock,
) -> None:
    session = timer.start_session("Primeiro motivo")
    advance_study(clock, source, 2 * SECOND_NS)
    connection.set_authorizer(deny_commit)
    try:
        with pytest.raises(sqlite3.Error):
            timer.pause_session(PauseReason.SUSPEND)
    finally:
        connection.set_authorizer(None)
    assert timer.persistence_failed and clock.pause_reason == PauseReason.SUSPEND
    source.advance(3600 * SECOND_NS)
    timer.heartbeat()
    assert not timer.persistence_failed and clock.pause_reason == PauseReason.SUSPEND
    assert completed_seconds(repository, session.id) == 2


def test_query_failure_during_heartbeat_also_freezes_the_clock(
    timer: TimerService, connection: sqlite3.Connection, clock: ClockService, source: FakeClock
) -> None:
    timer.start_session("Leitura indisponível")
    advance_study(clock, source, SECOND_NS)
    snapshot = clock.get_snapshot()

    def deny_read(
        action: int, arg1: str | None, arg2: str | None, database: str | None, trigger: str | None
    ) -> int:
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ else sqlite3.SQLITE_OK

    connection.set_authorizer(deny_read)
    try:
        with pytest.raises(sqlite3.Error):
            timer.heartbeat()
    finally:
        connection.set_authorizer(None)
    assert not clock.is_running and timer.persistence_failed
    assert clock.get_snapshot() is snapshot


def test_noop_heartbeat_cannot_clear_a_failed_resume(
    timer: TimerService, connection: sqlite3.Connection
) -> None:
    timer.start_session("Falha ainda não resolvida")
    timer.pause_session(PauseReason.USER)
    connection.execute("PRAGMA query_only = ON")
    try:
        with pytest.raises(sqlite3.Error):
            timer.resume_session()
        timer.heartbeat()
        assert timer.persistence_failed
    finally:
        connection.execute("PRAGMA query_only = OFF")
    timer.resume_session()
    assert not timer.persistence_failed


def test_persistence_logs_do_not_include_session_text_or_error_details(
    timer: TimerService,
    connection: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logging.getLogger("studytimer"), "propagate", True)
    timer.start_session("Concurso particular")
    connection.execute(
        "CREATE TRIGGER private_failure BEFORE UPDATE ON study_intervals "
        "BEGIN SELECT RAISE(ABORT, 'C:\\Users\\NomePrivado'); END"
    )
    with caplog.at_level(logging.ERROR, logger="studytimer.timer"), pytest.raises(sqlite3.Error):
        timer.heartbeat()
    assert "PERSISTENCE_FAILED type=IntegrityError" in caplog.text
    assert "NomePrivado" not in caplog.text and "Concurso particular" not in caplog.text


@pytest.mark.parametrize("checkpoint_s", [0, 5])
def test_recovery_uses_only_the_checkpoint_and_requires_explicit_resume(
    tmp_path: Path, checkpoint_s: int
) -> None:
    path = tmp_path / "estudos.db"
    source = FakeClock()
    connection = initialize_database(path)
    try:
        repository = StudyRepository(connection)
        clock = ClockService(source)
        timer = TimerService(repository, clock)
        session = timer.start_session("Processo interrompido")
        advance_study(clock, source, checkpoint_s * SECOND_NS)
        if checkpoint_s:
            timer.heartbeat()
        advance_study(clock, source, 3 * SECOND_NS)
    finally:
        connection.close()
    source.advance(86_400 * SECOND_NS)
    source.failure = OSError("Recuperação não deve ler o relógio")
    reopened = initialize_database(path)
    try:
        repository = StudyRepository(reopened)
        clock = ClockService(source)
        timer = TimerService(repository, clock)
        count = source.read_count
        recovered = timer.recover_pending()
        assert recovered is not None and recovered.id == session.id
        assert recovered.status == SessionStatus.PAUSED and recovered.finished_at is None
        assert source.read_count == count and not clock.is_running
        assert clock.get_snapshot() is None and clock.pause_reason is None
        assert completed_seconds(repository, session.id) == checkpoint_s
        assert repository.get_open_interval(session.id) is None
        assert timer.recover_pending() == recovered
        assert len(repository.get_session_intervals(session.id)) == 1
        source.failure = None
        timer.resume_session()
        advance_study(clock, source, 2 * SECOND_NS)
        timer.finish_session()
        assert completed_seconds(repository, session.id) == checkpoint_s + 2
    finally:
        reopened.close()


@pytest.mark.parametrize("state", ["idle", "paused", "finished"])
def test_recovery_preserves_paused_sessions_and_finished_history(
    repository: StudyRepository, connection: sqlite3.Connection, source: FakeClock, state: str
) -> None:
    if state != "idle":
        session, interval = repository.start_session("Histórico preservado", 1000)
        repository.pause_session(session.id, ClockSnapshot(interval.id, 1000, 2, 1002))
        if state == "finished":
            repository.finish_session(session.id)
    before = list(connection.iterdump())
    clock = ClockService(source)
    timer = TimerService(repository, clock)
    recovered = timer.recover_pending()
    assert recovered == repository.get_pending_session()
    assert list(connection.iterdump()) == before
    assert source.read_count == 0 and not clock.is_running


def test_recovery_failure_rolls_back_the_closure_and_can_be_retried(
    repository: StudyRepository, connection: sqlite3.Connection, source: FakeClock
) -> None:
    session, _ = repository.start_session("Recuperação atômica", 1000)
    before = repository.get_open_interval(session.id)
    clock = ClockService(source)
    timer = TimerService(repository, clock)
    connection.set_authorizer(deny_commit)
    try:
        with pytest.raises(sqlite3.Error):
            timer.recover_pending()
    finally:
        connection.set_authorizer(None)
    assert timer.persistence_failed and not clock.is_running
    assert repository.get_open_interval(session.id) == before
    assert repository.get_session(session.id) == session
    assert source.read_count == 0 and not connection.in_transaction
    recovered = timer.recover_pending()
    assert recovered is not None and recovered.status == SessionStatus.PAUSED
    assert not timer.persistence_failed and completed_seconds(repository, session.id) == 0


@pytest.mark.parametrize("frozen", [False, True])
def test_recovery_cannot_discard_the_current_process_snapshot(
    timer: TimerService, repository: StudyRepository, clock: ClockService, frozen: bool
) -> None:
    session = timer.start_session("Ainda neste processo")
    if frozen:
        clock.pause(PauseReason.WRITE_FAILURE)
    snapshot = clock.get_snapshot()
    with pytest.raises(RuntimeError):
        timer.recover_pending()
    assert clock.get_snapshot() is snapshot
    assert repository.get_session(session.id) == session


def test_heartbeat_without_corresponding_clock_requires_recovery(
    repository: StudyRepository, source: FakeClock
) -> None:
    session, _ = repository.start_session("Reinício", 1000)
    timer = TimerService(repository, ClockService(source))
    with pytest.raises(RuntimeError, match="recuperação"):
        timer.heartbeat()
    assert repository.get_session(session.id) == session and source.read_count == 0


@pytest.mark.parametrize("crash_during_commit", [False, True])
def test_abrupt_process_exit_and_new_process_recover_only_committed_seconds(
    tmp_path: Path, crash_during_commit: bool
) -> None:
    root = Path(__file__).resolve().parent.parent
    path = tmp_path / "process.db"
    writer = """
import os
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.services.clock_service import ClockService
from app.services.timer_service import TimerService
from tests.test_clock import FakeClock, SECOND_NS
from tests.test_timer import advance_study
connection = initialize_database(Path(sys.argv[2]))
source = FakeClock()
clock = ClockService(source)
timer = TimerService(StudyRepository(connection), clock)
timer.start_session('Teste isolado de processo')
advance_study(clock, source, 5 * SECOND_NS)
timer.heartbeat()
advance_study(clock, source, 3 * SECOND_NS)
if sys.argv[3] == 'True':
    def crash(action, arg1, arg2, database, trigger):
        if action == sqlite3.SQLITE_TRANSACTION and arg1 == 'COMMIT':
            os._exit(17)
        return sqlite3.SQLITE_OK
    connection.set_authorizer(crash)
    timer.heartbeat()
os._exit(17)
"""
    reader = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.services.clock_service import ClockService
from app.services.timer_service import TimerService
from tests.test_clock import FakeClock, SECOND_NS
from tests.test_timer import advance_study, completed_seconds
connection = initialize_database(Path(sys.argv[2]))
repository = StudyRepository(connection)
source = FakeClock(wall_time_s=1_800_172_800.75, monotonic_ns=0)
clock = ClockService(source)
timer = TimerService(repository, clock)
session = timer.recover_pending()
assert session is not None
result = [session.status.value, completed_seconds(repository, session.id), source.read_count]
timer.resume_session()
advance_study(clock, source, 2 * SECOND_NS)
timer.finish_session()
result.append(completed_seconds(repository, session.id))
print(json.dumps(result))
connection.close()
"""
    crashed = subprocess.run(
        [sys.executable, "-c", writer, str(root), str(path), str(crash_during_commit)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert crashed.returncode == 17, crashed.stderr
    assert path.with_name(path.name + "-wal").exists()
    recovered = subprocess.run(
        [sys.executable, "-c", reader, str(root), str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(recovered.stdout) == ["paused", 5, 0, 7]
