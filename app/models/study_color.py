"""Chaves de cores de tipos, independentes da aparência dos widgets."""

from enum import StrEnum


class StudyColor(StrEnum):
    """Paleta permitida; cada tema define a cor concreta na interface."""

    BLUE = "blue"
    TEAL = "teal"
    ORANGE = "orange"
    PURPLE = "purple"
    ROSE = "rose"
    CYAN = "cyan"
    AMBER = "amber"
    SLATE = "slate"
