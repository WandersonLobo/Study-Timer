"""Snapshot imutável do tempo validado de um intervalo aberto."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClockSnapshot:
    """Transporta somente tempo validado para substituir um intervalo aberto.

    elapsed_s é derivado de nanossegundos monotônicos aceitos. valid_until_utc_s
    deve ser igual a started_at + elapsed_s; não usa o relógio civil de término.
    O relatório substitui o checkpoint do interval_id, sem somar duas vezes.
    """

    interval_id: int
    started_at: int
    elapsed_s: int
    valid_until_utc_s: int
