"""Cronômetro com classificação; duração e persistência pertencem aos serviços."""

from collections.abc import Callable

import customtkinter as ctk

from app.models import Session, SessionStatus, StudyType, UIState
from app.ui import theme
from app.ui.formatting import format_clock


class TimerView(ctk.CTkFrame):
    """Conserva widgets e edição durante ticks e mudanças de aparência."""

    def __init__(
        self,
        master: ctk.CTkFrame,
        on_start: Callable[[], None],
        on_pause: Callable[[], None],
        on_finish: Callable[[], None],
        on_create_type: Callable[[], None],
        on_manage_types: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color=theme.BACKGROUND)
        self._types: dict[int, StudyType] = {}
        self._type_by_name: dict[str, int] = {}
        self._last_session_id: int | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            self, text="Cronômetro", font=("Segoe UI", 28, "bold"), text_color=theme.TEXT
        ).grid(row=0, column=0, padx=24, pady=20, sticky="w")
        body = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.SURFACE,
            corner_radius=12,
            border_width=1,
            border_color=theme.BORDER,
        )
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        body.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(body, text="Pronto", text_color=theme.SUCCESS)
        self.status_label.grid(row=0, column=0, padx=24, pady=(20, 10), sticky="w")
        ctk.CTkLabel(
            body, text="Tipo de estudo", text_color=theme.TEXT, font=("Segoe UI", 14, "bold")
        ).grid(row=1, column=0, padx=24, sticky="w")
        selection = ctk.CTkFrame(body, fg_color="transparent")
        selection.grid(row=2, column=0, padx=24, pady=(4, 0), sticky="ew")
        selection.grid_columnconfigure(1, weight=1)
        self.type_color = ctk.CTkLabel(selection, text="●", width=26, text_color=theme.MUTED)
        self.type_color.grid(row=0, column=0)
        self.type_menu = ctk.CTkOptionMenu(
            selection,
            values=["Sem tipo"],
            command=self._on_type_selected,
            height=36,
            fg_color=theme.SIDEBAR,
            button_color=theme.PRIMARY,
            button_hover_color=theme.HOVER,
            text_color=theme.TEXT,
            dropdown_fg_color=theme.SURFACE,
            dropdown_text_color=theme.TEXT,
            dropdown_hover_color=theme.SELECTION,
            dynamic_resizing=False,
        )
        self.type_menu.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        theme.keyboard_choice(self.type_menu, self._on_type_selected)
        self.new_type_button = ctk.CTkButton(
            selection,
            text="+ Novo tipo",
            width=112,
            height=36,
            command=on_create_type,
            fg_color=theme.PRIMARY,
            hover_color=theme.HOVER,
        )
        self.new_type_button.grid(row=0, column=2)
        self.manage_types_button = ctk.CTkButton(
            body,
            text="Gerenciar tipos",
            command=on_manage_types,
            width=120,
            fg_color="transparent",
            text_color=theme.LINK,
            hover_color=theme.SELECTION,
        )
        self.manage_types_button.grid(row=3, column=0, padx=24, pady=(2, 12), sticky="e")
        ctk.CTkLabel(
            body, text="Descrição do estudo", text_color=theme.TEXT, font=("Segoe UI", 14, "bold")
        ).grid(row=4, column=0, padx=24, sticky="w")
        self.name_entry = ctk.CTkEntry(
            body,
            placeholder_text="Descrição do estudo",
            height=38,
            fg_color=theme.SURFACE,
            text_color=theme.TEXT,
            border_color=theme.BORDER,
        )
        self.name_entry.grid(row=5, column=0, padx=24, pady=(4, 12), sticky="ew")
        self.elapsed_label = ctk.CTkLabel(
            body, text="00:00:00", font=("Consolas", 56), text_color=theme.TEXT
        )
        self.elapsed_label.grid(row=6, column=0, padx=12, pady=20)
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=7, column=0, padx=12, pady=(4, 24))
        self.start_button = ctk.CTkButton(
            actions,
            text="Iniciar estudo",
            command=on_start,
            width=130,
            height=40,
            fg_color=theme.PRIMARY,
            hover_color=theme.HOVER,
        )
        self.pause_button = ctk.CTkButton(
            actions,
            text="Pausar",
            command=on_pause,
            width=140,
            height=40,
            fg_color=theme.PRIMARY,
            hover_color=theme.HOVER,
        )
        self.finish_button = ctk.CTkButton(
            actions,
            text="Finalizar",
            command=on_finish,
            width=110,
            height=40,
            fg_color=theme.PRIMARY,
            hover_color=theme.HOVER,
        )
        for column, button in enumerate((self.start_button, self.pause_button, self.finish_button)):
            button.grid(row=0, column=column, padx=4)
        for button in (
            self.new_type_button,
            self.manage_types_button,
            self.start_button,
            self.pause_button,
            self.finish_button,
        ):
            theme.keyboard_button(button)

    def set_types(self, types: list[StudyType]) -> None:
        """Atualiza o catálogo conservando a identidade da seleção."""
        selected = self.get_type_id()
        self._types = {item.id: item for item in types}
        self._type_by_name = {item.name: item.id for item in types}
        self.type_menu.configure(values=["Sem tipo", *(item.name for item in types)])
        self.select_type(selected)

    def select_type(self, type_id: int | None) -> None:
        """Seleciona por id, inclusive na recuperação."""
        item = self._types.get(type_id) if type_id is not None else None
        self.type_menu.set(item.name if item else "Sem tipo")
        self._on_type_selected(item.name if item else "Sem tipo")

    def _on_type_selected(self, name: str) -> None:
        type_id = self._type_by_name.get(name)
        item = self._types.get(type_id) if type_id is not None else None
        self.type_color.configure(
            text_color=theme.STUDY_COLORS[item.color_key] if item else theme.MUTED
        )

    def get_type_id(self) -> int | None:
        return self._type_by_name.get(str(self.type_menu.get()))

    def get_name(self) -> str:
        return str(self.name_entry.get())

    def render(self, state: UIState, session: Session | None, elapsed_s: int, failed: bool) -> None:
        """Não perde descrição ou tipo em falhas de gravação."""
        pending = session is not None
        running = session is not None and session.status == SessionStatus.RUNNING
        if session is not None:
            self.select_type(session.study_type_id)
            self.name_entry.configure(state="normal")
            if self.get_name() != session.name:
                self.name_entry.delete(0, "end")
                self.name_entry.insert(0, session.name)
        elif self._last_session_id is not None:
            self.name_entry.configure(state="normal")
            self.name_entry.delete(0, "end")
        self._last_session_id = session.id if session else None
        self.name_entry.configure(state="disabled" if pending else "normal")
        for widget in (self.type_menu, self.new_type_button, self.manage_types_button):
            widget.configure(state="disabled" if pending else "normal")
        self.start_button.configure(
            text="Retomar" if pending else "Iniciar estudo",
            state="disabled" if running else "normal",
        )
        self.pause_button.configure(
            text="Tentar salvar pausa" if failed else "Pausar",
            state="normal" if running else "disabled",
        )
        self.finish_button.configure(state="normal" if pending else "disabled")
        for button in (
            self.start_button,
            self.pause_button,
            self.finish_button,
            self.new_type_button,
        ):
            button.configure(
                fg_color=theme.PRIMARY if button.cget("state") == "normal" else theme.DISABLED,
                text_color_disabled=theme.MUTED,
            )
            button._canvas.configure(takefocus=button.cget("state") == "normal")
        self.type_menu._canvas.configure(takefocus=not pending)
        self.manage_types_button._canvas.configure(takefocus=not pending)
        self.manage_types_button.configure(text_color_disabled=theme.MUTED)
        self.type_menu.configure(
            text_color_disabled=theme.MUTED,
            button_color=theme.DISABLED if pending else theme.PRIMARY,
        )
        self.elapsed_label.configure(text=format_clock(elapsed_s))
        labels = {
            UIState.IDLE: "Pronto",
            UIState.RUNNING: "Em andamento",
            UIState.PAUSED: "Pausado",
            UIState.RECOVERED: "Sessão recuperada · pausada",
        }
        self.status_label.configure(
            text="Contagem interrompida · operação não confirmada" if failed else labels[state],
            text_color=theme.ERROR if failed else theme.SUCCESS,
        )
