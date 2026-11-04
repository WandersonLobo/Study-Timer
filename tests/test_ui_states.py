"""Callbacks reais da aplicação com widgets simulados, SQLite e relógio controlado."""

import importlib.util
import sqlite3
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest

from app.database.repository import StudyRepository
from app.models import SessionStatus
from app.services.clock_service import ClockService
from app.services.preferences_service import PreferencesService
from app.services.report_service import ReportService
from app.services.study_type_service import StudyTypeService
from app.services.timer_service import TimerService
from app.windows_power import WindowsPowerMonitor
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_recovery import deny_commit
from tests.test_timer import completed_seconds


class Widget:
    """Simula somente widgets e fila after; não substitui serviços ou SQL."""

    def __init__(self, *args: object, **kwargs: Any) -> None:
        self.options = kwargs
        self._canvas = self
        self.bindings: dict[str, Callable[..., object]] = {}
        self.value = ""
        self.jobs: dict[str, tuple[int, Callable[[], None]]] = {}
        self.destroyed = False
        self.sequence = 0

    def configure(self, **kwargs: Any) -> None:
        self.options.update(kwargs)

    def grid(self, *args: object, **kwargs: object) -> None:
        pass

    pack = grid
    grid_remove = grid
    grid_rowconfigure = grid
    grid_columnconfigure = grid
    title = grid
    geometry = grid
    minsize = grid
    protocol = grid
    lift = grid
    update_idletasks = grid

    def winfo_id(self) -> int:
        return 0

    def set(self, value: str) -> None:
        self.value = value

    def cget(self, key: str) -> Any:
        return self.options.get(key)

    def bind(self, sequence: str, callback: Callable[..., object], **kwargs: object) -> None:
        self.bindings[sequence] = callback

    focus_set = grid

    def get(self) -> str:
        return self.value

    def delete(self, *args: object) -> None:
        self.value = ""

    def insert(self, index: int, text: str) -> None:
        self.value = text

    def after(self, delay: int, callback: Callable[[], None]) -> str:
        self.sequence += 1
        key = str(self.sequence)
        self.jobs[key] = (delay, callback)
        return key

    def after_idle(self, callback: Callable[[], None]) -> str:
        return self.after(0, callback)

    def after_cancel(self, key: str) -> None:
        del self.jobs[key]

    def destroy(self) -> None:
        self.destroyed = True

    def fire(self, delay: int) -> None:
        key = next(key for key, (ms, _) in self.jobs.items() if ms == delay)
        _, callback = self.jobs.pop(key)
        callback()


