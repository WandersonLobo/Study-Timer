"""Histórico integrado aos serviços reais com widgets e relógio controlados."""

import calendar
import sqlite3
from datetime import UTC, date
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest

from app.database.repository import StudyRepository
from app.services.clock_service import ClockService
from app.services.preferences_service import PreferencesService
from app.services.report_service import ReportService
from app.services.study_type_service import StudyTypeService
from app.services.timer_service import TimerService
from app.ui.history_view import intensity_color
from tests import test_ui_states
from tests.test_clock import FakeClock
from tests.test_recovery import deny_commit
from tests.test_reports import add_interval, stamp

ui_modules = test_ui_states.ui_modules


@pytest.fixture
def history_app(
    ui_modules: tuple[ModuleType, Mock],
    connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, TimerService, StudyRepository, FakeClock, Mock]:
    module, dialogs = ui_modules
    repository = StudyRepository(connection)
    source = FakeClock(wall_time_s=stamp(2024, 5, 10, 12) + 0.75)
    timer = TimerService(repository, ClockService(source))
    reports = ReportService(repository, lambda: UTC)
    monkeypatch.setattr(reports, "get_today", lambda: date(2024, 5, 10))
    app = module.Application(
        timer, reports, StudyTypeService(repository), PreferencesService(repository)
    )
    return app, timer, repository, source, dialogs


def test_month_navigation_changes_calendar_without_changing_current_cards(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, _, repository, _, dialogs = history_app
    add_interval(repository, stamp(2024, 5, 10, 12), 35)
    add_interval(repository, stamp(2024, 5, 10, 13), 35)
    add_interval(repository, stamp(2024, 4, 10, 12), 120, "Abril")
    app.show_view("history")
    view = app._history_view
    before = [label.options["text"] for label in view.total_labels]
    assert before == ["1 min", "1 min", "1 min"]
    assert "Maio" in view.month_label.options["text"]
    view.previous_button.options["command"]()
    assert "Abril" in view.month_label.options["text"]
    assert view.month_total_label.options["text"] == "Total do mês exibido: 2 min"
    assert [label.options["text"] for label in view.total_labels] == before
    slot = calendar.monthrange(2024, 4)[0] + 9
    view.day_buttons[slot].options["command"]()
    assert app._selected_day == date(2024, 4, 10)
    assert view._session_rows[0].options["text"] == "Abril"
    assert view._session_rows[1].options["text"] == "00:02:00"
    view.today_button.options["command"]()
    assert app._selected_day == date(2024, 5, 10)
    dialogs.showerror.assert_not_called()


def test_live_session_is_visible_before_heartbeat_and_once_only(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, repository, source, _ = history_app
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    app.show_view("history")
    for _ in range(8):
        source.advance(250_000_000)
        app.fire(250)
    view = app._history_view
    assert view._session_data[0].duration_s == 2
    interval = repository.get_open_interval(session.id)
    assert interval is not None and interval.last_seen_at == interval.started_at
    assert len(view._session_rows) == 2
    rows = tuple(view._session_rows)
    app.fire(5000)
    assert view._session_data[0].duration_s == 2
    assert tuple(view._session_rows) == rows
    app.on_pause()
    source.advance(100_000_000_000)
    app.fire(250)
    assert view._session_data[0].duration_s == 2
    assert timer.get_snapshot() is None


def test_idle_history_updates_current_cards_after_a_day_change(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, repository, _, _ = history_app
    add_interval(repository, stamp(2024, 5, 10, 12), 70)
    app.show_view("history")
    assert app._history_view.total_labels[0].options["text"] == "1 min"
    monkeypatch.setattr(app._reports, "get_today", lambda: date(2024, 5, 11))
    app.fire(250)
    assert app._history_view.total_labels[0].options["text"] == "0 min"
    assert app._history_view.total_labels[1].options["text"] == "1 min"


def test_calendar_year_boundaries_and_empty_days(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, _, _, _, dialogs = history_app
    app.show_view("history")
    app.on_month(-5)
    assert app._calendar_month == (2023, 12)
    app.on_month(1)
    assert app._calendar_month == (2024, 1)
    view = app._history_view
    assert len(view.day_buttons) == 42
    assert sum(b.options["state"] == "normal" for b in view.day_buttons) == 31
    assert view._session_data == ()
    app._calendar_month = (1, 1)
    app.on_month(-1)
    assert app._calendar_month == (1, 1)
    assert view.previous_button.options["state"] == "disabled"
    dialogs.showerror.assert_not_called()


def test_details_paginate_large_days_without_rebuilding_calendar(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, _, repository, _, _ = history_app
    start = stamp(2024, 5, 10, 12)
    with repository.transaction() as database:
        database.executemany(
            "INSERT INTO sessions (id, name, created_at, finished_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            [(i, "Sessão de teste", start, start + 35, "finished") for i in range(1, 121)],
        )
        database.executemany(
            "INSERT INTO study_intervals VALUES (?, ?, ?, ?, ?)",
            [(i, i, start, start + 35, start + 35) for i in range(1, 121)],
        )
    app.show_view("history")
    view = app._history_view
    cells = tuple(view.day_buttons)
    assert len(view._session_data) == 120 and len(view._session_rows) == 100
    view.more_button.options["command"]()
    assert len(view._session_rows) == 200
    app.fire(250)
    assert len(view._session_rows) == 200 and tuple(view.day_buttons) == cells
    view.more_button.options["command"]()
    assert len(view._session_rows) == 240
    assert view.more_button.options["state"] == "disabled"


def test_failed_write_in_history_freezes_and_marks_previous_values_stale(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, timer, _, source, dialogs = history_app
    app.on_start()
    app.show_view("history")
    source.advance(1_000_000_000)
    app.fire(250)
    connection.set_authorizer(deny_commit)
    try:
        app.on_pause()
    finally:
        connection.set_authorizer(None)
    assert not timer.is_running
    assert "não atualizado" in app._history_view.status_label.options["text"]
    dialogs.showerror.assert_called_once()
    source.advance(3600_000_000_000)
    app.on_pause()
    assert app._history_view._session_data[0].duration_s == 1


def test_calendar_intensity_uses_absolute_duration_bands() -> None:
    values = [intensity_color(s) for s in (0, 35, 900, 3600, 7200)]
    assert len(set(values)) == 5
    assert intensity_color(1) == intensity_color(899)
    assert intensity_color(900) == intensity_color(3599)
