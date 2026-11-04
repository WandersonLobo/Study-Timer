"""Seletor compacto de data com calendário local e limite de navegação."""

import calendar
from collections.abc import Callable
from datetime import date

import customtkinter as ctk

from app.ui import theme

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


class DatePicker(ctk.CTkToplevel):
    """Escolhe uma data sem alterar a sessão ou criar outra tela principal."""

    def __init__(
        self, master: ctk.CTk, selected: date, on_select: Callable[[date], None], max_date: date
    ) -> None:
        super().__init__(master, fg_color=theme.SURFACE)
        self._on_select = on_select
        self._max_date = min(max_date, date(9998, 12, 31))
        self._selected = min(selected, self._max_date)
        self._year = self._selected.year
        self._month = self._selected.month
        self._closed = False
        self._activation_job: str | None = None
        self.title("Selecionar data")
        self.geometry("420x410")
        self.minsize(390, 390)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        navigation = ctk.CTkFrame(self, fg_color="transparent")
        navigation.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        navigation.grid_columnconfigure(1, weight=1)
        self.previous_button = ctk.CTkButton(
            navigation,
            text="‹",
            width=36,
            command=lambda: self._move_month(-1),
            fg_color=theme.SIDEBAR,
            text_color=theme.TEXT,
            hover_color=theme.SELECTION,
        )
        self.previous_button.grid(row=0, column=0)
        self.month_label = ctk.CTkLabel(
            navigation, text="", font=("Segoe UI", 16, "bold"), text_color=theme.TEXT
        )
        self.month_label.grid(row=0, column=1, padx=8)
        self.next_button = ctk.CTkButton(
            navigation,
            text="›",
            width=36,
            command=lambda: self._move_month(1),
            fg_color=theme.SIDEBAR,
            text_color=theme.TEXT,
            hover_color=theme.SELECTION,
        )
        self.next_button.grid(row=0, column=2)
        self.cells = ctk.CTkFrame(self, fg_color="transparent")
        self.cells.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        for column, day_name in enumerate(("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")):
            self.cells.grid_columnconfigure(column, weight=1, uniform="calendar")
            ctk.CTkLabel(self.cells, text=day_name, text_color=theme.MUTED).grid(
                row=0, column=column, padx=2, pady=4
            )
        self.day_buttons: list[ctk.CTkButton] = []
        for index in range(42):
            button = ctk.CTkButton(
                self.cells,
                text="",
                width=38,
                height=32,
                fg_color=theme.SIDEBAR,
                text_color=theme.TEXT,
                hover_color=theme.SELECTION,
            )
            button.grid(row=index // 7 + 1, column=index % 7, padx=2, pady=2, sticky="ew")
            theme.keyboard_button(button)
            self.day_buttons.append(button)
        self.close_button = ctk.CTkButton(
            self,
            text="Cancelar",
            command=self.close,
            width=120,
            fg_color=theme.SIDEBAR,
            text_color=theme.TEXT,
            hover_color=theme.SELECTION,
        )
        self.close_button.grid(row=2, column=0, pady=(8, 16))
        for button in (self.previous_button, self.next_button, self.close_button):
            theme.keyboard_button(button)
        self.bind("<Escape>", lambda event: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._render()
        self._activation_job = self.after_idle(self._activate)

    def _activate(self) -> None:
        self._activation_job = None
        if not self._closed:
            self.grab_set()
            first, _ = calendar.monthrange(self._year, self._month)
            number = (
                self._selected.day
                if (self._year, self._month) == (self._selected.year, self._selected.month)
                else 1
            )
            self.day_buttons[first + number - 1]._canvas.focus_set()

    def _move_month(self, delta: int) -> None:
        ordinal = (self._year - 1) * 12 + self._month - 1 + delta
        maximum = (self._max_date.year - 1) * 12 + self._max_date.month - 1
        if 0 <= ordinal <= maximum:
            self._year, month = divmod(ordinal, 12)
            self._year += 1
            self._month = month + 1
            self._render()

    def _render(self) -> None:
        self.month_label.configure(text=f"{MONTH_NAMES[self._month - 1]} de {self._year}")
        first, count = calendar.monthrange(self._year, self._month)
        for index, button in enumerate(self.day_buttons):
            number = index - first + 1
            valid = 1 <= number <= count
            day = date(self._year, self._month, number) if valid else None
            enabled = day is not None and day <= self._max_date
            button.configure(
                text=str(number) if valid else "",
                state="normal" if enabled else "disabled",
                fg_color=theme.SELECTION if day == self._selected else theme.SIDEBAR,
                border_width=2 if day == self._selected else 0,
                border_color=theme.FOCUS,
                text_color_disabled=theme.MUTED,
                command=lambda selected=day: self.select_day(selected) if selected else None,
            )
            button._canvas.configure(takefocus=enabled)
        for button, enabled in (
            (self.previous_button, (self._year, self._month) > (1, 1)),
            (
                self.next_button,
                (self._year, self._month) < (self._max_date.year, self._max_date.month),
            ),
        ):
            button.configure(state="normal" if enabled else "disabled")
            button._canvas.configure(takefocus=enabled)

    def select_day(self, day: date) -> None:
        """Seleciona somente uma data válida e libera a modalidade antes do callback."""
        if self._closed or day > self._max_date or day.year > 9998:
            return
        self.close()
        self._on_select(day)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._activation_job is not None:
            self.after_cancel(self._activation_job)
            self._activation_job = None
        if self.grab_current() is self:
            self.grab_release()
        self.destroy()
