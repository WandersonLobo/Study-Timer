"""Janela principal e navegação; serviços são compartilhados entre as duas telas."""

import logging
from collections.abc import Callable
from datetime import date
from tkinter import messagebox
from typing import Literal

import customtkinter as ctk

from app.config import HEARTBEAT_INTERVAL_S, MIN_WINDOW_SIZE, TICK_INTERVAL_MS, WINDOW_SIZE
from app.models import PauseReason, Session, SessionStatus, UIState
from app.services.report_service import ReportService
from app.services.timer_service import TimerService
from app.ui.history_view import HistoryView
from app.ui.timer_view import TimerView
from app.windows_power import WindowsPowerMonitor


class Application(ctk.CTk):
    """Compõe somente Cronômetro e Histórico, sem acesso direto ao banco."""

    def __init__(self, timer: TimerService, reports: ReportService) -> None:
        super().__init__()
        self._timer = timer
        self._power = WindowsPowerMonitor(lambda: timer.freeze(PauseReason.SUSPEND))
        self._reports = reports
        today = reports.get_today()
        self._calendar_month = (today.year, today.month)
        self._selected_day = today
        self._visible_view: Literal["timer", "history"] = "timer"
        self._session: Session | None = None
        self._state = UIState.IDLE
        self._elapsed_s = 0
        self._failed = False
        self._closed = False
        self._tick_job: str | None = None
        self._heartbeat_job: str | None = None
        self._recovery_job: str | None = None
        self.title("StudyTimer")
        self.geometry(WINDOW_SIZE)
        self.minsize(*MIN_WINDOW_SIZE)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        sidebar = ctk.CTkFrame(self, width=180)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=12)
        ctk.CTkLabel(sidebar, text="StudyTimer", font=("Segoe UI", 24)).pack(padx=20, pady=32)
        ctk.CTkButton(sidebar, text="Cronômetro", command=lambda: self.show_view("timer")).pack(
            padx=16, pady=8
        )
        ctk.CTkButton(sidebar, text="Histórico", command=lambda: self.show_view("history")).pack(
            padx=16, pady=8
        )
        content = ctk.CTkFrame(self)
        content.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        self._timer_view = TimerView(content, self.on_start, self.on_pause, self.on_finish)
        self._history_view = HistoryView(content, self.on_month, self.on_day, self.on_today)
        self._views: dict[str, TimerView | HistoryView] = {
            "timer": self._timer_view,
            "history": self._history_view,
        }
        for view in self._views.values():
            view.grid(row=0, column=0, sticky="nsew")
        self.show_view("timer")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_idletasks()
        self._power.start(int(self.winfo_id()))
        self._refresh()
        if self._session is not None:
            self._state = UIState.RECOVERED
            self._render()
            self._recovery_job = self.after_idle(self._show_recovery)
        self._tick_job = self.after(TICK_INTERVAL_MS, self._poll)
        self._heartbeat_job = self.after(HEARTBEAT_INTERVAL_S * 1000, self._heartbeat)

    def show_view(self, name: Literal["timer", "history"]) -> None:
        """Alterna a tela sem reconstruir os serviços ou os widgets."""
        self._visible_view = name
        # CTkScrollableFrame encaminha lift ao contêiner externo; tkraise não.
        self._views[name].lift()
        if name == "history":
            self._run(lambda: None)

    def on_month(self, delta: int) -> None:
        """Navega apenas o calendário; cartões continuam na data atual."""

        def command() -> None:
            year, month = self._calendar_month
            ordinal = year * 12 + month - 1 + delta
            year, month = divmod(ordinal, 12)
            month += 1
            if not 1 <= year <= 9998:
                return
            self._calendar_month = (year, month)
            self._selected_day = date(year, month, 1)

        self._run(command)

    def on_day(self, day: date) -> None:
        """Seleciona detalhes sem alterar os cartões nem a sessão ativa."""

        def command() -> None:
            self._selected_day = day

        self._run(command)

    def on_today(self) -> None:
        """Volta ao mês e ao dia atuais no fuso do sistema."""

        def command() -> None:
            today = self._reports.get_today()
            self._calendar_month = (today.year, today.month)
            self._selected_day = today

        self._run(command)

    def _refresh_history(self) -> None:
        today = self._reports.get_today()
        snapshot = self._timer.get_snapshot()
        totals = self._reports.get_totals(today, snapshot)
        year, month = self._calendar_month
        days = self._reports.get_month_days(year, month, snapshot)
        sessions = self._reports.get_day_sessions(self._selected_day, snapshot)
        self._history_view.render(today, totals, year, month, days, self._selected_day, sessions)

    def on_start(self) -> None:
        """Inicia ou retoma conforme o estado persistido."""

        def command() -> None:
            if self._timer.get_active_session() is None:
                self._timer.start_session(self._timer_view.get_name())
            else:
                self._timer.resume_session()

        self._run(command)

    def on_pause(self) -> None:
        """Permite repetir a pausa usando o snapshot congelado após falha."""
        self._run(lambda: self._timer.pause_session(PauseReason.USER))

    def on_finish(self) -> None:
        """Só apresenta a finalização após o retorno confirmado do serviço."""
        self._run(self._timer.finish_session)

    def _run(self, command: Callable[[], object]) -> None:
        if self._closed:
            return
        try:
            if self._power.take_pending():
                command = self._timer.pause_for_power
            command()
            self._failed = self._timer.persistence_failed
            self._refresh()
        except Exception as error:
            self._handle_error(error)

    def _refresh(self) -> None:
        session = self._timer.get_active_session()
        elapsed = self._timer.get_elapsed_seconds()
        self._session, self._elapsed_s = session, elapsed
        self._state = (
            UIState.IDLE
            if session is None
            else UIState.RUNNING
            if self._timer.is_running
            else UIState.PAUSED
        )
        self._render()
        if self._visible_view == "history" and not self._failed:
            self._refresh_history()

    def _render(self) -> None:
        self._timer_view.render(self._state, self._session, self._elapsed_s, self._failed)

    def _poll(self) -> None:
        self._tick_job = None
        if self._closed:
            return
        if self._power.pending:
            self._run(self._timer.pause_for_power)
        if self._timer.is_running and not self._failed:
            self._run(self._timer.tick)
            if not self._timer.is_running and not self._failed:
                messagebox.showinfo(
                    "Contagem pausada",
                    "Foi detectada uma interrupção ou alteração do relógio. "
                    "A sessão foi pausada no último instante confiável.",
                    parent=self,
                )
        elif self._visible_view == "history" and not self._failed:
            self._run(lambda: None)
        if not self._closed:
            self._tick_job = self.after(TICK_INTERVAL_MS, self._poll)

    def _heartbeat(self) -> None:
        self._heartbeat_job = None
        if self._closed:
            return
        if self._power.pending:
            self._run(self._timer.pause_for_power)
        if self._timer.is_running and not self._failed:
            self._run(self._timer.heartbeat)
        if not self._closed:
            self._heartbeat_job = self.after(HEARTBEAT_INTERVAL_S * 1000, self._heartbeat)

    def _show_recovery(self) -> None:
        self._recovery_job = None
        if self._closed:
            return
        choice = messagebox.askyesnocancel(
            "Sessão recuperada",
            "Há uma sessão pendente, recuperada como pausada. "
            "O tempo com o programa fechado não foi contado.\n\n"
            "Sim: retomar. Não: finalizar. Cancelar: manter pausada.",
            default=messagebox.CANCEL,
            parent=self,
        )
        if choice is True:
            self.on_start()
        elif choice is False:
            self.on_finish()

    def _handle_error(self, error: Exception) -> None:
        self._timer.freeze()
        self._failed = True
        self._history_view.show_error()
        logging.getLogger("studytimer.ui").error(
            "UI_OPERATION_FAILED type=%s", type(error).__name__
        )
        try:
            self._refresh()
        except Exception:
            self._render()
        message = (
            "O nome deve conter no máximo 120 caracteres."
            if isinstance(error, ValueError)
            else "Não foi possível confirmar a operação. A contagem foi interrompida. "
            "Tente novamente. A janela permanecerá aberta se os dados não puderem ser salvos."
        )
        messagebox.showerror("StudyTimer", message, parent=self)

    def on_close(self) -> None:
        """Persiste pausa antes de cancelar callbacks e destruir a janela."""
        if self._closed:
            return
        try:
            if self._power.take_pending():
                self._timer.pause_for_power()
            session = self._timer.get_active_session()
            if session is not None and session.status == SessionStatus.RUNNING:
                self._timer.pause_session(PauseReason.SHUTDOWN)
            self._power.close()
        except Exception as error:
            self._handle_error(error)
            return
        self._closed = True
        for job in (self._tick_job, self._heartbeat_job, self._recovery_job):
            if job is not None:
                self.after_cancel(job)
        self.destroy()
