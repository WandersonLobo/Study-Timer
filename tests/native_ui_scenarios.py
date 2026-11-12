"""Aceite repetível com widgets Tk reais e banco temporário; sem suspensão física."""

import ctypes
import os
import socket
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date
from pathlib import Path
from time import perf_counter
from tkinter import BooleanVar, Misc
from unittest.mock import Mock

import pytest

from app.application import Application
from app.database.backup import create_backup, restore_backup
from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.models import AppearanceMode, SessionStatus
from app.services.clock_service import ClockService
from app.services.preferences_service import PreferencesService
from app.services.report_service import ReportService
from app.services.study_type_service import StudyTypeService
from app.services.timer_service import TimerService
from tests.test_clock import SECOND_NS, FakeClock
from tests.test_recovery import deny_commit
from tests.test_reports import add_interval, stamp


@contextmanager
def native_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: AppearanceMode = AppearanceMode.DARK,
) -> Iterator[tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection]]:
    from tkinter import messagebox

    for name in ("showerror", "showinfo", "askyesnocancel"):
        monkeypatch.setattr(messagebox, name, Mock(return_value=None))
    existing = (tmp_path / "estudos.db").exists()
    connection = initialize_database(tmp_path / "estudos.db")
    repository = StudyRepository(connection)
    if not existing:
        PreferencesService(repository).set_appearance_mode(mode)
    source = FakeClock(wall_time_s=stamp(2024, 5, 10, 12) + 0.75)
    timer = TimerService(repository, ClockService(source))
    reports = ReportService(repository, lambda: UTC)
    monkeypatch.setattr(reports, "get_today", lambda: date(2024, 5, 10))
    app = Application(timer, reports, StudyTypeService(repository), PreferencesService(repository))
    app.withdraw()
    try:
        yield app, timer, repository, source, connection
    except BaseException:
        if not app._closed:
            try:
                capture_evidence(app, "failure")
            except Exception:
                pass  # Uma falha de captura não esconde a falha original.
        raise
    finally:
        if not app._closed:
            connection.set_authorizer(None)
            connection.execute("PRAGMA query_only = OFF")
            app.on_close()
        connection.close()


def capture_evidence(app: Application, phase: str) -> None:
    """Captura somente a janela sintética, processando WM_PRINT no processo Tk."""
    directory = os.environ.get("STUDYTIMER_EVIDENCE_DIR")
    if not directory:
        return
    app.deiconify()
    app.update_idletasks()
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    user.GetAncestor.restype = ctypes.c_void_p
    hwnd = int(user.GetAncestor(app.winfo_id(), 2))
    output = Path(directory) / f"{sys.argv[1]}-{app._appearance.value}-{phase}.png"
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.capture_native_window",
            str(os.getpid()),
            str(hwnd),
            str(output),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = perf_counter() + 20
    done = BooleanVar(master=app, value=False)
    job: str | None = None

    def check_capture() -> None:
        nonlocal job
        job = None
        if child.poll() is not None or perf_counter() >= deadline:
            done.set(True)
        else:
            job = app.after(10, check_capture)

    try:
        job = app.after(10, check_capture)
        # update() tenta esvaziar toda a fila e pode nunca retornar quando
        # renderizações alimentam novos timers. vwait termina por condição.
        app.wait_variable(done)
        if child.poll() is None:
            raise RuntimeError("Prazo de captura da janela excedido.")
        if child.returncode != 0:
            raise RuntimeError("Não foi possível capturar a janela de teste.")
    finally:
        if job is not None:
            app.after_cancel(job)
        if child.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            child.kill()
        child.wait(timeout=5)


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
    assert_visible(app, app._history_view.period_label)
    assert app._history_view.report is not None and app._history_view.report.total_s == 0
    canvas = app._history_view.chart.canvas
    assert canvas.winfo_rootx() >= app.winfo_rootx()
    assert canvas.winfo_rootx() + canvas.winfo_width() <= app.winfo_rootx() + app.winfo_width()
    app._history_view.previous_button.invoke()
    assert app._history_selection.reference == date(2024, 5, 9)
    step(app, source, 1)
    app._history_view.today_button.invoke()
    assert app._history_view.report.total_s == 0
    app.show_view("timer")
    assert_visible(app, app._timer_view.elapsed_label)
    app._timer_view.pause_button.invoke()
    app.show_view("history")
    assert app._history_view._session_data[0].duration_s == 3
    app.show_view("timer")
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
            "INSERT INTO sessions (id, name, created_at, finished_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
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


