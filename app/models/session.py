"""Modelo imutável da sessão persistida."""

from dataclasses import dataclass

from app.models.session_status import SessionStatus


@dataclass(frozen=True, slots=True)
class Session:
    """Representa uma sessão persistida, com timestamps UTC inteiros."""

    id: int
    name: str
    created_at: int
    finished_at: int | None
    status: SessionStatus
