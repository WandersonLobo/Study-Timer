"""Motivos de pausa da sessão de estudo."""

from enum import StrEnum


class PauseReason(StrEnum):
    """Motivos de interrupção para diagnóstico e apresentação."""

    USER = "user"
    SHUTDOWN = "shutdown"
    SUSPEND = "suspend"
    TICK_GAP = "tick_gap"
    CLOCK_CHANGE = "clock_change"
    WRITE_FAILURE = "write_failure"
