"""Atualização v1 real, rollback de DDL e restauração sem alterar a origem."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.database import backup as backup_module
from app.database import connection as connection_module
from app.database.backup import create_backup, restore_backup
from app.database.connection import initialize_database
from app.database.health import DatabaseHealthError, DatabaseVersionError, validate_database
from app.database.migrations import migrate_database
from app.database.repository import StudyRepository
from app.database.schema_version import CURRENT_SCHEMA_VERSIONS, SUPPORTED_SCHEMA_VERSIONS
from app.models import SessionStatus
from app.services.clock_service import ClockService
from app.services.timer_service import TimerService
from tests.test_clock import FakeClock

V1_SCHEMA = Path(__file__).parent / "fixtures" / "schema_v1.sql"


def make_v1(path: Path, pending: str | None = None) -> None:
    """Mantém uma origem legada congelada, independente do schema de produção."""
    database = sqlite3.connect(path, isolation_level=None)
    try:
        database.execute("PRAGMA foreign_keys = ON")
        database.executescript(V1_SCHEMA.read_text(encoding="utf-8"))
        database.execute(
            "INSERT INTO sessions (id, name, created_at, finished_at, status) "
            "VALUES (7, 'Estudo antigo', 1000, 1164, 'finished')"
        )
        database.executemany(
            "INSERT INTO study_intervals "
            "(id, session_id, started_at, last_seen_at, ended_at) VALUES (?, ?, ?, ?, ?)",
            [(11, 7, 1000, 1037, 1037), (15, 7, 1100, 1164, 1164)],
        )
        if pending is not None:
            database.execute(
                "INSERT INTO sessions (id, name, created_at, status) "
                "VALUES (21, 'Pendente antiga', 2000, 'paused')"
            )
            if pending == "running":
                database.execute(
                    "INSERT INTO study_intervals "
                    "(id, session_id, started_at, last_seen_at) VALUES (29, 21, 2000, 2020)"
                )
                database.execute("UPDATE sessions SET status = 'running' WHERE id = 21")
            else:
                database.execute(
                    "INSERT INTO study_intervals "
                    "(id, session_id, started_at, last_seen_at, ended_at) "
                    "VALUES (29, 21, 2000, 2020, 2020)"
                )
    finally:
        database.close()


def legacy_rows(path: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    database = sqlite3.connect(path)
    try:
        sessions = database.execute(
            "SELECT id, name, created_at, finished_at, status FROM sessions ORDER BY id"
        ).fetchall()
        intervals = database.execute("SELECT * FROM study_intervals ORDER BY id").fetchall()
        return sessions, intervals
    finally:
        database.close()


def assert_v1_rolled_back(database: sqlite3.Connection) -> None:
    assert database.execute("PRAGMA user_version").fetchone()[0] == 1
    assert not database.in_transaction
    assert (
        database.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('study_types', 'app_preferences')"
        ).fetchall()
        == []
    )
    assert "study_type_id" not in {
        row[1] for row in database.execute("PRAGMA table_info(sessions)").fetchall()
    }
    assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("pending", [None, "paused", "running"])
def test_migration_preserves_every_legacy_record_and_backup(
    tmp_path: Path, pending: str | None
) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path, pending)
    original = legacy_rows(path)
    database = initialize_database(path)
    try:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 2
        assert legacy_rows(path) == original
        assert all(row[0] is None for row in database.execute("SELECT study_type_id FROM sessions"))
        assert database.execute("SELECT count(*) FROM study_types").fetchone()[0] == 0
        assert tuple(
            database.execute("SELECT id, appearance_mode FROM app_preferences").fetchone()
        ) == (
            1,
            "dark",
        )
        assert database.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert database.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert database.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert database.execute("PRAGMA synchronous").fetchone()[0] == 2
        StudyRepository(database).validate_invariants()
    finally:
        database.close()
    copies = list((tmp_path / "backups" / "before-migration").glob("*.db"))
    assert len(copies) == 1
    validate_database(copies[0], supported_versions=SUPPORTED_SCHEMA_VERSIONS)
    assert legacy_rows(copies[0]) == original
    with pytest.raises(DatabaseVersionError):
        validate_database(copies[0])


def test_running_session_is_recovered_only_after_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path, "running")
    database = initialize_database(path)
    try:
        repository = StudyRepository(database)
        assert repository.get_pending_session() is not None
        source = FakeClock()
        timer = TimerService(repository, ClockService(source))
        recovered = timer.recover_pending()
        assert recovered is not None and recovered.id == 21
        assert recovered.status == SessionStatus.PAUSED and recovered.study_type_id is None
        assert timer.get_elapsed_seconds() == 20
        assert source.read_count == 0
        assert repository.get_open_interval(21) is None
    finally:
        database.close()


def test_reopening_does_not_repeat_migration_or_destroy_its_backup(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path)
    original = legacy_rows(path)
    for _ in range(8):
        database = initialize_database(path)
        try:
            migrate_database(database)
            assert database.execute("SELECT count(*) FROM app_preferences").fetchone()[0] == 1
        finally:
            database.close()
    assert legacy_rows(path) == original
    assert len(list((tmp_path / "backups" / "before-migration").glob("*.db"))) == 1
    assert len(list((tmp_path / "backups").glob("*.db"))) == 5


def test_fresh_and_migrated_schemas_have_equivalent_structure(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path)
    migrated = initialize_database(path)
    fresh = initialize_database(tmp_path / "fresh.db")
    try:
        for table in ("sessions", "study_intervals", "study_types", "app_preferences"):
            # A posição física da coluna adicionada não modifica o contrato.
            left = {tuple(row)[1:] for row in migrated.execute(f"PRAGMA table_info({table})")}
            right = {tuple(row)[1:] for row in fresh.execute(f"PRAGMA table_info({table})")}
            assert left == right
            assert [
                tuple(row) for row in migrated.execute(f"PRAGMA foreign_key_list({table})")
            ] == [tuple(row) for row in fresh.execute(f"PRAGMA foreign_key_list({table})")]
            assert {tuple(row)[1:4] for row in migrated.execute(f"PRAGMA index_list({table})")} == {
                tuple(row)[1:4] for row in fresh.execute(f"PRAGMA index_list({table})")
            }
        assert [
            tuple(row)
            for row in migrated.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
            )
        ] == [
            tuple(row)
            for row in fresh.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
        ]
    finally:
        migrated.close()
        fresh.close()


@pytest.mark.parametrize("failure", ["ddl", "version", "commit"])
def test_failed_migration_rolls_back_ddl_and_preserves_records(
    tmp_path: Path, failure: str
) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path, "running")
    original = legacy_rows(path)
    database = sqlite3.connect(path, isolation_level=None)
    database.row_factory = sqlite3.Row

    def deny(
        action: int, first: str | None, second: str | None, db: str | None, sql: str | None
    ) -> int:
        if (
            (failure == "ddl" and action == sqlite3.SQLITE_ALTER_TABLE)
            or (
                failure == "version"
                and action == sqlite3.SQLITE_PRAGMA
                and first == "user_version"
                and second == "2"
            )
            or (failure == "commit" and action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT")
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    database.set_authorizer(deny)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            migrate_database(database)
        database.set_authorizer(None)
        assert_v1_rolled_back(database)
    finally:
        database.close()
    assert legacy_rows(path) == original


def test_exit_before_commit_does_not_publish_partial_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path, "paused")
    original = legacy_rows(path)
    script = """
