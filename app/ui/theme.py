"""Paleta compartilhada para Claro/Escuro."""

from collections.abc import Callable

import customtkinter as ctk

from app.models import AppearanceMode, StudyColor

Color = tuple[str, str]
BACKGROUND: Color = ("#F5F6FA", "#242424")
SURFACE: Color = ("#FFFFFF", "#2B2B2B")
SIDEBAR: Color = ("#EEF1F6", "#2B2B2B")
BORDER: Color = ("#D5DAE3", "#505050")
TEXT: Color = ("#18202B", "#F2F3F5")
MUTED: Color = ("#606975", "#B5BAC3")
PRIMARY: Color = ("#1677FF", "#1F6AA5")
LINK: Color = ("#0965DE", "#82BEFF")
HOVER: Color = ("#0965DE", "#144870")
SELECTION: Color = ("#DCEAFF", "#17476B")
DISABLED: Color = ("#E6E9EF", "#3A3A3A")
ERROR: Color = ("#AC2030", "#FF969F")
SUCCESS: Color = ("#15732E", "#8DDBA4")
FOCUS: Color = ("#1677FF", "#6DBBFF")
STUDY_COLORS: dict[StudyColor, Color] = {
    StudyColor.BLUE: ("#1677FF", "#63A4FF"),
    StudyColor.TEAL: ("#008F80", "#35C8B6"),
    StudyColor.ORANGE: ("#B76600", "#F5A33B"),
    StudyColor.PURPLE: ("#8146C4", "#BB91EF"),
    StudyColor.ROSE: ("#B63968", "#F18AAE"),
    StudyColor.CYAN: ("#087FA1", "#5ED0ED"),
    StudyColor.AMBER: ("#966600", "#E7BF55"),
    StudyColor.SLATE: ("#586678", "#AFBAC9"),
}
COLOR_NAMES: dict[StudyColor, str] = {
    StudyColor.BLUE: "Azul",
    StudyColor.TEAL: "Verde",
    StudyColor.ORANGE: "Laranja",
    StudyColor.PURPLE: "Roxo",
    StudyColor.ROSE: "Rosa",
    StudyColor.CYAN: "Ciano",
    StudyColor.AMBER: "Âmbar",
    StudyColor.SLATE: "Cinza",
}


def apply_appearance(mode: AppearanceMode) -> None:
    """Atualiza widgets existentes, sem recriar janela ou serviços."""
    ctk.set_appearance_mode(mode.value)


def resolve_color(color: Color, mode: AppearanceMode) -> str:
    """Resolve cores para desenhos Tk que não aceitam pares."""
    return color[0 if mode == AppearanceMode.LIGHT else 1]


def keyboard_button(button: ctk.CTkButton) -> None:
    """Adapta o Canvas do CTk 5.2.2 para Tab, Enter, Espaço e foco visível."""
    button._canvas.configure(takefocus=True)
    button.bind("<Return>", lambda event: button.invoke(), add="+")
    button.bind("<space>", lambda event: button.invoke(), add="+")
    button.bind(
        "<FocusIn>", lambda event: button.configure(border_width=2, border_color=FOCUS), add="+"
    )
    button.bind("<FocusOut>", lambda event: button.configure(border_width=0), add="+")


def keyboard_choice(menu: ctk.CTkOptionMenu, on_select: Callable[[str], None]) -> None:
    """Permite selecionar por setas sem abrir menus nativos ou editar o texto."""
    menu._canvas.configure(takefocus=True)

    def move(delta: int) -> str:
        if menu.cget("state") != "disabled":
            values = list(menu.cget("values"))
            if values:
                current = str(menu.get())
                index = values.index(current) if current in values else 0
                value = values[(index + delta) % len(values)]
                menu.set(value)
                on_select(value)
        return "break"

    menu.bind("<Down>", lambda event: move(1), add="+")
    menu.bind("<Up>", lambda event: move(-1), add="+")
    menu.bind("<space>", lambda event: move(1), add="+")