@pytest.fixture
def ui_modules(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ModuleType, Mock]]:
    monkeypatch.setattr(WindowsPowerMonitor, "start", lambda self, hwnd: None)
    ctk = ModuleType("customtkinter")
    for name in (
        "CTk",
        "CTkFrame",
        "CTkScrollableFrame",
        "CTkLabel",
        "CTkButton",
        "CTkEntry",
        "CTkOptionMenu",
        "CTkToplevel",
    ):
        ctk.__dict__[name] = Widget
    ctk.__dict__["set_appearance_mode"] = Mock()
    dialogs = Mock()
    dialogs.askyesnocancel.return_value = None
    tk = ModuleType("tkinter")
    tk.__dict__["messagebox"] = dialogs
    monkeypatch.setitem(sys.modules, "customtkinter", ctk)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    root = Path(__file__).resolve().parent.parent
    modules = []
    for name, relative in (
        ("app.ui.theme", "app/ui/theme.py"),
        ("app.ui.study_type_dialog", "app/ui/study_type_dialog.py"),
        ("app.ui.timer_view", "app/ui/timer_view.py"),
        ("app.ui.history_view", "app/ui/history_view.py"),
        ("app.application", "app/application.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, root / relative)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        if name == "app.ui.theme":
            import app.ui

            monkeypatch.setattr(app.ui, "theme", module, raising=False)
        modules.append(module)
    yield modules[-1], dialogs


@pytest.fixture
def setup_ui(
    ui_modules: tuple[ModuleType, Mock], connection: sqlite3.Connection
) -> tuple[Any, TimerService, StudyRepository, FakeClock, Mock]:
    module, dialogs = ui_modules
    source = FakeClock()
    repository = StudyRepository(connection)
    timer = TimerService(repository, ClockService(source))
    app = module.Application(
        timer,
        ReportService(repository),
        StudyTypeService(repository),
        PreferencesService(repository),
    )
    return app, timer, repository, source, dialogs


def test_buttons_drive_full_cycle_and_exclude_pauses(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    view = app._timer_view
    assert view.start_button.options["state"] == "normal"
    assert view.finish_button.options["state"] == "disabled"
    view.name_entry.value = "  Matemática  "
    view.start_button.options["command"]()
    session = timer.get_active_session()
    assert session is not None
    assert view.name_entry.options["state"] == "disabled"
    assert view.name_entry.value == "Matemática"
    assert view.start_button.options["state"] == "disabled"
    for _ in range(20):
        source.advance(250_000_000)
        app.fire(250)
    app.fire(5000)
    interval = repository.get_open_interval(session.id)
    assert interval is not None and interval.last_seen_at == session.created_at + 5
    assert view.elapsed_label.options["text"] == "00:00:05"
    view.pause_button.options["command"]()
    assert view.start_button.options["text"] == "Retomar"
    assert view.pause_button.options["state"] == "disabled"
    source.advance(3600 * SECOND_NS)
    view.start_button.options["command"]()
    for _ in range(8):
        source.advance(250_000_000)
        app.fire(250)
    view.finish_button.options["command"]()
    assert completed_seconds(repository, session.id) == 7
    assert timer.get_active_session() is None
    assert view.name_entry.options["state"] == "normal"
    assert view.elapsed_label.options["text"] == "00:00:00"
    dialogs.showerror.assert_not_called()


def test_close_pauses_and_cancels_callbacks(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, repository, source, _ = setup_ui
    app.on_start()
    source.advance(SECOND_NS)
    app.fire(250)
    session = timer.get_active_session()
    assert session is not None
    app.on_close()
    assert app.destroyed and not app.jobs
    assert not timer.is_running
    paused = repository.get_session(session.id)
    assert paused is not None and paused.status == SessionStatus.PAUSED
    assert completed_seconds(repository, session.id) == 1


@pytest.mark.parametrize("operation", ["pause", "finish", "heartbeat", "close"])
def test_write_failure_stops_counting_and_can_be_retried(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
    operation: str,
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    app.on_start()
    source.advance(SECOND_NS)
    app.fire(250)
    session = timer.get_active_session()
    assert session is not None
    command = {
        "pause": app.on_pause,
        "finish": app.on_finish,
        "heartbeat": lambda: app.fire(5000),
        "close": app.on_close,
    }[operation]
    connection.set_authorizer(deny_commit)
    try:
        command()
    finally:
        connection.set_authorizer(None)
    assert not app.destroyed and not timer.is_running
    assert timer.persistence_failed
    assert "não confirmada" in app._timer_view.status_label.options["text"]
    dialogs.showerror.assert_called_once()
    source.advance(3600 * SECOND_NS)
    app.fire(250)
    app.fire(5000)
    assert timer.persistence_failed
    if operation == "heartbeat":
        app.on_pause()
    else:
        command()
    assert not timer.persistence_failed
    assert completed_seconds(repository, session.id) == 1


@pytest.mark.parametrize("choice", [True, False, None])
def test_recovery_dialog_requires_an_explicit_choice(
    ui_modules: tuple[ModuleType, Mock], connection: sqlite3.Connection, choice: bool | None
) -> None:
    module, dialogs = ui_modules
    repository = StudyRepository(connection)
    session, _ = repository.start_session("Recuperada", 1000)
    source = FakeClock()
    timer = TimerService(repository, ClockService(source))
    timer.recover_pending()
    dialogs.askyesnocancel.return_value = choice
    app = module.Application(
        timer,
        ReportService(repository),
        StudyTypeService(repository),
        PreferencesService(repository),
    )
    assert "recuperada" in app._timer_view.status_label.options["text"]
    assert not timer.is_running and source.read_count == 0
    app.fire(0)
    assert timer.is_running == (choice is True)
    result = repository.get_session(session.id)
    assert result is not None
    expected = (
        SessionStatus.RUNNING
        if choice is True
        else SessionStatus.FINISHED
        if choice is False
        else SessionStatus.PAUSED
    )
    assert result.status == expected


def test_gap_pauses_immediately_and_navigation_preserves_the_timer(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    app.show_view("history")
    source.advance(SECOND_NS)
    app.fire(250)
    source.advance(20 * SECOND_NS)
    app.fire(250)
    assert not timer.is_running
    assert completed_seconds(repository, session.id) == 1
    dialogs.showinfo.assert_called_once()
    app.fire(250)
    dialogs.showinfo.assert_called_once()


def test_invalid_name_is_editable_and_errors_hide_private_details(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, _, _, dialogs = setup_ui
    app._timer_view.name_entry.value = "x" * 121
    app.on_start()
    assert timer.get_active_session() is None
    assert app._timer_view.name_entry.options["state"] == "normal"
    app._handle_error(OSError(r"C:\Users\NomePrivado\Estudo"))
    assert "NomePrivado" not in str(dialogs.showerror.call_args)


@pytest.mark.parametrize("resume", [False, True])
def test_failed_start_or_resume_keeps_a_safe_retry_available(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
    resume: bool,
) -> None:
    app, timer, _, _, dialogs = setup_ui
    if resume:
        app.on_start()
        app.on_pause()
    connection.set_authorizer(deny_commit)
    try:
        app.on_start()
    finally:
        connection.set_authorizer(None)
    assert not timer.is_running
    assert app._timer_view.start_button.options["state"] == "normal"
    assert app._timer_view.name_entry.options["state"] == ("disabled" if resume else "normal")
    dialogs.showerror.assert_called_once()
    app.on_start()
    assert timer.is_running and not timer.persistence_failed


def test_source_failure_keeps_snapshot_and_allows_persisting_the_pause(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    source.advance(SECOND_NS)
    app.fire(250)
    source.failure = OSError("Origem privada")
    app.fire(250)
    assert not timer.is_running
    dialogs.showerror.assert_called_once()
    app.on_pause()
    assert completed_seconds(repository, session.id) == 1


def test_idle_close_does_not_create_a_session(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, _, source, _ = setup_ui
    app.on_close()
    assert app.destroyed and timer.get_active_session() is None
    assert source.read_count == 0


def test_close_before_recovery_dialog_cancels_all_pending_callbacks(
    ui_modules: tuple[ModuleType, Mock],
    connection: sqlite3.Connection,
) -> None:
    module, dialogs = ui_modules
    repository = StudyRepository(connection)
    repository.start_session("Pendente", 1000)
    timer = TimerService(repository, ClockService(FakeClock()))
    timer.recover_pending()
    app = module.Application(
        timer,
        ReportService(repository),
        StudyTypeService(repository),
        PreferencesService(repository),
    )
    app.on_close()
    assert app.destroyed and not app.jobs
    dialogs.askyesnocancel.assert_not_called()
