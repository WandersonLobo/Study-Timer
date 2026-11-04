"""Modelo imutável de um intervalo de estudo."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StudyInterval:
    """Representa um intervalo aberto ou encerrado de uma sessão."""

    id: int
    session_id: int
    started_at: int
    last_seen_at: int
    ended_at: int | None
