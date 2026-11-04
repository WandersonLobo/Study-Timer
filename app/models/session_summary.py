"""Resumo imutável da contribuição diária de uma sessão."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """Parcela de uma sessão atribuída ao dia local consultado."""

    session_id: int
    name: str
    duration_s: int
