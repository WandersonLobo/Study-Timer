"""Histórico integrado com filtros, navegação e relógio controlado."""

import sqlite3
from datetime import UTC, date
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest

from app.database.repository import StudyRepository
from app.models import HistorySelection, ReportPeriod, StudyColor
from app.services.clock_service import ClockService
from app.services.preferences_service import PreferencesService
from app.services.report_service import ReportService
from app.services.study_type_service import StudyTypeService
from app.services.timer_service import TimerService
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


def test_selected_period_controls_every_metric_and_navigation(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, _, repository, _, dialogs = history_app
    add_interval(repository, stamp(2024, 5, 10, 12), 70)
    add_interval(repository, stamp(2024, 4, 10, 12), 120, "Abril")
    app.show_view("history")
    view = app._history_view
    assert view.report.total_s == 70 and view.average_label.options["text"] == "1min"
    app.on_period_mode(ReportPeriod.MONTH)
    assert view.report.total_s == 70
    app.on_period_step(-1)
    assert view.report.total_s == 120 and view.total_label.options["text"] == "2min"
    assert view.report.selection.reference == date(2024, 4, 1)
    assert "Abril" in view.period_label.options["text"]
    app.on_today()
    assert view.report.start_day == date(2024, 5, 1)
    assert view.report.average_days == 10
    assert app._history_selection.period == ReportPeriod.MONTH
    app.on_period_step(1)
    assert view.report.start_day == date(2024, 5, 1)
    dialogs.showerror.assert_not_called()


def test_ticks_and_recovery_checkpoint_leave_sqlite_and_history_unchanged(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, timer, repository, source, _ = history_app
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    app.show_view("history")
    view = app._history_view
    before = view.report
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        for _ in range(8):
            source.advance(250_000_000)
            app.fire(250)
        app.fire(5000)
    finally:
        connection.set_trace_callback(None)
    assert statements == []
    assert view.report is before and before.total_s == 0
    assert app._timer_view.elapsed_label.options["text"] == "00:00:02"
    interval = repository.get_open_interval(session.id)
    assert interval is not None and interval.last_seen_at == interval.started_at
    app.on_pause()
    source.advance(100_000_000_000)
    app.fire(250)
    assert view.report.total_s == 2 and timer.get_snapshot() is None


def test_midnight_preserves_reference_and_updates_partial_mean(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, repository, _, _ = history_app
    add_interval(repository, stamp(2024, 5, 10, 12), 70)
    app.on_period_mode(ReportPeriod.WEEK)
    app.show_view("history")
    assert app._history_view.report.average_days == 5
    monkeypatch.setattr(app._reports, "get_today", lambda: date(2024, 5, 11))
    app.fire(250)
    assert app._history_view.report.average_days == 5
    app.show_view("timer")
    app.show_view("history")
    assert app._history_view.report.average_days == 6
    assert app._history_selection.reference == date(2024, 5, 10)
    assert app._history_view.report.total_s == 70


def test_filters_drilldown_back_and_today_preserve_contract(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, _, repository, _, dialogs = history_app
    item = repository.create_study_type("POO", StudyColor.BLUE)
    s, i = repository.start_session("Objetos", stamp(2024, 5, 10, 12), item.id)
    from app.models import ClockSnapshot

    repository.finish_session(s.id, ClockSnapshot(i.id, i.started_at, 120, i.started_at + 120))
    add_interval(repository, stamp(2024, 5, 10, 13), 35)
    app.on_period_mode(ReportPeriod.WEEK)
    app.show_view("history")
    app.on_type_filter(item.id)
    assert app._history_view.report.total_s == 120
    assert app._history_view.filter_label.options["text"] == "POO"
    parent = app._history_selection
    app._history_view.chart.select_bucket(4)
    assert app._history_selection.period == ReportPeriod.DAY
    assert app._history_selection.study_type_id == item.id
    assert app._history_view._session_data[0].name == "Objetos"
    app.on_history_back()
    assert app._history_selection == parent
    app.on_type_filter(None)
    assert app._history_view.report.total_s == 35
    assert app._history_selection.type_filter == "untyped"
    app.on_today()
    assert app._history_selection.period == ReportPeriod.WEEK
    assert app._history_selection.type_filter == "all"
    assert app._history_view.report.total_s == 155
    dialogs.showerror.assert_not_called()


def test_boundaries_and_empty_period(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, _, _, _, dialogs = history_app
    app.show_view("history")
    app._history_selection = HistorySelection(ReportPeriod.MONTH, date(1, 1, 1))
    app.on_period_step(-1)
    assert app._history_selection.reference == date(1, 1, 1)
    assert app._history_view.report.total_s == 0 and app._history_view._session_data == ()
    app.on_today()
    app.on_day(date(2025, 1, 1))
    assert app._history_selection.reference == date(2024, 5, 10)
    dialogs.showerror.assert_not_called()


def test_pagination_and_widget_identity_survive_ticks_and_theme(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, _, repository, _, _ = history_app
    start = stamp(2024, 5, 10, 12)
    with repository.transaction() as db:
        db.executemany(
            "INSERT INTO sessions (id,name,created_at,finished_at,status) VALUES (?,?,?,?,?)",
            [(i, "Sessão", start, start + 35, "finished") for i in range(1, 121)],
        )
        db.executemany(
            "INSERT INTO study_intervals VALUES (?,?,?,?,?)",
            [(i, i, start, start + 35, start + 35) for i in range(1, 121)],
        )
    app.show_view("history")
    view = app._history_view
    assert len(view._session_rows) == 100
    view._show_more()
    rows = tuple(view._session_rows)
    app.fire(250)
    app.on_appearance("Claro")
    assert tuple(view._session_rows) == rows and len(rows) == 200
    view._show_more()
    assert len(view._session_rows) == 240


def test_failed_write_preserves_stale_result_until_safe_retry(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, timer, _, source, dialogs = history_app
    app.on_start()
    app.show_view("history")
    source.advance(1_000_000_000)
    app.fire(250)
    before = app._history_view.report
    connection.set_authorizer(deny_commit)
    try:
        app.on_pause()
    finally:
        connection.set_authorizer(None)
    assert not timer.is_running
    assert app._history_view.report is before
    assert "não atualizado" in app._history_view.status_label.options["text"]
    dialogs.showerror.assert_called_once()
    app.on_pause()
    assert app._history_view.report.total_s == 1


def test_filter_label_in_empty_period_uses_current_type_name(
    history_app: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, _, repository, _, _ = history_app
    item = repository.create_study_type("POO", StudyColor.BLUE)
    app.on_type_filter(item.id)
    app.show_view("history")
    assert app._history_view.filter_label.options["text"] == "POO"
    repository.update_study_type(item.id, "Objetos", StudyColor.PURPLE)
    app.show_view("timer")
    app.show_view("history")
    assert app._history_view.filter_label.options["text"] == "Objetos"
