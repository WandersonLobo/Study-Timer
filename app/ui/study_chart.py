"""Gráfico de estudos em Canvas, desenhado a partir de resultados imutáveis."""

from __future__ import annotations

import math
from collections.abc import Callable
from tkinter import Canvas, Event

import customtkinter as ctk

from app.models import AppearanceMode
from app.models.period_report import PeriodReport
from app.ui import theme
from app.ui.formatting import format_clock


class StudyChart(ctk.CTkFrame):
    """Apresenta segundos já agregados, sem acesso a serviços ou relógios."""

    def __init__(self, master: ctk.CTkFrame, on_select: Callable[[int], None]) -> None:
        super().__init__(master, fg_color=theme.SURFACE, corner_radius=10)
        self._on_select = on_select
        self._report: PeriodReport | None = None
        self._context: tuple[object, ...] | None = None
        self.selected_index: int | None = None
        self._regions: list[tuple[float, float]] = []
        self._plot_top = 0.0
        self._plot_bottom = 0.0
        self._focused = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.canvas = Canvas(
            self,
            height=280,
            width=300,
            borderwidth=0,
            highlightthickness=2,
            takefocus=True,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.canvas.bind("<Configure>", lambda event: self._draw_chart())
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda event: self.canvas.delete("tooltip"))
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Left>", lambda event: self._move(-1))
        self.canvas.bind("<Right>", lambda event: self._move(1))
        self.canvas.bind("<Return>", lambda event: self._activate())
        self.canvas.bind("<space>", lambda event: self._activate())
        self.canvas.bind("<Escape>", lambda event: self.canvas.delete("tooltip"))
        self.canvas.bind("<FocusIn>", lambda event: self._focus(True))
        self.canvas.bind("<FocusOut>", lambda event: self._focus(False))
        self.refresh_theme()

    def render(self, report: PeriodReport) -> None:
        """Conserva o índice selecionado em atualizações do mesmo período."""
        context = (report.selection.period, report.start_utc, report.end_utc)
        changed = report != self._report
        if context != self._context:
            self.selected_index = None
        self._context = context
        self._report = report
        if self.selected_index is not None and self.selected_index >= len(report.buckets):
            self.selected_index = None
        if changed:
            self._draw_chart()

    def refresh_theme(self) -> None:
        """Atualiza somente apresentação, sem consultar o banco."""
        self._draw_chart()

    def _set_appearance_mode(self, mode_string: str) -> None:
        super()._set_appearance_mode(mode_string)
        if hasattr(self, "canvas"):
            self._draw_chart()

    def _set_scaling(self, new_widget_scaling: float, new_window_scaling: float) -> None:
        super()._set_scaling(new_widget_scaling, new_window_scaling)
        if hasattr(self, "canvas"):
            self.canvas.configure(height=round(280 * self._get_widget_scaling()))
            self._draw_chart()

    def _color(self, value: theme.Color) -> str:
        mode = AppearanceMode.LIGHT if ctk.get_appearance_mode() == "Light" else AppearanceMode.DARK
        return theme.resolve_color(value, mode)

    @staticmethod
    def _axis_label(seconds: int) -> str:
        if seconds == 0:
            return "0"
        if seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds >= 3600:
            return f"{seconds / 3600:g}h"
        return f"{seconds // 60}min"

    @staticmethod
    def _axis_step(maximum: int) -> int:
        for step in (60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400):
            if maximum <= step * 3:
                return step
        return math.ceil(maximum / (3 * 86400)) * 86400

    def _draw_chart(self) -> None:
        if not hasattr(self, "canvas"):
            return
        canvas = self.canvas
        canvas.configure(
            background=self._color(theme.SURFACE),
            highlightbackground=self._color(theme.SURFACE),
            highlightcolor=self._color(theme.FOCUS),
        )
        canvas.delete("all")
        self._regions.clear()
        report = self._report
        if report is None:
            return
        scale = float(self._get_widget_scaling())
        width = max(160, canvas.winfo_width())
        height = max(160, canvas.winfo_height())
        small_font = ("Segoe UI", -max(9, round(11 * scale)))
        left = 58 * scale
        right = width - 16 * scale
        top = 14 * scale
        leading = report.ranking[:5]
        has_others = len(report.ranking) > 5
        legend_rows = 2 if len(leading) + int(has_others) > 3 else 1
        bottom = max(top + 40, height - (42 + 23 * legend_rows) * scale)
        self._plot_top, self._plot_bottom = top, bottom
        maximum = max((bucket.duration_s for bucket in report.buckets), default=0)
        step = self._axis_step(maximum)
        ceiling = max(step * 3, math.ceil(maximum / step) * step)
        for value in range(0, ceiling + 1, step):
            y = bottom - (bottom - top) * value / ceiling
            canvas.create_line(left, y, right, y, fill=self._color(theme.BORDER))
            canvas.create_text(
                left - 8 * scale,
                y,
                text=self._axis_label(value),
                font=small_font,
                fill=self._color(theme.MUTED),
                anchor="e",
            )
        count = len(report.buckets)
        if count:
            slot = max(1.0, (right - left) / count)
            visible_ids = {item.type_id for item in leading}
            spacing = max(1, slot * 0.2)
            label_stride = max(1, math.ceil(count / max(4, (right - left) / (65 * scale))))
            for index, bucket in enumerate(report.buckets):
                x0, x1 = left + slot * index, left + slot * (index + 1)
                self._regions.append((x0, x1))
                y = bottom
                bucket_totals = {item.type_id: item.duration_s for item in bucket.totals}
                contributions = [
                    (
                        bucket_totals.get(item.type_id, 0),
                        theme.STUDY_COLORS[item.color_key]
                        if item.color_key is not None
                        else theme.MUTED,
                    )
                    for item in leading
                ]
                other_s = sum(
                    item.duration_s for item in bucket.totals if item.type_id not in visible_ids
                )
                if other_s:
                    contributions.append((other_s, theme.MUTED))
                for seconds, color in contributions:
                    if seconds <= 0:
                        continue
                    following = y - (bottom - top) * seconds / ceiling
                    canvas.create_rectangle(
                        x0 + spacing,
                        following,
                        x1 - spacing,
                        y,
                        fill=self._color(color),
                        outline="",
                        tags=(f"bucket:{index}", "bar"),
                    )
                    y = following
                if index == self.selected_index:
                    canvas.create_rectangle(
                        x0 + 1,
                        top,
                        x1 - 1,
                        bottom + 2 * scale,
                        outline=self._color(theme.FOCUS),
                        width=2,
                        dash=(3, 2),
                    )
                if index % label_stride == 0 or index == count - 1:
                    label = bucket.label.split(" ")[0] if count > 10 else bucket.label
                    canvas.create_text(
                        (x0 + x1) / 2,
                        bottom + 15 * scale,
                        text=label,
                        font=small_font,
                        fill=self._color(theme.TEXT),
                        anchor="n",
                    )
        legend = [
            (
                item.name,
                theme.STUDY_COLORS[item.color_key] if item.color_key is not None else theme.MUTED,
            )
            for item in leading
        ]
        if has_others:
            legend.append(("Outros", theme.MUTED))
        columns = 3 if legend_rows == 2 else max(1, len(legend))
        legend_width = max(1, (right - left) / columns)
        for index, (name, color) in enumerate(legend):
            x = left + (index % columns) * legend_width
            y = bottom + (42 + (index // columns) * 23) * scale
            label = name if len(name) <= 23 else name[:22] + "…"
            canvas.create_rectangle(
                x, y - 5 * scale, x + 9 * scale, y + 4 * scale, fill=self._color(color), outline=""
            )
            canvas.create_text(
                x + 15 * scale,
                y,
                text=label,
                font=small_font,
                fill=self._color(theme.TEXT),
                anchor="w",
            )
        if self._focused:
            canvas.configure(highlightbackground=self._color(theme.FOCUS))
            if self.selected_index is not None:
                self._show_tooltip(self.selected_index)

    def _index_at(self, x: float, y: float) -> int | None:
        if not self._plot_top <= y <= self._plot_bottom:
            return None
        return next(
            (index for index, (left, right) in enumerate(self._regions) if left <= x < right), None
        )

    def _motion(self, event: Event[Canvas]) -> None:
        index = self._index_at(event.x, event.y)
        self.canvas.delete("tooltip")
        if index is not None:
            self._show_tooltip(index)

    def _click(self, event: Event[Canvas]) -> None:
        self.canvas.focus_set()
        index = self._index_at(event.x, event.y)
        if index is not None:
            self.select_bucket(index)

    def select_bucket(self, index: int) -> None:
        """Seleciona e aciona o mesmo callback usado pelo mouse e teclado."""
        if self._report is None or not 0 <= index < len(self._report.buckets):
            return
        self.selected_index = index
        self._draw_chart()
        self._show_tooltip(index)
        self._on_select(index)

    def _move(self, delta: int) -> str:
        if self._report is not None and self._report.buckets:
            if self.selected_index is None:
                self.selected_index = 0 if delta > 0 else len(self._report.buckets) - 1
            else:
                self.selected_index = (self.selected_index + delta) % len(self._report.buckets)
            self._draw_chart()
            self._show_tooltip(self.selected_index)
        return "break"

    def _activate(self) -> str:
        if self._report is not None and self._report.buckets:
            self.select_bucket(self.selected_index if self.selected_index is not None else 0)
        return "break"

    def _focus(self, focused: bool) -> None:
        self._focused = focused
        self._draw_chart()

    def _show_tooltip(self, index: int) -> None:
        report = self._report
        if report is None or not 0 <= index < len(report.buckets):
            return
        self.canvas.delete("tooltip")
        bucket = report.buckets[index]
        lines = [f"{bucket.label} · {format_clock(bucket.duration_s)}"]
        lines.extend(f"{item.name}  {format_clock(item.duration_s)}" for item in bucket.totals[:8])
        if len(bucket.totals) > 8:
            remaining = sum(item.duration_s for item in bucket.totals[8:])
            lines.append(f"Outros ({len(bucket.totals) - 8} tipos)  {format_clock(remaining)}")
        scale = float(self._get_widget_scaling())
        width = min(390 * scale, max(100, self.canvas.winfo_width() - 24))
        x = 12 * scale
        y = 12 * scale
        text_id = self.canvas.create_text(
            x + 10,
            y + 8,
            text="\n".join(lines),
            anchor="nw",
            width=width - 20,
            font=("Segoe UI", -max(11, round(12 * scale))),
            fill=self._color(theme.TEXT),
            tags="tooltip",
        )
        bounds = self.canvas.bbox(text_id)
        if bounds is not None:
            rect = self.canvas.create_rectangle(
                bounds[0] - 8,
                bounds[1] - 6,
                bounds[2] + 8,
                bounds[3] + 6,
                fill=self._color(theme.SIDEBAR),
                outline=self._color(theme.BORDER),
                tags="tooltip",
            )
            self.canvas.tag_lower(rect, text_id)