import os
import sqlite3
import sys
from app.database.migrations import migrate_database
database = sqlite3.connect(sys.argv[1], isolation_level=None)
database.row_factory = sqlite3.Row
database.execute('PRAGMA foreign_keys = ON')
database.execute('PRAGMA journal_mode = WAL')
database.execute('PRAGMA synchronous = FULL')
def stop_before_commit(action, first, second, db, sql):
    if action == sqlite3.SQLITE_TRANSACTION and first == 'COMMIT':
        os._exit(17)
    return sqlite3.SQLITE_OK
database.set_authorizer(stop_before_commit)
migrate_database(database)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 17, result.stderr
    database = sqlite3.connect(path)
    try:
        assert_v1_rolled_back(database)
    finally:
        database.close()
    assert legacy_rows(path) == original


def test_backup_failure_prevents_any_schema_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path)
    original = legacy_rows(path)

    def fail_backup(*args: object, **kwargs: object) -> Path:
        raise OSError("falha sintética no backup")

    monkeypatch.setattr(connection_module, "create_backup", fail_backup)
    with pytest.raises(OSError):
        initialize_database(path)
    database = sqlite3.connect(path)
    try:
        assert_v1_rolled_back(database)
    finally:
        database.close()
    assert legacy_rows(path) == original


@pytest.mark.parametrize("version", [0, 3, 999])
def test_unknown_version_is_not_migrated_or_marked_corrupt(tmp_path: Path, version: int) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path)
    database = sqlite3.connect(path)
    database.execute(f"PRAGMA user_version = {version}")
    database.close()
    original = path.read_bytes()
    with pytest.raises(DatabaseVersionError):
        initialize_database(path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.corrupt"))
    assert not (tmp_path / "backups").exists()


def test_invalid_legacy_session_state_does_not_commit_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path, "paused")
    database = sqlite3.connect(path, isolation_level=None)
    database.row_factory = sqlite3.Row
    database.execute("UPDATE study_intervals SET ended_at = NULL WHERE id = 29")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            migrate_database(database)
        assert_v1_rolled_back(database)
    finally:
        database.close()


