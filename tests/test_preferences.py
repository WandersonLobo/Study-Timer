"""Preferência de aparência local com validação e rollback reais."""

import sqlite3
from pathlib import Path

import pytest

from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.models import AppearanceMode
from app.services.preferences_service import PreferencesService
from tests.test_recovery import deny_commit


def test_default_and_both_modes_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "preferences.db"
    for mode in (AppearanceMode.LIGHT, AppearanceMode.DARK):
        connection = initialize_database(path)
        try:
            service = PreferencesService(StudyRepository(connection))
            assert service.get_appearance_mode() == AppearanceMode.DARK
            service.set_appearance_mode(mode)
        finally:
            connection.close()
        connection = initialize_database(path)
        try:
            service = PreferencesService(StudyRepository(connection))
            assert service.get_appearance_mode() == mode
            service.set_appearance_mode(AppearanceMode.DARK)
        finally:
            connection.close()


def test_invalid_mode_and_commit_failure_preserve_preference(
    connection: sqlite3.Connection,
) -> None:
    service = PreferencesService(StudyRepository(connection))
    with pytest.raises(ValueError):
        service.set_appearance_mode("system")  # type: ignore[arg-type]
    connection.set_authorizer(deny_commit)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            service.set_appearance_mode(AppearanceMode.LIGHT)
    finally:
        connection.set_authorizer(None)
    assert service.get_appearance_mode() == AppearanceMode.DARK
    assert not connection.in_transaction


def test_database_constraints_and_missing_preference_are_not_silently_reset(
    connection: sqlite3.Connection,
) -> None:
    service = PreferencesService(StudyRepository(connection))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE app_preferences SET appearance_mode = 'invalid'")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO app_preferences VALUES (2, 'dark')")
    connection.execute("DELETE FROM app_preferences")
    for action in (
        service.get_appearance_mode,
        lambda: service.set_appearance_mode(AppearanceMode.LIGHT),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            action()
