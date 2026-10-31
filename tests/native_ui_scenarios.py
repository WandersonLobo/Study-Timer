"""Aceite repetível com widgets Tk reais e banco temporário; sem suspensão física."""

import socket
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date
from pathlib import Path
from time import perf_counter
from tkinter import Misc
from unittest.mock import Mock

import pytest

from app.application import Application
from app.database.backup import create_backup, restore_backup
from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.models import SessionStatus
from app.services.clock_service import ClockService
from app.services.report_service import ReportService
from app.services.timer_service import TimerService
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_recovery import deny_commit
from tests.test_reports import add_interval, stamp


@contextmanager
def native_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection]]:
    from tkinter import messagebox

    for name in ("showerror", "showinfo", "askyesnocancel"):
        monkeypatch.setattr(messagebox, name, Mock(return_value=None))
    connection = initialize_database(tmp_path / "estudos.db")
    repository = StudyRepository(connection)
    source = FakeClock(wall_time_s=stamp(2024, 5, 10, 12) + 0.75)
    timer = TimerService(repository, ClockService(source))
    reports = ReportService(repository, lambda: UTC)
    monkeypatch.setattr(reports, "get_today", lambda: date(2024, 5, 10))
    app = Application(timer, reports)
    app.withdraw()
    try:
        yield app, timer, repository, source, connection
    finally:
        if not app._closed:
            connection.set_authorizer(None)
            connection.execute("PRAGMA query_only = OFF")
            app.on_close()
        connection.close()


def step(app: Application, source: FakeClock, seconds: int) -> None:
    """Entrega callbacks determinísticos sem dormir ou criar cadeias after duplicadas."""
    for _ in range(seconds * 4):
        source.advance(250_000_000)
        if app._tick_job is not None:
            app.after_cancel(app._tick_job)
        app._poll()
    app.update_idletasks()


def assert_visible(app: Application, widget: Misc) -> None:
    """Confere o widget realmente exposto, incluindo o contêiner rolável externo."""
    app.update_idletasks()
    content = app._timer_view.master
    surface = widget
    while surface.master is not content:
        parent = surface.master
        assert parent is not None
        surface = parent
    # winfo children retorna a ordem de empilhamento, do fundo para a frente.
    # Evita depender de outras janelas do desktop sobrepostas durante o teste.
    assert content.winfo_children()[-1] is surface, "A tela selecionada está encoberta"


def test_native_full_cycle_and_minimum_window(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, timer, repository, source, _ = native_app
    app.deiconify()
    app.geometry("900x600")
    app.update_idletasks()
    prefix = "Nome de teste "
    app._timer_view.name_entry.insert(0, prefix + "x" * (120 - len(prefix)))
    app._timer_view.start_button.invoke()
    session = timer.get_active_session()
    assert session is not None
    assert app._timer_view.name_entry.cget("state") == "disabled"
    step(app, source, 2)
    app.show_view("history")
    app.update_idletasks()
    assert_visible(app, app._history_view.month_label)
    assert app._history_view._session_data[0].duration_s == 2
    for button in app._history_view.day_buttons:
        assert button.winfo_rootx() >= app.winfo_rootx()
        assert button.winfo_rootx() + button.winfo_width() <= app.winfo_rootx() + app.winfo_width()
    app._history_view.previous_button.invoke()
    assert app._calendar_month == (2024, 4)
    step(app, source, 1)
    app._history_view.today_button.invoke()
    assert app._history_view._session_data[0].duration_s == 3
    app.show_view("timer")
    assert_visible(app, app._timer_view.elapsed_label)
    app._timer_view.pause_button.invoke()
    source.advance(3600 * SECOND_NS)
    app._timer_view.start_button.invoke()
    step(app, source, 2)
    app._timer_view.finish_button.invoke()
    assert timer.get_active_session() is None
    assert (
        sum(
            i.ended_at - i.started_at
            for i in repository.get_session_intervals(session.id)
            if i.ended_at is not None
        )
        == 5
    )
    app.on_close()
    assert app._closed


def test_native_failed_commit_close_retry_and_recovery(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, timer, repository, source, connection = native_app
    app.on_start()
    step(app, source, 3)
    session = timer.get_active_session()
    assert session is not None
    connection.set_authorizer(deny_commit)
    app.on_close()
    connection.set_authorizer(None)
    assert not app._closed and not timer.is_running
    assert timer.persistence_failed and app._failed
    source.advance(3600 * SECOND_NS)
    app.on_close()
    assert app._closed
    recovered = TimerService(repository, ClockService(FakeClock()))
    paused = recovered.recover_pending()
    assert paused is not None and paused.status == SessionStatus.PAUSED
    assert recovered.get_elapsed_seconds() == 3


def test_native_ui_without_socket_access_and_backup_restore(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, timer, repository, source, connection = native_app
    monkeypatch.setattr(
        socket, "socket", Mock(side_effect=AssertionError("Rede bloqueada no teste"))
    )
    app.on_start()
    step(app, source, 2)
    app.on_pause()
    app.show_view("history")
    assert app._history_view._session_data[0].duration_s == 2
    app.on_finish()
    backup = create_backup(connection, tmp_path / "backups")
    add_interval(repository, stamp(2024, 5, 10, 13), 35)
    app.on_close()
    connection.close()
    restore_backup(backup, tmp_path / "estudos.db")
    reopened = initialize_database(tmp_path / "estudos.db")
    try:
        assert reopened.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
        assert reopened.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reopened.close()


def test_native_history_thousand_sessions(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, repository, _, _ = native_app
    start = stamp(2024, 5, 10, 12)
    with repository.transaction() as database:
        database.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
            [(i, "Desempenho sintético", start, start + 35, "finished") for i in range(1, 1001)],
        )
        database.executemany(
            "INSERT INTO study_intervals VALUES (?, ?, ?, ?, ?)",
            [(i, i, start, start + 35, start + 35) for i in range(1, 1001)],
        )
    began = perf_counter()
    app.show_view("history")
    app.update_idletasks()
    elapsed = perf_counter() - began
    assert len(app._history_view._session_data) == 1000
    assert len(app._history_view._session_rows) == 100
    assert elapsed < 2, f"Histórico levou {elapsed:.3f}s"
    print(f"Native history / 1000 sessions / first page: {elapsed:.3f}s")
    app._history_view.more_button.invoke()
    assert len(app._history_view._session_rows) == 200
    app.on_close()


if __name__ == "__main__":
    scenarios = {
        "cycle": test_native_full_cycle_and_minimum_window,
        "recovery": test_native_failed_commit_close_retry_and_recovery,
        "offline_backup": test_native_ui_without_socket_access_and_backup_restore,
        "history_1000": test_native_history_thousand_sessions,
    }
    with pytest.MonkeyPatch.context() as patch:
        with native_app(Path(sys.argv[2]), patch) as state:
            scenarios[sys.argv[1]](state, Path(sys.argv[2]), patch)
