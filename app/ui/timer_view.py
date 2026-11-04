"""Widgets do cronômetro; comandos são fornecidos pela janela."""

from collections.abc import Callable

import customtkinter as ctk

from app.models import Session, SessionStatus, UIState


class TimerView(ctk.CTkFrame):
    """Apresenta estado e formata segundos calculados pelo serviço."""

    def __init__(
        self,
        master: ctk.CTkFrame,
        on_start: Callable[[], None],
        on_pause: Callable[[], None],
        on_finish: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Cronômetro", font=("Segoe UI", 28)).grid(
            row=0, column=0, padx=24, pady=(32, 16)
        )
        self.status_label = ctk.CTkLabel(self, text="Pronto")
        self.status_label.grid(row=1, column=0)
        self.name_entry = ctk.CTkEntry(self, placeholder_text="Nome da sessão", width=340)
        self.name_entry.grid(row=2, column=0, padx=24, pady=24)
        self.elapsed_label = ctk.CTkLabel(self, text="00:00:00", font=("Consolas", 64))
        self.elapsed_label.grid(row=3, column=0, padx=24, pady=24)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=4, column=0, padx=24, pady=16)
        self.start_button = ctk.CTkButton(actions, text="Iniciar", command=on_start, width=120)
        self.pause_button = ctk.CTkButton(actions, text="Pausar", command=on_pause, width=150)
        self.finish_button = ctk.CTkButton(actions, text="Finalizar", command=on_finish, width=120)
        for column, button in enumerate((self.start_button, self.pause_button, self.finish_button)):
            button.grid(row=0, column=column, padx=6)
        ctk.CTkLabel(self, text="O tempo de pausa não é contabilizado").grid(row=5, column=0)
        ctk.CTkLabel(
            self,
            text="Ao fechar, a sessão é salva como pausada.",
            wraplength=480,
        ).grid(row=6, column=0, padx=24, pady=24)

    def get_name(self) -> str:
        """Lê o nome sem validar ou persistir na camada visual."""
        return str(self.name_entry.get())

    def render(self, state: UIState, session: Session | None, elapsed_s: int, failed: bool) -> None:
        """Aplica estado dos controles sem modificar o conteúdo digitado em idle."""
        pending = session is not None
        running = session is not None and session.status == SessionStatus.RUNNING
        if session is not None:
            self.name_entry.configure(state="normal")
            if self.get_name() != session.name:
                self.name_entry.delete(0, "end")
                self.name_entry.insert(0, session.name)
        self.name_entry.configure(state="disabled" if pending else "normal")
        self.start_button.configure(
            text="Retomar" if pending else "Iniciar",
            state="disabled" if running else "normal",
        )
        self.pause_button.configure(
            text="Tentar salvar pausa" if failed else "Pausar",
            state="normal" if running else "disabled",
        )
        self.finish_button.configure(state="normal" if pending else "disabled")
        hours, remainder = divmod(elapsed_s, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.elapsed_label.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        labels = {
            UIState.IDLE: "Pronto",
            UIState.RUNNING: "Em andamento",
            UIState.PAUSED: "Pausado",
            UIState.RECOVERED: "Sessão recuperada · pausada",
        }
        self.status_label.configure(
            text="Contagem interrompida · operação não confirmada" if failed else labels[state]
        )
