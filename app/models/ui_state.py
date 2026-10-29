"""Estados de apresentação da sessão de estudo."""

from enum import StrEnum


class UIState(StrEnum):
    """Estados visuais previstos na especificação 1.1."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    RECOVERED = "recovered"