def test_native_types_and_themes(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tkinter import messagebox

    import customtkinter as ctk

    app, timer, repository, source, connection = native_app
    app.deiconify()
    app.geometry("900x600")
    app.update()
    view = app._timer_view
    view.name_entry.insert(0, "Descrição preservada")
    app.on_create_type()
    dialog = app._type_dialog
    assert dialog is not None
    app.update()
    dialog.close()
    assert view.get_name() == "Descrição preservada" and view.get_type_id() is None
    assert not app._types.list_types() and app.grab_current() is None
    app.on_create_type()
    dialog = app._type_dialog
    assert dialog is not None
    app.update()
    dialog.name_entry.insert(0, "POO")
    connection.set_authorizer(deny_commit)
    try:
        dialog.save_button.invoke()
    finally:
        connection.set_authorizer(None)
    assert dialog.winfo_exists() and app._types.list_types() == []
    assert isinstance(messagebox.showerror, Mock)
    messagebox.showerror.assert_called_once()
    messagebox.showerror.reset_mock()
    dialog.save_button.invoke()
    assert not dialog.winfo_exists() and app.grab_current() is None
    item = app._types.list_types()[0]
    assert view.get_type_id() == item.id
    app.on_create_type()
    dialog = app._type_dialog
    assert dialog is not None
    app.update()
    dialog.name_entry.insert(0, "poo")
    dialog.save()
    assert dialog.winfo_exists() and len(app._types.list_types()) == 1
    assert isinstance(messagebox.showerror, Mock)
    messagebox.showerror.assert_called_once()
    dialog.close()
    app.on_manage_types()
    dialog = app._type_dialog
    assert dialog is not None
    app.update()
    dialog.select_type(item.id)
    dialog.name_entry.delete(0, "end")
    dialog.name_entry.insert(0, "Objetos")
    dialog.save()
    assert view.type_menu.get() == "Objetos"
    dialog.toggle_archived()
    assert app._types.list_types() == [] and view.get_type_id() is None
    dialog.toggle_archived()
    assert view.get_type_id() == item.id
    # Pares de cor atualizam inclusive o diálogo existente, sem reconstruí-lo.
    current = app._appearance
    label = "Claro" if current == AppearanceMode.DARK else "Escuro"
    app.on_appearance(label)
    app.update()
    assert app._type_dialog is dialog and dialog.winfo_exists()
    assert ctk.get_appearance_mode().lower() == app._appearance.value
    dialog.close()
    # O seletor pode ser operado pelo Canvas que recebe o foco via Tab.
    view.type_menu._canvas.focus_force()
    view.type_menu._canvas.event_generate("<Up>")
    app.update()
    assert view.get_type_id() is None
    view.type_menu._canvas.event_generate("<Down>")
    app.update()
    assert view.get_type_id() == item.id
    app.on_start()
    step(app, source, 2)
    session = timer.get_active_session()
    assert session is not None and session.study_type_id == item.id
    jobs = (app._tick_job, app._heartbeat_job)
    app.on_appearance("Claro" if app._appearance == AppearanceMode.DARK else "Escuro")
    assert timer.is_running and (app._tick_job, app._heartbeat_job) == jobs
    assert view.get_name() == "Descrição preservada"
    assert repository.get_session(session.id) == session
    for widget in (view.new_type_button, view.manage_types_button):
        assert widget.cget("state") == "disabled"
    app.on_manage_types()
    assert app._type_dialog is dialog  # Não abriu outro durante a sessão.
    app.show_view("history")
    app.show_view("timer")
    app.update_idletasks()
    for widget in (view.type_menu, view.name_entry, view.start_button, view.finish_button):
        assert widget.winfo_rootx() >= app.winfo_rootx()
        assert widget.winfo_rootx() + widget.winfo_width() <= app.winfo_rootx() + app.winfo_width()
    app.on_pause()
    source.advance(3600 * SECOND_NS)
    app.on_start()
    step(app, source, 1)
    app.on_finish()
    assert view.get_name() == "" and view.get_type_id() == item.id
    assert repository.get_session_intervals(session.id)[-1].ended_at is not None
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    view.name_entry.insert(0, "Retomar depois")
    app.on_start()
    step(app, source, 1)
    app.on_close()


def test_native_dialog_failures(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tkinter import messagebox

    app, timer, _, _, _ = native_app
    app.deiconify()
    app.update()
    app.on_create_type()
    dialog = app._type_dialog
    assert dialog is not None
    app.update()
    dialog.save()
    assert dialog.winfo_exists() and not app._types.list_types()
    dialog.name_entry.insert(0, "Tipo salvo")
    monkeypatch.setattr(dialog, "_on_saved", Mock(side_effect=OSError("conteúdo privado")))
    dialog.save()
    assert len(app._types.list_types()) == 1 and not dialog.winfo_exists()
    assert app.grab_current() is None
    app.on_manage_types()
    manager = app._type_dialog
    assert manager is not None and manager is not dialog
    app.update()
    assert len(manager._items) == 1
    manager.close()
    # Falhar na leitura depois de criar o Toplevel não deixa uma janela órfã.
    items = app._types.list_types()
    monkeypatch.setattr(app._types, "list_types", Mock(side_effect=[items, OSError("privado")]))
    before = app.winfo_children()
    app.on_create_type()
    assert app.winfo_children() == before
    assert not timer.is_running and not app._failed
    assert isinstance(messagebox.showerror, Mock)
    assert "privado" not in str(messagebox.showerror.call_args_list)
    app.on_close()


def test_native_scaled_layout(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import customtkinter as ctk

    app, _, _, _, _ = native_app
    app.deiconify()
    app.geometry("900x600")
    app.update()
    try:
        for scale in (1.0, 1.25, 1.5, 2.0):
            ctk.set_widget_scaling(scale)
            ctk.set_window_scaling(scale)
            app.geometry("900x600")
            app.update()
            view = app._timer_view
            for widget in (view.type_menu, view.name_entry, view.start_button, view.finish_button):
                assert widget.winfo_rootx() >= app.winfo_rootx()
                assert (
                    widget.winfo_rootx() + widget.winfo_width()
                    <= app.winfo_rootx() + app.winfo_width()
                ), (
                    scale,
                    str(widget),
                    widget.winfo_rootx(),
                    widget.winfo_width(),
                    app.winfo_rootx(),
                    app.winfo_width(),
                    app.geometry(),
                )
            assert view.finish_button.winfo_rooty() + view.finish_button.winfo_height() <= (
                app.winfo_rooty() + app.winfo_height()
            )
    finally:
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)
        app.on_close()


def test_native_reopened_types(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import customtkinter as ctk

    app, timer, _, _, _ = native_app
    item = app._types.list_types()[0]
    assert item.name == "Objetos"
    assert app._timer_view.get_type_id() == item.id
    assert app._timer_view.get_name() == "Retomar depois"
    assert not timer.is_running
    assert app._timer_view.type_menu.cget("state") == "disabled"
    assert ctk.get_appearance_mode().lower() == app._preferences.get_appearance_mode().value
    app.on_close()


def test_native_period_history(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import customtkinter as ctk

    from app.models import ClockSnapshot, HistorySelection, ReportPeriod, StudyColor

    app, timer, repository, source, connection = native_app
    types = [
        app._types.create_type(name, color)
        for name, color in (
            ("POO", StudyColor.BLUE),
            ("Banco de Dados", StudyColor.TEAL),
            ("Redes", StudyColor.ORANGE),
        )
    ]
    for name, hour, seconds, type_id, day in (
        ("Objetos", 8, 90, types[0].id, 10),
        ("Consultas SQL", 9, 120, types[1].id, 10),
        ("Rede antiga", 14, 40, types[2].id, 10),
        ("Estudo livre", 18, 30, None, 10),
        ("Início do mês", 8, 200, None, 1),
    ):
        start = stamp(2024, 5, day, hour)
        session, interval = repository.start_session(name, start, type_id)
        repository.finish_session(
            session.id, ClockSnapshot(interval.id, start, seconds, start + seconds)
        )
    app._types.archive_type(types[2].id)
    changes = connection.total_changes
    reads = source.read_count
    app.deiconify()
    app.geometry("1180x740")
    app.show_view("history")
    app.update()
    view = app._history_view
    assert view.report is not None and view.report.total_s == 280
    assert len(view.chart._regions) == 24 and len(view.chart.canvas.find_withtag("bar")) == 4
    view.period_buttons[ReportPeriod.WEEK].invoke()
    app.update()
    assert view.report.total_s == 280 and view.report.average_days == 5
    assert len(view.chart._regions) == 7
    assert any(item.type_id == types[2].id for item in view.report.ranking)
    # Dia futuro vazio não pode contornar a navegação desabilitada.
    selection = app._history_selection
    view.chart.select_bucket(6)
    assert app._history_selection == selection
    view._ranking_rows[0][0].invoke()
    assert view.report.total_s == 120 and view.report.filter_name == "Banco de Dados"
    parent = app._history_selection
    canvas = view.chart.canvas
    x0, x1 = view.chart._regions[4]
    canvas.event_generate("<Button-1>", x=int((x0 + x1) / 2), y=int(view.chart._plot_bottom - 2))
    app.update()
    assert app._history_selection == HistorySelection(
        ReportPeriod.DAY, date(2024, 5, 10), "type", types[1].id
    )
    assert view._session_data[0].name == "Consultas SQL"
    view.back_button.invoke()
    assert app._history_selection == parent
    view.clear_filter_button.invoke()
    app.on_type_filter(None)
    assert view.report.total_s == 30 and view.report.filter_name == "Sem tipo"
    view.today_button.invoke()
    assert app._history_selection == HistorySelection(ReportPeriod.WEEK, date(2024, 5, 10))
    assert view.report.total_s == 280
    view.period_buttons[ReportPeriod.MONTH].invoke()
    assert view.report.total_s == 480 and len(view.chart._regions) == 31
    view.chart.select_bucket(0)
    assert app._history_selection.reference == date(2024, 5, 1)
    assert view.report.total_s == 200
    view.back_button.invoke()
    assert app._history_selection == HistorySelection(ReportPeriod.MONTH, date(2024, 5, 10))
    view.period_label.invoke()
    picker = app._date_picker
    assert picker is not None
    app.update()
    assert len(picker.day_buttons) == 42
    picker.select_day(date(2024, 5, 9))
    assert app.grab_current() is None and not picker.winfo_exists()
    view.period_buttons[ReportPeriod.DAY].invoke()
    assert view.report.total_s == 0
    view.today_button.invoke()
    canvas = view.chart.canvas
    canvas.focus_force()
    canvas.event_generate("<Right>")
    canvas.event_generate("<Return>")
    app.update()
    assert view.chart.selected_index is not None
    before = view.report
    index = view.chart.selected_index
    background = canvas.cget("background")
    app.on_appearance("Claro" if app._appearance == AppearanceMode.DARK else "Escuro")
    app.update()
    # app.update também entrega o refresh periódico: igualdade de valor,
    # não identidade do objeto, é o contrato do relatório preservado.
    assert view.report == before and view.chart.selected_index == index
    assert canvas.cget("background") != background
    assert ctk.get_appearance_mode().lower() == app._appearance.value
    # Somente a preferência mudou; relatórios e navegação não escrevem estudo.
    assert connection.total_changes == changes + 1 and source.read_count == reads
    app.geometry("900x600")
    app.update()
    assert not view._wide
    app.show_view("timer")
    app.on_start()
    step(app, source, 2)
    app.show_view("history")
    assert view.report.total_s == 280
    assert timer.is_running
    app.on_pause()
    assert view.report.total_s == 282
    app.on_close()


def test_native_visual_evidence(
    native_app: tuple[Application, TimerService, StudyRepository, FakeClock, sqlite3.Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.clock_snapshot import ClockSnapshot
    from app.models.report_period import ReportPeriod
    from app.models.study_color import StudyColor

    app, _, repository, _, _ = native_app
    # Este cenário captura estados estáticos; ciclos e atualização ao vivo
    # são exercitados pelos outros cenários. Evita redesenhos periódicos
    # concorrentes com WM_PRINT, mantendo os snapshots sintéticos estáveis.
    for attribute in ("_tick_job", "_heartbeat_job"):
        pending = getattr(app, attribute)
        if pending is not None:
            app.after_cancel(pending)
            setattr(app, attribute, None)
    study_type = app._types.create_type("POO", StudyColor.BLUE)
    for day, hour, seconds in ((8, 10, 1800), (9, 15, 2700), (10, 9, 3600)):
        start = stamp(2024, 5, day, hour)
        session, interval = repository.start_session("Exercícios de classes", start, study_type.id)
        repository.finish_session(
            session.id, ClockSnapshot(interval.id, start, seconds, start + seconds)
        )
    app.deiconify()
    app.geometry("1180x740")
    app.update_idletasks()
    assert_visible(app, app._timer_view.elapsed_label)
    capture_evidence(app, "timer")
    app.show_view("history")
    view = app._history_view
    for period in ReportPeriod:
        view.period_buttons[period].invoke()
        app.update_idletasks()
        assert view.report is not None and view.report.total_s > 0
        assert_visible(app, view.period_label)
        canvas = view.chart.canvas
        assert canvas.winfo_rootx() >= app.winfo_rootx()
        assert canvas.winfo_rootx() + canvas.winfo_width() <= app.winfo_rootx() + app.winfo_width()
        capture_evidence(app, period.value)
    app.on_close()


if __name__ == "__main__":
    scenarios = {
        "cycle": test_native_full_cycle_and_minimum_window,
        "recovery": test_native_failed_commit_close_retry_and_recovery,
        "offline_backup": test_native_ui_without_socket_access_and_backup_restore,
        "history_1000": test_native_history_thousand_sessions,
        "types_themes": test_native_types_and_themes,
        "reopened_types": test_native_reopened_types,
        "dialog_errors": test_native_dialog_failures,
        "scaling": test_native_scaled_layout,
        "period_history": test_native_period_history,
        "visual": test_native_visual_evidence,
    }
    with pytest.MonkeyPatch.context() as patch:
        mode = AppearanceMode(sys.argv[3]) if len(sys.argv) > 3 else AppearanceMode.DARK
        with native_app(Path(sys.argv[2]), patch, mode) as state:
            scenarios[sys.argv[1]](state, Path(sys.argv[2]), patch)
