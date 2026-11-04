"""Catálogo e vínculo de sessões com SQLite real e tempo simulado."""

import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.models import ClockSnapshot, PauseReason, SessionStatus, StudyColor, StudyType
from app.services.clock_service import ClockService
from app.services.study_type_service import StudyTypeService
from app.services.timer_service import TimerService
from app.validation import normalize_study_type_name
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_recovery import deny_commit


@pytest.fixture
def repository(connection: sqlite3.Connection) -> StudyRepository:
    return StudyRepository(connection)


@pytest.fixture
def catalog(repository: StudyRepository) -> StudyTypeService:
    return StudyTypeService(repository)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("  Banco\tde\nDados  ", "Banco de Dados"),
        ("ＰＯＯ", "POO"),
        ("Lo\u0301gica", "Lógica"),
        ("A\x00\u202eB", "AB"),
        ("x" * 60, "x" * 60),
    ],
)
def test_type_name_normalizes_unicode_and_spaces(name: str, expected: str) -> None:
    assert normalize_study_type_name(name) == expected


@pytest.mark.parametrize("name", ["", " \t\x00\n", "x" * 61, "SEM TIPO", "Ｓｅｍ　ｔｉｐｏ"])
def test_invalid_names_do_not_create_rows(catalog: StudyTypeService, name: str) -> None:
    with pytest.raises(ValueError):
        catalog.create_type(name, StudyColor.BLUE)
    assert catalog.list_types(include_archived=True) == []


def test_casefold_uniqueness_covers_archived_and_preserves_accents(
    catalog: StudyTypeService,
) -> None:
    first = catalog.create_type("Straße", StudyColor.BLUE)
    catalog.archive_type(first.id)
    with pytest.raises(ValueError, match="ativo ou arquivado"):
        catalog.create_type("STRASSE", StudyColor.TEAL)
    accented = catalog.create_type("Lógica", StudyColor.PURPLE)
    plain = catalog.create_type("Logica", StudyColor.ORANGE)
    assert accented.id != plain.id
    assert first not in catalog.list_types()
    assert len(catalog.list_types(include_archived=True)) == 3
    restored = catalog.restore_type(first.id)
    assert restored.id == first.id and not restored.is_archived


def test_catalog_updates_atomically_without_reclassifying_sessions(
    repository: StudyRepository, catalog: StudyTypeService
) -> None:
    first = catalog.create_type("POO", StudyColor.BLUE)
    second = catalog.create_type("Redes", StudyColor.ORANGE)
    session, interval = repository.start_session("Herança", 1000, first.id)
    repository.finish_session(session.id, ClockSnapshot(interval.id, 1000, 70, 1070))
    before = repository.get_session_intervals(session.id)
    updated = catalog.update_type(first.id, "Orientação a objetos", StudyColor.TEAL)
    assert updated.id == first.id
    stored = repository.get_session(session.id)
    assert stored is not None and stored.study_type_id == first.id
    assert repository.get_session_intervals(session.id) == before
    with pytest.raises(ValueError):
        catalog.update_type(first.id, second.name, StudyColor.AMBER)
    assert repository.get_study_type(first.id) == updated
    archived = catalog.archive_type(first.id)
    assert archived.is_archived
    assert repository.get_report_intervals(1000, 1100)[0][0].study_type_id == first.id


@pytest.mark.parametrize("paused", [False, True])
def test_cannot_archive_type_of_pending_session(
    repository: StudyRepository, catalog: StudyTypeService, paused: bool
) -> None:
    study_type = catalog.create_type("POO", StudyColor.BLUE)
    session, interval = repository.start_session("Herança", 1000, study_type.id)
    if paused:
        repository.pause_session(session.id, ClockSnapshot(interval.id, 1000, 0, 1000))
    with pytest.raises(ValueError, match="pendente"):
        catalog.archive_type(study_type.id)
    assert repository.get_study_type(study_type.id) == study_type


