"""Estrutura visual inicial do Histórico, sem dados fictícios."""

import customtkinter as ctk


class HistoryView(ctk.CTkScrollableFrame):
    """Reserva espaço rolável para cartões, calendário e detalhes do dia."""

    def __init__(self, master: ctk.CTkFrame) -> None:
        super().__init__(master)
        self.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkLabel(self, text="Histórico", font=("Segoe UI", 28)).grid(
            row=0, column=0, columnspan=3, padx=24, pady=32
        )
        for column, label in enumerate(("Hoje", "Esta semana", "Mês atual")):
            card = ctk.CTkFrame(self)
            card.grid(row=1, column=column, padx=8, pady=16, sticky="ew")
            ctk.CTkLabel(card, text=label).pack(padx=12, pady=(12, 4))
            ctk.CTkLabel(card, text="—", font=("Segoe UI", 24)).pack(padx=12, pady=(4, 12))
        ctk.CTkLabel(self, text="Calendário mensal · total do mês exibido: —").grid(
            row=2, column=0, columnspan=3, padx=24, pady=24
        )
        ctk.CTkLabel(
            self,
            text="Calendário e detalhes serão conectados ao serviço de relatórios.",
            wraplength=480,
        ).grid(row=3, column=0, columnspan=3, padx=24, pady=24)
