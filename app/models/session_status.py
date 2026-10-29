"""Estados persistidos de uma sessão de estudo."""

from enum import StrEnum


class SessionStatus(StrEnum):
    """Estados persistidos no banco; idle e recovered pertencem à interface."""

    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