def test_direct_repository_boundaries_and_model_are_validated(
    repository: StudyRepository, catalog: StudyTypeService
) -> None:
    for name in ("", "x" * 61, "Sem tipo"):
        with pytest.raises(ValueError):
            repository.create_study_type(name, StudyColor.BLUE)
    with pytest.raises(ValueError):
        repository.create_study_type("POO", "invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        StudyType(1, "POO", "invalid")  # type: ignore[arg-type]
    for action in (catalog.archive_type, catalog.restore_type):
        with pytest.raises(ValueError, match="não existe"):
            action(999)
    with pytest.raises(ValueError):
        catalog.update_type(999, "POO", StudyColor.BLUE)
    study_type = catalog.create_type("POO", StudyColor.BLUE)
    with pytest.raises(FrozenInstanceError):
        study_type.name = "Outro"  # type: ignore[misc]


def test_duplicate_unicode_names_and_parameterized_text(
    repository: StudyRepository, catalog: StudyTypeService
) -> None:
    study_type = catalog.create_type("  ＰＯＯ  ", StudyColor.BLUE)
    with pytest.raises(ValueError):
        repository.create_study_type("poo", StudyColor.TEAL)
    literal = "Robert'); DROP TABLE sessions;--"
    assert catalog.create_type(literal, StudyColor.ROSE).name == literal
    assert repository.get_study_type(study_type.id) == study_type
    assert repository.get_pending_session() is None


@pytest.mark.parametrize("operation", ["create", "update", "archive", "restore"])
def test_type_commands_rollback_when_commit_is_denied(
    connection: sqlite3.Connection,
    catalog: StudyTypeService,
    operation: str,
) -> None:
    study_type = catalog.create_type("POO", StudyColor.BLUE)
    if operation == "restore":
        catalog.archive_type(study_type.id)
    before = catalog.list_types(include_archived=True)
    connection.set_authorizer(deny_commit)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            if operation == "create":
                catalog.create_type("Redes", StudyColor.ORANGE)
            elif operation == "update":
                catalog.update_type(study_type.id, "Outra", StudyColor.TEAL)
            elif operation == "archive":
                catalog.archive_type(study_type.id)
            else:
                catalog.restore_type(study_type.id)
    finally:
        connection.set_authorizer(None)
    assert catalog.list_types(include_archived=True) == before
    assert not connection.in_transaction


def test_classification_survives_entire_cycle_recovery_and_zero_report(
    repository: StudyRepository, catalog: StudyTypeService
) -> None:
    study_type = catalog.create_type("POO", StudyColor.BLUE)
    source = FakeClock()
    timer = TimerService(repository, ClockService(source))
    session = timer.start_session("Herança", study_type.id)
    assert (
        repository.get_zero_duration_sessions(session.created_at, session.created_at + 1)[
            0
        ].study_type_id
        == study_type.id
    )
    source.advance(SECOND_NS)
    timer.tick()
    timer.heartbeat()
    recovered = TimerService(repository, ClockService(FakeClock()))
    pending = recovered.recover_pending()
    assert pending is not None and pending.study_type_id == study_type.id
    assert pending.status == SessionStatus.PAUSED
    assert recovered.get_elapsed_seconds() == 1
    assert recovered.resume_session().study_type_id == study_type.id
    assert recovered.pause_session(PauseReason.USER).study_type_id == study_type.id
    assert recovered.finish_session().study_type_id == study_type.id
    assert (
        repository.get_report_intervals(session.created_at, session.created_at + 2)[0][
            0
        ].study_type_id
        == study_type.id
    )


def test_invalid_type_never_starts_clock_or_inserts_session(
    repository: StudyRepository, catalog: StudyTypeService
) -> None:
    study_type = catalog.create_type("POO", StudyColor.BLUE)
    catalog.archive_type(study_type.id)
    clock = ClockService(FakeClock())
    timer = TimerService(repository, clock)
    for type_id in (999, study_type.id):
        with pytest.raises(ValueError):
            timer.start_session("Inválido", type_id)
        assert repository.get_pending_session() is None
        assert not clock.is_running and clock.get_snapshot() is None
    assert timer.start_session("Livre").study_type_id is None


def test_catalog_and_session_type_persist_after_reopening(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    connection = initialize_database(path)
    repository = StudyRepository(connection)
    study_type = repository.create_study_type("POO", StudyColor.BLUE)
    session, _ = repository.start_session("Herança", 1000, study_type.id)
    connection.close()
    reopened = initialize_database(path)
    try:
        repository = StudyRepository(reopened)
        assert repository.get_study_type(study_type.id) == study_type
        assert repository.get_pending_session() == session
    finally:
        reopened.close()
