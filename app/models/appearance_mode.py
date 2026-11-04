"""Preferência persistida de aparência, sem dependência da interface."""

from enum import StrEnum


class AppearanceMode(StrEnum):
    """Modos solicitados para a futura interface."""

    LIGHT = "light"
    DARK = "dark"