def test_v1_backup_uses_explicit_policy_and_retains_five(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path)
    database = sqlite3.connect(path, isolation_level=None)
    try:
        database.execute("PRAGMA journal_mode = WAL")
        database.execute("PRAGMA wal_autocheckpoint = 0")
        database.execute("UPDATE sessions SET name = 'Última escrita WAL' WHERE id = 7")
        for _ in range(7):
            copied = create_backup(
                database, tmp_path / "copies", supported_versions=SUPPORTED_SCHEMA_VERSIONS
            )
        assert len(list((tmp_path / "copies").glob("*.db"))) == 5
        validate_database(copied, supported_versions=frozenset({1}))
        assert legacy_rows(copied) == legacy_rows(path)
        with pytest.raises(DatabaseVersionError):
            validate_database(copied, supported_versions=CURRENT_SCHEMA_VERSIONS)
    finally:
        database.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Restauração usa lock Windows.")
@pytest.mark.parametrize("source_version", [1, 2])
@pytest.mark.parametrize("target_version", [None, 1, 2])
def test_restore_prepares_legacy_copy_and_preserves_origin(
    tmp_path: Path, source_version: int, target_version: int | None
) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    make_v1(source, "paused")
    if source_version == 2:
        initialize_database(source).close()
    source_bytes = source.read_bytes()
    original = legacy_rows(source)
    if target_version is not None:
        make_v1(target)
        if target_version == 2:
            initialize_database(target).close()
        database = sqlite3.connect(target)
        database.execute("UPDATE sessions SET name = 'Destino anterior'")
        database.commit()
        database.close()
    restore_backup(source, target)
    assert source.read_bytes() == source_bytes
    assert legacy_rows(target) == original
    validate_database(target)
    database = sqlite3.connect(target)
    try:
        assert (
            database.execute("SELECT appearance_mode FROM app_preferences").fetchone()[0] == "dark"
        )
    finally:
        database.close()
    copies = list((tmp_path / "backups" / "before-restore").glob("*.db"))
    assert len(copies) == (1 if target_version is not None else 0)
    if copies:
        assert legacy_rows(copies[0])[0][0][1] == "Destino anterior"


@pytest.mark.skipif(sys.platform != "win32", reason="Restauração usa lock Windows.")
def test_restore_preparation_failure_leaves_source_and_destination_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    make_v1(source)
    initialize_database(target).close()
    before = source.read_bytes(), target.read_bytes()

    def fail_migration(connection: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("falha sintética de preparação")

    monkeypatch.setattr(backup_module, "migrate_database", fail_migration)
    with pytest.raises(sqlite3.OperationalError):
        restore_backup(source, target)
    assert (source.read_bytes(), target.read_bytes()) == before
    assert not (tmp_path / "backups" / "before-restore").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Restauração usa lock Windows.")
def test_restore_refuses_corrupt_destination_without_overwriting(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    make_v1(source)
    target.write_bytes(b"destino corrompido para teste")
    before = source.read_bytes(), target.read_bytes()
    with pytest.raises((DatabaseHealthError, sqlite3.DatabaseError)):
        restore_backup(source, target)
    assert (source.read_bytes(), target.read_bytes()) == before


@pytest.mark.skipif(sys.platform != "win32", reason="Restauração usa lock Windows.")
def test_restore_retention_cannot_delete_selected_origin(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    database = initialize_database(target)
    try:
        database.execute(
            "INSERT INTO sessions (id, name, created_at, finished_at, status) "
            "VALUES (7, 'Origem selecionada', 1000, 1000, 'finished')"
        )
        directory = tmp_path / "backups" / "before-restore"
        origin = create_backup(database, directory)
        original_bytes = origin.read_bytes()
        for _ in range(4):
            create_backup(database, directory)
        database.execute("UPDATE sessions SET name = 'Destino posterior' WHERE id = 7")
    finally:
        database.close()
    restore_backup(origin, target)
    assert origin.is_file(), "A rotação não pode excluir o backup usado na restauração."
    assert origin.read_bytes() == original_bytes
    assert legacy_rows(target)[0][0][1] == "Origem selecionada"
    assert len(list(directory.glob("studytimer-*.db"))) == 5


def test_backup_validation_failure_does_not_publish_partial_copy(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_v1(path)
    database = sqlite3.connect(path, isolation_level=None)
    try:
        with pytest.raises(DatabaseVersionError):
            create_backup(database, tmp_path / "copies")
        assert not list((tmp_path / "copies").iterdir())
    finally:
        database.close()


@pytest.mark.parametrize("policy", [frozenset(), frozenset({999}), frozenset({1, 2, 999})])
def test_validation_policy_cannot_disable_known_version_check(
    tmp_path: Path, policy: frozenset[int]
) -> None:
    path = tmp_path / "current.db"
    initialize_database(path).close()
    with pytest.raises(ValueError):
        validate_database(path, supported_versions=policy)
