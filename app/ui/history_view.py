"""Histórico com cartões, calendário local e detalhes diários paginados."""

import calendar
from collections.abc import Callable
from datetime import date

import customtkinter as ctk

from app.models import PeriodTotals, SessionSummary
from app.ui import theme
from app.ui.formatting import format_clock, format_minutes

MONTH_NAMES = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)


def intensity_color(seconds: int) -> theme.Color:
    """Faixas fixas em segundos; não mudam de significado ao trocar de mês."""
    if seconds <= 0:
        return ("#E8EDF3", "#3A3A3A")
    if seconds < 15 * 60:
        return ("#D9EAFB", "#315E79")
    if seconds < 60 * 60:
        return ("#BBD8F4", "#226C9C")
    if seconds < 120 * 60:
        return ("#93BDE6", "#175596")
    return ("#69A1D5", "#10366E")


class HistoryView(ctk.CTkScrollableFrame):
    """Recebe resultados prontos e callbacks, sem SQL ou cálculo de duração."""

    def __init__(
        self,
        master: ctk.CTkFrame,
        on_month: Callable[[int], None],
        on_day: Callable[[date], None],
        on_today: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color=theme.SURFACE)
        self.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkLabel(self, text="Histórico", font=("Segoe UI", 28)).grid(
            row=0, column=0, columnspan=3, padx=24, pady=32
        )
        self.total_labels: list[ctk.CTkLabel] = []
        for column, label in enumerate(("Hoje", "Esta semana", "Mês atual")):
            card = ctk.CTkFrame(self, fg_color=theme.SIDEBAR)
            card.grid(row=1, column=column, padx=8, pady=16, sticky="ew")
            ctk.CTkLabel(card, text=label).pack(padx=12, pady=(12, 4))
            total = ctk.CTkLabel(card, text="—", font=("Segoe UI", 24))
            total.pack(padx=12, pady=(4, 12))
            self.total_labels.append(total)
        navigation = ctk.CTkFrame(self, fg_color="transparent")
        navigation.grid(row=2, column=0, columnspan=3, padx=12, pady=(12, 0), sticky="ew")
        navigation.grid_columnconfigure(1, weight=1)
        self.previous_button = ctk.CTkButton(
            navigation, text="◀", width=44, command=lambda: on_month(-1)
        )
        self.previous_button.grid(row=0, column=0, padx=4)
        self.month_label = ctk.CTkLabel(navigation, text="", font=("Segoe UI", 20))
        self.month_label.grid(row=0, column=1, padx=8)
        self.next_button = ctk.CTkButton(
            navigation, text="▶", width=44, command=lambda: on_month(1)
        )
        self.next_button.grid(row=0, column=2, padx=4)
        self.today_button = ctk.CTkButton(navigation, text="Hoje", width=60, command=on_today)
        self.today_button.grid(row=0, column=3, padx=4)
        self.month_total_label = ctk.CTkLabel(self, text="")
        self.month_total_label.grid(row=3, column=0, columnspan=3, pady=8)
        cells = ctk.CTkFrame(self)
        cells.grid(row=4, column=0, columnspan=3, padx=12, sticky="ew")
        self.day_buttons: list[ctk.CTkButton] = []
        self._on_day = on_day
        for column, name in enumerate(("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")):
            cells.grid_columnconfigure(column, weight=1, uniform="days")
            ctk.CTkLabel(cells, text=name).grid(row=0, column=column, pady=4)
        for slot in range(42):
            button = ctk.CTkButton(cells, text="", width=60, height=46, corner_radius=6)
            button.grid(row=slot // 7 + 1, column=slot % 7, padx=2, pady=2, sticky="ew")
            self.day_buttons.append(button)
        self.day_label = ctk.CTkLabel(self, text="", font=("Segoe UI", 18))
        self.day_label.grid(row=6, column=0, columnspan=3, pady=8)
        self._details = ctk.CTkFrame(self)
        self._details.grid(row=7, column=0, columnspan=3, padx=12, sticky="ew")
        self._details.grid_columnconfigure(0, weight=1)
        self._empty_label = ctk.CTkLabel(self._details, text="Nenhuma sessão neste dia.")
        self._session_rows: list[ctk.CTkLabel] = []
        self._session_data: tuple[SessionSummary, ...] = ()
        self._session_limit = 50
        self._details_key: tuple[date, tuple[SessionSummary, ...]] | None = None
        self.more_button = ctk.CTkButton(self, text="Mostrar mais", command=self._show_more)
        self.more_button.grid(row=8, column=0, columnspan=3, pady=12)
        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.grid(row=9, column=0, columnspan=3, pady=8)
        self._calendar_key: object = None
        self._totals: PeriodTotals | None = None

    def render(
        self,
        reference: date,
        totals: PeriodTotals,
        year: int,
        month: int,
        days: dict[date, int],
        selected: date,
        sessions: list[SessionSummary],
    ) -> None:
        """Atualiza só valores alterados; preserva botões e foco durante ticks."""
        if totals != self._totals:
            for label, seconds in zip(
                self.total_labels, (totals.today_s, totals.week_s, totals.month_s), strict=True
            ):
                label.configure(text=format_minutes(seconds))
            self._totals = totals
        key = (reference, year, month, tuple(days.items()), selected)
        if key != self._calendar_key:
            self.month_label.configure(text=f"{MONTH_NAMES[month - 1]} de {year}")
            self.month_total_label.configure(
                text=f"Total do mês exibido: {format_minutes(sum(days.values()))}"
            )
            self.previous_button.configure(
                state="disabled" if (year, month) == (1, 1) else "normal"
            )
            self.next_button.configure(
                state="disabled" if (year, month) == (9998, 12) else "normal"
            )
            first_weekday, count = calendar.monthrange(year, month)
            for slot, button in enumerate(self.day_buttons):
                number = slot - first_weekday + 1
                if not 1 <= number <= count:
                    button.configure(
                        text="", state="disabled", fg_color=theme.DISABLED, border_width=0
                    )
                    continue
                day = date(year, month, number)
                seconds = days[day]
                button.configure(
                    text=f"{number}\n{format_minutes(seconds)}",
                    state="normal",
                    fg_color=intensity_color(seconds),
                    text_color=theme.TEXT,
                    border_width=2 if day in (selected, reference) else 0,
                    border_color="#E4B84B" if day == selected else "#4EB8E8",
                    command=lambda day=day: self._on_day(day),
                )
            self._calendar_key = key
        details_key = (selected, tuple(sessions))
        self.day_label.configure(text=f"Sessões de {selected:%d/%m/%Y}")
        if details_key != self._details_key:
            # Novos segundos não voltam a paginação ao início no mesmo dia.
            if self._details_key is None or self._details_key[0] != selected:
                self._session_limit = 50
            self._session_data = tuple(sessions)
            self._render_sessions()
            self._details_key = details_key
        self.status_label.configure(text="")

    def _render_sessions(self) -> None:
        visible = self._session_data[: self._session_limit]
        needed = len(visible) * 2
        while len(self._session_rows) > needed:
            self._session_rows.pop().destroy()
        self._empty_label.grid_remove()
        while len(self._session_rows) < needed:
            index = len(self._session_rows) // 2
            label = ctk.CTkLabel(self._details, text="", wraplength=380, anchor="w", justify="left")
            label.grid(row=index, column=0, padx=8, pady=4, sticky="w")
            duration = ctk.CTkLabel(self._details, text="")
            duration.grid(row=index, column=1, padx=8, pady=4, sticky="e")
            self._session_rows.extend((label, duration))
        for index, session in enumerate(visible):
            self._session_rows[index * 2].configure(text=session.name)
            self._session_rows[index * 2 + 1].configure(text=format_clock(session.duration_s))
        if not self._session_data:
            self._empty_label.grid(row=0, column=0, padx=12, pady=12)
        self.more_button.configure(
            state="normal" if len(self._session_data) > self._session_limit else "disabled"
        )

    def _show_more(self) -> None:
        self._session_limit += 50
        self._render_sessions()

    def show_error(self) -> None:
        """Mantém os valores anteriores identificados como desatualizados."""
        self.status_label.configure(text="Histórico não atualizado · operação não confirmada")
