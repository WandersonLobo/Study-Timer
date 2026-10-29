"""Estrutura visual inicial da tela Cronômetro."""

import customtkinter as ctk


class TimerView(ctk.CTkFrame):
    """Exibe os pontos de integração do cronômetro, ainda sem ações de sessão."""

    def __init__(self, master: ctk.CTkFrame) -> None:
        super().__init__(master)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Cronômetro", font=("Segoe UI", 28)).grid(
            row=0, column=0, padx=24, pady=(32, 16)
        )
        ctk.CTkLabel(self, text="Pronto · estrutura inicial").grid(row=1, column=0)
        self.name_entry = ctk.CTkEntry(self, placeholder_text="Nome da sessão", width=340)
        self.name_entry.grid(row=2, column=0, padx=24, pady=24)
        self.elapsed_label = ctk.CTkLabel(self, text="00:00:00", font=("Consolas", 64))
        self.elapsed_label.grid(row=3, column=0, padx=24, pady=24)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=4, column=0, padx=24, pady=16)
        for column, label in enumerate(("Iniciar", "Pausar", "Finalizar")):
            ctk.CTkButton(actions, text=label, state="disabled", width=120).grid(
                row=0, column=column, padx=6
            )
        ctk.CTkLabel(self, text="O tempo de pausa não é contabilizado").grid(row=5, column=0)
        ctk.CTkLabel(
            self,
            text="Ações disponíveis após a implementação do serviço de cronômetro.",
            wraplength=480,
        ).grid(row=6, column=0, padx=24, pady=24)
