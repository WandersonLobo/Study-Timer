"""Janela principal e navegação; serviços são compartilhados entre as duas telas."""

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from tkinter import messagebox
from typing import Literal

import customtkinter as ctk

from app.config import HEARTBEAT_INTERVAL_S, MIN_WINDOW_SIZE, TICK_INTERVAL_MS, WINDOW_SIZE
from app.models import (
    AppearanceMode,
    HistorySelection,
    PauseReason,
    ReportPeriod,
    Session,
    SessionStatus,
    UIState,
)
from app.services.preferences_service import PreferencesService
from app.services.report_service import ReportService
from app.services.study_type_service import StudyTypeService
from app.services.timer_service import TimerService
from app.ui import theme
from app.ui.date_picker import DatePicker
from app.ui.history_view import HistoryView
from app.ui.study_type_dialog import StudyTypeDialog
from app.ui.timer_view import TimerView
from app.windows_power import WindowsPowerMonitor


class Application(ctk.CTk):
    """Compõe somente Cronômetro e Histórico, sem acesso direto ao banco."""

    def __init__(
        self,
        timer: TimerService,
        reports: ReportService,
        types: StudyTypeService,
        preferences: PreferencesService,
    ) -> None:
        self._appearance = preferences.get_appearance_mode()
        theme.apply_appearance(self._appearance)
        super().__init__(fg_color=theme.BACKGROUND)
        self._types = types
        self._preferences = preferences
        self._type_dialog: StudyTypeDialog | None = None
        self._timer = timer
        self._power = WindowsPowerMonitor(lambda: timer.freeze(PauseReason.SUSPEND))
        self._reports = reports
        today = reports.get_today()
        self._history_selection = HistorySelection(ReportPeriod.DAY, today)
        self._history_parent: HistorySelection | None = None
        self._date_picker: DatePicker | None = None
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
        sidebar = ctk.CTkFrame(self, width=180, fg_color=theme.SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=12)
        ctk.CTkLabel(
            sidebar, text="StudyTimer", text_color=theme.TEXT, font=("Segoe UI", 24, "bold")
        ).pack(padx=20, pady=32)
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for name, label in (("timer", "Cronômetro"), ("history", "Histórico")):
            button = ctk.CTkButton(
                sidebar,
                text=label,
                command=lambda view=name: self.show_view(view),
                hover_color=theme.SELECTION,
            )
            button.pack(padx=16, pady=8)
            theme.keyboard_button(button)
            self._nav_buttons[name] = button
        self.theme_menu = ctk.CTkOptionMenu(
            sidebar,
            values=["Claro", "Escuro"],
            command=self.on_appearance,
            fg_color=theme.SURFACE,
            text_color=theme.TEXT,
            button_color=theme.PRIMARY,
            dropdown_fg_color=theme.SURFACE,
            dropdown_text_color=theme.TEXT,
            dropdown_hover_color=theme.SELECTION,
        )
        theme.keyboard_choice(self.theme_menu, self.on_appearance)
        self.theme_menu.set("Claro" if self._appearance == AppearanceMode.LIGHT else "Escuro")
        self.theme_menu.pack(side="bottom", padx=12, pady=20)
        content = ctk.CTkFrame(self, fg_color=theme.BACKGROUND)
        content.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        self._timer_view = TimerView(
            content,
            self.on_start,
            self.on_pause,
            self.on_finish,
            self.on_create_type,
            self.on_manage_types,
        )
        self._reload_types()
        self._history_view = HistoryView(
            content,
            self.on_period_step,
            self.on_period_mode,
            self.on_pick_date,
            self.on_today,
            self.on_type_filter,
            self.on_clear_filter,
            self.on_bucket,
            self.on_history_back,
        )
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
        for view, button in self._nav_buttons.items():
            button.configure(
                fg_color=theme.SELECTION if view == name else "transparent",
                text_color=theme.LINK if view == name else theme.TEXT,
            )
        # CTkScrollableFrame encaminha lift ao contêiner externo; tkraise não.
        self._views[name].lift()
        if name == "history":
            self._run(lambda: None)

    def on_period_step(self, delta: int) -> None:
        """Navega uma unidade do modo, sem alterar o filtro."""

        def command() -> None:
            selection = self._history_selection
            try:
                if selection.period == ReportPeriod.MONTH:
                    ordinal = selection.reference.year * 12 + selection.reference.month - 1 + delta
                    year, month = divmod(ordinal, 12)
                    candidate = date(year, month + 1, 1)
                else:
                    candidate = selection.reference + timedelta(
                        days=delta * (7 if selection.period == ReportPeriod.WEEK else 1)
                    )
                if not 1 <= candidate.year <= 9998:
                    return
                updated = replace(selection, reference=candidate)
                first, _ = self._reports.get_period_dates(updated)
                if first > self._reports.get_today():
                    return
            except (OverflowError, ValueError):
                return
            self._history_selection = updated
            self._history_parent = None

        self._run(command)

    def on_period_mode(self, period: ReportPeriod) -> None:
        def command() -> None:
            self._history_selection = replace(self._history_selection, period=period)
            self._history_parent = None

        self._run(command)

    def on_day(self, day: date) -> None:
        def command() -> None:
            if day <= self._reports.get_today() and day.year <= 9998:
                self._history_selection = replace(self._history_selection, reference=day)
                self._history_parent = None

        self._run(command)

    def on_today(self) -> None:
        def command() -> None:
            self._history_selection = HistorySelection(
                self._history_selection.period, self._reports.get_today()
            )
            self._history_parent = None

        self._run(command)

    def on_type_filter(self, type_id: int | None) -> None:
        def command() -> None:
            self._history_selection = replace(
                self._history_selection,
                type_filter="untyped" if type_id is None else "type",
                study_type_id=type_id,
            )

        self._run(command)

    def on_clear_filter(self) -> None:
        self._run(lambda: self._clear_history_filter())

    def _clear_history_filter(self) -> None:
        self._history_selection = replace(
            self._history_selection, type_filter="all", study_type_id=None
        )

    def on_bucket(self, index: int) -> None:
        report = self._history_view.report
        if report is None or report.selection.period == ReportPeriod.DAY:
            return
        if not 0 <= index < len(report.buckets):
            return
        if report.buckets[index].day > self._reports.get_today():
            return

        def command() -> None:
            self._history_parent = self._history_selection
            self._history_selection = replace(
                self._history_selection,
                period=ReportPeriod.DAY,
                reference=report.buckets[index].day,
            )

        self._run(command)

    def on_history_back(self) -> None:
        def command() -> None:
            if self._history_parent is not None:
                self._history_selection = self._history_parent
                self._history_parent = None

        self._run(command)

    def on_pick_date(self) -> None:
        if self._closed:
            return
        if self._date_picker is not None and self._date_picker.winfo_exists():
            self._date_picker.lift()
            return
        self._date_picker = DatePicker(
            self, self._history_selection.reference, self.on_day, self._reports.get_today()
        )

    def _refresh_history(self) -> None:
        report = self._reports.get_period_report(
            self._history_selection, self._timer.get_snapshot()
        )
        self._history_view.render(
            report,
            self._reports.get_today(),
            self._history_parent.period if self._history_parent else None,
        )

    def on_start(self) -> None:
        """Inicia ou retoma conforme o estado persistido."""

        def command() -> None:
            if self._timer.get_active_session() is None:
                self._timer.start_session(
                    self._timer_view.get_name(), self._timer_view.get_type_id()
                )
            else:
                self._timer.resume_session()

        self._run(
            command,
            validation_message="Verifique a descrição (até 120 caracteres) e o tipo selecionado.",
        )

    def _reload_types(self) -> None:
        items = self._types.list_types(include_archived=True)
        pending = self._timer.get_active_session()
        self._timer_view.set_types(
            [
                item
                for item in items
                if not item.is_archived
                or (pending is not None and pending.study_type_id == item.id)
            ]
        )

    def _type_saved(self, type_id: int | None) -> None:
        self._reload_types()
        self._timer_view.select_type(type_id)

    def on_create_type(self) -> None:
        self._open_types(manage=False)

    def on_manage_types(self) -> None:
        self._open_types(manage=True)

    def _open_types(self, *, manage: bool) -> None:
        if self._closed:
            return
        try:
            if self._timer.get_active_session() is not None:
                return
        except Exception as error:
            self._handle_error(error)
            return
        if self._type_dialog is not None and self._type_dialog.winfo_exists():
            self._type_dialog.lift()
            self._type_dialog.focus_set()
            return
        try:
            self._reload_types()
            self._type_dialog = StudyTypeDialog(self, self._types, self._type_saved, manage=manage)
        except Exception as error:
            logging.getLogger("studytimer.ui").error(
                "TYPE_DIALOG_FAILED type=%s", type(error).__name__
            )
            messagebox.showerror(
                "Tipos de estudo",
                "Não foi possível carregar os tipos. Tente novamente.",
                parent=self,
            )

    def on_appearance(self, label: str) -> None:
        if self._closed:
            return
        previous = self._appearance
        try:
            mode = {"Claro": AppearanceMode.LIGHT, "Escuro": AppearanceMode.DARK}[label]
            self._preferences.set_appearance_mode(mode)
        except Exception as error:
            self.theme_menu.set("Claro" if previous == AppearanceMode.LIGHT else "Escuro")
            logging.getLogger("studytimer.ui").error(
                "APPEARANCE_SAVE_FAILED type=%s", type(error).__name__
            )
            messagebox.showerror(
                "Aparência", "Não foi possível salvar a aparência. Tente novamente.", parent=self
            )
            return
        theme.apply_appearance(mode)
        self._appearance = mode
        self._history_view.refresh_theme()

    def on_pause(self) -> None:
        """Permite repetir a pausa usando o snapshot congelado após falha."""
        self._run(lambda: self._timer.pause_session(PauseReason.USER))

    def on_finish(self) -> None:
        """Só apresenta a finalização após o retorno confirmado do serviço."""
        self._run(self._timer.finish_session)

    def _run(self, command: Callable[[], object], *, validation_message: str | None = None) -> None:
        if self._closed:
            return
        try:
            if self._power.take_pending():
                command = self._timer.pause_for_power
            command()
            self._failed = self._timer.persistence_failed
            self._refresh()
        except Exception as error:
            self._handle_error(error, validation_message=validation_message)

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

    def _handle_error(self, error: Exception, *, validation_message: str | None = None) -> None:
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
            validation_message
            if isinstance(error, ValueError) and validation_message is not None
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
        if self._date_picker is not None and self._date_picker.winfo_exists():
            self._date_picker.close()
        if self._type_dialog is not None and self._type_dialog.winfo_exists():
            self._type_dialog.close()
        for job in (self._tick_job, self._heartbeat_job, self._recovery_job):
            if job is not None:
                self.after_cancel(job)
        self.destroy()
