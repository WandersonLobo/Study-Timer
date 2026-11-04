"""Histórico por período e tipo, alimentado por um único relatório imutável."""

from collections.abc import Callable
from datetime import date, timedelta

import customtkinter as ctk

from app.models import PeriodReport, PeriodSessionSummary, ReportPeriod
from app.ui import theme
from app.ui.formatting import format_clock, format_duration_compact
from app.ui.study_chart import StudyChart

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


class HistoryView(ctk.CTkScrollableFrame):
    """Renderiza dados prontos sem executar SQL ou calcular durações."""

    def __init__(
        self,
        master: ctk.CTkFrame,
        on_step: Callable[[int], None],
        on_mode: Callable[[ReportPeriod], None],
        on_day_picker: Callable[[], None],
        on_today: Callable[[], None],
        on_filter: Callable[[int | None], None],
        on_clear_filter: Callable[[], None],
        on_bucket: Callable[[int], None],
        on_back: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color=theme.BACKGROUND)
        self.report: PeriodReport | None = None
        self._on_filter = on_filter
        self._session_limit = 50
        self._rank_limit = 10
        self._selection_key: object = None
        self._session_data: tuple[PeriodSessionSummary, ...] = ()
        self._session_rows: list[ctk.CTkLabel] = []
        self._ranking_rows: list[tuple[ctk.CTkButton, ctk.CTkProgressBar, ctk.CTkLabel]] = []
        self._average_tip: ctk.CTkToplevel | None = None
        self._wide: bool | None = None
        self._layout_key: object = None
        self.grid_columnconfigure((0, 1), weight=1, uniform="history")
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="Histórico", font=("Segoe UI", 28, "bold"), text_color=theme.TEXT
        ).grid(row=0, column=0, sticky="w")
        modes = ctk.CTkFrame(header, fg_color=theme.SIDEBAR)
        modes.grid(row=0, column=1, sticky="e")
        self.period_buttons: dict[ReportPeriod, ctk.CTkButton] = {}
        for column, (mode, label) in enumerate(
            ((ReportPeriod.DAY, "Dia"), (ReportPeriod.WEEK, "Semana"), (ReportPeriod.MONTH, "Mês"))
        ):
            button = ctk.CTkButton(
                modes, text=label, width=72, command=lambda value=mode: on_mode(value)
            )
            button.grid(row=0, column=column, padx=2, pady=2)
            theme.keyboard_button(button)
            self.period_buttons[mode] = button
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        nav.grid_columnconfigure(1, weight=1)
        self.previous_button = ctk.CTkButton(nav, text="‹", width=40, command=lambda: on_step(-1))
        self.previous_button.grid(row=0, column=0, padx=(0, 6))
        self.period_label = ctk.CTkButton(
            nav,
            text="",
            command=on_day_picker,
            fg_color=theme.SURFACE,
            text_color=theme.TEXT,
            hover_color=theme.SELECTION,
            height=34,
        )
        self.period_label.grid(row=0, column=1, sticky="ew")
        self.next_button = ctk.CTkButton(nav, text="›", width=40, command=lambda: on_step(1))
        self.next_button.grid(row=0, column=2, padx=6)
        self.today_button = ctk.CTkButton(nav, text="Hoje", width=60, command=on_today)
        self.today_button.grid(row=0, column=3)
        for button in (
            self.previous_button,
            self.period_label,
            self.next_button,
            self.today_button,
        ):
            theme.keyboard_button(button)
        metrics = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=12)
        metrics.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        metrics.grid_columnconfigure((0, 1), weight=1)
        self.average_label = ctk.CTkLabel(
            metrics, text="", font=("Segoe UI", 28, "bold"), text_color=theme.TEXT, anchor="w"
        )
        self.average_label.grid(row=0, column=0, padx=20, pady=(12, 0), sticky="ew")
        self.average_caption = ctk.CTkLabel(metrics, text="", text_color=theme.MUTED, anchor="w")
        self.average_caption.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="w")
        self.total_label = ctk.CTkLabel(
            metrics, text="", font=("Segoe UI", 24, "bold"), text_color=theme.TEXT, anchor="e"
        )
        self.total_label.grid(row=0, column=1, padx=20, pady=(12, 0), sticky="ew")
        self.total_caption = ctk.CTkLabel(metrics, text="", text_color=theme.MUTED, anchor="e")
        self.total_caption.grid(row=1, column=1, padx=20, pady=(0, 12), sticky="e")
        self.average_label.bind("<Enter>", lambda event: self._show_average_tip())
        self.average_label.bind("<Leave>", lambda event: self._hide_average_tip())
        context = ctk.CTkFrame(self, fg_color="transparent")
        context.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8))
        context.grid_columnconfigure(0, weight=1)
        self.filter_label = ctk.CTkLabel(context, text="", text_color=theme.TEXT, anchor="w")
        self.filter_label.configure(wraplength=220, justify="left")
        self.filter_label.grid(row=0, column=0, sticky="w")
        self.clear_filter_button = ctk.CTkButton(
            context, text="Todos os tipos", width=120, command=on_clear_filter
        )
        self.clear_filter_button.grid(row=0, column=1, padx=4)
        self.back_button = ctk.CTkButton(context, text="", width=140, command=on_back)
        self.back_button.grid(row=0, column=2, padx=4)
        for button in (self.clear_filter_button, self.back_button):
            theme.keyboard_button(button)
        self.chart = StudyChart(self, on_bucket)
        self.chart.grid(row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        self._ranking_panel = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=12)
        self._ranking_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self._ranking_panel,
            text="Tipos mais estudados",
            text_color=theme.TEXT,
            font=("Segoe UI", 19, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=12)
        self._ranking_body = ctk.CTkFrame(self._ranking_panel, fg_color="transparent")
        self._ranking_body.grid(row=1, column=0, sticky="ew", padx=12)
        self._ranking_body.grid_columnconfigure(0, weight=1)
        self.more_types_button = ctk.CTkButton(
            self._ranking_panel, text="Mostrar mais tipos", command=self._show_more_types
        )
        self.more_types_button.grid(row=2, column=0, pady=12)
        theme.keyboard_button(self.more_types_button)
        self._session_panel = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=12)
        self._session_panel.grid_columnconfigure(0, weight=1)
        self.day_label = ctk.CTkLabel(
            self._session_panel,
            text="Sessões do período",
            font=("Segoe UI", 19, "bold"),
            text_color=theme.TEXT,
        )
        self.day_label.grid(row=0, column=0, sticky="w", padx=16, pady=12)
        self._details = ctk.CTkFrame(self._session_panel, fg_color="transparent")
        self._details.grid(row=1, column=0, sticky="ew", padx=12)
        self._details.grid_columnconfigure(0, weight=1)
        self.more_button = ctk.CTkButton(
            self._session_panel, text="Mostrar mais", command=self._show_more
        )
        self.more_button.grid(row=2, column=0, pady=12)
        theme.keyboard_button(self.more_button)
        self._empty_label = ctk.CTkLabel(
            self, text="Sem estudos neste período.", text_color=theme.MUTED
        )
        self._empty_label.grid(row=7, column=0, columnspan=2, pady=12)
        self.status_label = ctk.CTkLabel(self, text="", text_color=theme.ERROR)
        self.status_label.grid(row=8, column=0, columnspan=2, pady=6)
        self.bind("<Configure>", lambda event: self._layout_details())

    def render(
        self, report: PeriodReport, today: date, parent_period: ReportPeriod | None = None
    ) -> None:
        key = report.selection
        if key != self._selection_key:
            self._session_limit, self._rank_limit = 50, 10
            self._selection_key = key
        changed = report != self.report
        if changed:
            self._hide_average_tip()
        self.report = report
        self._session_data = report.sessions
        period = report.selection.period
        for mode, button in self.period_buttons.items():
            button.configure(
                fg_color=theme.PRIMARY if mode == period else theme.SIDEBAR,
                text_color=("white" if mode == period else theme.TEXT),
                hover_color=theme.HOVER if mode == period else theme.SELECTION,
            )
        self.period_label.configure(text=self._period_title(report))
        self.previous_button.configure(
            state="disabled" if report.start_day == date.min else "normal"
        )
        self.next_button.configure(state="normal" if report.end_day <= today else "disabled")
        total = format_duration_compact(report.total_s)
        self.average_label.configure(
            text=total if period == ReportPeriod.DAY else format_duration_compact(report.average_s)
        )
        self.average_caption.configure(
            text="Total estudado no dia" if period == ReportPeriod.DAY else "Média diária"
        )
        self.total_label.configure(text="" if period == ReportPeriod.DAY else total)
        self.total_caption.configure(
            text=""
            if period == ReportPeriod.DAY
            else ("Total semanal" if period == ReportPeriod.WEEK else "Total mensal")
        )
        filtered = report.selection.type_filter != "all"
        name = report.filter_name or "Tipo selecionado"
        self.filter_label.configure(text=name if filtered else "")
        if filtered:
            self.clear_filter_button.grid()
        else:
            self.clear_filter_button.grid_remove()
        if parent_period is not None:
            self.back_button.configure(
                text="Voltar à semana" if parent_period == ReportPeriod.WEEK else "Voltar ao mês"
            )
            self.back_button.grid()
        else:
            self.back_button.grid_remove()
        if changed:
            self.chart.render(report)
            self._render_ranking()
            self._render_sessions()
        if not report.sessions and report.total_s == 0:
            self._empty_label.grid()
        else:
            self._empty_label.grid_remove()
        self._layout_details()
        self.status_label.configure(text="")

    @staticmethod
    def _period_title(report: PeriodReport) -> str:
        first = report.start_day
        if report.selection.period == ReportPeriod.MONTH:
            return f"{MONTH_NAMES[first.month - 1]} de {first.year}"
        if report.selection.period == ReportPeriod.WEEK:
            last = report.end_day - timedelta(days=1)
            return f"{first:%d/%m} – {last:%d/%m/%Y}"
        return f"{first.day} de {MONTH_NAMES[first.month - 1].lower()} de {first.year}"

    def _layout_details(self) -> None:
        if self.report is None:
            return
        show_sessions = (
            self.report.selection.period == ReportPeriod.DAY
            or self.report.selection.type_filter != "all"
        )
        logical_width = int(self.winfo_width() / self._get_widget_scaling())
        wide = logical_width >= 850 and show_sessions
        key = (self.winfo_width(), show_sessions, len(self._session_rows))
        if key == self._layout_key:
            return
        self._layout_key = key
        self._ranking_panel.grid(
            row=5, column=0, columnspan=1 if wide else 2, sticky="nsew", padx=12, pady=(0, 12)
        )
        if show_sessions:
            self._session_panel.grid(
                row=5 if wide else 6,
                column=1 if wide else 0,
                columnspan=1 if wide else 2,
                sticky="nsew",
                padx=12,
                pady=(0, 12),
            )
        else:
            self._session_panel.grid_remove()
        wrap = max(100, (logical_width // 2 if wide else logical_width) - 150)
        if wide != self._wide:
            self._wide = wide
        for label in self._session_rows[::2]:
            label.configure(wraplength=wrap)

    def _render_ranking(self) -> None:
        if self.report is None:
            return
        visible = self.report.ranking[: self._rank_limit]
        while len(self._ranking_rows) > len(visible):
            for widget in self._ranking_rows.pop():
                widget.destroy()
        while len(self._ranking_rows) < len(visible):
            index = len(self._ranking_rows)
            button = ctk.CTkButton(
                self._ranking_body,
                text="",
                anchor="w",
                fg_color="transparent",
                hover_color=theme.SELECTION,
                height=30,
            )
            button.grid(row=index * 2, column=0, sticky="ew")
            theme.keyboard_button(button)
            duration = ctk.CTkLabel(self._ranking_body, text="", text_color=theme.TEXT)
            button.bind("<Enter>", lambda event, row=index: self._show_rank_tip(row), add="+")
            button.bind("<Leave>", lambda event: self._hide_average_tip(), add="+")
            button.bind("<FocusIn>", lambda event, row=index: self._show_rank_tip(row), add="+")
            button.bind("<FocusOut>", lambda event: self._hide_average_tip(), add="+")
            duration.grid(row=index * 2, column=1, padx=(8, 0), sticky="e")
            bar = ctk.CTkProgressBar(self._ranking_body, height=5, fg_color=theme.DISABLED)
            bar.grid(row=index * 2 + 1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
            self._ranking_rows.append((button, bar, duration))
        for (button, bar, duration), item in zip(self._ranking_rows, visible, strict=True):
            color = theme.STUDY_COLORS[item.color_key] if item.color_key else theme.MUTED
            button.configure(
                text="● " + (item.name if len(item.name) <= 30 else item.name[:29] + "…"),
                text_color=color,
                command=lambda type_id=item.type_id: self._on_filter(type_id),
            )
            bar.configure(progress_color=color)
            bar.set(item.percentage / 100)
            duration.configure(
                text=f"{format_duration_compact(item.duration_s)}  {item.percentage:.0f}%"
            )
        if len(self.report.ranking) > self._rank_limit:
            self.more_types_button.grid()
        else:
            self.more_types_button.grid_remove()

    def _render_sessions(self) -> None:
        visible = self._session_data[: self._session_limit]
        needed = len(visible) * 2
        while len(self._session_rows) > needed:
            self._session_rows.pop().destroy()
        while len(self._session_rows) < needed:
            index = len(self._session_rows) // 2
            label = ctk.CTkLabel(
                self._details,
                text="",
                anchor="w",
                justify="left",
                text_color=theme.TEXT,
                wraplength=300,
            )
            label.grid(row=index, column=0, sticky="ew", pady=5)
            duration = ctk.CTkLabel(self._details, text="", text_color=theme.TEXT, width=76)
            duration.grid(row=index, column=1, sticky="e", padx=(8, 0), pady=5)
            self._session_rows.extend((label, duration))
        for index, item in enumerate(visible):
            self._session_rows[index * 2].configure(
                text=f"{item.name}\n{item.type_name} · {item.day:%d/%m/%Y}"
            )
            self._session_rows[index * 2 + 1].configure(text=format_clock(item.duration_s))
        if len(self._session_data) > self._session_limit:
            self.more_button.grid()
        else:
            self.more_button.grid_remove()
        self.day_label.configure(
            text="Sessões do dia"
            if self.report is not None and self.report.selection.period == ReportPeriod.DAY
            else "Sessões do período"
        )

    def _show_more(self) -> None:
        self._session_limit += 50
        self._render_sessions()
        self._layout_details()

    def _show_more_types(self) -> None:
        self._rank_limit += 10
        self._render_ranking()

    def refresh_theme(self) -> None:
        self.chart.refresh_theme()

    def _show_average_tip(self) -> None:
        if self.report is None or self.report.selection.period == ReportPeriod.DAY:
            return
        self._show_text_tip(
            self.average_label, f"Média dos {self.report.average_days} dias do período"
        )

    def _show_rank_tip(self, index: int) -> None:
        if self.report is not None and index < len(self._ranking_rows):
            self._show_text_tip(self._ranking_rows[index][0], self.report.ranking[index].name)

    def _show_text_tip(self, widget: ctk.CTkLabel | ctk.CTkButton, text: str) -> None:
        self._hide_average_tip()
        self._average_tip = ctk.CTkToplevel(self)
        self._average_tip.overrideredirect(True)
        self._average_tip.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + 32}")
        ctk.CTkLabel(
            self._average_tip,
            text=text,
            wraplength=320,
            text_color=theme.TEXT,
            fg_color=theme.SURFACE,
        ).pack(padx=8, pady=4)

    def _hide_average_tip(self) -> None:
        if self._average_tip is not None:
            self._average_tip.destroy()
            self._average_tip = None

    def show_error(self) -> None:
        self.status_label.configure(text="Histórico não atualizado · operação não confirmada")
