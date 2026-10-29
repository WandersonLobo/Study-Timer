"""Janela principal e navegação; serviços são compartilhados entre as duas telas."""

from typing import Literal

import customtkinter as ctk

from app.config import MIN_WINDOW_SIZE, WINDOW_SIZE
from app.services.report_service import ReportService
from app.services.timer_service import TimerService
from app.ui.history_view import HistoryView
from app.ui.timer_view import TimerView


class Application(ctk.CTk):
    """Compõe somente Cronômetro e Histórico, sem acesso direto ao banco."""

    def __init__(self, timer: TimerService, reports: ReportService) -> None:
        super().__init__()
        self._timer = timer
        self._reports = reports
        self.title("StudyTimer · estrutura inicial")
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
        self._views: dict[str, TimerView | HistoryView] = {
            "timer": TimerView(content),
            "history": HistoryView(content),
        }
        for view in self._views.values():
            view.grid(row=0, column=0, sticky="nsew")
        self.show_view("timer")

    def show_view(self, name: Literal["timer", "history"]) -> None:
        """Alterna a tela sem reconstruir os serviços ou os widgets."""
        self._views[name].tkraise()
