"""Protege dados existentes, valida backups e verifica retenção automática."""

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.database.backup import create_backup, restore_backup
from app.database.connection import initialize_database
from app.database.health import DatabaseHealthError, DatabaseVersionError, validate_database


def test_corrupt_database_is_preserved_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "estudos.db"
    original = b"This is not a SQLite database.\n" * 100
    path.write_bytes(original)
    with pytest.raises(DatabaseHealthError):
        initialize_database(path)
    assert path.read_bytes() == original
    copies = list(tmp_path.glob("*.corrupt"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == original


def test_future_version_is_rejected_without_mutating_file(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 999")
    connection.close()
    original = path.read_bytes()
    with pytest.raises(DatabaseVersionError):
        initialize_database(path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.corrupt"))


def test_backup_includes_committed_wal_records_and_retains_five(tmp_path: Path) -> None:
    connection = initialize_database(tmp_path / "estudos.db")
    try:
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", (1, "Privado", 1000, 1000, "finished")
        )
        directory = tmp_path / "backups"
        for _ in range(7):
            backup = create_backup(connection, directory)
        with patch("app.database.backup.datetime") as wall_clock:
            wall_clock.now.return_value = datetime(2000, 1, 1, tzinfo=UTC)
            backup = create_backup(connection, directory)
        assert backup.is_file()
        assert len(list(directory.glob("studytimer-*.db"))) == 5
        validate_database(backup)
        restored = sqlite3.connect(backup)
        try:
            assert restored.execute("SELECT name FROM sessions").fetchone()[0] == "Privado"
        finally:
            restored.close()
    finally:
        connection.close()


def test_reopening_database_creates_validated_automatic_backup(tmp_path: Path) -> None:
    path = tmp_path / "estudos.db"
    initialize_database(path).close()
    initialize_database(path).close()
    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    validate_database(backups[0])


@pytest.mark.skipif(sys.platform != "win32", reason="Restauração obtém lock Windows.")
def test_restore_validates_version_and_preserves_current_database(tmp_path: Path) -> None:
    path = tmp_path / "estudos.db"
    connection = initialize_database(path)
    connection.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", (1, "Original", 1000, 1000, "finished")
    )
    backup = create_backup(connection, tmp_path / "backups")
    for _ in range(4):
        create_backup(connection, tmp_path / "backups")
    connection.execute("UPDATE sessions SET name = ?", ("Modificado",))
    connection.close()
    invalid = tmp_path / "invalid.db"
    invalid_connection = sqlite3.connect(invalid)
    invalid_connection.execute("PRAGMA user_version = 999")
    invalid_connection.close()
    with pytest.raises(DatabaseVersionError):
        restore_backup(invalid, path)
    restore_backup(backup, path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT name FROM sessions").fetchone()[0] == "Original"
    finally:
        connection.close()
    previous = list((tmp_path / "backups" / "before-restore").glob("studytimer-*.db"))
    assert len(previous) == 1
    connection = sqlite3.connect(previous[0])
    try:
        assert connection.execute("SELECT name FROM sessions").fetchone()[0] == "Modificado"
    finally:
        connection.close()
