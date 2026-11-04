"""Energia: mensagens Win32 reais e duração simulada sem suspender o computador."""

import ctypes
import gc
import sqlite3
import sys
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import Mock

import pytest

from app.database.repository import StudyRepository
from app.models import (
    AppearanceMode,
    HistorySelection,
    PauseReason,
    ReportPeriod,
    SessionStatus,
    StudyColor,
)
from app.services.timer_service import TimerService
from app.windows_power import (
    POWER_EVENTS,
    WM_POWERBROADCAST,
    WindowsPowerMonitor,
)
from tests import test_ui_states
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_recovery import deny_commit
from tests.test_timer import completed_seconds

setup_ui = test_ui_states.setup_ui
ui_modules = test_ui_states.ui_modules


@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
@pytest.mark.parametrize("view", ["timer", "history"])
@pytest.mark.parametrize("already_paused", [False, True])
def test_power_events_preserve_type_theme_and_history(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    mode: AppearanceMode,
    view: str,
    already_paused: bool,
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    reference = date(2024, 5, 10)
    monkeypatch.setattr(app._reports, "get_today", lambda: reference)
    monkeypatch.setattr(app._reports, "_timezone_source", lambda: UTC)
    source.wall_time_s = datetime(2024, 5, 10, 12, tzinfo=UTC).timestamp()
    app._history_selection = HistorySelection(ReportPeriod.DAY, reference)
    kind = app._types.create_type("Tipo de energia", StudyColor.BLUE)
    app._type_saved(kind.id)
    app.on_appearance("Claro" if mode == AppearanceMode.LIGHT else "Escuro")
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    source.advance(SECOND_NS)
    app.fire(250)
    if already_paused:
        app.on_pause()
    app.show_view(view)
    source.advance(200_000_000)
    app._power.notify(4)
    reads = source.read_count
    source.advance(3600 * SECOND_NS)
    app._power.notify(18)
    app.fire(250)
    assert source.read_count == reads and not timer.is_running
    pending = timer.get_active_session()
    assert pending is not None and pending.study_type_id == kind.id
    assert pending.status == SessionStatus.PAUSED
    assert completed_seconds(repository, session.id) == 1
    assert app._preferences.get_appearance_mode() == mode
    assert app._timer_view.get_type_id() == kind.id
    assert len(repository.get_session_intervals(session.id)) == 1
    if view == "history":
        assert app._history_view.report.total_s == 1
        assert app._history_view.report.ranking[0].type_id == kind.id
    app.on_start()
    source.advance(SECOND_NS)
    app.fire(250)
    app.on_finish()
    assert completed_seconds(repository, session.id) == 2
    dialogs.showerror.assert_not_called()


@pytest.mark.parametrize("event", sorted(POWER_EVENTS))
@pytest.mark.parametrize("monotonic_advances", [False, True])
def test_power_event_excludes_sleep_and_requires_explicit_resume(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    event: int,
    monotonic_advances: bool,
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    source.advance(SECOND_NS)
    app.fire(250)
    source.advance(200_000_000)  # Fração ainda não confirmada.
    count = source.read_count
    app._power.notify(event)
    assert not timer.is_running and app._power.pending
    # Nem SQL nem UI no callback nativo: sessão ainda running até a fila Tk.
    assert timer.get_active_session() == session
    source.advance(3600 * SECOND_NS if monotonic_advances else 0, wall_delta_s=3600)
    app.fire(250)
    app._power.notify(18)
    app._power.notify(7)
    app.fire(5000)
    assert source.read_count == count
    assert completed_seconds(repository, session.id) == 1
    paused = timer.get_active_session()
    assert paused is not None and paused.status == SessionStatus.PAUSED
    assert app._timer_view.start_button.options["text"] == "Retomar"
    assert len(repository.get_session_intervals(session.id)) == 1
    app.on_start()
    source.advance(SECOND_NS)
    app.fire(250)
    app.on_finish()
    assert completed_seconds(repository, session.id) == 2
    dialogs.showerror.assert_not_called()


def test_queued_user_action_first_drains_the_power_pause(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, repository, _, _ = setup_ui
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    app._power.notify(18)
    app.on_start()
    assert not timer.is_running
    assert len(repository.get_session_intervals(session.id)) == 1
    app.on_start()
    assert timer.is_running


def test_power_pause_failure_preserves_first_reason_and_frozen_cut(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    connection: sqlite3.Connection,
) -> None:
    app, timer, repository, source, dialogs = setup_ui
    app.on_start()
    session = timer.get_active_session()
    assert session is not None
    source.advance(SECOND_NS)
    app.fire(250)
    app._power.notify(4)
    connection.set_authorizer(deny_commit)
    try:
        app.fire(250)
    finally:
        connection.set_authorizer(None)
    assert timer.persistence_failed and not timer.is_running
    assert timer._clock.pause_reason == PauseReason.SUSPEND
    dialogs.showerror.assert_called_once()
    source.advance(3600 * SECOND_NS)
    app.on_pause()
    assert completed_seconds(repository, session.id) == 1
    assert not timer.persistence_failed


def test_unrelated_event_does_not_pause(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
) -> None:
    app, timer, _, _, _ = setup_ui
    app.on_start()
    assert not app._power.notify(10)  # PBT_APMPOWERSTATUSCHANGE, bateria/AC.
    assert timer.is_running and not app._power.pending


@pytest.mark.parametrize("state", ["idle", "paused", "finished"])
def test_power_events_preserve_nonrunning_states(
    setup_ui: tuple[Any, TimerService, StudyRepository, FakeClock, Mock],
    state: str,
) -> None:
    app, timer, _, source, dialogs = setup_ui
    if state != "idle":
        app.on_start()
        app.on_pause()
        if state == "finished":
            app.on_finish()
    previous = timer.get_active_session()
    count = source.read_count
    app._power.notify(4)
    app.fire(250)
    app._power.notify(18)
    app.fire(250)
    assert timer.get_active_session() == previous
    assert not timer.is_running and source.read_count == count
    dialogs.showerror.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="API Win32")
@pytest.mark.parametrize("destroy_first", [False, True])
def test_native_hwnd_subclass_receives_messages_and_releases_resources(destroy_first: bool) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.argtypes = [
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    user32.DestroyWindow.restype = ctypes.c_int
    # Janela nativa oculta, sem Tk e sem suspender o PC.
    hwnd = user32.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0, None, None, None, None)
    assert hwnd
    interrupted = Mock()
    monitor = WindowsPowerMonitor(interrupted)
    try:
        baseline = user32.SendMessageW(hwnd, WM_POWERBROADCAST, 10, 0)
        monitor.start(hwnd)
        with pytest.raises(RuntimeError):
            monitor.start(hwnd)
        gc.collect()  # Callback permanece vivo com ponteiros de tamanho nativo.
        for event in sorted(POWER_EVENTS):
            assert user32.SendMessageW(hwnd, WM_POWERBROADCAST, event, 0) == 1
        assert interrupted.call_count == 4 and monitor.take_pending()
        assert not monitor.take_pending()
        assert user32.SendMessageW(hwnd, WM_POWERBROADCAST, 10, 0) == baseline
        if destroy_first:
            assert user32.DestroyWindow(hwnd)
            assert monitor._hwnd is None and monitor._registration is None
        monitor.close()
        monitor.close()
        if not destroy_first:
            user32.SendMessageW(hwnd, WM_POWERBROADCAST, 4, 0)
        assert interrupted.call_count == 4
    finally:
        monitor.close()
        if not destroy_first:
            user32.DestroyWindow(hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="API Win32")
def test_invalid_window_fails_explicitly() -> None:
    monitor = WindowsPowerMonitor(Mock())
    with pytest.raises(OSError):
        monitor.start(0)
    monitor.close()


def test_registration_failure_removes_partial_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    user32, comctl32 = Mock(), Mock()
    user32.GetAncestor.return_value = 123
    user32.RegisterSuspendResumeNotification.return_value = None
    comctl32.SetWindowSubclass.return_value = 1
    comctl32.RemoveWindowSubclass.return_value = 1
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name, **kwargs: user32 if name == "user32" else comctl32
    )
    monitor = WindowsPowerMonitor(Mock())
    with pytest.raises(OSError):
        monitor.start(123)
    comctl32.RemoveWindowSubclass.assert_called_once()
    user32.UnregisterSuspendResumeNotification.assert_not_called()
    monitor.close()


def test_callback_failure_cannot_escape_the_native_boundary() -> None:
    callback = Mock(side_effect=OSError("Caminho privado"))
    monitor = WindowsPowerMonitor(callback)
    monitor._comctl32 = Mock()
    monitor._comctl32.DefSubclassProc.return_value = 42
    assert monitor._window_proc(123, WM_POWERBROADCAST, 4, 0, 0, 0) == 42
    assert monitor.pending


def test_notification_cleanup_failure_allows_retry() -> None:
    monitor = WindowsPowerMonitor(Mock())
    monitor._hwnd = 123
    monitor._registration = 456
    monitor._user32 = Mock()
    monitor._comctl32 = Mock()
    monitor._user32.UnregisterSuspendResumeNotification.side_effect = [0, 1]
    monitor._comctl32.RemoveWindowSubclass.return_value = 1
    with pytest.raises(OSError):
        monitor.close()
    monitor._comctl32.RemoveWindowSubclass.assert_not_called()
    monitor.close()
    assert monitor._hwnd is None and monitor._registration is None
