"""Cadastro e gerenciamento local de tipos em um diálogo reutilizável."""

import logging
from collections.abc import Callable
from tkinter import messagebox

import customtkinter as ctk

from app.models import StudyColor, StudyType
from app.services.study_type_service import StudyTypeService
from app.ui import theme


class StudyTypeDialog(ctk.CTkToplevel):
    """O catálogo confirma operações antes de atualizar seleção ou formulário."""

    def __init__(
        self,
        master: ctk.CTk,
        service: StudyTypeService,
        on_saved: Callable[[int | None], None],
        *,
        manage: bool = False,
    ) -> None:
        super().__init__(master, fg_color=theme.BACKGROUND)
        self._service = service
        self._on_saved = on_saved
        self._manage = manage
        self._selected_id: int | None = None
        self._closed = False
        self._activation_job: str | None = None
        self._rows: list[ctk.CTkButton] = []
        self._items: dict[int, StudyType] = {}
        self.title("Gerenciar tipos" if manage else "Novo tipo")
        self.geometry("520x560" if manage else "480x330")
        self.minsize(420, 320)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(self, fg_color=theme.SURFACE)
        body.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        body.grid_columnconfigure(0, weight=1)
        self._list = ctk.CTkScrollableFrame(body, height=150, fg_color=theme.SIDEBAR)
        if manage:
            self._list.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
            new_button = ctk.CTkButton(
                body,
                text="+ Novo tipo",
                command=self.clear_selection,
                fg_color=theme.PRIMARY,
                hover_color=theme.HOVER,
            )
            new_button.grid(row=1, column=0, sticky="w", padx=12, pady=8)
            theme.keyboard_button(new_button)
        ctk.CTkLabel(body, text="Nome", text_color=theme.TEXT).grid(
            row=2, column=0, padx=12, sticky="w"
        )
        self.name_entry = ctk.CTkEntry(
            body,
            fg_color=theme.SURFACE,
            text_color=theme.TEXT,
            border_color=theme.BORDER,
            height=36,
        )
        self.name_entry.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 8))
        ctk.CTkLabel(body, text="Cor", text_color=theme.TEXT).grid(
            row=4, column=0, padx=12, sticky="w"
        )
        self.color_menu = ctk.CTkOptionMenu(
            body,
            values=list(theme.COLOR_NAMES.values()),
            command=self._show_color,
            fg_color=theme.SIDEBAR,
            text_color=theme.TEXT,
            button_color=theme.PRIMARY,
            dropdown_fg_color=theme.SURFACE,
            dropdown_text_color=theme.TEXT,
            dropdown_hover_color=theme.SELECTION,
        )
        self.color_menu.grid(row=5, column=0, sticky="ew", padx=12, pady=4)
        theme.keyboard_choice(self.color_menu, self._show_color)
        self.color_preview = ctk.CTkLabel(
            body, text="●", text_color=theme.STUDY_COLORS[StudyColor.BLUE]
        )
        self.color_preview.grid(row=6, column=0, sticky="w", padx=12)
        self.archive_button = ctk.CTkButton(
            body,
            text="Arquivar",
            command=self.toggle_archived,
            fg_color=theme.SIDEBAR,
            text_color=theme.TEXT,
            hover_color=theme.SELECTION,
        )
        if manage:
            self.archive_button.grid(row=7, column=0, sticky="w", padx=12, pady=4)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, pady=(0, 12))
        self.save_button = ctk.CTkButton(
            actions,
            text="Salvar",
            width=120,
            command=self.save,
            fg_color=theme.PRIMARY,
            hover_color=theme.HOVER,
        )
        self.save_button.grid(row=0, column=0, padx=6)
        self.cancel_button = ctk.CTkButton(
            actions,
            text="Fechar" if manage else "Cancelar",
            width=120,
            command=self.close,
            fg_color=theme.SIDEBAR,
            text_color=theme.TEXT,
            hover_color=theme.SELECTION,
        )
        self.cancel_button.grid(row=0, column=1, padx=6)
        for button in (self.save_button, self.cancel_button, self.archive_button):
            theme.keyboard_button(button)
        self.bind("<Escape>", lambda event: self.close())
        self.name_entry.bind("<Return>", lambda event: self.save())
        self.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.refresh()
        except Exception:
            self.destroy()
            raise
        self._activation_job = self.after_idle(self._activate)

    def _activate(self) -> None:
        self._activation_job = None
        if not self._closed:
            self.grab_set()
            self.name_entry.focus_set()

    def _show_color(self, label: str) -> None:
        color = next(key for key, name in theme.COLOR_NAMES.items() if name == label)
        self.color_preview.configure(text_color=theme.STUDY_COLORS[color])

    def refresh(self) -> None:
        items = self._service.list_types(include_archived=True)
        self._items = {item.id: item for item in items}
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        for item in items if self._manage else []:
            row = ctk.CTkButton(
                self._list,
                text=item.name + (" · arquivado" if item.is_archived else ""),
                text_color=theme.STUDY_COLORS[item.color_key],
                fg_color="transparent",
                hover_color=theme.SELECTION,
                anchor="w",
                command=lambda type_id=item.id: self.select_type(type_id),
            )
            row.pack(fill="x", padx=4, pady=2)
            self._rows.append(row)
            theme.keyboard_button(row)
        self.archive_button.configure(
            state="normal" if self._selected_id is not None else "disabled"
        )

    def clear_selection(self) -> None:
        self._selected_id = None
        self.name_entry.delete(0, "end")
        self.color_menu.set(theme.COLOR_NAMES[StudyColor.BLUE])
        self._show_color(theme.COLOR_NAMES[StudyColor.BLUE])
        self.archive_button.configure(state="disabled")
        self.name_entry.focus_set()

    def select_type(self, type_id: int) -> None:
        item = self._items[type_id]
        self._selected_id = type_id
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, item.name)
        self.color_menu.set(theme.COLOR_NAMES[item.color_key])
        self._show_color(theme.COLOR_NAMES[item.color_key])
        self.archive_button.configure(
            text="Reativar" if item.is_archived else "Arquivar", state="normal"
        )
        self.name_entry.focus_set()

    def save(self) -> None:
        try:
            color = next(
                key for key, name in theme.COLOR_NAMES.items() if name == self.color_menu.get()
            )
            if self._selected_id is None:
                item = self._service.create_type(str(self.name_entry.get()), color)
            else:
                item = self._service.update_type(
                    self._selected_id, str(self.name_entry.get()), color
                )
        except ValueError as error:
            messagebox.showerror("Tipo de estudo", str(error), parent=self)
            return
        except Exception as error:
            self._show_failure(error)
            return
        self._saved(item)

    def toggle_archived(self) -> None:
        if self._selected_id is None:
            return
        try:
            item = self._items[self._selected_id]
            changed = (
                self._service.restore_type(item.id)
                if item.is_archived
                else self._service.archive_type(item.id)
            )
        except ValueError as error:
            messagebox.showerror("Tipo de estudo", str(error), parent=self)
            return
        except Exception as error:
            self._show_failure(error)
            return
        self._saved(changed)

    def _saved(self, item: StudyType) -> None:
        self._selected_id = item.id
        try:
            self._on_saved(None if item.is_archived else item.id)
            if self._manage:
                self.refresh()
                self.select_type(item.id)
            else:
                self.close()
        except Exception as error:
            logging.getLogger("studytimer.ui").error(
                "TYPE_REFRESH_FAILED type=%s", type(error).__name__
            )
            messagebox.showerror(
                "Tipos de estudo",
                "O tipo foi salvo, mas o catálogo não pôde ser atualizado. "
                "Abra o gerenciamento novamente.",
                parent=self,
            )
            self.close()

    def _show_failure(self, error: Exception) -> None:
        logging.getLogger("studytimer.ui").error(
            "TYPE_OPERATION_FAILED type=%s", type(error).__name__
        )
        messagebox.showerror(
            "Tipo de estudo", "Não foi possível salvar o tipo. Tente novamente.", parent=self
        )

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
