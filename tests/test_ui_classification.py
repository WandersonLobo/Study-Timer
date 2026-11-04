"""Regressões da classificação e aparência com SQLite e relógio controlados."""

import sqlite3
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest

from app.database.repository import StudyRepository
from app.models import AppearanceMode, StudyColor, UIState
from app.services.clock_service import ClockService
from app.services.preferences_service import PreferencesService
from app.services.report_service import ReportService
from app.services.study_type_service import StudyTypeService
from app.services.timer_service import TimerService
from tests import test_ui_states
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_recovery import deny_commit

ui_modules = test_ui_states.ui_modules
setup_ui = test_ui_states.setup_ui


@pytest.mark.parametrize("state", ["idle", "running", "paused", "recovered"])
def test_appearance_preserves_session_jobs_and_unsaved_text(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    state: str,
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    app._timer_view.name_entry.value = "Descrição ainda não salva"
    if state != "idle":
        app.on_start()
        source.advance(SECOND_NS)
        app.fire(250)
        if state != "running":
            app.on_pause()
        if state == "recovered":
            app._state = UIState.RECOVERED
            app._render()
    session = timer.get_active_session()
    intervals = repository.get_session_intervals(session.id) if session else []
    jobs = dict(app.jobs)
    reads = source.read_count
    for label, mode in (("Claro", AppearanceMode.LIGHT), ("Escuro", AppearanceMode.DARK)):
        app.on_appearance(label)
        assert app._preferences.get_appearance_mode() == mode
        assert app._appearance == mode
        assert app.jobs == jobs
        assert timer.get_active_session() == session
        assert source.read_count == reads
        assert app._timer_view.get_name() == "Descrição ainda não salva"
        if session:
            assert repository.get_session_intervals(session.id) == intervals
    dialogs.showerror.assert_not_called()


def test_failed_preference_write_preserves_running_timer_and_previous_selection(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, timer, _, _, dialogs = setup_ui
    app.on_start()
    jobs = dict(app.jobs)
    connection.set_authorizer(deny_commit)
    try:
        app.on_appearance("Claro")
    finally:
        connection.set_authorizer(None)
    assert timer.is_running and not timer.persistence_failed and not app._failed
    assert app._appearance == AppearanceMode.DARK
    assert app.theme_menu.get() == "Escuro"
    assert app.jobs == jobs
    assert app._preferences.get_appearance_mode() == AppearanceMode.DARK
    dialogs.showerror.assert_called_once()


def test_theme_change_cannot_clear_failed_session_write(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, timer, _, _, _ = setup_ui
    app.on_start()
    connection.set_authorizer(deny_commit)
    try:
        app.on_pause()
    finally:
        connection.set_authorizer(None)
    app.on_appearance("Claro")
    assert timer.persistence_failed and app._failed and not timer.is_running


def test_selection_drives_session_and_only_successful_finish_clears_description(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, timer, repository, source, _ = setup_ui
    item = app._types.create_type("POO", StudyColor.BLUE)
    app._type_saved(item.id)
    view = app._timer_view
    view.name_entry.value = "Herança"
    app.on_start()
    session = timer.get_active_session()
    assert session is not None and session.study_type_id == item.id
    for widget in (view.type_menu, view.new_type_button, view.manage_types_button):
        assert widget.options["state"] == "disabled"
    source.advance(SECOND_NS)
    app.fire(250)
    connection.set_authorizer(deny_commit)
    try:
        app.on_finish()
    finally:
        connection.set_authorizer(None)
    assert view.get_name() == "Herança" and view.get_type_id() == item.id
    app.on_finish()
    assert view.get_name() == "" and view.get_type_id() == item.id
    finished = repository.get_session(session.id)
    assert finished is not None and finished.study_type_id == item.id
    assert view.type_menu.options["state"] == "normal"


def test_recovered_category_is_loaded_before_render_and_theme_before_root(
    ui_modules: tuple[ModuleType, Mock],
    connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _ = ui_modules
    repository = StudyRepository(connection)
    types = StudyTypeService(repository)
    preferences = PreferencesService(repository)
    item = types.create_type("Banco de Dados", StudyColor.TEAL)
    repository.start_session("SQL", 1000, item.id)
    timer = TimerService(repository, ClockService(FakeClock()))
    timer.recover_pending()
    preferences.set_appearance_mode(AppearanceMode.LIGHT)
    order: list[str] = []
    original = test_ui_states.Widget.__init__

    def initialize(self: Any, *args: object, **kwargs: Any) -> None:
        order.append("widget")
        original(self, *args, **kwargs)

    monkeypatch.setattr(test_ui_states.Widget, "__init__", initialize)
    monkeypatch.setattr(module.ctk, "set_appearance_mode", lambda mode: order.append(mode))
    app = module.Application(timer, ReportService(repository), types, preferences)
    assert order[0] == "light"
    assert app._timer_view.get_type_id() == item.id
    assert app._timer_view.get_name() == "SQL"
    assert app._timer_view.new_type_button.options["state"] == "disabled"


def test_catalog_reload_handles_rename_archive_and_keyboard_choice(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, _, _, _, _ = setup_ui
    first = app._types.create_type("POO", StudyColor.BLUE)
    second = app._types.create_type("Redes", StudyColor.ORANGE)
    app._type_saved(first.id)
    app._types.update_type(first.id, "Objetos", StudyColor.PURPLE)
    app._reload_types()
    assert app._timer_view.get_type_id() == first.id
    assert app._timer_view.type_menu.get() == "Objetos"
    menu = app._timer_view.type_menu
    menu.bindings["<Down>"](None)
    assert app._timer_view.get_type_id() == second.id
    app._types.archive_type(second.id)
    app._reload_types()
    assert app._timer_view.get_type_id() is None
